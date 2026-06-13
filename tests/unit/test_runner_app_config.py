import pytest
from utils.runner_app_config import RunnerAppConfig
from utils.globals import SoftwareType, WorkflowType, Sampler, Scheduler
from sd_runner.prompter_configuration import PrompterConfiguration


class TestRunnerAppConfigDefaults:
    def test_default_software_type_is_string(self):
        cfg = RunnerAppConfig()
        assert isinstance(cfg.software_type, str)

    def test_default_workflow_type_is_string(self):
        cfg = RunnerAppConfig()
        assert isinstance(cfg.workflow_type, str)

    def test_prompter_config_is_prompter_configuration(self):
        cfg = RunnerAppConfig()
        assert isinstance(cfg.prompter_config, PrompterConfiguration)

    def test_n_latents_default(self):
        cfg = RunnerAppConfig()
        assert cfg.n_latents == 1

    def test_total_default(self):
        cfg = RunnerAppConfig()
        assert cfg.total == 2


class TestRunnerAppConfigSerialization:
    def test_to_dict_returns_dict(self):
        cfg = RunnerAppConfig()
        d = cfg.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_prompter_config_is_dict(self):
        cfg = RunnerAppConfig()
        d = cfg.to_dict()
        assert isinstance(d["prompter_config"], dict)

    def test_to_dict_enums_are_strings(self):
        cfg = RunnerAppConfig()
        d = cfg.to_dict()
        assert isinstance(d["software_type"], str)
        assert isinstance(d["workflow_type"], str)
        assert isinstance(d["sampler"], str)
        assert isinstance(d["scheduler"], str)

    def test_from_dict_round_trip_basic_fields(self):
        original = RunnerAppConfig()
        original.positive_tags = "sunset, clouds"
        original.negative_tags = "blur"
        original.n_latents = 3
        original.total = 5

        restored = RunnerAppConfig.from_dict(original.to_dict())

        assert restored.positive_tags == original.positive_tags
        assert restored.negative_tags == original.negative_tags
        assert restored.n_latents == original.n_latents
        assert restored.total == original.total

    def test_from_dict_round_trip_prompter_config(self):
        original = RunnerAppConfig()
        original.prompter_config.set_category("colors", low=2, high=5)
        original.prompter_config.multiplier = 1.75

        restored = RunnerAppConfig.from_dict(original.to_dict())

        assert isinstance(restored.prompter_config, PrompterConfiguration)
        colors = restored.prompter_config.get_category_config("colors")
        assert colors.low == 2 and colors.high == 5
        assert abs(restored.prompter_config.multiplier - 1.75) < 1e-9

    def test_from_dict_adds_missing_backwards_compat_fields(self):
        d = RunnerAppConfig().to_dict()
        # Remove fields that were added later
        for key in ("edit_suffix", "exclusion_tags", "source_prompt_add_user_prompt",
                    "batch_limit", "dimension_variation", "continuous_seed_variation"):
            d.pop(key, None)
        restored = RunnerAppConfig.from_dict(d)
        assert hasattr(restored, "edit_suffix")
        assert hasattr(restored, "exclusion_tags")
        assert hasattr(restored, "batch_limit")


class TestRunnerAppConfigEquality:
    def test_two_defaults_are_equal(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        assert a == b

    def test_timestamp_does_not_affect_equality(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        a.timestamp = "2020-01-01T00:00:00"
        b.timestamp = "2025-06-01T12:00:00"
        assert a == b

    def test_different_tags_not_equal(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        b.positive_tags = "cats"
        assert a != b

    def test_not_equal_to_non_config(self):
        cfg = RunnerAppConfig()
        assert cfg != "not a config"

    def test_hash_consistent_for_equal_configs(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        assert hash(a) == hash(b)

    def test_hash_differs_for_different_configs(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        b.positive_tags = "mountains"
        assert hash(a) != hash(b)

    def test_usable_in_set(self):
        a = RunnerAppConfig()
        b = RunnerAppConfig()
        c = RunnerAppConfig()
        c.positive_tags = "unique"
        s = {a, b, c}
        assert len(s) == 2


class TestGetPrompterConfigCopy:
    def test_copy_is_independent(self):
        cfg = RunnerAppConfig()
        copy = cfg.get_prompter_config_copy()
        copy.multiplier = 99.0
        assert cfg.prompter_config.multiplier != 99.0

    def test_none_prompter_config_returns_none(self):
        cfg = RunnerAppConfig()
        cfg.prompter_config = None
        assert cfg.get_prompter_config_copy() is None
