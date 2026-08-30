"""Tests for BlacklistItem.apply_to_prompt_tags.

The property answers "is this item checked against what the user typed?".
Off, the item still filters generated content -- concepts, expansions, the
random vocabulary -- but leaves the user's own prompt tags alone. It defaults
on, so nothing about an existing blacklist changes.
"""

from __future__ import annotations

import pytest

from sd_runner.blacklist import Blacklist, BlacklistItem


def add_item(string: str, **kwargs) -> BlacklistItem:
    """Append an item to the live blacklist (reset between tests by conftest)."""
    item = BlacklistItem(string, **kwargs)
    Blacklist.TAG_BLACKLIST.append(item)
    return item


# ---------------------------------------------------------------------------
# The property itself
# ---------------------------------------------------------------------------

class TestPropertyDefaults:
    def test_it_defaults_to_on(self):
        """Every item before this existed applied to the user's prompt tags."""
        assert BlacklistItem("bad word").apply_to_prompt_tags is True

    def test_it_can_be_turned_off(self):
        assert BlacklistItem("bad word", apply_to_prompt_tags=False).apply_to_prompt_tags is False

    def test_it_is_independent_of_apply_to_whole_prompt(self):
        """Different axes: what to match against, versus how to match."""
        item = BlacklistItem("bad word", apply_to_whole_prompt=True, apply_to_prompt_tags=False)
        assert item.apply_to_whole_prompt is True
        assert item.apply_to_prompt_tags is False


class TestSerialization:
    def test_to_dict_includes_it(self):
        assert BlacklistItem("bad word").to_dict()["apply_to_prompt_tags"] is True

    @pytest.mark.parametrize("value", [True, False])
    def test_it_round_trips(self, value):
        item = BlacklistItem("bad word", apply_to_prompt_tags=value)
        assert BlacklistItem.from_dict(item.to_dict()).apply_to_prompt_tags is value

    def test_an_item_stored_before_the_property_existed_applies_to_prompt_tags(self):
        """Missing means True, or an upgrade would quietly stop filtering."""
        assert BlacklistItem.from_dict({"string": "bad word"}).apply_to_prompt_tags is True

    def test_a_non_bool_value_falls_back_to_on(self):
        data = {"string": "bad word", "apply_to_prompt_tags": "no"}
        assert BlacklistItem.from_dict(data).apply_to_prompt_tags is True

    def test_it_is_a_csv_column(self):
        assert "apply_to_prompt_tags" in BlacklistItem.CSV_FIELDNAMES

    @pytest.mark.parametrize("text,expected", [("True", True), ("False", False)])
    def test_csv_import_coerces_the_text_back(self, text, expected):
        item = BlacklistItem.from_csv_row({"string": "bad word", "apply_to_prompt_tags": text})
        assert item.apply_to_prompt_tags is expected

    def test_a_csv_without_the_column_still_imports(self):
        """An export written before the property existed."""
        item = BlacklistItem.from_csv_row({"string": "bad word", "enabled": "True"})
        assert item.apply_to_prompt_tags is True


# ---------------------------------------------------------------------------
# What it changes: the user's own prompt tags
# ---------------------------------------------------------------------------

class TestUserPromptChecking:
    def test_an_applying_item_is_found_in_the_users_tags(self):
        add_item("bad word")
        assert Blacklist.find_blacklisted_items("good tag, bad word")

    def test_an_exempted_item_is_not_found_in_the_users_tags(self):
        add_item("bad word", apply_to_prompt_tags=False)
        assert Blacklist.find_blacklisted_items("good tag, bad word") == {}

    def test_exempting_one_item_does_not_exempt_the_others(self):
        add_item("bad word", apply_to_prompt_tags=False)
        add_item("worse word")
        result = Blacklist.find_blacklisted_items("bad word, worse word")
        assert "worse word" in result
        assert "bad word" not in result

    def test_a_disabled_item_is_still_ignored_either_way(self):
        add_item("bad word", enabled=False, apply_to_prompt_tags=True)
        assert Blacklist.find_blacklisted_items("bad word") == {}

    def test_an_exempted_whole_prompt_item_is_not_found_either(self):
        """The whole-prompt branch is a separate loop and needs the same gate."""
        add_item(
            "bad word",
            use_space_as_optional_nonword=True,
            apply_to_whole_prompt=True,
            apply_to_prompt_tags=False,
        )
        assert Blacklist.find_blacklisted_items("bad, word") == {}

    def test_an_applying_whole_prompt_item_is_still_found(self):
        add_item(
            "bad word",
            use_space_as_optional_nonword=True,
            apply_to_whole_prompt=True,
        )
        assert Blacklist.find_blacklisted_items("bad, word")


class TestDetailedUserPromptChecking:
    """The obfuscation pass over the user's tags honours it too.

    The dictionary is emptied so "bcat" counts as an unknown word and gets the
    truncation treatment, the same way the existing detailed-check tests do it.
    """

    @pytest.fixture(autouse=True)
    def empty_dictionary(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.concepts.Concepts.get_dictionary_set", lambda: set()
        )

    def test_an_applying_item_is_caught_through_obfuscation(self):
        add_item("cat")
        assert Blacklist.check_user_prompt_detailed("bcat")

    def test_an_exempted_item_is_not_caught_through_obfuscation(self):
        add_item("cat", apply_to_prompt_tags=False)
        assert Blacklist.check_user_prompt_detailed("bcat") == {}


# ---------------------------------------------------------------------------
# What it does not change: generated content
# ---------------------------------------------------------------------------

class TestGeneratedContentStillFiltered:
    def test_an_exempted_item_still_filters_concepts(self):
        """The whole point: exempt the user's wording, not the app's."""
        add_item("bad word", apply_to_prompt_tags=False)
        # user_prompt=False is the generated-content path, and it pins the
        # filter mode so the assertion does not depend on the configured one.
        whitelist, filtered = Blacklist.filter_concepts(
            ["good word", "bad word"], do_cache=False, user_prompt=False
        )
        assert "bad word" in filtered
        assert "bad word" not in whitelist

    def test_an_exempted_item_is_still_a_violation_for_a_single_string(self):
        """get_violation_item is not user-prompt specific and stays ungated."""
        add_item("bad word", apply_to_prompt_tags=False)
        assert Blacklist.get_violation_item("bad word") is not None
