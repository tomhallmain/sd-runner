import pytest
from utils.globals import Globals
from utils.time_estimator import TimeEstimator


class TestEstimateSeconds:
    def test_returns_positive_integer(self):
        result = TimeEstimator.estimate_seconds("txt2img")
        assert isinstance(result, int) and result > 0

    def test_scales_with_n_latents(self):
        one = TimeEstimator.estimate_seconds("txt2img", n_latents=1)
        three = TimeEstimator.estimate_seconds("txt2img", n_latents=3)
        assert three == one * 3

    def test_zero_latents_returns_zero(self):
        assert TimeEstimator.estimate_seconds("txt2img", n_latents=0) == 0

    def test_resolution_argument_accepted(self):
        # Resolution is not currently used in the implementation but must not raise.
        result = TimeEstimator.estimate_seconds("txt2img", n_latents=1, resolution=(512, 512))
        assert isinstance(result, int)


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


class TestEstimateTime:
    def test_returns_string(self):
        result = TimeEstimator.estimate_time("txt2img", n_latents=2)
        assert isinstance(result, str) and result


class TestEstimateQueueTime:
    def test_returns_positive_for_nonempty_queue(self):
        result = TimeEstimator.estimate_queue_time(queue_size=5)
        assert isinstance(result, int) and result > 0

    def test_zero_queue_returns_zero(self):
        assert TimeEstimator.estimate_queue_time(queue_size=0) == 0

    def test_scales_with_queue_size(self):
        one = TimeEstimator.estimate_queue_time(queue_size=1)
        five = TimeEstimator.estimate_queue_time(queue_size=5)
        assert five == one * 5

    def test_scales_with_avg_latents(self):
        base = TimeEstimator.estimate_queue_time(queue_size=2, avg_latents_per_job=1.0)
        double = TimeEstimator.estimate_queue_time(queue_size=2, avg_latents_per_job=2.0)
        assert double == base * 2
