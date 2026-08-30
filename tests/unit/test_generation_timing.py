"""Measured generation rates and model load times.

A sample is one observation of backend time plus the descriptors that shaped
it. What is worth asserting here is mostly what the store *refuses* to do:
mix step counts, learn from a sample that paid for a model load, or answer
with a number when it has none.
"""

import pytest

from utils.generation_timing import (
    OUTLIER_FACTOR,
    WINDOW,
    GenerationTimingStore,
    work_units,
)

BACKEND = "ComfyUI"
ARCH = "SDXL"
MODEL = "juggernautXL_v9.safetensors"
OTHER_MODEL = "realvisXLV20.safetensors"

#: Exactly one megapixel, so a duration and its rate are the same number.
#: 1024 would be 1.049 MP and make every expected value awkward.
MP = 1000


@pytest.fixture
def store():
    return GenerationTimingStore()


def warm(store, seconds, model=MODEL, steps=-1, width=MP, height=MP, n_latents=1):
    store.record(BACKEND, ARCH, model, seconds, width, height,
                 steps=steps, n_latents=n_latents, warm=True)


# ---------------------------------------------------------------------------
# The rate basis
# ---------------------------------------------------------------------------

class TestWorkUnits:
    def test_scales_with_area_not_edge_length(self):
        """Doubling both dimensions is four times the work, not twice."""
        assert work_units(2048, 2048) == work_units(1024, 1024) * 4

    def test_scales_with_latents(self):
        assert work_units(512, 512, n_latents=3) == work_units(512, 512) * 3

    def test_degenerate_dimensions_do_not_divide_by_zero(self):
        assert work_units(0, 0) > 0


# ---------------------------------------------------------------------------
# Warm samples build the rate
# ---------------------------------------------------------------------------

class TestRate:
    def test_no_samples_means_no_estimate(self):
        """Not a zero, and not a guess -- callers must see the absence."""
        assert GenerationTimingStore().rate(BACKEND, ARCH, MODEL) is None

    def test_a_rate_is_seconds_per_unit(self, store):
        warm(store, seconds=10.0)  # 1 megapixel, so 10s per unit
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(10.0)

    def test_samples_average(self, store):
        warm(store, seconds=10.0)
        warm(store, seconds=20.0)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(15.0)

    def test_a_rate_generalises_across_resolution(self, store):
        """The point of dividing by area: one sample predicts other sizes.

        Twice the edge is four times the pixels, so four times the time.
        """
        warm(store, seconds=10.0, width=1000, height=1000)
        estimate = store.estimate_seconds(
            BACKEND, ARCH, MODEL, width=2000, height=2000, image_count=1
        )
        assert estimate == pytest.approx(40.0)

    def test_the_window_bounds_what_is_kept(self, store):
        for _ in range(WINDOW + 10):
            warm(store, seconds=10.0)
        assert store.sample_count(BACKEND, ARCH, MODEL) == WINDOW

    def test_recent_samples_displace_old_ones(self, store):
        for _ in range(WINDOW):
            warm(store, seconds=10.0)
        for _ in range(WINDOW):
            warm(store, seconds=20.0)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(20.0)

    def test_a_zero_duration_is_not_a_sample(self, store):
        warm(store, seconds=0)
        assert store.rate(BACKEND, ARCH, MODEL) is None


class TestStepCountsAreNeverMixed:
    """A 20-step and a 50-step sample describe different work per image."""

    def test_a_different_step_count_is_a_different_entry(self, store):
        warm(store, seconds=10.0, steps=20)
        assert store.rate(BACKEND, ARCH, MODEL, steps=50) is None

    def test_each_step_count_keeps_its_own_rate(self, store):
        warm(store, seconds=10.0, steps=20)
        warm(store, seconds=25.0, steps=50)
        assert store.rate(BACKEND, ARCH, MODEL, steps=20) == pytest.approx(10.0)
        assert store.rate(BACKEND, ARCH, MODEL, steps=50) == pytest.approx(25.0)

    def test_the_workflow_default_is_its_own_entry(self, store):
        """steps=-1 means 'whatever the workflow says', which is a real key."""
        warm(store, seconds=10.0, steps=-1)
        assert store.rate(BACKEND, ARCH, MODEL, steps=-1) == pytest.approx(10.0)
        assert store.rate(BACKEND, ARCH, MODEL, steps=30) is None


class TestArchitectureFallback:
    """A new checkpoint borrows from its siblings until it has samples."""

    def test_an_unseen_model_uses_its_architectures_rate(self, store):
        warm(store, seconds=10.0, model=MODEL)
        assert store.rate(BACKEND, ARCH, OTHER_MODEL) == pytest.approx(10.0)

    def test_its_own_samples_win_once_it_has_them(self, store):
        warm(store, seconds=10.0, model=MODEL)
        warm(store, seconds=30.0, model=OTHER_MODEL)
        assert store.rate(BACKEND, ARCH, OTHER_MODEL) == pytest.approx(30.0)

    def test_another_architecture_does_not_answer(self, store):
        warm(store, seconds=10.0)
        assert store.rate(BACKEND, "SD_15", MODEL) is None

    def test_another_backend_does_not_answer(self, store):
        """A local rate must never be applied to a cloud service."""
        warm(store, seconds=10.0)
        assert store.rate("StabilityAI", ARCH, MODEL) is None


# ---------------------------------------------------------------------------
# Cold samples measure the model load
# ---------------------------------------------------------------------------

class TestModelLoad:
    def cold(self, store, seconds, model=MODEL):
        store.record(BACKEND, ARCH, model, seconds, MP, MP, warm=False)

    def test_a_cold_sample_does_not_pollute_the_rate(self, store):
        warm(store, seconds=10.0)
        self.cold(store, seconds=90.0)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(10.0)

    def test_the_excess_over_the_rate_is_the_load(self, store):
        warm(store, seconds=10.0)
        self.cold(store, seconds=28.0)  # 10s of generation, 18s of loading
        assert store.load_seconds(BACKEND, ARCH, MODEL) == pytest.approx(18.0)

    def test_a_cold_sample_before_any_rate_is_dropped(self, store):
        """There is nothing to subtract yet, so the load cannot be isolated."""
        self.cold(store, seconds=90.0)
        assert store.load_seconds(BACKEND, ARCH, MODEL) is None

    def test_a_cold_sample_faster_than_the_rate_is_not_a_load(self, store):
        warm(store, seconds=10.0)
        self.cold(store, seconds=8.0)
        assert store.load_seconds(BACKEND, ARCH, MODEL) is None

    def test_load_time_is_added_per_switch(self, store):
        warm(store, seconds=10.0)
        self.cold(store, seconds=28.0)  # load = 18s
        one_image_no_switch = store.estimate_seconds(
            BACKEND, ARCH, MODEL, MP, MP, image_count=1, model_switches=0
        )
        one_image_two_switches = store.estimate_seconds(
            BACKEND, ARCH, MODEL, MP, MP, image_count=1, model_switches=2
        )
        assert one_image_two_switches == pytest.approx(one_image_no_switch + 36.0)


class TestOutlierRejection:
    """The backend can unload a model without this side knowing."""

    def test_a_wildly_slow_warm_sample_is_discarded(self, store):
        warm(store, seconds=10.0)
        warm(store, seconds=10.0 * OUTLIER_FACTOR * 2)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(10.0)

    def test_an_ordinary_fluctuation_is_kept(self, store):
        warm(store, seconds=10.0)
        warm(store, seconds=14.0)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(12.0)

    def test_the_first_sample_is_never_an_outlier(self, store):
        """There is no running rate to compare it against."""
        warm(store, seconds=999.0)
        assert store.rate(BACKEND, ARCH, MODEL) == pytest.approx(999.0)


# ---------------------------------------------------------------------------
# Estimating
# ---------------------------------------------------------------------------

class TestEstimateSeconds:
    def test_no_data_is_no_estimate(self, store):
        """Must stay None: callers turn a number into a refusal, not an absence."""
        assert store.estimate_seconds(BACKEND, ARCH, MODEL, MP, MP, 10) is None

    def test_it_scales_with_image_count(self, store):
        warm(store, seconds=10.0)
        one = store.estimate_seconds(BACKEND, ARCH, MODEL, MP, MP, image_count=1)
        ten = store.estimate_seconds(BACKEND, ARCH, MODEL, MP, MP, image_count=10)
        assert ten == pytest.approx(one * 10)


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

class TestPersistence:
    def test_a_rate_survives_a_round_trip(self, store):
        warm(store, seconds=10.0)
        restored = GenerationTimingStore()
        restored.load_from_dict(store.to_dict())
        assert restored.rate(BACKEND, ARCH, MODEL) == pytest.approx(10.0)

    def test_step_counts_survive_separately(self, store):
        warm(store, seconds=10.0, steps=20)
        warm(store, seconds=25.0, steps=50)
        restored = GenerationTimingStore()
        restored.load_from_dict(store.to_dict())
        assert restored.rate(BACKEND, ARCH, MODEL, steps=20) == pytest.approx(10.0)
        assert restored.rate(BACKEND, ARCH, MODEL, steps=50) == pytest.approx(25.0)

    def test_load_time_survives(self, store):
        warm(store, seconds=10.0)
        store.record(BACKEND, ARCH, MODEL, 28.0, MP, MP, warm=False)
        restored = GenerationTimingStore()
        restored.load_from_dict(store.to_dict())
        assert restored.load_seconds(BACKEND, ARCH, MODEL) == pytest.approx(18.0)

    def test_the_stored_form_is_an_average_not_a_sample_list(self, store):
        for _ in range(WINDOW):
            warm(store, seconds=10.0)
        stored = store.to_dict()[BACKEND][ARCH]["models"][MODEL]
        assert stored["rates"]["-1"] == pytest.approx(10.0)
        assert stored["samples"] == WINDOW

    def test_an_architecture_aggregate_is_written(self, store):
        warm(store, seconds=10.0, model=MODEL)
        warm(store, seconds=30.0, model=OTHER_MODEL)
        aggregate = store.to_dict()[BACKEND][ARCH]["_aggregate"]
        assert aggregate["rate"] == pytest.approx(20.0)

    def test_a_restored_average_is_outweighed_by_new_samples(self, store):
        """The machine may have changed since it was written."""
        warm(store, seconds=30.0)
        restored = GenerationTimingStore()
        restored.load_from_dict(store.to_dict())
        for _ in range(9):
            warm(restored, seconds=10.0)
        assert restored.rate(BACKEND, ARCH, MODEL) == pytest.approx(12.0)

    def test_an_empty_store_round_trips(self):
        store = GenerationTimingStore()
        assert store.to_dict() == {}

    @pytest.mark.parametrize("junk", [None, [], "nonsense", {"ComfyUI": "bad"}])
    def test_malformed_stored_data_is_ignored(self, junk):
        store = GenerationTimingStore()
        store.load_from_dict(junk)
        assert store.rate(BACKEND, ARCH, MODEL) is None

    def test_clear_forgets_everything(self, store):
        warm(store, seconds=10.0)
        store.clear()
        assert store.rate(BACKEND, ARCH, MODEL) is None
