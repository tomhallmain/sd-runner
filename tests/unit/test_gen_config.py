import pytest
from sd_runner.gen_config import GenConfig
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from utils.globals import WorkflowType


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_model(id="model.safetensors"):
    return Model(id=id, path="some/path")


def make_resolution(width=1024, height=1024, random_skip=False):
    return Resolution(width=width, height=height, random_skip=random_skip)


def make_run_config(**kwargs):
    return RunConfig(args=kwargs if kwargs else None)


def make_gen_config(**kwargs) -> GenConfig:
    defaults = dict(
        workflow_id="simple_image_gen.json",
        n_latents=1,
        positive="a sunset",
        negative="blurry",
        models=[make_model()],
        resolutions=[make_resolution()],
        run_config=make_run_config(seed=42),
    )
    defaults.update(kwargs)
    return GenConfig(**defaults)


# ---------------------------------------------------------------------------
# prepare() — empty lists get a [None] sentinel; already-populated stay intact
# ---------------------------------------------------------------------------

class TestPrepare:
    def test_empty_ip_adapters_gets_none_sentinel(self):
        cfg = make_gen_config(ip_adapters=[])
        cfg.prepare()
        assert cfg.ip_adapters == [None]

    def test_empty_control_nets_gets_none_sentinel(self):
        cfg = make_gen_config(control_nets=[])
        cfg.prepare()
        assert cfg.control_nets == [None]

    def test_empty_vaes_gets_none_sentinel(self):
        cfg = make_gen_config(vaes=[])
        cfg.prepare()
        assert cfg.vaes == [None]

    def test_empty_loras_gets_none_sentinel(self):
        cfg = make_gen_config(loras=[])
        cfg.prepare()
        assert cfg.loras == [None]

    def test_populated_ip_adapters_unchanged(self):
        cfg = make_gen_config(ip_adapters=["ip_adapter.bin"])
        cfg.prepare()
        assert cfg.ip_adapters == ["ip_adapter.bin"]

    def test_prepare_resets_resolutions_skipped(self):
        cfg = make_gen_config()
        cfg.resolutions_skipped = 3
        cfg.prepare()
        assert cfg.resolutions_skipped == 0

    def test_extra_whitespace_in_positive_collapsed(self):
        # NOTE: the regex in prepare() is "  {2,}" (matches 3+ spaces only),
        # so double-spaces survive. This test documents actual behaviour;
        # consider fixing the regex to " {2,}" to collapse all runs.
        cfg = make_gen_config(positive="a  sunset   scene")
        cfg.prepare()
        assert "   " not in cfg.positive  # 3+ spaces are collapsed
        assert cfg.positive == "a  sunset scene"  # double-space still present


# ---------------------------------------------------------------------------
# maximum_gens / maximum_gens_per_latent
# ---------------------------------------------------------------------------

class TestMaximumGens:
    def test_single_model_single_resolution_single_latent(self):
        cfg = make_gen_config(n_latents=1, models=[make_model()], resolutions=[make_resolution()])
        cfg.prepare()
        assert cfg.maximum_gens() == 1

    def test_scales_with_n_latents(self):
        cfg = make_gen_config(n_latents=3, models=[make_model()], resolutions=[make_resolution()])
        cfg.prepare()
        assert cfg.maximum_gens() == 3

    def test_scales_with_model_count(self):
        cfg = make_gen_config(n_latents=1, models=[make_model("a"), make_model("b")], resolutions=[make_resolution()])
        cfg.prepare()
        assert cfg.maximum_gens() == 2

    def test_scales_with_resolution_count(self):
        cfg = make_gen_config(n_latents=1, models=[make_model()],
                              resolutions=[make_resolution(), make_resolution()])
        cfg.prepare()
        assert cfg.maximum_gens() == 2

    def test_product_of_all_dimensions(self):
        cfg = make_gen_config(
            n_latents=2,
            models=[make_model("a"), make_model("b")],
            resolutions=[make_resolution(), make_resolution()],
        )
        cfg.prepare()
        assert cfg.maximum_gens() == 8  # 2 latents × 2 models × 2 resolutions

    def test_exclude_skipped_reduces_count(self):
        cfg = make_gen_config(n_latents=1, models=[make_model()],
                              resolutions=[make_resolution(), make_resolution()])
        cfg.prepare()
        cfg.resolutions_skipped = 1
        assert cfg.maximum_gens(exclude_skipped=True) == 1
        assert cfg.maximum_gens(exclude_skipped=False) == 2


# ---------------------------------------------------------------------------
# register_run — countdown logic
# ---------------------------------------------------------------------------

class TestRegisterRun:
    def test_default_always_returns_true(self):
        cfg = make_gen_config()
        # Default countdown_value is -1; -1 != 0 → True
        assert cfg.register_run() is True

    def test_countdown_zero_returns_false(self):
        cfg = make_gen_config()
        cfg.countdown_value = 0
        assert cfg.register_run() is False

    def test_countdown_decrements(self):
        cfg = make_gen_config()
        cfg.countdown_value = 2
        assert cfg.register_run() is True   # 2 → 1, returns True
        assert cfg.register_run() is True   # 1 → 0, returns True
        assert cfg.register_run() is False  # 0 != 0 → False

    def test_set_countdown_mode_uses_resolutions_skipped(self):
        cfg = make_gen_config()
        cfg.resolutions_skipped = 3
        cfg.set_countdown_mode()
        assert cfg.countdown_value == 3

    def test_reset_countdown_mode_restores_negative_one(self):
        cfg = make_gen_config()
        cfg.countdown_value = 5
        cfg.reset_countdown_mode()
        assert cfg.countdown_value == -1


# ---------------------------------------------------------------------------
# __eq__ / __hash__
# ---------------------------------------------------------------------------

class TestGenConfigEquality:
    def test_equal_configs(self):
        a = make_gen_config()
        b = make_gen_config()
        assert a == b

    def test_not_equal_different_positive(self):
        a = make_gen_config(positive="sunset")
        b = make_gen_config(positive="mountain")
        assert a != b

    def test_not_equal_different_negative(self):
        a = make_gen_config(negative="blurry")
        b = make_gen_config(negative="noisy")
        assert a != b

    def test_not_equal_when_seed_is_none(self):
        # __eq__ returns False when either seed is None
        a = make_gen_config()
        b = make_gen_config()
        a.seed = None
        assert a != b

    def test_not_equal_when_seed_is_minus_one(self):
        # seed = -1 means "random" — these are never considered equal
        a = make_gen_config()
        b = make_gen_config()
        a.seed = -1
        b.seed = -1
        assert a != b

    def test_not_equal_to_other_type(self):
        cfg = make_gen_config()
        assert cfg != "not a GenConfig"

    def test_hash_equal_for_equal_configs(self):
        a = make_gen_config()
        b = make_gen_config()
        assert hash(a) == hash(b)


# ---------------------------------------------------------------------------
# prompts_match
# ---------------------------------------------------------------------------

class TestPromptsMatch:
    def test_matching_prompts(self):
        a = make_gen_config(positive="sunset", negative="blur")
        b = make_gen_config(positive="sunset", negative="blur")
        assert a.prompts_match(b) is True

    def test_different_positive_does_not_match(self):
        a = make_gen_config(positive="sunset")
        b = make_gen_config(positive="mountain")
        assert a.prompts_match(b) is False

    def test_different_negative_does_not_match(self):
        a = make_gen_config(negative="blurry")
        b = make_gen_config(negative="noisy")
        assert a.prompts_match(b) is False

    def test_none_prior_config_returns_false(self):
        cfg = make_gen_config()
        assert cfg.prompts_match(None) is False
