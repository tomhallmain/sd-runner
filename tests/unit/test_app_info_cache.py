import json
import pytest
from utils.app_info_cache import AppInfoCache
from utils.runner_app_config import RunnerAppConfig


def _make_config(positive_tags="test prompt", **kwargs) -> RunnerAppConfig:
    cfg = RunnerAppConfig()
    cfg.positive_tags = positive_tags
    for k, v in kwargs.items():
        setattr(cfg, k, v)
    return cfg


# ---------------------------------------------------------------------------
# get / set — info dict
# ---------------------------------------------------------------------------

class TestGetSet:
    def test_set_and_get_value(self, app_cache):
        app_cache.set("my_key", "my_value")
        assert app_cache.get("my_key") == "my_value"

    def test_get_missing_key_returns_none(self, app_cache):
        assert app_cache.get("nonexistent") is None

    def test_get_missing_key_returns_default(self, app_cache):
        assert app_cache.get("nonexistent", default_val="fallback") == "fallback"

    def test_overwrite_existing_key(self, app_cache):
        app_cache.set("key", "first")
        app_cache.set("key", "second")
        assert app_cache.get("key") == "second"

    def test_set_stores_various_types(self, app_cache):
        app_cache.set("list_val", [1, 2, 3])
        assert app_cache.get("list_val") == [1, 2, 3]


# ---------------------------------------------------------------------------
# set_history / get_history
# ---------------------------------------------------------------------------

class TestSetGetHistory:
    def test_empty_history_returns_default_config_dict(self, app_cache):
        result = app_cache.get_history(0)
        assert isinstance(result, dict)
        assert "model_tags" in result

    def test_set_history_stores_entry(self, app_cache):
        cfg = _make_config(positive_tags="sunset, ocean")
        app_cache.set_history(cfg)
        stored = app_cache.get_history(0)
        assert stored["positive_tags"] == "sunset, ocean"

    def test_most_recent_entry_at_index_zero(self, app_cache):
        app_cache.set_history(_make_config(positive_tags="first"))
        app_cache.set_history(_make_config(positive_tags="second"))
        assert app_cache.get_history(0)["positive_tags"] == "second"
        assert app_cache.get_history(1)["positive_tags"] == "first"

    def test_set_history_deduplicates_consecutive(self, app_cache):
        cfg = _make_config(positive_tags="sunset")
        app_cache.set_history(cfg)
        result = app_cache.set_history(cfg)
        assert result is False
        assert app_cache.get_last_history_index() == 0

    def test_get_history_invalid_index_raises(self, app_cache):
        app_cache.set_history(_make_config(positive_tags="a"))
        with pytest.raises(Exception, match="Invalid history index"):
            app_cache.get_history(999)

    def test_get_history_negative_index_raises(self, app_cache):
        app_cache.set_history(_make_config(positive_tags="a"))
        with pytest.raises(Exception, match="Invalid history index"):
            app_cache.get_history(-1)


# ---------------------------------------------------------------------------
# get_last_history_index / clamp_config_history_index
# ---------------------------------------------------------------------------

class TestHistoryIndexOps:
    def test_last_index_empty_history_returns_zero(self, app_cache):
        assert app_cache.get_last_history_index() == 0

    def test_last_index_with_entries(self, app_cache):
        for i in range(3):
            app_cache.set_history(_make_config(positive_tags=f"tag_{i}"))
        assert app_cache.get_last_history_index() == 2

    def test_clamp_empty_history_returns_zero(self, app_cache):
        assert app_cache.clamp_config_history_index(5) == 0

    def test_clamp_within_bounds(self, app_cache):
        for i in range(3):
            app_cache.set_history(_make_config(positive_tags=f"tag_{i}"))
        assert app_cache.clamp_config_history_index(1) == 1

    def test_clamp_beyond_end(self, app_cache):
        app_cache.set_history(_make_config(positive_tags="only"))
        assert app_cache.clamp_config_history_index(99) == 0

    def test_clamp_negative_to_zero(self, app_cache):
        app_cache.set_history(_make_config(positive_tags="neg"))
        assert app_cache.clamp_config_history_index(-5) == 0


# ---------------------------------------------------------------------------
# add_prompt_history_entry / get_recent_prompts
# ---------------------------------------------------------------------------

class TestPromptHistory:
    def test_empty_positive_tags_returns_false(self, app_cache):
        assert app_cache.add_prompt_history_entry("", "neg") is False

    def test_whitespace_positive_tags_returns_false(self, app_cache):
        assert app_cache.add_prompt_history_entry("   ") is False

    def test_adds_entry(self, app_cache):
        result = app_cache.add_prompt_history_entry("ocean, waves", "blur")
        assert result is True
        recent = app_cache.get_recent_prompts(1)
        assert recent[0]["positive_tags"] == "ocean, waves"
        assert recent[0]["negative_tags"] == "blur"

    def test_deduplicates_consecutive_identical_entry(self, app_cache):
        app_cache.add_prompt_history_entry("same prompt", timestamp="2026-01-01T00:00:00")
        result = app_cache.add_prompt_history_entry("same prompt", timestamp="2026-01-01T00:00:00")
        assert result is False

    def test_recent_prompts_empty_when_no_history(self, app_cache):
        assert app_cache.get_recent_prompts() == []

    def test_recent_prompts_limit_respected(self, app_cache):
        for i in range(10):
            app_cache.add_prompt_history_entry(f"prompt_{i}")
        assert len(app_cache.get_recent_prompts(3)) == 3

    def test_recent_prompts_most_recent_first(self, app_cache):
        app_cache.add_prompt_history_entry("first")
        app_cache.add_prompt_history_entry("second")
        recent = app_cache.get_recent_prompts(2)
        assert recent[0]["positive_tags"] == "second"
        assert recent[1]["positive_tags"] == "first"


# ---------------------------------------------------------------------------
# get_prompt_tags_by_frequency
# ---------------------------------------------------------------------------

class TestGetPromptTagsByFrequency:
    def test_empty_history_returns_empty_dict(self, app_cache):
        assert app_cache.get_prompt_tags_by_frequency() == {}

    def test_counts_tags_across_entries(self, app_cache):
        app_cache.add_prompt_history_entry("sunset, ocean")
        app_cache.add_prompt_history_entry("mountain, ocean")
        counts = app_cache.get_prompt_tags_by_frequency()
        assert counts["ocean"] == 2
        assert counts["sunset"] == 1
        assert counts["mountain"] == 1

    def test_strips_outer_parentheses(self, app_cache):
        app_cache.add_prompt_history_entry("(sunset)")
        counts = app_cache.get_prompt_tags_by_frequency()
        assert "sunset" in counts
        assert "(sunset)" not in counts

    def test_strips_outer_brackets(self, app_cache):
        app_cache.add_prompt_history_entry("[sunset]")
        counts = app_cache.get_prompt_tags_by_frequency()
        assert "sunset" in counts

    def test_weighted_gives_higher_weight_to_newer_entry(self, app_cache):
        # Insert in chronological order (add_prompt_history_entry inserts at front)
        app_cache.add_prompt_history_entry("old_tag")
        app_cache.add_prompt_history_entry("new_tag")
        weighted = app_cache.get_prompt_tags_by_frequency(weighted=True)
        # new_tag is at index 0 (weight 1.0), old_tag at index 1 (weight < 1.0)
        assert weighted["new_tag"] > weighted["old_tag"]


# ---------------------------------------------------------------------------
# set_directory / get_directory / normalize_directory_key
# ---------------------------------------------------------------------------

class TestDirectoryOperations:
    def test_set_and_get_directory(self, app_cache, tmp_path):
        app_cache.set_directory(str(tmp_path), "last_file", "image.png")
        assert app_cache.get_directory(str(tmp_path), "last_file") == "image.png"

    def test_get_missing_key_returns_default(self, app_cache, tmp_path):
        result = app_cache.get_directory(str(tmp_path), "missing", default_val="default")
        assert result == "default"

    def test_get_missing_directory_returns_default(self, app_cache, tmp_path):
        result = app_cache.get_directory(str(tmp_path / "nonexistent"), "key")
        assert result is None

    def test_normalize_trailing_slash_consistent(self, tmp_path):
        key1 = AppInfoCache.normalize_directory_key(str(tmp_path))
        key2 = AppInfoCache.normalize_directory_key(str(tmp_path) + "/")
        assert key1 == key2

    def test_overwrite_directory_value(self, app_cache, tmp_path):
        app_cache.set_directory(str(tmp_path), "key", "old")
        app_cache.set_directory(str(tmp_path), "key", "new")
        assert app_cache.get_directory(str(tmp_path), "key") == "new"


# ---------------------------------------------------------------------------
# edit history
# ---------------------------------------------------------------------------

class TestEditHistory:
    def test_not_recorded_returns_false(self, app_cache):
        assert app_cache.edit_output_exists("output_0001.png") is False

    def test_record_then_exists(self, app_cache):
        app_cache.record_edit_output("output_0001.png")
        assert app_cache.edit_output_exists("output_0001.png") is True

    def test_different_name_not_affected(self, app_cache):
        app_cache.record_edit_output("a.png")
        assert app_cache.edit_output_exists("b.png") is False

    def test_multiple_entries_independent(self, app_cache):
        app_cache.record_edit_output("x.png")
        app_cache.record_edit_output("y.png")
        assert app_cache.edit_output_exists("x.png") is True
        assert app_cache.edit_output_exists("y.png") is True


# ---------------------------------------------------------------------------
# wipe_instance
# ---------------------------------------------------------------------------

class TestWipeInstance:
    def test_wipe_clears_info_key(self, app_cache):
        app_cache.set("key", "value")
        app_cache.wipe_instance()
        assert app_cache.get("key") is None

    def test_wipe_clears_history(self, app_cache):
        app_cache.set_history(_make_config())
        app_cache.wipe_instance()
        # After wipe, history is empty; get_history(0) falls back to default dict
        result = app_cache.get_history(0)
        assert isinstance(result, dict)

    def test_wipe_clears_directory_info(self, app_cache, tmp_path):
        app_cache.set_directory(str(tmp_path), "k", "v")
        app_cache.wipe_instance()
        assert app_cache.get_directory(str(tmp_path), "k") is None


# ---------------------------------------------------------------------------
# export_as_json
# ---------------------------------------------------------------------------

class TestExportAsJson:
    def test_export_creates_valid_json_file(self, app_cache, tmp_path):
        app_cache.set("export_key", "export_val")
        out = tmp_path / "export.json"
        app_cache.export_as_json(str(out))
        with open(out) as f:
            data = json.load(f)
        assert data[AppInfoCache.INFO_KEY]["export_key"] == "export_val"

    def test_exported_json_contains_history(self, app_cache, tmp_path):
        app_cache.set_history(_make_config(positive_tags="beach"))
        out = tmp_path / "export.json"
        app_cache.export_as_json(str(out))
        with open(out) as f:
            data = json.load(f)
        assert any(e["positive_tags"] == "beach"
                   for e in data[AppInfoCache.HISTORY_KEY])
