"""Tests for BlacklistItem's language and which text an item applies to."""

import csv

import pytest

from sd_runner.globals import BlacklistTextOrigin
from sd_runner.prompts.blacklist import (
    Blacklist, BlacklistItem, ModelBlacklistItem, normalize_user_tag,
)


class TestLanguageProperty:
    def test_it_defaults_to_none(self):
        assert BlacklistItem("wort").language is None

    def test_english_normalises_to_none(self):
        assert BlacklistItem("wort", language="en-US").language is None

    def test_a_regional_code_keeps_its_language(self):
        assert BlacklistItem("wort", language="de-AT").language == "de"

    def test_an_invalid_code_applies_everywhere_and_is_kept_for_the_report(self):
        item = BlacklistItem("wort", language="deutsch")
        assert item.language is None
        assert item.invalid_language == "deutsch"

    def test_identity_ignores_the_language(self):
        assert BlacklistItem("wort", language="de") == BlacklistItem("wort")


class TestSerialisation:
    @pytest.mark.parametrize("language", [None, "de"])
    def test_language_round_trips(self, language):
        item = BlacklistItem("wort", language=language)
        assert BlacklistItem.from_dict(item.to_dict()).language == language

    @pytest.mark.parametrize("value", [True, False])
    def test_apply_to_generated_round_trips(self, value):
        item = BlacklistItem("wort", apply_to_generated=value)
        assert BlacklistItem.from_dict(item.to_dict()).apply_to_generated is value

    def test_stored_data_from_before_these_fields_loads(self):
        item = BlacklistItem.from_dict({"string": "wort"})
        assert item.language is None
        assert item.apply_to_generated is True

    def test_a_non_string_language_is_unusable(self):
        assert BlacklistItem.from_dict({"string": "wort", "language": 5}).language is None

    def test_csv_round_trip(self, tmp_path):
        path = str(tmp_path / "bl.csv")
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("wort", language="de", apply_to_generated=False))
        Blacklist.export_blacklist_csv(path)
        Blacklist.TAG_BLACKLIST.clear()
        Blacklist.import_blacklist_csv(path)
        item = Blacklist.TAG_BLACKLIST[0]
        assert item.language == "de"
        assert item.apply_to_generated is False

    def test_an_eight_column_csv_still_imports(self, tmp_path):
        path = tmp_path / "bl.csv"
        columns = list(BlacklistItem.CSV_FIELDNAMES[:8])
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            writer.writerow({name: BlacklistItem("wort").to_dict()[name] for name in columns})
        Blacklist.import_blacklist_csv(str(path))
        item = Blacklist.TAG_BLACKLIST[0]
        assert item.language is None
        assert item.apply_to_generated is True

    def test_model_items_keep_these_fields_out_of_their_stored_data(self):
        data = ModelBlacklistItem("model").to_dict()
        assert "language" not in data
        assert "apply_to_generated" not in data


class TestImportReport:
    def test_it_names_a_narrowed_item(self, tmp_path):
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("wort"))
        path = tmp_path / "bl.csv"
        path.write_text("string,language\nwort,de\n", encoding="utf-8")
        report = Blacklist.import_blacklist_csv(str(path))
        assert [item.string for item in report.narrowed] == ["wort"]

    def test_a_new_item_with_a_language_is_not_narrowed(self, tmp_path):
        path = tmp_path / "bl.csv"
        path.write_text("string,language\nwort,de\n", encoding="utf-8")
        assert Blacklist.import_blacklist_csv(str(path)).narrowed == []

    def test_it_names_an_invalid_language(self, tmp_path):
        path = tmp_path / "bl.csv"
        path.write_text("string,language\nwort,deutsch\n", encoding="utf-8")
        assert Blacklist.import_blacklist_csv(str(path)).invalid_language == ["deutsch"]

    def test_it_names_an_item_scoped_to_nothing(self, tmp_path):
        path = tmp_path / "bl.csv"
        path.write_text("string,apply_to_prompt_tags,apply_to_generated\nwort,False,False\n", encoding="utf-8")
        report = Blacklist.import_blacklist_csv(str(path))
        assert [item.string for item in report.empty_scope] == ["wort"]


class TestAppliesTo:
    def test_an_item_with_no_language_always_applies(self):
        item = BlacklistItem("wort")
        assert item.applies_to(frozenset()) is True
        assert item.applies_to(frozenset({"fr"})) is True

    def test_a_language_item_needs_its_language_in_the_basket(self):
        item = BlacklistItem("wort", language="de")
        assert item.applies_to(frozenset({"de", "fr"})) is True
        assert item.applies_to(frozenset({"fr"})) is False
        assert item.applies_to(frozenset()) is False

    def test_none_is_every_supported_language(self):
        assert BlacklistItem("wort", language="de").applies_to(None) is True


class TestTextOrigin:
    @pytest.mark.parametrize("tags, generated, user_applies, generated_applies", [
        (True, True, True, True),
        (False, True, False, True),
        (True, False, True, False),
    ])
    def test_each_setting(self, tags, generated, user_applies, generated_applies):
        item = BlacklistItem("wort", apply_to_prompt_tags=tags, apply_to_generated=generated)
        assert item.applies_to_origin(BlacklistTextOrigin.USER) is user_applies
        assert item.applies_to_origin(BlacklistTextOrigin.GENERATED) is generated_applies
        assert item.applies_to_origin(BlacklistTextOrigin.EXTERNAL) is True

    def test_both_off_falls_back_to_both_on(self):
        item = BlacklistItem("wort", apply_to_prompt_tags=False, apply_to_generated=False)
        assert item.apply_to_prompt_tags is True
        assert item.apply_to_generated is True
        assert item.scope_was_empty is True


class TestVersion:
    @pytest.mark.parametrize("attribute, value", [
        ("language", "de"),
        ("apply_to_whole_prompt", True),
        ("apply_to_prompt_tags", False),
        ("apply_to_generated", False),
    ])
    def test_it_changes_with_each_field(self, attribute, value):
        item = BlacklistItem("wort")
        Blacklist.TAG_BLACKLIST.append(item)
        Blacklist.invalidate_version_cache()
        before = Blacklist.get_version()
        setattr(item, attribute, value)
        Blacklist.invalidate_version_cache()
        assert Blacklist.get_version() != before


class TestLanguagesInChecks:
    @pytest.fixture(autouse=True)
    def german_item(self):
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("wort", language="de"))

    def test_left_out_means_every_supported_language(self):
        assert Blacklist.find_blacklisted_items("ein wort")
        _whitelist, filtered = Blacklist.filter_concepts(["ein wort"], do_cache=False)
        assert filtered

    def test_a_basket_without_the_language_skips_the_item(self):
        assert Blacklist.find_blacklisted_items("ein wort", frozenset({"fr"})) == {}
        _whitelist, filtered = Blacklist.filter_concepts(["ein wort"], do_cache=False, languages=frozenset())
        assert filtered == {}

    def test_a_basket_with_the_language_applies_the_item(self):
        assert Blacklist.find_blacklisted_items("ein wort", frozenset({"de"}))

    def test_the_filter_cache_does_not_reuse_a_result_across_baskets(self):
        _whitelist, german = Blacklist.filter_concepts(["ein wort"], languages=frozenset({"de"}))
        _whitelist, english = Blacklist.filter_concepts(["ein wort"], languages=frozenset())
        assert german
        assert english == {}

    def test_items_with_a_language_take_no_part_in_the_suffix_check(self, monkeypatch):
        monkeypatch.setattr("sd_runner.prompts.concepts.Concepts.get_dictionary_set", lambda: set())
        assert Blacklist.check_user_prompt_detailed("xwort") == {}

    def test_items_without_a_language_still_take_part(self, monkeypatch):
        monkeypatch.setattr("sd_runner.prompts.concepts.Concepts.get_dictionary_set", lambda: set())
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("global"))
        assert Blacklist.check_user_prompt_detailed("xglobal")


class TestNormalizeUserTag:
    @pytest.mark.parametrize("tag, expected", [
        ("Red Dress", "red dress"),
        ("((red dress))", "red dress"),
        ("[red dress]", "red dress"),
        ("(red dress:1.2)", "red dress"),
        ("  red dress  ", "red dress"),
        ("", ""),
    ])
    def test_it_keeps_only_the_wording(self, tag, expected):
        assert normalize_user_tag(tag) == expected
