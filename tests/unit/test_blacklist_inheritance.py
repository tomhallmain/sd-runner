"""A translated line is judged by the line it translates."""

import json

import pytest

from sd_runner.globals import BlacklistMode, PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concept_sets import SourceAnchors
from sd_runner.prompts.concepts import Concepts

ANCHORS = SourceAnchors({"Kuss": frozenset({"kiss"}), "Fluss": frozenset({"river"})}, None, "anchors")


@pytest.fixture
def kiss():
    item = BlacklistItem("kiss")
    Blacklist.TAG_BLACKLIST.append(item)
    return item


def filter_lines(lines, **kwargs):
    return Blacklist.filter_concepts(lines, do_cache=False, user_prompt=False, anchors=ANCHORS, **kwargs)


class TestFiltering:
    def test_a_line_passes_alone_but_not_with_its_source(self, kiss):
        assert Blacklist.filter_concepts(["Kuss"], do_cache=False, user_prompt=False)[1] == {}
        whitelist, filtered = filter_lines(["Kuss"])
        assert whitelist == []
        assert filtered == {"Kuss": "kiss"}

    def test_a_clean_source_leaves_the_line(self, kiss):
        whitelist, filtered = filter_lines(["Fluss"])
        assert whitelist == ["Fluss"]
        assert filtered == {}

    def test_a_line_with_no_source_gets_the_plain_check(self, kiss):
        assert filter_lines(["Baum"])[0] == ["Baum"]

    def test_a_disabled_item_is_not_inherited(self, kiss):
        kiss.enabled = False
        assert filter_lines(["Kuss"])[0] == ["Kuss"]

    def test_a_user_only_item_is_not_inherited(self):
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("kiss", apply_to_generated=False))
        assert filter_lines(["Kuss"])[0] == ["Kuss"]

    def test_a_whole_prompt_item_is_not_inherited(self):
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("kiss", apply_to_whole_prompt=True))
        assert filter_lines(["Kuss"])[0] == ["Kuss"]

    def test_items_of_another_language_do_not_judge_an_english_source(self):
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("kiss", language="de"))
        assert filter_lines(["Kuss"], languages=frozenset({"de"}))[1] == {}

    def test_a_source_in_its_own_language_is_checked_in_that_language(self):
        anchors = SourceAnchors({"Kiss": frozenset({"Kuss"})}, "de", "german source")
        Blacklist.TAG_BLACKLIST.append(BlacklistItem("kuss", language="de"))
        _whitelist, filtered = Blacklist.filter_concepts(["Kiss"], do_cache=False, user_prompt=False, anchors=anchors)
        assert filtered == {"Kiss": "kuss"}

    def test_the_cache_does_not_share_a_result_with_no_anchors(self, kiss):
        Blacklist.filter_concepts(["Kuss"], user_prompt=False)
        assert Blacklist.filter_concepts(["Kuss"], user_prompt=False, anchors=ANCHORS)[1] == {"Kuss": "kiss"}

    def test_remove_word_mode_drops_the_whole_line(self, kiss):
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_WORD_OR_PHRASE)
        whitelist, filtered = Blacklist.filter_concepts(["Kuss"], do_cache=False, anchors=ANCHORS)
        assert whitelist == []
        assert filtered == {"Kuss": "kiss"}

    def test_log_only_mode_keeps_the_line(self, kiss):
        Blacklist.set_blacklist_mode(BlacklistMode.LOG_ONLY)
        whitelist, filtered = Blacklist.filter_concepts(["Kuss"], do_cache=False, anchors=ANCHORS)
        assert whitelist == ["Kuss"]
        assert filtered == {"Kuss": "kiss"}


class TestConceptSet:
    @pytest.fixture
    def translated_set(self, tmp_path, kiss):
        source = tmp_path / "source"
        translated = tmp_path / "translated"
        source.mkdir()
        translated.mkdir()
        (source / "a.txt").write_text("kiss\nriver\n", encoding="utf-8")
        (translated / "a.txt").write_text("Kuss\nFluss\n", encoding="utf-8")
        (translated / "concept_set.json").write_text(
            json.dumps({"language": "de", "source_set": str(source)}), encoding="utf-8",
        )
        return translated

    def test_loading_a_translated_set_sets_its_anchors(self, translated_set):
        Concepts.set_concepts_dir(str(translated_set))
        assert Blacklist.get_source_anchors().sources("Kuss") == frozenset({"kiss"})

    def test_loading_another_set_clears_them(self, translated_set, tmp_path):
        Concepts.set_concepts_dir(str(translated_set))
        Concepts.set_concepts_dir(str(tmp_path))
        assert Blacklist.get_source_anchors() is None

    def test_sampling_never_returns_an_inherited_block(self, translated_set):
        Concepts.set_concepts_dir(str(translated_set))
        for _attempt in range(20):
            assert Concepts.sample_whitelisted(["Kuss", "Fluss"], 1, 1, PromptMode.SFW) == ["Fluss"]

    def test_the_concept_editor_reports_an_inherited_block(self, translated_set):
        Concepts.set_concepts_dir(str(translated_set))
        assert Concepts.find_blacklist_violation("Kuss").string == "kiss"
        assert Concepts.find_blacklist_violation("Fluss") is None
