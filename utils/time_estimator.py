import math

from utils.globals import Globals
from utils.translations import I18N

_ = I18N._


class TimeEstimator:
    """Time estimates for image generation runs.

    An estimate has three parts, kept separate because their confidence
    differs::

        rate x megapixels x images             # measured, per model
        + model_switches x load_seconds        # measured, per model
        + pacing                               # see below

    The first two come from ``utils.generation_timing``, which learns them from
    completed generations. For a long time neither existed and the pacing was
    the *whole* estimate, which expanded to exactly the sleep the run would
    perform, so the backend's actual work contributed nothing. That is why
    estimates used to be unreliable in both directions and why no amount of
    tuning fixed them: the term for the thing being measured was missing rather
    than wrong.

    Pacing is now whichever of two things applies, because ``_sleep_for_delay``
    waits on the generations it dispatched rather than for a fixed interval:

    - **Timed model.** The generation term already covers that wait, so all
      that remains is the short floor the loop holds per iteration. Charging
      the full interval here as well double-counted the same seconds, which
      made estimates for timed models run high by the entire delay term.
    - **Untimed model.** No generation term exists, so the old ceiling stands
      as the only available signal.

    A model that has never been timed therefore falls back to the ceiling
    alone -- callers must not read a low estimate as permission, nor a missing
    one as a reason to refuse.

    Callers: the long-run confirmation dialog, ``config.server_run_max_seconds``
    (which *refuses* requests over its ceiling), and the sidebar label.
    """

    @staticmethod
    def format_time(seconds: int) -> str:
        """
        Format a time duration in seconds into a human-readable string.
        
        Args:
            seconds: Time duration in seconds
            
        Returns:
            A formatted string representing the time (e.g. "~2d 3h 30m 15s")
        """
        # Convert to days, hours, minutes and seconds
        days = int(seconds // (24 * 3600))
        seconds = seconds % (24 * 3600)
        hours = int(seconds // 3600)
        seconds = seconds % 3600
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        
        # Format the time string
        parts = []
        if days > 0:
            parts.append(_("~{0}d").format(days))
        if hours > 0 or days > 0:
            parts.append(_("{0}h").format(hours))
        if minutes > 0 or hours > 0 or days > 0:
            parts.append(_("{0}m").format(minutes))
        parts.append(_("{0}s").format(seconds))
        
        return " ".join(parts)
    
    @staticmethod
    def delay_seconds(image_count: float) -> int:
        """The most the app will pace for *image_count* images.

        An upper bound rather than a fixed cost. ``Run._sleep_for_delay``
        computes this same figure but treats it as a ceiling, continuing as
        soon as the generations it dispatched have finished -- so a run that
        keeps up with its backend pays much less than this, and the estimate
        errs high. Still computed from the same constant, so the bound is
        exact even though the cost is not.
        """
        return int(Globals.GENERATION_DELAY_TIME_SECONDS * image_count)

    @staticmethod
    def estimate_queue_time(image_count: float,
                            avg_latents_per_job: float = 1.0) -> int:
        """Estimate the seconds *image_count* images will take.

        Despite the name this serves single runs as well as queues. Pass the
        image count directly, or a per-latent count plus *avg_latents_per_job*
        -- the two are multiplied.

        The pacing ceiling only, since without a ``GenConfig`` there is nothing
        to look a measured rate up with. Callers holding one should use
        ``estimate_run_seconds``, which accounts for the generation itself and
        charges only the pacing floor once it can.
        """
        return TimeEstimator.delay_seconds(image_count * avg_latents_per_job)

    @staticmethod
    def estimate_run_seconds(gen_config, image_count: float) -> int:
        """Estimate the seconds a run producing *image_count* images will take.

        Measured generation and model-load time when this model has been timed
        before, plus whatever the run loop's pacing adds on top. Falls back to
        the pacing ceiling alone when the model has not been timed, which is
        what every estimate used to be -- so an unmeasured model is no worse
        off than before, and callers must not treat the absence of timing data
        as a reason to refuse work.
        """
        generation = TimeEstimator._generation_seconds(gen_config, image_count)
        pacing = TimeEstimator._pacing_seconds(
            gen_config, image_count, measured=generation is not None
        )
        return int(pacing + (generation or 0))

    @staticmethod
    def _pacing_seconds(gen_config, image_count: float, measured: bool) -> int:
        """What the run loop's own pacing adds, beyond the generation itself.

        Unmeasured, this is the whole estimate, and it stays the old ceiling --
        it is the only signal available, and the size ceiling that refuses work
        is built on it.

        Measured, the generation term already accounts for the wait. The loop
        waits *for* the generations it dispatched rather than for a fixed
        interval, so charging the ceiling as well would count the same seconds
        twice -- which is what made estimates for timed models run high by the
        whole delay term. What is genuinely left is the short floor the loop
        holds each iteration even when the backend is already idle.
        """
        if not measured:
            return TimeEstimator.delay_seconds(image_count)
        return int(Globals.MINIMUM_PACING_SECONDS * TimeEstimator._iterations(
            gen_config, image_count
        ))

    @staticmethod
    def _iterations(gen_config, image_count: float) -> int:
        """How many run-loop iterations *image_count* images will take.

        The loop paces once per iteration, not once per image. Callers derive
        image_count as images-per-iteration x iterations, so dividing recovers
        the iteration count. Anything unusable falls back to one iteration,
        which under-counts a floor measured in single seconds rather than
        raising over an advisory number.
        """
        if image_count <= 0:
            return 0
        try:
            per_iteration = gen_config.maximum_gens()
        except Exception:
            per_iteration = 0
        if not per_iteration or per_iteration <= 0:
            return 1
        return math.ceil(image_count / per_iteration)

    @staticmethod
    def _generation_seconds(gen_config, image_count: float):
        """Measured generation time for this config, or None if unmeasured."""
        try:
            from utils.generation_timing import generation_timing

            models = getattr(gen_config, "models", None) or []
            resolutions = getattr(gen_config, "resolutions", None) or []
            if not models or not resolutions:
                return None
            model = models[0]
            resolution = resolutions[0]
            architecture = getattr(model, "architecture_type", None)
            return generation_timing.estimate_seconds(
                backend=str(getattr(gen_config, "software_type", "") or ""),
                architecture=getattr(architecture, "name", str(architecture)),
                model=str(getattr(model, "id", model)),
                width=getattr(resolution, "width", 0),
                height=getattr(resolution, "height", 0),
                image_count=image_count,
                steps=getattr(gen_config, "steps", -1) or -1,
                # Switches within one pass over the models. Repeats across
                # `total` iterations are not counted, so this errs low -- which
                # is the safe direction for the size ceiling, since a ceiling
                # is a guard rather than a precondition.
                model_switches=max(0, len(models) - 1),
            )
        except Exception:
            # An estimate is advisory; never let a missing or malformed timing
            # store stop the run it was describing.
            return None 