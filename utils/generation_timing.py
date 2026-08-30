"""Observed generation times, reduced to a rate the estimator can use.

A **sample** is one observation of how long a backend actually took to produce
an image, plus the descriptors that determine that cost. Samples are not kept
individually -- they reduce to a rate:

    rate = seconds / (megapixels * n_latents)

**Why resolution is divided out but steps are not.** Normalising exists to
generalise across what varies. Resolution varies *within* a run, since a run
iterates its resolution tags, so dividing by it is what keeps the table useful.
Step count does not: it is one setting applied to a whole run, and it is
usually not even known here -- ``steps`` defaults to -1, meaning "whatever the
workflow JSON specifies". Dividing by an unknown would make every default
configuration unmeasurable, so steps are part of the key instead, with -1 as
its own entry meaning the workflow's own value.

**Warm and cold.** In ComfyUI the checkpoint loader is a node inside the graph,
so a model load happens inside the measured window and can dwarf the generation
itself. A sample taken when the model just changed is therefore not a rate
sample -- it is a measurement of the load, which the estimator needs in its own
right, since a run iterating five models pays five loads.

Structure, backend outermost so a rate measured against a local ComfyUI is
never applied to a cloud service:

    {backend: {architecture: {"_aggregate": ..., "models": {model: {...}}}}}

Lookup goes model -> the architecture's aggregate -> nothing, so a newly
downloaded checkpoint gets a sane number from its siblings and converges on its
own once it has samples.
"""

import threading
from typing import Optional

from utils.logging_setup import get_logger

logger = get_logger("generation_timing")

#: Samples kept per key. A rolling window rather than a lifetime average, so a
#: GPU change, a driver update or a different backend is absorbed without
#: needing to be detected.
WINDOW = 20

#: A warm sample this many times the running rate is treated as a hidden model
#: reload rather than a real generation. The backend owns the loaded model, so
#: it can unload under memory pressure or be driven by another client without
#: this side knowing -- the guard bounds the damage rather than preventing it.
OUTLIER_FACTOR = 4.0

_AGGREGATE = "_aggregate"


def _mean(values: list) -> float:
    return sum(values) / len(values) if values else 0.0


def work_units(width: int, height: int, n_latents: int = 1) -> float:
    """The cost basis a duration is divided by to give a rate."""
    megapixels = (max(1, int(width)) * max(1, int(height))) / 1_000_000
    return megapixels * max(1, int(n_latents))


class GenerationTimingStore:
    """Rates and model load times, keyed by backend/architecture/model/steps.

    Safe to call from any thread: samples arrive from the generator's executor
    threads while the estimator reads from the GUI thread.
    """

    def __init__(self):
        self._lock = threading.Lock()
        # {backend: {architecture: {model: {"rate": {steps: [..]},
        #                                   "load": [..]}}}}
        self._samples: dict = {}

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------
    def record(
        self,
        backend: str,
        architecture: str,
        model: str,
        seconds: float,
        width: int,
        height: int,
        steps: int = -1,
        n_latents: int = 1,
        warm: bool = True,
    ) -> None:
        """Record one observation.

        *warm* is False when the model differs from the previous dispatch, or
        it is the first since startup. A cold observation measures the load and
        never contributes to the rate.
        """
        if seconds <= 0:
            return
        units = work_units(width, height, n_latents)
        steps_key = str(int(steps))

        with self._lock:
            entry = self._entry(backend, architecture, model)
            if warm:
                rate = seconds / units
                running = _mean(entry["rate"].setdefault(steps_key, []))
                if running and rate > running * OUTLIER_FACTOR:
                    logger.debug(
                        f"Discarding a warm timing sample for {model}: "
                        f"{rate:.3f}s/unit is over {OUTLIER_FACTOR}x the running "
                        "rate, so the model was probably reloaded unseen"
                    )
                    return
                _append(entry["rate"][steps_key], rate)
                return

            # Cold: the excess over what the generation itself should have cost
            # is the load. Needs a warm rate to subtract; until one exists the
            # sample is dropped rather than guessed at.
            rate = self._lookup_rate(backend, architecture, model, steps_key)
            if rate is None:
                return
            load = seconds - (rate * units)
            if load > 0:
                _append(entry["load"], load)

    def _entry(self, backend: str, architecture: str, model: str) -> dict:
        """The per-model sample lists, created on first use. Lock held."""
        return (
            self._samples
            .setdefault(backend, {})
            .setdefault(architecture, {})
            .setdefault(model, {"rate": {}, "load": []})
        )

    # ------------------------------------------------------------------
    # Reading
    # ------------------------------------------------------------------
    def _lookup_rate(self, backend, architecture, model, steps_key) -> Optional[float]:
        """This model's rate at this step count, else its architecture's
        aggregate at the same step count. Lock held.

        Step counts are never mixed: a 20-step and a 50-step sample describe
        different amounts of work per image, and averaging them would produce a
        number that describes neither.
        """
        models = self._samples.get(backend, {}).get(architecture, {})
        own = models.get(model, {}).get("rate", {}).get(steps_key)
        if own:
            return _mean(own)
        siblings = [
            r for entry in models.values()
            for r in entry["rate"].get(steps_key, [])
        ]
        return _mean(siblings) if siblings else None

    def rate(self, backend: str, architecture: str, model: str,
             steps: int = -1) -> Optional[float]:
        """Seconds per megapixel-latent, or None when nothing is known yet."""
        with self._lock:
            return self._lookup_rate(backend, architecture, model, str(int(steps)))

    def load_seconds(self, backend: str, architecture: str,
                     model: str) -> Optional[float]:
        """Seconds a switch to this model costs, or None when unmeasured.

        Independent of step count -- loading a checkpoint costs the same
        whatever is done with it afterwards.
        """
        with self._lock:
            models = self._samples.get(backend, {}).get(architecture, {})
            own = models.get(model, {}).get("load")
            if own:
                return _mean(own)
            siblings = [v for entry in models.values() for v in entry["load"]]
            return _mean(siblings) if siblings else None

    def sample_count(self, backend: str, architecture: str, model: str,
                     steps: int = -1) -> int:
        with self._lock:
            models = self._samples.get(backend, {}).get(architecture, {})
            return len(models.get(model, {}).get("rate", {}).get(str(int(steps)), []))

    def estimate_seconds(
        self,
        backend: str,
        architecture: str,
        model: str,
        width: int,
        height: int,
        image_count: float,
        steps: int = -1,
        model_switches: int = 0,
    ) -> Optional[float]:
        """Predicted backend time, or None when this key has no data.

        None means "no estimate", which callers must not turn into a refusal --
        not knowing a model's speed yet is not a reason to reject work.
        """
        rate = self.rate(backend, architecture, model, steps)
        if rate is None:
            return None
        # n_latents is folded into image_count by the caller, so the basis here
        # is one image.
        total = rate * work_units(width, height, 1) * image_count
        if model_switches > 0:
            load = self.load_seconds(backend, architecture, model)
            if load:
                total += load * model_switches
        return total

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    def to_dict(self) -> dict:
        """Averages rather than raw samples: the window is a smoothing device,
        not history worth carrying across sessions."""
        with self._lock:
            out = {}
            for backend, architectures in self._samples.items():
                for architecture, models in architectures.items():
                    entries = {}
                    for model, entry in models.items():
                        rates = {
                            steps: _mean(values)
                            for steps, values in entry["rate"].items() if values
                        }
                        if not rates and not entry["load"]:
                            continue
                        stored = {"rates": rates,
                                  "samples": sum(len(v) for v in entry["rate"].values())}
                        if entry["load"]:
                            stored["load_seconds"] = _mean(entry["load"])
                        entries[model] = stored
                    if not entries:
                        continue
                    group = out.setdefault(backend, {}).setdefault(architecture, {})
                    group["models"] = entries
                    all_rates = [r for e in entries.values() for r in e["rates"].values()]
                    if all_rates:
                        group[_AGGREGATE] = {
                            "rate": _mean(all_rates),
                            "samples": sum(e["samples"] for e in entries.values()),
                        }
            return out

    def load_from_dict(self, data: dict) -> None:
        """Restore averages as single samples.

        A restored average counts as one observation, so a session's own
        measurements outweigh it within a few generations. That is deliberate:
        the machine may have changed since it was written.
        """
        if not isinstance(data, dict):
            return
        with self._lock:
            self._samples = {}
            for backend, architectures in data.items():
                if not isinstance(architectures, dict):
                    continue
                for architecture, group in architectures.items():
                    if not isinstance(group, dict):
                        continue
                    for model, stored in (group.get("models") or {}).items():
                        if not isinstance(stored, dict):
                            continue
                        entry = self._entry(backend, architecture, model)
                        for steps, rate in (stored.get("rates") or {}).items():
                            if isinstance(rate, (int, float)) and rate > 0:
                                entry["rate"].setdefault(str(steps), []).append(float(rate))
                        load = stored.get("load_seconds")
                        if isinstance(load, (int, float)) and load > 0:
                            entry["load"].append(float(load))

    def clear(self) -> None:
        with self._lock:
            self._samples = {}


def _append(values: list, value: float) -> None:
    values.append(value)
    del values[:-WINDOW]


#: Process-wide store. Generators record into it; the estimator reads from it.
generation_timing = GenerationTimingStore()
