import pytest
from sd_runner.concepts import ConceptConfiguration
from sd_runner.prompter_configuration import LegacyPrompterConfiguration, PrompterConfiguration
from utils.globals import PromptMode


def make_config(**kwargs) -> PrompterConfiguration:
    return PrompterConfiguration(**kwargs)


class TestPrompterConfigurationDefaults:
    def test_all_required_categories_present_after_init(self):
        cfg = make_config()
        for name in PrompterConfiguration.REQUIRED_CATEGORIES:
            assert name in cfg.categories, f"Missing required category: {name}"

    def test_default_prompt_mode_is_sfw(self):
        cfg = make_config()
        assert cfg.prompt_mode == PromptMode.SFW

    def test_default_multiplier_is_one(self):
        cfg = make_config()
        assert cfg.multiplier == 1.0

    def test_concepts_dir_defaults_to_string(self):
        cfg = make_config()
        assert isinstance(cfg.concepts_dir, str)


class TestSetAndGetCategory:
    def test_set_and_get_category_basic(self):
        cfg = make_config()
        cfg.set_category("colors", low=1, high=4)
        cat = cfg.get_category_config("colors")
        assert cat.low == 1
        assert cat.high == 4

    def test_alias_concepts_maps_to_media_features(self):
        cfg = make_config()
        cfg.set_category("concepts", low=2, high=5)
        cat = cfg.get_category_config("media_features")
        assert cat.low == 2
        assert cat.high == 5

    def test_get_unknown_category_returns_zero_config(self):
        cfg = make_config()
        cat = cfg.get_category_config("totally_unknown")
        assert cat.low == 0 and cat.high == 0

    def test_set_category_preserves_subcategory_weights(self):
        cfg = make_config()
        # witticisms has subcategory_weights set in defaults
        original_weights = cfg.categories["witticisms"].subcategory_weights.copy()
        cfg.set_category("witticisms", low=1, high=2)
        assert cfg.categories["witticisms"].subcategory_weights == original_weights


class TestWitticisms:
    def test_get_witticisms_weights_returns_tuple(self):
        cfg = make_config()
        sayings, puns = cfg.get_witticisms_weights()
        assert isinstance(sayings, float) and isinstance(puns, float)

    def test_set_witticisms_weights_persisted(self):
        cfg = make_config()
        cfg.set_witticisms_weights(2.0, 0.5)
        sayings, puns = cfg.get_witticisms_weights()
        assert sayings == 2.0
        assert puns == 0.5

    def test_get_witticisms_ratio_equal_weights(self):
        cfg = make_config()
        cfg.set_witticisms_weights(1.0, 1.0)
        assert abs(cfg.get_witticisms_ratio() - 0.5) < 1e-9

    def test_get_witticisms_ratio_all_puns(self):
        cfg = make_config()
        cfg.set_witticisms_weights(0.0, 1.0)
        assert cfg.get_witticisms_ratio() == 1.0

    def test_get_witticisms_ratio_all_sayings(self):
        cfg = make_config()
        cfg.set_witticisms_weights(1.0, 0.0)
        assert cfg.get_witticisms_ratio() == 0.0


class TestSpecificChances:
    def test_set_and_get_specific_locations_chance(self):
        cfg = make_config()
        cfg.set_specific_locations_chance(0.75)
        assert abs(cfg.get_specific_locations_chance() - 0.75) < 1e-9

    def test_set_and_get_specific_times_chance(self):
        cfg = make_config()
        cfg.set_specific_times_chance(0.6)
        assert abs(cfg.get_specific_times_chance() - 0.6) < 1e-9


class TestPrompterConfigurationSerialization:
    def test_to_dict_contains_categories_key(self):
        cfg = make_config()
        d = cfg.to_dict()
        assert "categories" in d

    def test_to_dict_prompt_mode_is_string(self):
        cfg = make_config(prompt_mode=PromptMode.NSFW)
        d = cfg.to_dict()
        assert d["prompt_mode"] == "NSFW"

    def test_set_from_dict_round_trip(self):
        original = make_config(
            prompt_mode=PromptMode.SFW,
            multiplier=1.5,
            art_styles_chance=0.4,
        )
        original.set_category("colors", low=1, high=3)
        original.set_witticisms_weights(0.8, 0.3)

        d = original.to_dict()
        restored = make_config()
        restored.set_from_dict(d)

        assert restored.prompt_mode == original.prompt_mode
        assert abs(restored.multiplier - original.multiplier) < 1e-9
        assert abs(restored.art_styles_chance - original.art_styles_chance) < 1e-9

        colors = restored.get_category_config("colors")
        assert colors.low == 1 and colors.high == 3

    def test_set_from_dict_legacy_format_loads(self):
        # Legacy format has no 'categories' key; uses old field names
        legacy_dict = {
            "prompt_mode": "SFW",
            "concepts": (1, 3),
            "positions": (0, 2),
            "locations": (0, 1, 0.3),
            "animals": (0, 1, 0.1),
            "colors": (0, 2),
            "times": (0, 1, 0.3),
            "dress": (0, 2, 0.5),
            "expressions": (1, 1),
            "actions": (0, 2),
            "descriptions": (0, 1),
            "characters": (0, 1),
            "random_words": (0, 5),
            "nonsense": (0, 0),
            "jargon": (0, 2),
            "sayings": (0, 2),
            "puns": (0, 1),
            "art_styles_chance": 0.3,
        }
        cfg = make_config()
        cfg.set_from_dict(legacy_dict)
        assert cfg.prompt_mode == PromptMode.SFW
        for name in PrompterConfiguration.REQUIRED_CATEGORIES:
            assert name in cfg.categories


class TestPrompterConfigurationEquality:
    def test_equal_defaults(self):
        a = make_config()
        b = make_config()
        assert a == b

    def test_not_equal_different_multiplier(self):
        a = make_config(multiplier=1.0)
        b = make_config(multiplier=2.0)
        assert a != b

    def test_not_equal_different_category(self):
        a = make_config()
        b = make_config()
        b.set_category("colors", low=99, high=99)
        assert a != b

    def test_original_tags_excluded_from_equality(self):
        a = make_config(original_positive_tags="cats")
        b = make_config(original_positive_tags="dogs")
        assert a == b

    def test_hash_consistent(self):
        a = make_config()
        b = make_config()
        assert hash(a) == hash(b)

    def test_hash_differs_for_different_multiplier(self):
        a = make_config(multiplier=1.0)
        b = make_config(multiplier=2.0)
        assert hash(a) != hash(b)


class TestLegacyPrompterConfiguration:
    def test_to_prompter_configuration_returns_prompter_configuration(self):
        legacy = LegacyPrompterConfiguration()
        result = legacy.to_prompter_configuration()
        assert isinstance(result, PrompterConfiguration)

    def test_to_prompter_configuration_all_required_categories_present(self):
        legacy = LegacyPrompterConfiguration()
        result = legacy.to_prompter_configuration()
        for name in PrompterConfiguration.REQUIRED_CATEGORIES:
            assert name in result.categories

    def test_bool_expressions_converted(self):
        legacy = LegacyPrompterConfiguration(expressions=True)
        legacy._handle_old_types()
        assert legacy.expressions == (1, 1)

        legacy_false = LegacyPrompterConfiguration(expressions=False)
        legacy_false._handle_old_types()
        assert legacy_false.expressions == (0, 0)

    def test_concepts_maps_to_media_features(self):
        legacy = LegacyPrompterConfiguration(concepts=(2, 4))
        result = legacy.to_prompter_configuration()
        mf = result.get_category_config("media_features")
        assert mf.low == 2 and mf.high == 4
