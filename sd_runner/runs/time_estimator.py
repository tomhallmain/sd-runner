import math

from sd_runner.config import config
from sd_runner.globals import Globals
from lib.translations import I18N

_ = I18N._


class TimeEstimator:
    """Time estimates for image generation runs.

    An estimate has a measured generation term and a delay term. How they
    combine follows ``config.force_delay``, because that flag decides whether
    ``_sleep_for_delay`` holds the interval or treats it as a ceiling::

        force_delay:
            max(generation, delay x images)
        otherwise:
            generation + pacing floor          # timed model
            delay x images                     # untimed model

    Generation is ``rate x megapixels x images`` plus model-load time, from
    ``sd_runner.runs.generation_timing``. For a long time neither existed and
    the delay was the *whole* estimate, which expanded to exactly the sleep
    the run would perform, so the backend's actual work contributed nothing.

    - **force_delay on.** The loop holds the full delay even when the
      generation finishes inside it. The two overlap, so a timed model is the
      longer of them. A fast job still occupies the whole delay; a slow one
      is not charged the delay again on top of the time it already took.
    - **force_delay off.** The loop continues once the dispatched work is
      idle, so a timed model's generation term already covers that wait and
      only the short per-iteration floor remains. Charging the full delay as
      well would count the same seconds twice. An untimed model has no
      generation term, so the delay ceiling is the whole estimate.

    A model that has never been timed therefore falls back to the delay
    alone in either mode -- callers must not read a low estimate as
    permission, nor a missing one as a reason to refuse.

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
        """The configured delay for *image_count* images.

        ``Run._sleep_for_delay`` computes the same figure. With
        ``config.force_delay`` it waits that long even after the dispatched
        work has finished. Without the flag the figure is a ceiling: the loop
        continues as soon as that work is idle, so a run that keeps up with
        its backend pays less than this.
        """
        return int(Globals.GENERATION_DELAY_TIME_SECONDS * image_count)

    @staticmethod
    def estimate_queue_time(image_count: float,
                            avg_latents_per_job: float = 1.0) -> int:
        """Estimate the seconds *image_count* images will take.

        Despite the name this serves single runs as well as queues. Pass the
        image count directly, or a per-latent count plus *avg_latents_per_job*
        -- the two are multiplied.

        The configured delay only, since without a ``GenConfig`` there is nothing
        to look a measured rate up with. Callers holding one should use
        ``estimate_run_seconds``, which accounts for the generation itself and
        for whether ``config.force_delay`` holds the delay or treats it as a
        ceiling.
        """
        return TimeEstimator.delay_seconds(image_count * avg_latents_per_job)

    @staticmethod
    def estimate_run_seconds(gen_config, image_count: float) -> int:
        """Estimate the seconds a run producing *image_count* images will take.

        With ``config.force_delay``, the longer of measured generation time and
        the configured delay: the loop holds the delay even when the generation
        finishes inside it, and the two overlap, so they are not added.
        Without the flag, measured generation time plus the short floor the
        loop holds once the backend is idle. Falls back to the delay alone when
        the model has not been timed, in either mode -- so an unmeasured model
        is no worse off than before, and callers must not treat the absence of
        timing data as a reason to refuse work.
        """
        generation = TimeEstimator._generation_seconds(gen_config, image_count)
        if config.force_delay:
            delay = TimeEstimator.delay_seconds(image_count)
            if generation is None:
                return int(delay)
            return int(max(delay, generation))
        pacing = TimeEstimator._pacing_seconds(
            gen_config, image_count, measured=generation is not None
        )
        return int(pacing + (generation or 0))

    @staticmethod
    def _pacing_seconds(gen_config, image_count: float, measured: bool) -> int:
        """What the run loop adds when ``config.force_delay`` is off.

        Unmeasured, this is the whole estimate, and it stays the delay
        ceiling -- it is the only signal available, and the size ceiling that
        refuses work is built on it.

        Measured, the generation term already accounts for the wait. The loop
        continues once the work it dispatched is idle, so charging the ceiling
        as well would count the same seconds twice. What is left is the short
        floor the loop holds each iteration even when the backend is already
        idle.
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
            from sd_runner.runs.generation_timing import generation_timing

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