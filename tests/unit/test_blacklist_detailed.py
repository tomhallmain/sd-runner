import json
import csv
import pytest

from sd_runner.blacklist import Blacklist, BlacklistItem


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
        "sd_runner.concepts.Concepts.get_dictionary_set",
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
# import — CSV  (tested via manually written files)
#
# NOTE: export_blacklist_csv() uses csv.DictWriter without extrasaction='ignore',
# so it raises ValueError when BlacklistItem.to_dict() returns fields beyond
# ['string', 'enabled'].  The export bug is documented by the xfail test below;
# the import tests are written against hand-crafted CSV files to stay independent.
# ---------------------------------------------------------------------------

def _write_csv(path: str, rows: list[dict]) -> None:
    """Write a minimal CSV file in the format import_blacklist_csv expects."""
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
        # Empty list never calls writerow(), so no extrasaction error.
        csv_path = str(tmp_path / "empty.csv")
        Blacklist.export_blacklist_csv(csv_path)
        with open(csv_path, encoding="utf-8") as f:
            content = f.read()
        assert "string" in content
        lines = [ln for ln in content.splitlines() if ln.strip()]
        assert len(lines) == 1  # header only

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "export_blacklist_csv uses csv.DictWriter(fieldnames=['string','enabled']) "
            "without extrasaction='ignore', but BlacklistItem.to_dict() returns extra "
            "fields (use_regex, use_word_boundary, etc.), causing ValueError."
        ),
    )
    def test_export_nonempty_list_raises(self, tmp_path):
        _add("cat")
        Blacklist.export_blacklist_csv(str(tmp_path / "blacklist.csv"))


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
