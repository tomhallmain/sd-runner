import math

import pytest
from sd_runner.config import config
from sd_runner.globals import Globals
from sd_runner.runs.time_estimator import TimeEstimator


class TestDelaySeconds:
    """The delay figure both pacing modes compute.

    With ``force_delay`` the loop waits it out. Without the flag it is the
    ceiling the loop may leave once the dispatched work is idle.
    """

    def test_matches_the_interval_the_run_computes(self):
        assert TimeEstimator.delay_seconds(7) == Globals.GENERATION_DELAY_TIME_SECONDS * 7

    def test_scales_with_image_count(self):
        one = TimeEstimator.delay_seconds(1)
        three = TimeEstimator.delay_seconds(3)
        assert three == one * 3

    def test_no_images_is_no_delay(self):
        assert TimeEstimator.delay_seconds(0) == 0

    def test_returns_a_whole_number_of_seconds(self):
        assert isinstance(TimeEstimator.delay_seconds(2.5), int)


class TestFormatTime:
    def test_seconds_only(self):
        # 45 seconds: only the seconds part, no minutes or hours
        result = TimeEstimator.format_time(45)
        assert "45" in result
        assert "h" not in result

    def test_minutes_and_seconds(self):
        # 90 seconds = 1m 30s
        result = TimeEstimator.format_time(90)
        assert "1" in result
        assert "30" in result

    def test_hours_minutes_seconds(self):
        # 3661 seconds = 1h 1m 1s
        result = TimeEstimator.format_time(3661)
        assert "1h" in result or "1" in result
        assert "s" in result

    def test_days(self):
        # 86400 seconds = 1 day; result should have 4 space-separated parts (day + h + m + s)
        result = TimeEstimator.format_time(86400)
        assert "1" in result
        assert len(result.split()) == 4

    def test_zero_seconds(self):
        result = TimeEstimator.format_time(0)
        assert "0" in result and "s" in result

    def test_returns_string(self):
        assert isinstance(TimeEstimator.format_time(100), str)


class TestEstimateQueueTime:
    def test_returns_positive_for_nonempty_queue(self):
        result = TimeEstimator.estimate_queue_time(5)
        assert isinstance(result, int) and result > 0

    def test_zero_queue_returns_zero(self):
        assert TimeEstimator.estimate_queue_time(0) == 0

    def test_scales_with_image_count(self):
        one = TimeEstimator.estimate_queue_time(1)
        five = TimeEstimator.estimate_queue_time(5)
        assert five == one * 5

    def test_scales_with_avg_latents(self):
        base = TimeEstimator.estimate_queue_time(2, avg_latents_per_job=1.0)
        double = TimeEstimator.estimate_queue_time(2, avg_latents_per_job=2.0)
        assert double == base * 2

    def test_a_count_and_a_latent_multiplier_are_interchangeable(self):
        """Callers pass either shape; both must reach the same total."""
        assert (TimeEstimator.estimate_queue_time(6)
                == TimeEstimator.estimate_queue_time(3, avg_latents_per_job=2.0))

    def test_it_is_the_pacing_delay_alone(self):
        """This entry point deliberately excludes generation time.

        It is what callers without a GenConfig get, and they have nothing to
        look a rate up with. estimate_run_seconds is the one that adds the
        measured terms.
        """
        assert TimeEstimator.estimate_queue_time(4) == TimeEstimator.delay_seconds(4)


class TestEstimateRunSeconds:
    """The entry point that accounts for measured generation time.

    ``force_delay`` off charges a timed model the generation plus the short
    floor, because the loop leaves the delay once the work is idle.
    ``force_delay`` on charges the longer of generation and the full delay,
    because the hold and the generation overlap. An untimed model gets the
    delay alone in either mode.
    """

    def make_config(self):
        from tests.utils import make_gen_config, make_model, make_resolution
        return make_gen_config(
            models=[make_model(id="a_model.safetensors")],
            resolutions=[make_resolution(width=1000, height=1000)],
        )

    def descriptors(self, gen_config):
        model = gen_config.models[0]
        return {
            "backend": str(gen_config.software_type or ""),
            "architecture": getattr(model.architecture_type, "name",
                                    str(model.architecture_type)),
            "model": str(model.id),
        }

    @pytest.mark.parametrize("force_delay", [False, True])
    def test_an_unmeasured_model_falls_back_to_the_delay(self, force_delay, monkeypatch):
        """No worse off than before any of this existed, in either mode."""
        monkeypatch.setattr(config, "force_delay", force_delay)
        gen_config = self.make_config()
        assert (TimeEstimator.estimate_run_seconds(gen_config, 4)
                == TimeEstimator.delay_seconds(4))

    def measured_config(self, seconds=10.0):
        from sd_runner.runs.generation_timing import generation_timing

        gen_config = self.make_config()
        generation_timing.record(
            seconds=seconds, width=1000, height=1000,
            steps=gen_config.steps or -1, **self.descriptors(gen_config)
        )
        return gen_config

    def pacing_for(self, gen_config, images):
        """The floor the loop holds, once per iteration, when force_delay is off."""
        iterations = math.ceil(images / gen_config.maximum_gens())
        return Globals.MINIMUM_PACING_SECONDS * iterations

    def test_a_measured_model_is_generation_time_plus_the_pacing_floor(self, monkeypatch):
        """force_delay off: the delay ceiling is not charged again."""
        monkeypatch.setattr(config, "force_delay", False)
        gen_config = self.measured_config()
        estimate = TimeEstimator.estimate_run_seconds(gen_config, 4)
        assert estimate == pytest.approx(
            40.0 + self.pacing_for(gen_config, 4), abs=1
        )

    def test_a_measured_model_is_not_charged_the_full_delay(self, monkeypatch):
        """force_delay off: generation time already covers the wait."""
        monkeypatch.setattr(config, "force_delay", False)
        gen_config = self.measured_config()
        estimate = TimeEstimator.estimate_run_seconds(gen_config, 4)
        assert estimate < TimeEstimator.delay_seconds(4) + 40.0

    def test_ceiling_mode_scales_with_image_count(self, monkeypatch):
        monkeypatch.setattr(config, "force_delay", False)
        gen_config = self.measured_config()
        one = TimeEstimator.estimate_run_seconds(gen_config, 1)
        ten = TimeEstimator.estimate_run_seconds(gen_config, 10)
        generation_one = one - self.pacing_for(gen_config, 1)
        generation_ten = ten - self.pacing_for(gen_config, 10)
        assert generation_ten == pytest.approx(generation_one * 10, abs=1)

    def test_a_fast_measured_model_still_pays_the_full_delay(self, monkeypatch):
        """force_delay on: finishing inside the delay does not shrink the estimate."""
        monkeypatch.setattr(config, "force_delay", True)
        gen_config = self.measured_config(seconds=1.0)
        assert (TimeEstimator.estimate_run_seconds(gen_config, 4)
                == TimeEstimator.delay_seconds(4))

    def test_a_slow_measured_model_is_not_charged_the_delay_on_top(self, monkeypatch):
        """force_delay on: the hold overlaps the generation, so the two are not added."""
        monkeypatch.setattr(config, "force_delay", True)
        gen_config = self.measured_config(seconds=100.0)
        estimate = TimeEstimator.estimate_run_seconds(gen_config, 4)
        assert estimate == pytest.approx(400.0, abs=1)
        assert estimate < TimeEstimator.delay_seconds(4) + 400.0

    def test_forced_delay_scales_with_image_count(self, monkeypatch):
        monkeypatch.setattr(config, "force_delay", True)
        gen_config = self.measured_config()
        one = TimeEstimator.estimate_run_seconds(gen_config, 1)
        ten = TimeEstimator.estimate_run_seconds(gen_config, 10)
        assert ten == pytest.approx(one * 10, abs=1)

    @pytest.mark.parametrize("force_delay", [False, True])
    def test_a_config_without_models_falls_back_to_the_delay(self, force_delay, monkeypatch):
        """Nothing to look a rate up with; must not raise, in either mode."""
        monkeypatch.setattr(config, "force_delay", force_delay)
        from tests.utils import make_gen_config
        gen_config = make_gen_config(models=[])
        assert (TimeEstimator.estimate_run_seconds(gen_config, 4)
                == TimeEstimator.delay_seconds(4))

    @pytest.mark.parametrize("force_delay", [False, True])
    def test_a_broken_timing_store_does_not_break_the_estimate(self, force_delay, monkeypatch):
        """An estimate is advisory and must never fail the run it describes."""
        monkeypatch.setattr(config, "force_delay", force_delay)
        from sd_runner.runs import generation_timing as timing_module

        def explode(*args, **kwargs):
            raise RuntimeError("timing store unavailable")

        monkeypatch.setattr(
            timing_module.generation_timing, "estimate_seconds", explode
        )
        assert (TimeEstimator.estimate_run_seconds(self.make_config(), 4)
                == TimeEstimator.delay_seconds(4))
