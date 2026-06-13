import pytest
from ui_qt.presets.preset import Preset
from utils.globals import PromptMode


def make_preset(**kwargs):
    defaults = dict(
        name="My Preset",
        prompt_mode=PromptMode.SFW,
        positive_tags="mountain, fog",
        negative_tags="blurry",
        edit_suffix="",
    )
    defaults.update(kwargs)
    return Preset(**defaults)


class TestPresetConstruction:
    def test_prompt_mode_stored_as_name_string(self):
        p = make_preset(prompt_mode=PromptMode.NSFW)
        assert p.prompt_mode == "NSFW"

    def test_prompt_mode_string_passthrough(self):
        p = make_preset(prompt_mode="SFW")
        assert p.prompt_mode == "SFW"

    def test_edit_suffix_defaults_to_empty(self):
        p = Preset(name="x", prompt_mode=PromptMode.SFW, positive_tags="", negative_tags="")
        assert p.edit_suffix == ""


class TestPresetSerialization:
    def test_to_dict_contains_all_fields(self):
        p = make_preset()
        d = p.to_dict()
        assert set(d.keys()) == {"name", "prompt_mode", "positive_tags", "negative_tags", "edit_suffix"}

    def test_to_dict_prompt_mode_is_string(self):
        p = make_preset(prompt_mode=PromptMode.NSFW)
        assert p.to_dict()["prompt_mode"] == "NSFW"

    def test_from_dict_round_trip(self):
        p = make_preset(positive_tags="sunset, ocean", edit_suffix="_edit")
        restored = Preset.from_dict(p.to_dict())
        assert restored.name == p.name
        assert restored.prompt_mode == p.prompt_mode
        assert restored.positive_tags == p.positive_tags
        assert restored.negative_tags == p.negative_tags
        assert restored.edit_suffix == p.edit_suffix


class TestPresetEquality:
    def test_equal_presets(self):
        a = make_preset()
        b = make_preset()
        assert a == b

    def test_not_equal_different_positive_tags(self):
        a = make_preset(positive_tags="cats")
        b = make_preset(positive_tags="dogs")
        assert a != b

    def test_not_equal_different_negative_tags(self):
        a = make_preset(negative_tags="blurry")
        b = make_preset(negative_tags="noisy")
        assert a != b

    def test_not_equal_different_edit_suffix(self):
        a = make_preset(edit_suffix="")
        b = make_preset(edit_suffix="_v2")
        assert a != b

    def test_name_does_not_affect_equality(self):
        a = make_preset(name="Alpha")
        b = make_preset(name="Beta")
        assert a == b

    def test_hash_equal_for_equal_presets(self):
        a = make_preset()
        b = make_preset()
        assert hash(a) == hash(b)

    def test_hash_differs_for_different_tags(self):
        a = make_preset(positive_tags="cats")
        b = make_preset(positive_tags="dogs")
        assert hash(a) != hash(b)

    def test_usable_in_set(self):
        a = make_preset()
        b = make_preset()
        c = make_preset(positive_tags="different")
        s = {a, b, c}
        assert len(s) == 2


class TestPresetFromRunnerAppConfig:
    def test_from_runner_app_config_maps_fields(self):
        from utils.runner_app_config import RunnerAppConfig
        rac = RunnerAppConfig()
        rac.positive_tags = "ocean, waves"
        rac.negative_tags = "blur"
        rac.edit_suffix = "_out"
        p = Preset.from_runner_app_config("My Preset", rac)
        assert p.name == "My Preset"
        assert p.positive_tags == "ocean, waves"
        assert p.negative_tags == "blur"
        assert p.edit_suffix == "_out"


class TestPresetReadableStr:
    def test_readable_str_format(self):
        p = make_preset(name="Sunset", prompt_mode=PromptMode.SFW)
        assert "SFW" in p.readable_str()
        assert "Sunset" in p.readable_str()
