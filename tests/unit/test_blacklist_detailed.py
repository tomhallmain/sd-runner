import json
import csv
import pytest

from sd_runner.prompts.blacklist import Blacklist, BlacklistItem


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add(*tags: str) -> None:
    for tag in tags:
        Blacklist.add_to_blacklist(tag)


def _patch_dictionary(monkeypatch, words: set = None) -> None:
    """Make Concepts.get_dictionary_set() return a controlled set of words."""
    word_set = words if words is not None else set()
    monkeypatch.setattr(
        "sd_runner.prompts.concepts.Concepts.get_dictionary_set",
        lambda: word_set,
    )


# ---------------------------------------------------------------------------
# check_user_prompt_detailed — obfuscation detection
# ---------------------------------------------------------------------------

class TestCheckUserPromptDetailed:
    def test_prefix_stripped_word_detected(self, monkeypatch):
        # "bcat" is not a dictionary word; truncating to "cat" hits the blacklist
        _patch_dictionary(monkeypatch)
        _add("cat")
        result = Blacklist.check_user_prompt_detailed("bcat")
        assert "bcat" in result
        assert result["bcat"] == "cat"

    def test_longer_prefix_detected(self, monkeypatch):
        # "xxdog" with start_idx=2 → "dog"
        _patch_dictionary(monkeypatch)
        _add("dog")
        result = Blacklist.check_user_prompt_detailed("xxdog")
        assert "xxdog" in result

    def test_dictionary_word_skipped(self, monkeypatch):
        # If the word IS in the dictionary, it's not subjected to detailed checking,
        # so an obfuscated match inside it won't be flagged here
        _patch_dictionary(monkeypatch, words={"bcat"})
        _add("cat")
        result = Blacklist.check_user_prompt_detailed("bcat")
        assert "bcat" not in result

    def test_clean_text_returns_empty(self, monkeypatch):
        _patch_dictionary(monkeypatch)
        _add("badword")
        result = Blacklist.check_user_prompt_detailed("sunshine, mountains, lake")
        assert result == {}

    def test_disabled_item_ignored(self, monkeypatch):
        _patch_dictionary(monkeypatch)
        Blacklist.add_to_blacklist(BlacklistItem("cat", enabled=False))
        result = Blacklist.check_user_prompt_detailed("bcat")
        assert result == {}

    def test_comma_separated_parts_each_checked(self, monkeypatch):
        _patch_dictionary(monkeypatch)
        _add("cat", "dog")
        result = Blacklist.check_user_prompt_detailed("xcat, xdog")
        assert "xcat" in result
        assert "xdog" in result

    def test_outer_parens_stripped(self, monkeypatch):
        # Words wrapped in parentheses should still be checked
        _patch_dictionary(monkeypatch)
        _add("cat")
        result = Blacklist.check_user_prompt_detailed("(xcat)")
        assert "xcat" in result

    def test_short_word_ignored(self, monkeypatch):
        # Words with fewer than 2 characters are skipped entirely
        _patch_dictionary(monkeypatch)
        _add("x")
        result = Blacklist.check_user_prompt_detailed("x")
        assert result == {}


# ---------------------------------------------------------------------------
# import — CSV
#
# The import tests below write their own two-column files, which is also the
# legacy export format, so they stay independent of export_blacklist_csv.
# TestCSVRoundTrip covers the two working against each other.
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list[dict]) -> None:
    """Write a legacy two-column CSV, the older export_blacklist_csv format."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["string", "enabled"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


class TestCSVImport:
    def test_single_item_loaded(self, tmp_path):
        _write_csv(str(tmp_path / "bl.csv"), [{"string": "wolf", "enabled": "True"}])
        Blacklist.import_blacklist_csv(str(tmp_path / "bl.csv"))
        assert any(i.string == "wolf" for i in Blacklist.TAG_BLACKLIST)

    def test_multiple_items_loaded(self, tmp_path):
        rows = [{"string": t, "enabled": "True"} for t in ("cat", "dog", "bird")]
        _write_csv(str(tmp_path / "bl.csv"), rows)
        Blacklist.import_blacklist_csv(str(tmp_path / "bl.csv"))
        strings = {i.string for i in Blacklist.TAG_BLACKLIST}
        assert strings == {"cat", "dog", "bird"}

    def test_disabled_state_honoured(self, tmp_path):
        _write_csv(str(tmp_path / "bl.csv"), [{"string": "disabled_tag", "enabled": "False"}])
        Blacklist.import_blacklist_csv(str(tmp_path / "bl.csv"))
        items = {i.string: i for i in Blacklist.TAG_BLACKLIST}
        assert "disabled_tag" in items
        assert items["disabled_tag"].enabled is False

    def test_count_matches_rows(self, tmp_path):
        rows = [{"string": t, "enabled": "True"} for t in ("alpha", "beta", "gamma")]
        _write_csv(str(tmp_path / "bl.csv"), rows)
        Blacklist.import_blacklist_csv(str(tmp_path / "bl.csv"))
        assert len(Blacklist.TAG_BLACKLIST) == 3


class TestCSVExport:
    def test_empty_blacklist_writes_header_only(self, tmp_path):
        csv_path = str(tmp_path / "empty.csv")
        Blacklist.export_blacklist_csv(csv_path)
        with open(csv_path, encoding="utf-8") as f:
            content = f.read()
        assert "string" in content
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) == 1  # header only

    def test_export_nonempty_list_succeeds(self, tmp_path):
        """Regression: DictWriter used to raise ValueError on the extra to_dict keys."""
        _add("cat")
        csv_path = str(tmp_path / "blacklist.csv")
        Blacklist.export_blacklist_csv(csv_path)
        with open(csv_path, encoding="utf-8") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        assert len(lines) == 2  # header + one item

    def test_header_covers_every_to_dict_field(self, tmp_path):
        _add("cat")
        csv_path = str(tmp_path / "blacklist.csv")
        Blacklist.export_blacklist_csv(csv_path)
        with open(csv_path, newline="", encoding="utf-8") as f:
            header = next(csv.reader(f))
        assert set(header) == set(Blacklist.TAG_BLACKLIST[0].to_dict().keys())

    def test_multiple_items_each_get_a_row(self, tmp_path):
        for tag in ("cat", "dog", "bird"):
            _add(tag)
        csv_path = str(tmp_path / "blacklist.csv")
        Blacklist.export_blacklist_csv(csv_path)
        with open(csv_path, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        assert {r["string"] for r in rows} == {"cat", "dog", "bird"}


class TestCSVRoundTrip:
    """Export then import must preserve the settings, not just the string."""

    def _round_trip(self, tmp_path, item):
        Blacklist.TAG_BLACKLIST = [item]
        csv_path = str(tmp_path / "roundtrip.csv")
        Blacklist.export_blacklist_csv(csv_path)
        Blacklist.TAG_BLACKLIST = []
        Blacklist.import_blacklist_csv(csv_path)
        assert len(Blacklist.TAG_BLACKLIST) == 1
        return Blacklist.TAG_BLACKLIST[0]

    def test_string_preserved(self, tmp_path):
        assert self._round_trip(tmp_path, BlacklistItem("wolf")).string == "wolf"

    def test_disabled_state_preserved(self, tmp_path):
        item = BlacklistItem("wolf", enabled=False)
        assert self._round_trip(tmp_path, item).enabled is False

    def test_regex_flag_preserved(self, tmp_path):
        item = BlacklistItem("wo.f", use_regex=True)
        assert self._round_trip(tmp_path, item).use_regex is True

    def test_word_boundary_flag_preserved(self, tmp_path):
        item = BlacklistItem("wolf", use_word_boundary=False)
        assert self._round_trip(tmp_path, item).use_word_boundary is False

    def test_whole_prompt_flag_preserved(self, tmp_path):
        item = BlacklistItem("wolf", apply_to_whole_prompt=True)
        assert self._round_trip(tmp_path, item).apply_to_whole_prompt is True

    def test_exception_pattern_preserved(self, tmp_path):
        item = BlacklistItem("wolf", exception_pattern="wolfram")
        assert self._round_trip(tmp_path, item).exception_pattern == "wolfram"

    def test_absent_exception_pattern_stays_none(self, tmp_path):
        assert self._round_trip(tmp_path, BlacklistItem("wolf")).exception_pattern is None

    def test_legacy_two_column_file_still_imports(self, tmp_path):
        """Older exports had only string/enabled; the rest fall back to defaults."""
        path = str(tmp_path / "legacy.csv")
        _write_csv(path, [{"string": "wolf", "enabled": "False"}])
        Blacklist.import_blacklist_csv(path)
        item = Blacklist.TAG_BLACKLIST[0]
        assert item.string == "wolf"
        assert item.enabled is False
        assert item.use_regex is False
        assert item.use_word_boundary is True


# ---------------------------------------------------------------------------
# import / export — JSON round-trip
# ---------------------------------------------------------------------------

class TestJSONRoundTrip:
    def test_single_item_preserved(self, tmp_path):
        _add("bear")
        json_path = str(tmp_path / "blacklist.json")
        Blacklist.export_blacklist_json(json_path)
        Blacklist.TAG_BLACKLIST.clear()

        Blacklist.import_blacklist_json(json_path)
        strings = [item.string for item in Blacklist.TAG_BLACKLIST]
        assert "bear" in strings

    def test_multiple_items_preserved(self, tmp_path):
        _add("fox", "deer", "elk")
        json_path = str(tmp_path / "blacklist.json")
        Blacklist.export_blacklist_json(json_path)
        Blacklist.TAG_BLACKLIST.clear()

        Blacklist.import_blacklist_json(json_path)
        strings = {item.string for item in Blacklist.TAG_BLACKLIST}
        assert strings == {"fox", "deer", "elk"}

    def test_enabled_state_preserved(self, tmp_path):
        Blacklist.add_to_blacklist(BlacklistItem("disabled_tag", enabled=False))
        json_path = str(tmp_path / "blacklist.json")
        Blacklist.export_blacklist_json(json_path)
        Blacklist.TAG_BLACKLIST.clear()

        Blacklist.import_blacklist_json(json_path)
        items = {item.string: item for item in Blacklist.TAG_BLACKLIST}
        assert "disabled_tag" in items
        assert items["disabled_tag"].enabled is False

    def test_exported_file_is_valid_json(self, tmp_path):
        _add("lynx", "puma")
        json_path = str(tmp_path / "blacklist.json")
        Blacklist.export_blacklist_json(json_path)
        with open(json_path, encoding="utf-8") as f:
            data = json.load(f)
        assert isinstance(data, list)
        assert len(data) == 2

    def test_invalid_json_raises(self, tmp_path):
        bad_path = str(tmp_path / "bad.json")
        with open(bad_path, "w") as f:
            f.write('{"not": "a list"}')
        with pytest.raises(ValueError, match="Invalid JSON"):
            Blacklist.import_blacklist_json(bad_path)


# ---------------------------------------------------------------------------
# get_version
# ---------------------------------------------------------------------------

class TestGetVersion:
    def test_version_is_string(self):
        v = Blacklist.get_version()
        assert isinstance(v, str) and v

    def test_version_changes_on_add(self):
        v0 = Blacklist.get_version()
        _add("newitem")
        v1 = Blacklist.get_version()
        assert v0 != v1

    def test_version_changes_on_remove(self):
        _add("removeitem")
        v0 = Blacklist.get_version()
        item = Blacklist.TAG_BLACKLIST[0]
        Blacklist.TAG_BLACKLIST.remove(item)
        # Force cache invalidation (length changed)
        Blacklist._filter_cache.version_cache = None
        v1 = Blacklist.get_version()
        assert v0 != v1

    def test_version_stable_with_unchanged_list(self):
        _add("stable")
        v0 = Blacklist.get_version()
        v1 = Blacklist.get_version()
        assert v0 == v1

    def test_empty_list_has_version(self):
        # Empty blacklist still returns a valid version string
        assert Blacklist.TAG_BLACKLIST == []
        v = Blacklist.get_version()
        assert isinstance(v, str) and v

    def test_same_length_replacement_changes_version(self):
        """The cached version keys on list length, so a swap could go unnoticed."""
        Blacklist.set_blacklist([BlacklistItem("alpha")])
        v0 = Blacklist.get_version()
        Blacklist.set_blacklist([BlacklistItem("omega")])
        assert Blacklist.get_version() != v0

    def test_invalidate_version_cache_forces_recompute(self):
        _add("alpha")
        v0 = Blacklist.get_version()
        Blacklist.TAG_BLACKLIST[0].enabled = False
        Blacklist.invalidate_version_cache()
        assert Blacklist.get_version() != v0

    def test_clear_changes_version(self):
        _add("alpha")
        v0 = Blacklist.get_version()
        Blacklist.clear()
        assert Blacklist.get_version() != v0


# ---------------------------------------------------------------------------
# Filter cache invalidation
#
# The cache is keyed on the concept list plus the blacklist version. Keying on
# the concept list alone meant a result computed under one blacklist was served
# under another -- and the cache persists to disk between sessions.
# ---------------------------------------------------------------------------

class TestFilterCacheInvalidation:
    CONCEPTS = ["wolf", "meadow"]

    def test_filtering_reflects_a_later_add(self):
        before, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" in before
        _add("wolf")
        after, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" not in after

    def test_filtering_reflects_a_later_remove(self):
        _add("wolf")
        before, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" not in before
        Blacklist.remove_item(Blacklist.TAG_BLACKLIST[0])
        after, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" in after

    def test_filtering_reflects_a_same_length_replacement(self):
        """set_blacklist defaults to clear_cache=False, so only the key protects this."""
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        before, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" not in before and "meadow" in before

        Blacklist.set_blacklist([BlacklistItem("meadow")])
        after, _ = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert "wolf" in after
        assert "meadow" not in after

    def test_cache_key_includes_the_blacklist_version(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.filter_concepts(list(self.CONCEPTS))
        keys_before = set(Blacklist._filter_cache.cache.keys())

        Blacklist.set_blacklist([BlacklistItem("meadow")])
        Blacklist.filter_concepts(list(self.CONCEPTS))
        keys_after = set(Blacklist._filter_cache.cache.keys())

        assert keys_after - keys_before, "same concepts under a new blacklist reused the key"

    def test_repeated_identical_call_reuses_the_entry(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.filter_concepts(list(self.CONCEPTS))
        count_after_first = len(Blacklist._filter_cache.cache)
        Blacklist.filter_concepts(list(self.CONCEPTS))
        assert len(Blacklist._filter_cache.cache) == count_after_first
