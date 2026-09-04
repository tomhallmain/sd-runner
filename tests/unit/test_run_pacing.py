"""How the run loop paces itself between iterations.

The loop used to sleep an interval guessed from the image count, which
over-slept on fast models and under-slept on slow ones. With a live count of
in-flight generations it waits for the work it dispatched instead, treating
that interval as a ceiling.

No wall-clock is involved: ``time.sleep`` is replaced by a tick counter, and
the fake generator reports itself finished after a given number of ticks. So
these assert on seconds *waited*, not seconds elapsed.
"""

import pytest

from sd_runner.runs import run as run_module
from sd_runner.runs.run import Run
from tests.utils import make_run_config
from utils.globals import Globals


@pytest.fixture
def ticks(monkeypatch):
    """Count sleeps instead of performing them. One entry per second waited."""
    counted = []
    monkeypatch.setattr(run_module.time, "sleep", lambda seconds: counted.append(seconds))
    return counted


@pytest.fixture(autouse=True)
def one_second_per_image(monkeypatch):
    """Makes a ceiling of N seconds readable as maximum_gens=N."""
    monkeypatch.setattr(Globals, "GENERATION_DELAY_TIME_SECONDS", 1)


class FakeGen:
    """Reports work in flight until *drains_after* seconds have been waited.

    ``None`` never drains, standing in for a backend that died without
    releasing its count.
    """

    def __init__(self, ticks, drains_after=None):
        self._ticks = ticks
        self._drains_after = drains_after

    @property
    def pending_counter(self):
        if self._drains_after is None:
            return 1
        return 0 if len(self._ticks) >= self._drains_after else 1


def make_run(auto_run=True):
    return Run(make_run_config(auto_run=auto_run), ui_callbacks=None)


class TestCompletionPacing:
    def test_it_continues_once_the_dispatched_work_finishes(self, ticks):
        """The point of the change: a fast backend is not waited out."""
        gen = FakeGen(ticks, drains_after=2)
        make_run()._sleep_for_delay(maximum_gens=30, gen=gen)
        assert len(ticks) == 2

    def test_it_waits_the_full_ceiling_when_work_never_finishes(self, ticks):
        """A backend that dies without releasing must not stall the loop."""
        gen = FakeGen(ticks, drains_after=None)
        make_run()._sleep_for_delay(maximum_gens=5, gen=gen)
        assert len(ticks) == 5

    def test_it_never_returns_instantly(self, ticks):
        """A backend failing immediately must not be hammered at loop speed."""
        gen = FakeGen(ticks, drains_after=0)
        make_run()._sleep_for_delay(maximum_gens=10, gen=gen)
        assert len(ticks) == Globals.MINIMUM_PACING_SECONDS

    def test_without_a_generator_it_waits_the_whole_interval(self, ticks):
        """Nothing to observe, so the previous fixed behaviour stands."""
        make_run()._sleep_for_delay(maximum_gens=4, gen=None)
        assert len(ticks) == 4

    def test_the_ceiling_scales_with_the_image_count(self, ticks):
        gen = FakeGen(ticks, drains_after=None)
        make_run()._sleep_for_delay(maximum_gens=3, gen=gen)
        assert len(ticks) == 3


class TestPacingIsSkippable:
    def test_no_pacing_when_auto_run_is_off(self, ticks):
        gen = FakeGen(ticks, drains_after=None)
        make_run(auto_run=False)._sleep_for_delay(maximum_gens=9, gen=gen)
        assert ticks == []

    def test_cancelling_stops_the_wait(self, ticks):
        run = make_run()
        run.is_cancelled = True
        gen = FakeGen(ticks, drains_after=None)
        run._sleep_for_delay(maximum_gens=9, gen=gen)
        assert ticks == []
