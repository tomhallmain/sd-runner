from utils.globals import Globals
from utils.translations import I18N

_ = I18N._


class TimeEstimator:
    """Time estimates for image generation runs.

    An estimate has three parts, kept separate because their confidence
    differs::

        delay_seconds(images)                  # exact
        + rate x megapixels x images           # measured, per model
        + model_switches x load_seconds        # measured, per model

    The delay is not an estimate at all -- it is the app's own
    ``Run._sleep_for_delay``, computed from the same constant. For a long time
    it was the *whole* estimate, which expanded to exactly the sleep the run
    would perform, so the backend's actual work contributed nothing. That is
    why estimates used to be unreliable in both directions and why no amount of
    tuning fixed them: the term for the thing being measured was missing rather
    than wrong.

    The other two come from ``utils.generation_timing``, which learns them from
    completed generations. A model it has never timed yields no generation
    term, so the estimate falls back to the delay alone -- callers must not
    read a low estimate as permission, nor a missing one as a reason to refuse.

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
        """The pacing sleep the app will perform for *image_count* images.

        Exact, not estimated: it is the app's own ``_sleep_for_delay``, computed
        from the same constant. Named separately from the estimate so the part
        that is known stays distinguishable from the part that is guessed.
        """
        return int(Globals.GENERATION_DELAY_TIME_SECONDS * image_count)

    @staticmethod
    def estimate_queue_time(image_count: float,
                            avg_latents_per_job: float = 1.0) -> int:
        """Estimate the seconds *image_count* images will take.

        Despite the name this serves single runs as well as queues. Pass the
        image count directly, or a per-latent count plus *avg_latents_per_job*
        -- the two are multiplied.

        The pacing delay only. Callers holding a ``GenConfig`` should use
        ``estimate_run_seconds``, which can also account for the generation
        itself.
        """
        return TimeEstimator.delay_seconds(image_count * avg_latents_per_job)

    @staticmethod
    def estimate_run_seconds(gen_config, image_count: float) -> int:
        """Estimate the seconds a run producing *image_count* images will take.

        The pacing delay, plus measured generation and model-load time when
        this model has been timed before. Falls back to the delay alone when it
        has not, which is what every estimate used to be -- so an unmeasured
        model is no worse off than before, and callers must not treat the
        absence of timing data as a reason to refuse work.
        """
        delay = TimeEstimator.delay_seconds(image_count)
        generation = TimeEstimator._generation_seconds(gen_config, image_count)
        return int(delay + (generation or 0))

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