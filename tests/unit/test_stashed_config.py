"""Stashed run configs -- naming a run setup and recalling it later.

A stash is the complement of a preset: the preset owns the four prompt fields,
the stash owns everything else. Most of what is worth asserting is what a stash
deliberately does *not* carry, and that the whole-dict storage decision holds up
against ``RunnerAppConfig.from_dict``, which is the trap this feature was most
likely to fall into.

``PresetsWindow`` is imported inside each test to keep PySide6 out of collection
for the rest of the unit suite.
"""

import pytest

from ui_qt.presets.stashed_config import StashedConfig
from utils.runner_app_config import RunnerAppConfig


def _window():
    from ui_qt.presets.presets_window import PresetsWindow
    return PresetsWindow


def _config(**kwargs) -> RunnerAppConfig:
    cfg = RunnerAppConfig()
    cfg.positive_tags = "a beach at sunset"
    cfg.negative_tags = "blurry"
    for key, value in kwargs.items():
        setattr(cfg, key, value)
    return cfg


# ---------------------------------------------------------------------------
# What a stash captures
# ---------------------------------------------------------------------------

class TestStashingTheCurrentConfig:
    def test_it_keeps_the_run_settings(self):
        stash = StashedConfig.from_runner_app_config(
            "night", _config(model_tags="someModel", total=7)
        )
        assert stash.config["model_tags"] == "someModel"
        assert stash.config["total"] == 7

    def test_it_does_not_keep_the_prompt_text(self):
        """Otherwise stashing would retain prompt text that the blacklist purge
        strips from run history."""
        stash = StashedConfig.from_runner_app_config("night", _config())
        assert stash.config["positive_tags"] == ""
        assert stash.config["negative_tags"] == ""

    def test_the_prompt_keys_still_exist(self):
        """Emptied, not dropped -- from_dict does not backfill these two."""
        stash = StashedConfig.from_runner_app_config("night", _config())
        assert "positive_tags" in stash.config
        assert "negative_tags" in stash.config

    def test_it_does_not_alter_the_config_it_captured(self):
        cfg = _config()
        StashedConfig.from_runner_app_config("night", cfg)
        assert cfg.positive_tags == "a beach at sunset"

    def test_it_records_when_it_was_saved(self):
        import datetime
        stash = StashedConfig.from_runner_app_config("night", _config())
        assert datetime.datetime.fromisoformat(stash.saved_at)


# ---------------------------------------------------------------------------
# The trap: from_dict replaces __dict__ and backfills only some fields
# ---------------------------------------------------------------------------

class TestSurvivingFromDict:
    def test_a_stash_reconstructs_without_raising(self):
        """Storing the whole dict is what buys this. A dict with the prompt
        fields omitted raises on the first read instead."""
        stash = StashedConfig.from_runner_app_config("night", _config())
        assert RunnerAppConfig.from_dict(stash.config) is not None

    def test_the_reconstruction_carries_the_run_settings(self):
        stash = StashedConfig.from_runner_app_config(
            "night", _config(model_tags="someModel", resolutions="portrait3")
        )
        restored = RunnerAppConfig.from_dict(stash.config)
        assert restored.model_tags == "someModel"
        assert restored.resolutions == "portrait3"

    def test_the_prompter_config_survives_as_an_object(self):
        stash = StashedConfig.from_runner_app_config("night", _config())
        restored = RunnerAppConfig.from_dict(stash.config)
        assert restored.prompter_config.prompt_mode is not None


# ---------------------------------------------------------------------------
# Serialization and persistence
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def test_to_dict_and_back(self):
        stash = StashedConfig.from_runner_app_config("night", _config(total=3))
        restored = StashedConfig.from_dict(stash.to_dict())
        assert restored.name == "night"
        assert restored.config["total"] == 3
        assert restored.saved_at == stash.saved_at

    def test_stashes_reach_the_cache_and_come_back(self, app_cache):
        w = _window()
        w.stashed_configs.append(
            StashedConfig.from_runner_app_config("night", _config(total=3))
        )
        w.store_stashed_configs(persist=False)
        w.stashed_configs.clear()
        w.set_stashed_configs()
        assert [s.name for s in w.stashed_configs] == ["night"]
        assert w.stashed_configs[0].config["total"] == 3

    def test_loading_replaces_rather_than_appends(self, app_cache):
        """Loading twice must not double the list."""
        w = _window()
        w.stashed_configs.append(
            StashedConfig.from_runner_app_config("night", _config())
        )
        w.store_stashed_configs(persist=False)
        w.set_stashed_configs()
        w.set_stashed_configs()
        assert len(w.stashed_configs) == 1

    def test_an_entry_with_no_name_is_dropped_on_load(self, app_cache):
        w = _window()
        app_cache.set(w.STASHED_CONFIGS_KEY, [{"name": "", "config": {"total": 1}}])
        w.set_stashed_configs()
        assert w.stashed_configs == []

    def test_an_entry_with_no_config_is_dropped_on_load(self, app_cache):
        w = _window()
        app_cache.set(w.STASHED_CONFIGS_KEY, [{"name": "night", "config": {}}])
        w.set_stashed_configs()
        assert w.stashed_configs == []


# ---------------------------------------------------------------------------
# Lookup
# ---------------------------------------------------------------------------

class TestLookup:
    def test_it_finds_a_stash_by_name(self, app_cache):
        w = _window()
        stash = StashedConfig.from_runner_app_config("night", _config())
        w.stashed_configs.append(stash)
        assert w.get_stashed_config_by_name("night") is stash

    def test_an_unknown_name_returns_none(self, app_cache):
        assert _window().get_stashed_config_by_name("nope") is None

    def test_names_come_back_sorted(self, app_cache):
        w = _window()
        for name in ("zebra", "apple", "moon"):
            w.stashed_configs.append(
                StashedConfig.from_runner_app_config(name, _config())
            )
        assert w.get_stashed_config_names() == ["apple", "moon", "zebra"]


# ---------------------------------------------------------------------------
# Display
# ---------------------------------------------------------------------------

class TestReadableStr:
    def test_it_names_the_stash_and_its_workflow(self):
        stash = StashedConfig.from_runner_app_config(
            "night", _config(workflow_type="SIMPLE_IMAGE_GEN", model_tags="someModel")
        )
        assert "night" in str(stash)
        assert "SIMPLE_IMAGE_GEN" in str(stash)

    def test_a_stash_with_no_detail_is_just_its_name(self):
        assert str(StashedConfig("bare", {"workflow_type": "", "model_tags": ""})) == "bare"
