"""Tests for BlacklistItem.apply_to_whole_prompt and related Blacklist logic."""

from __future__ import annotations

import pytest

from sd_runner.blacklist import Blacklist, BlacklistItem


# ---------------------------------------------------------------------------
# BlacklistItem serialisation
# ---------------------------------------------------------------------------

class TestBlacklistItemSerialization:
    def test_to_dict_includes_apply_to_whole_prompt_false(self):
        item = BlacklistItem("bad word")
        assert item.to_dict()["apply_to_whole_prompt"] is False

    def test_to_dict_includes_apply_to_whole_prompt_true(self):
        item = BlacklistItem("bad word", apply_to_whole_prompt=True)
        assert item.to_dict()["apply_to_whole_prompt"] is True

    def test_from_dict_roundtrip_true(self):
        item = BlacklistItem("bad word", apply_to_whole_prompt=True)
        restored = BlacklistItem.from_dict(item.to_dict())
        assert restored.apply_to_whole_prompt is True

    def test_from_dict_roundtrip_false(self):
        item = BlacklistItem("bad word", apply_to_whole_prompt=False)
        restored = BlacklistItem.from_dict(item.to_dict())
        assert restored.apply_to_whole_prompt is False

    def test_from_dict_defaults_to_false_when_key_absent(self):
        data = {"string": "bad word"}
        item = BlacklistItem.from_dict(data)
        assert item.apply_to_whole_prompt is False

    def test_from_dict_ignores_non_bool_value(self):
        data = {"string": "bad word", "apply_to_whole_prompt": "yes"}
        item = BlacklistItem.from_dict(data)
        assert item.apply_to_whole_prompt is False


# ---------------------------------------------------------------------------
# BlacklistItem.find_match_text
# ---------------------------------------------------------------------------

class TestFindMatchText:
    def test_returns_matched_substring(self):
        item = BlacklistItem("bad", use_word_boundary=True)
        assert item.find_match_text("something bad here") == "bad"

    def test_returns_none_when_no_match(self):
        item = BlacklistItem("bad", use_word_boundary=True)
        assert item.find_match_text("something good here") is None

    def test_strips_boundary_character(self):
        item = BlacklistItem("bad phrase", use_word_boundary=True, use_space_as_optional_nonword=True)
        result = item.find_match_text("really bad phrase done")
        assert result == "bad phrase"

    def test_case_insensitive_non_regex(self):
        item = BlacklistItem("Bad", use_regex=False, use_word_boundary=False)
        assert item.find_match_text("BAD content") == "bad"

    def test_regex_item_returns_match(self):
        item = BlacklistItem(r"b.d", use_regex=True, use_word_boundary=False)
        result = item.find_match_text("abc bad def")
        assert result is not None and result.startswith("b") and result.endswith("d")


# ---------------------------------------------------------------------------
# find_blacklisted_items — whole-prompt vs per-tag behaviour
# ---------------------------------------------------------------------------

class TestFindBlacklistedItemsWholePrompt:
    def _add_item(self, string: str, **kwargs) -> BlacklistItem:
        item = BlacklistItem(string, **kwargs)
        Blacklist.TAG_BLACKLIST.append(item)
        return item

    def test_per_tag_item_matches_individual_tag(self):
        self._add_item("bad word", use_word_boundary=True, use_space_as_optional_nonword=True)
        result = Blacklist.find_blacklisted_items("good tag, bad word, another tag")
        assert "bad word" in result

    def test_per_tag_item_does_not_match_cross_tag_pattern(self):
        # "bad" and "word" are separate tags — a per-tag item "bad word" should not match
        self._add_item("bad word", use_word_boundary=True, use_space_as_optional_nonword=True)
        result = Blacklist.find_blacklisted_items("bad, word")
        assert not result

    def test_whole_prompt_item_matches_cross_tag_pattern(self):
        self._add_item(
            "bad word",
            use_word_boundary=True,
            use_space_as_optional_nonword=True,
            apply_to_whole_prompt=True,
        )
        result = Blacklist.find_blacklisted_items("bad, word")
        assert result  # "bad word" spans the comma boundary in the raw text

    def test_whole_prompt_item_uses_matched_substring_as_key(self):
        self._add_item(
            "bad",
            use_word_boundary=True,
            apply_to_whole_prompt=True,
        )
        result = Blacklist.find_blacklisted_items("something bad here")
        # key should be the matched substring, not the entire prompt
        assert "bad" in result

    def test_whole_prompt_item_skipped_in_per_tag_loop(self):
        # A whole-prompt item should NOT produce false positives when
        # the pattern happens to match an individual tag.
        # It should still appear in the result (matched via the whole-prompt pass),
        # but the mechanism should be the whole-prompt pass, not the per-tag loop.
        # Here we verify the result contains the match regardless of which loop caught it.
        self._add_item("bad", apply_to_whole_prompt=True, use_word_boundary=True)
        result = Blacklist.find_blacklisted_items("bad, good")
        assert result  # whole-prompt pass catches it

    def test_per_tag_item_is_skipped_for_whole_prompt_check(self):
        # A per-tag item should not fire on the full prompt text with a comma in between
        self._add_item("alpha, beta", use_regex=False, use_word_boundary=False, apply_to_whole_prompt=False)
        result = Blacklist.find_blacklisted_items("alpha, beta")
        # the per-tag loop splits on comma, so neither "alpha" nor "beta" alone matches "alpha, beta"
        assert not result

    def test_disabled_whole_prompt_item_ignored(self):
        self._add_item("bad word", apply_to_whole_prompt=True, enabled=False)
        result = Blacklist.find_blacklisted_items("bad word")
        assert not result

    def test_multiple_whole_prompt_matches_all_recorded(self):
        self._add_item("alpha", use_word_boundary=True, apply_to_whole_prompt=True)
        self._add_item("beta", use_word_boundary=True, apply_to_whole_prompt=True)
        result = Blacklist.find_blacklisted_items("alpha, beta")
        assert len(result) == 2

    def test_mixed_per_tag_and_whole_prompt_items(self):
        self._add_item("per tag item", use_word_boundary=True, use_space_as_optional_nonword=True)
        self._add_item("whole item", use_word_boundary=True, use_space_as_optional_nonword=True, apply_to_whole_prompt=True)
        result = Blacklist.find_blacklisted_items("per tag item, whole item")
        # Both should fire
        assert len(result) == 2


# ---------------------------------------------------------------------------
# _filter_concepts_cached — whole-prompt items must be skipped
# ---------------------------------------------------------------------------

class TestFilterConceptsSkipsWholePromptItems:
    def test_whole_prompt_item_does_not_filter_individual_concept(self):
        item = BlacklistItem("bad", use_word_boundary=True, apply_to_whole_prompt=True)
        Blacklist.TAG_BLACKLIST.append(item)
        whitelist, filtered = Blacklist._filter_concepts_cached(("bad", "good"), do_cache=False)
        # whole-prompt item must not filter individual concepts
        assert "bad" in whitelist
        assert not filtered

    def test_per_tag_item_still_filters_individual_concept(self):
        item = BlacklistItem("bad", use_word_boundary=True, apply_to_whole_prompt=False)
        Blacklist.TAG_BLACKLIST.append(item)
        whitelist, filtered = Blacklist._filter_concepts_cached(("bad", "good"), do_cache=False)
        assert "bad" not in whitelist
        assert "bad" in filtered
