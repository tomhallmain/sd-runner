import pytest
from sd_runner.blacklist import BlacklistItem, ModelBlacklistItem


# ---------------------------------------------------------------------------
# Glob / wildcard patterns  (use_regex=True, * treated as .*)
# ---------------------------------------------------------------------------

class TestGlobPatterns:
    def test_star_both_sides_matches_substring(self):
        item = BlacklistItem("*oo*", use_regex=True)
        assert item.matches_tag("balloon") is True

    def test_star_both_sides_no_match(self):
        item = BlacklistItem("*oo*", use_regex=True)
        assert item.matches_tag("apple") is False

    def test_star_prefix_matches_start(self):
        item = BlacklistItem("cat*", use_regex=True)
        assert item.matches_tag("cats") is True

    def test_star_prefix_no_match(self):
        item = BlacklistItem("cat*", use_regex=True)
        assert item.matches_tag("bobcat") is False

    def test_star_suffix_matches_end(self):
        item = BlacklistItem("*cat", use_regex=True)
        assert item.matches_tag("bobcat") is True

    def test_star_suffix_no_match_when_not_at_end(self):
        item = BlacklistItem("*cat", use_regex=True)
        assert item.matches_tag("categories") is False

    def test_glob_case_insensitive(self):
        item = BlacklistItem("*OO*", use_regex=True)
        assert item.matches_tag("balloon") is True


# ---------------------------------------------------------------------------
# Exception patterns
# ---------------------------------------------------------------------------

class TestExceptionPatterns:
    def test_exception_prevents_match(self):
        item = BlacklistItem("cat", exception_pattern="bobcat")
        assert item.matches_tag("bobcat") is False

    def test_exception_does_not_prevent_other_matches(self):
        item = BlacklistItem("cat", exception_pattern="bobcat")
        assert item.matches_tag("big cat") is True

    def test_exception_pattern_regex(self):
        # Exception pattern is itself a regex
        item = BlacklistItem("nude", exception_pattern=r"not\s+nude")
        assert item.matches_tag("not nude scene") is False
        assert item.matches_tag("nude scene") is True

    def test_invalid_exception_pattern_does_not_crash(self):
        # An invalid regex for exception_pattern must not raise; item is constructed normally
        item = BlacklistItem("cat", exception_pattern="[invalid(")
        # exception_pattern is cleared; item still matches normally
        assert item.exception_pattern is None
        assert item.matches_tag("cat") is True

    def test_no_exception_pattern_matches_normally(self):
        item = BlacklistItem("dog")
        assert item.matches_tag("dog") is True
        assert item.exception_pattern is None
        assert item.exception_regex_pattern is None


# ---------------------------------------------------------------------------
# remove_blacklisted_content
# ---------------------------------------------------------------------------

class TestRemoveBlacklistedContent:
    def test_full_tag_match_returns_empty(self):
        item = BlacklistItem("cat", use_word_boundary=False)
        result = item.remove_blacklisted_content("cat")
        assert result == ""

    def test_partial_match_leaves_remainder(self):
        item = BlacklistItem("cat", use_word_boundary=False)
        result = item.remove_blacklisted_content("black cat fur")
        assert "cat" not in result
        assert result != ""

    def test_no_match_unchanged(self):
        item = BlacklistItem("dog")
        result = item.remove_blacklisted_content("big fluffy cat")
        assert result == "big fluffy cat"

    def test_removes_extra_whitespace(self):
        item = BlacklistItem("messy", use_word_boundary=False)
        result = item.remove_blacklisted_content("messy messy text")
        # After removal whitespace should be collapsed, not doubled
        assert "  " not in result


# ---------------------------------------------------------------------------
# to_dict / from_dict round-trip (including optional fields)
# ---------------------------------------------------------------------------

class TestBlacklistItemSerialization:
    def test_round_trip_defaults(self):
        item = BlacklistItem("wolf")
        restored = BlacklistItem.from_dict(item.to_dict())
        assert restored.string == item.string
        assert restored.enabled == item.enabled
        assert restored.use_regex == item.use_regex
        assert restored.use_word_boundary == item.use_word_boundary

    def test_round_trip_with_exception_pattern(self):
        item = BlacklistItem("nude", exception_pattern="not nude")
        restored = BlacklistItem.from_dict(item.to_dict())
        assert restored.exception_pattern == "not nude"

    def test_round_trip_exception_pattern_none(self):
        item = BlacklistItem("cat")
        restored = BlacklistItem.from_dict(item.to_dict())
        assert restored.exception_pattern is None

    def test_from_dict_returns_none_for_missing_string(self):
        assert BlacklistItem.from_dict({"enabled": True}) is None

    def test_from_dict_returns_none_for_non_dict(self):
        assert BlacklistItem.from_dict("not a dict") is None

    def test_from_dict_invalid_types_use_defaults(self):
        data = {
            "string": "test",
            "enabled": "yes",        # should default to True
            "use_regex": "false",    # should default to False
            "use_word_boundary": 1,  # should default to True
        }
        item = BlacklistItem.from_dict(data)
        assert item is not None
        assert item.enabled is True
        assert item.use_regex is False
        assert item.use_word_boundary is True


# ---------------------------------------------------------------------------
# __eq__ and __hash__
# ---------------------------------------------------------------------------

class TestBlacklistItemEquality:
    def test_same_string_equal(self):
        a = BlacklistItem("cat")
        b = BlacklistItem("cat")
        assert a == b

    def test_same_string_case_insensitive_equal(self):
        # Non-regex mode lowercases the string at construction
        a = BlacklistItem("Cat")
        b = BlacklistItem("cat")
        assert a == b

    def test_different_strings_not_equal(self):
        a = BlacklistItem("cat")
        b = BlacklistItem("dog")
        assert a != b

    def test_equals_plain_string(self):
        item = BlacklistItem("cat")
        assert item == "cat"

    def test_not_equal_to_unrelated_type(self):
        assert BlacklistItem("cat") != 42

    def test_hash_equal_for_equal_items(self):
        a = BlacklistItem("wolf")
        b = BlacklistItem("wolf")
        assert hash(a) == hash(b)

    def test_hash_differs_for_different_items(self):
        a = BlacklistItem("wolf")
        b = BlacklistItem("bear")
        assert hash(a) != hash(b)

    def test_set_deduplication(self):
        items = {BlacklistItem("cat"), BlacklistItem("cat"), BlacklistItem("dog")}
        assert len(items) == 2


# ---------------------------------------------------------------------------
# ModelBlacklistItem
# ---------------------------------------------------------------------------

class TestModelBlacklistItem:
    def test_word_boundary_always_false(self):
        item = ModelBlacklistItem("flux")
        assert item.use_word_boundary is False

    def test_basic_matching(self):
        item = ModelBlacklistItem("flux")
        assert item.matches_tag("flux_dev.safetensors") is True
        assert item.matches_tag("sdxl_base.safetensors") is False

    def test_from_dict_round_trip(self):
        item = ModelBlacklistItem("sdxl", enabled=False, use_regex=True)
        restored = ModelBlacklistItem.from_dict(item.to_dict())
        assert restored.string == item.string
        assert restored.enabled == item.enabled
        assert restored.use_regex == item.use_regex
        assert restored.use_word_boundary is False

    def test_from_dict_with_exception_pattern(self):
        item = ModelBlacklistItem("flux", exception_pattern="flux_turbo")
        restored = ModelBlacklistItem.from_dict(item.to_dict())
        assert restored.exception_pattern == "flux_turbo"

    def test_exception_prevents_model_match(self):
        item = ModelBlacklistItem("flux", exception_pattern="flux_turbo")
        assert item.matches_tag("flux_dev.safetensors") is True
        assert item.matches_tag("flux_turbo.safetensors") is False

    def test_equality_with_parent_class(self):
        model_item = ModelBlacklistItem("flux")
        blacklist_item = BlacklistItem("flux")
        # __eq__ compares .string; ModelBlacklistItem inherits it
        assert model_item == blacklist_item
