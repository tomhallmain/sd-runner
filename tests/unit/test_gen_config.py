import pytest
from sd_runner.concepts import HardConcepts
from sd_runner.gen_config import GenConfig
from sd_runner.prompter_configuration import PrompterConfiguration
from tests.utils import make_gen_config, make_model, make_resolution, make_run_config
from utils.globals import ArchitectureType, Globals, PromptMode, WorkflowType


# ---------------------------------------------------------------------------
# Helpers — architecture-specific variants used only by this module
# ---------------------------------------------------------------------------

def make_xl_model(id="xl_model.safetensors"):
    return make_model(id=id, is_xl=True)


def make_sd15_model(id="sd15_model.safetensors"):
    model = make_model(id=id)
    model.architecture_type = ArchitectureType.SD_15
    return model


@pytest.fixture(autouse=True)
def restore_redo_parameters():
    """REDO_PARAMETERS is class-level; set_redo_params would leak between tests."""
    original = list(GenConfig.REDO_PARAMETERS)
    yield
    GenConfig.REDO_PARAMETERS = original


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


# ---------------------------------------------------------------------------
# Architecture helpers — delegate to the first model
# ---------------------------------------------------------------------------

class TestArchitectureHelpers:
    def test_architecture_type_comes_from_first_model(self):
        cfg = make_gen_config(models=[make_xl_model(), make_model()])
        assert cfg.architecture_type() == ArchitectureType.SDXL

    def test_is_xl_true_for_sdxl_model(self):
        cfg = make_gen_config(models=[make_xl_model()])
        assert cfg.is_xl() is True

    def test_is_xl_false_for_sd15_model(self):
        cfg = make_gen_config(models=[make_sd15_model()])
        assert cfg.is_xl() is False

    def test_max_image_scale_to_side_illustrious(self):
        cfg = make_gen_config(models=[make_model()])
        cfg.models[0].architecture_type = ArchitectureType.ILLUSTRIOUS
        assert cfg.max_image_scale_to_side() == 1536

    def test_max_image_scale_to_side_sdxl(self):
        cfg = make_gen_config(models=[make_xl_model()])
        assert cfg.max_image_scale_to_side() == 1024

    def test_max_image_scale_to_side_default(self):
        cfg = make_gen_config(models=[make_sd15_model()])
        assert cfg.max_image_scale_to_side() == 768

    def test_get_ip_adapter_models_differ_by_architecture(self):
        xl = make_gen_config(models=[make_xl_model()]).get_ip_adapter_models()
        sd15 = make_gen_config(models=[make_sd15_model()]).get_ip_adapter_models()
        assert xl != sd15


class TestGetPromptMode:
    def test_returns_mode_from_run_config(self):
        prompter_config = PrompterConfiguration()
        prompter_config.prompt_mode = PromptMode.NSFW
        cfg = make_gen_config(run_config=make_run_config(prompter_config=prompter_config))
        assert cfg.get_prompt_mode() == PromptMode.NSFW

    def test_reflects_a_later_mode_change(self):
        prompter_config = PrompterConfiguration()
        prompter_config.prompt_mode = PromptMode.SFW
        cfg = make_gen_config(run_config=make_run_config(prompter_config=prompter_config))
        prompter_config.prompt_mode = PromptMode.NSFL
        assert cfg.get_prompt_mode() == PromptMode.NSFL

    def test_get_prompter_config_is_the_run_config_object(self):
        prompter_config = PrompterConfiguration()
        cfg = make_gen_config(run_config=make_run_config(prompter_config=prompter_config))
        assert cfg.get_prompter_config() is prompter_config


# ---------------------------------------------------------------------------
# Redo prompt detection and parameter gating
# ---------------------------------------------------------------------------

class TestIsRedoPrompt:
    def test_png_workflow_id_is_redo(self):
        assert make_gen_config(workflow_id="C:/out/image_00042.png").is_redo_prompt() is True

    def test_json_workflow_id_is_not_redo(self):
        assert make_gen_config(workflow_id="simple_image_gen.json").is_redo_prompt() is False

    def test_non_string_workflow_id_is_not_redo(self):
        assert make_gen_config(workflow_id=WorkflowType.SIMPLE_IMAGE_GEN).is_redo_prompt() is False


class TestRedoParam:
    def test_non_redo_run_always_returns_the_value(self):
        cfg = make_gen_config(workflow_id="simple_image_gen.json")
        GenConfig.set_redo_params("")
        assert cfg.redo_param("model", "fallback") == "fallback"

    def test_listed_param_returns_the_value(self):
        cfg = make_gen_config(workflow_id="prior.png")
        GenConfig.set_redo_params("model,seed")
        assert cfg.redo_param("model", "fallback") == "fallback"

    def test_unlisted_param_returns_none(self):
        cfg = make_gen_config(workflow_id="prior.png")
        GenConfig.set_redo_params("model,seed")
        assert cfg.redo_param("resolution", "fallback") is None


class TestSetRedoParams:
    def test_empty_string_clears(self):
        GenConfig.set_redo_params("")
        assert GenConfig.REDO_PARAMETERS == []

    def test_whitespace_only_clears(self):
        GenConfig.set_redo_params("   ")
        assert GenConfig.REDO_PARAMETERS == []

    def test_comma_separated_values_are_stripped(self):
        GenConfig.set_redo_params(" model , seed ,resolution")
        assert GenConfig.REDO_PARAMETERS == ["model", "seed", "resolution"]


class TestRedoPreparation:
    def test_redo_run_trims_models_when_not_a_redo_param(self):
        GenConfig.set_redo_params("seed")
        cfg = make_gen_config(
            workflow_id="prior.png", models=[make_model("a"), make_model("b")]
        )
        cfg.prepare()
        assert len(cfg.models) == 1

    def test_redo_run_keeps_models_when_listed_as_a_redo_param(self):
        GenConfig.set_redo_params("models")
        cfg = make_gen_config(
            workflow_id="prior.png", models=[make_model("a"), make_model("b")]
        )
        cfg.prepare()
        assert len(cfg.models) == 2

    def test_redo_run_clears_resolutions_when_not_a_redo_param(self):
        GenConfig.set_redo_params("seed")
        cfg = make_gen_config(
            workflow_id="prior.png",
            resolutions=[make_resolution(), make_resolution(512, 512)],
        )
        cfg.prepare()
        assert cfg.resolutions == [None]

    def test_non_redo_run_leaves_models_alone(self):
        GenConfig.set_redo_params("seed")
        cfg = make_gen_config(models=[make_model("a"), make_model("b")])
        cfg.prepare()
        assert len(cfg.models) == 2


# ---------------------------------------------------------------------------
# validate() — returns True unless a flagged concept forces a confirmation
# ---------------------------------------------------------------------------

@pytest.fixture
def no_flagged_concepts(monkeypatch):
    """Neutralise the disk-loaded concept lists validate() consults."""
    monkeypatch.setattr(Globals, "SKIP_CONFIRMATIONS", False)
    monkeypatch.setattr(HardConcepts, "hard_concepts", [])
    monkeypatch.setattr(HardConcepts, "exclusionary_concepts", [])
    monkeypatch.setattr(HardConcepts, "boring_concepts", [])


class TestValidate:
    def test_clean_prompt_passes(self, no_flagged_concepts):
        assert make_gen_config(positive="a calm lake").validate() is True

    def test_empty_prompt_passes(self, no_flagged_concepts):
        assert make_gen_config(positive="").validate() is True

    def test_skip_confirmations_short_circuits(self, monkeypatch):
        monkeypatch.setattr(Globals, "SKIP_CONFIRMATIONS", True)
        monkeypatch.setattr(HardConcepts, "hard_concepts", ["lake"])
        assert make_gen_config(positive="a calm lake").validate() is True

    def test_redo_prompt_short_circuits(self, monkeypatch):
        monkeypatch.setattr(Globals, "SKIP_CONFIRMATIONS", False)
        monkeypatch.setattr(HardConcepts, "hard_concepts", ["lake"])
        cfg = make_gen_config(workflow_id="prior.png", positive="a calm lake")
        assert cfg.validate() is True

    def test_hard_concept_prompts_for_confirmation(self, no_flagged_concepts, monkeypatch):
        monkeypatch.setattr(HardConcepts, "hard_concepts", ["lake"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": "y")
        assert make_gen_config(positive="a calm lake").validate() is True

    def test_declined_confirmation_fails_validation(self, no_flagged_concepts, monkeypatch):
        monkeypatch.setattr(HardConcepts, "hard_concepts", ["lake"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
        assert make_gen_config(positive="a calm lake").validate() is False

    def test_exclusionary_concept_prompts_for_confirmation(self, no_flagged_concepts, monkeypatch):
        monkeypatch.setattr(HardConcepts, "exclusionary_concepts", ["lake"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
        assert make_gen_config(positive="a calm lake").validate() is False

    def test_boring_concept_prompts_for_confirmation(self, no_flagged_concepts, monkeypatch):
        monkeypatch.setattr(HardConcepts, "boring_concepts", ["lake"])
        monkeypatch.setattr("builtins.input", lambda _prompt="": "n")
        assert make_gen_config(positive="a calm lake").validate() is False


# ---------------------------------------------------------------------------
# Seed selection
# ---------------------------------------------------------------------------

class TestGetSeed:
    def test_configured_seed_is_used(self):
        cfg = make_gen_config(run_config=make_run_config(seed=1234))
        assert cfg.get_seed() == 1234

    def test_negative_seed_becomes_random(self):
        cfg = make_gen_config(run_config=make_run_config(seed=-1))
        assert cfg.get_seed() >= 0

    def test_none_seed_becomes_random(self):
        cfg = make_gen_config()
        cfg.seed = None
        assert cfg.get_seed() >= 0

    def test_continuous_variation_ignores_configured_seed(self):
        cfg = make_gen_config(run_config=make_run_config(seed=1234))
        cfg.continuous_seed_variation = True
        seeds = {cfg.get_seed() for _ in range(20)}
        assert seeds != {1234}

    def test_random_seed_within_expected_bound(self):
        for _ in range(20):
            assert 0 <= GenConfig.random_seed() < 9999999999999
