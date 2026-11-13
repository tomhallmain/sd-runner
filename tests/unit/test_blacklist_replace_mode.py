"""The replace mode, the mode in the filter cache key, and the redo prompt check."""

import pytest

from lib.translations import _
from sd_runner.globals import BlacklistMode, PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistException, BlacklistItem
from sd_runner.workflow_prompts.comfy import WorkflowPromptComfy


@pytest.fixture
def dictionary(monkeypatch):
    """Replace the dictionary with *words* and skip loading the real one."""
    from sd_runner.prompts.concepts import Concepts

    def _set(words):
        monkeypatch.setattr(Concepts, "ALL_WORDS_LIST", list(words))
        monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
    return _set


@pytest.fixture
def prevent_execution(monkeypatch):
    from sd_runner.config import config
    monkeypatch.setattr(config, "blacklist_prevent_execution", True)


# ---------------------------------------------------------------------------
# The mode is part of the filter cache key
# ---------------------------------------------------------------------------

class TestModeInTheCacheKey:
    CONCEPTS = ["grey wolf", "meadow"]

    def test_a_mode_change_applies_to_concepts_already_cached(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.LOG_ONLY)
        kept, _filtered = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert kept == ["grey wolf", "meadow"]

        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        kept, filtered = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert kept == ["meadow"]
        assert filtered == {"grey wolf": "wolf"}

        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(list(self.CONCEPTS))
        assert kept == ["grey", "meadow"]

    def test_the_prefilter_shares_one_entry_across_modes(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.LOG_ONLY)
        Blacklist.filter_concepts(list(self.CONCEPTS), user_prompt=False)
        count = len(Blacklist._filter_cache.cache)
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(list(self.CONCEPTS), user_prompt=False)
        assert kept == ["meadow"]
        assert len(Blacklist._filter_cache.cache) == count


# ---------------------------------------------------------------------------
# Replacing
# ---------------------------------------------------------------------------

class TestReplaceBlacklistedContent:
    def test_the_match_is_replaced_and_the_separator_kept(self):
        item = BlacklistItem("wolf")
        assert item.replace_blacklisted_content("(grey wolf)", "fox") == "(grey fox)"

    def test_the_match_is_found_regardless_of_case(self):
        item = BlacklistItem("wolf")
        assert item.replace_blacklisted_content("Grey Wolf", "fox") == "Grey fox"

    def test_a_tag_without_a_match_is_unchanged(self):
        assert BlacklistItem("wolf").replace_blacklisted_content("meadow", "fox") == "meadow"


class TestReplaceMode:
    def test_a_blocked_word_is_replaced_and_the_order_kept(self, dictionary):
        dictionary(["sunflower"])
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        kept, filtered = Blacklist.filter_concepts(["dusk", "grey wolf", "meadow"])
        assert kept == ["dusk", "grey sunflower", "meadow"]
        assert filtered == {"grey wolf": "wolf"}

    def test_a_blocked_replacement_word_is_drawn_again(self, dictionary, monkeypatch):
        import random
        dictionary(["wolfish", "sunflower"])
        draws = iter(["wolfish", "sunflower"])
        monkeypatch.setattr(random, "choice", lambda _words: next(draws))
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(["grey wolf"])
        assert kept == ["grey sunflower"]

    def test_only_blocked_words_remove_the_match(self, dictionary):
        dictionary(["wolfhound"])
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(["grey wolf", "meadow"])
        assert kept == ["grey", "meadow"]

    def test_no_dictionary_removes_the_match(self, dictionary):
        dictionary([])
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(["grey wolf"])
        assert kept == ["grey"]

    def test_the_concept_list_prefilter_still_drops_whole_tags(self, dictionary):
        dictionary(["sunflower"])
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        kept, _filtered = Blacklist.filter_concepts(["grey wolf", "meadow"], user_prompt=False)
        assert kept == ["meadow"]

    def test_the_users_text_is_left_for_generation(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        text = "grey wolf, meadow"
        assert Blacklist.strip_user_positive_tags(text) == (text, {})

    def test_whole_prompt_items_cannot_be_replaced(self):
        Blacklist.set_blacklist([BlacklistItem("wolf"), BlacklistItem("night sky", apply_to_whole_prompt=True)])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        assert Blacklist.can_replace_all({"grey wolf": "wolf"})
        assert not Blacklist.can_replace_all({"grey wolf": "wolf", "night sky": "night sky"})

    def test_other_modes_do_not_replace(self):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        assert not Blacklist.can_replace_all({"grey wolf": "wolf"})

    def test_the_notice_follows_the_mode(self):
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        assert Blacklist.filtering_notice({"grey wolf": "wolf"}) == _(
            "Blacklisted words in one or more tags were replaced with random words.")
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        assert Blacklist.filtering_notice({"grey wolf": "wolf"}) == _(
            "One or more tags were removed due to blacklist failure.")

    def test_a_taken_prompt_is_replaced(self, dictionary, prevent_execution):
        from sd_runner.prompts.prompter import Prompter
        dictionary(["sunflower"])
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.REPLACE_WORD_OR_PHRASE)
        positive, negative = Prompter.filter_taken_prompt("grey wolf, meadow", "wolf")
        assert positive == "grey sunflower, meadow"
        assert negative == "wolf"


# ---------------------------------------------------------------------------
# Redo: the stored workflow's prompt
# ---------------------------------------------------------------------------

def _workflow(nodes: dict) -> WorkflowPromptComfy:
    prompt = WorkflowPromptComfy.__new__(WorkflowPromptComfy)
    prompt.workflow_filename = "image.png"
    prompt.json = nodes
    return prompt


class TestStoredClipText:
    def test_the_text_at_the_samplers_positive_input(self):
        prompt = _workflow({
            "3": {"class_type": "KSampler", "inputs": {"positive": ["6", 0], "negative": ["7", 0]}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "grey wolf"}},
            "7": {"class_type": "CLIPTextEncode", "inputs": {"text": "blurry"}},
        })
        assert prompt.get_clip_text(positive=True) == "grey wolf"
        assert prompt.get_clip_text(positive=False) == "blurry"

    def test_conditioning_nodes_and_linked_text_are_followed(self):
        prompt = _workflow({
            "3": {"class_type": "KSampler", "inputs": {"positive": ["9", 0]}},
            "9": {"class_type": "FluxGuidance", "inputs": {"conditioning": ["6", 0], "guidance": 3.5}},
            "6": {"class_type": "CLIPTextEncode", "inputs": {"text": ["8", 0]}},
            "8": {"class_type": "PrimitiveStringMultiline", "inputs": {"value": "grey wolf"}},
        })
        assert prompt.get_clip_text() == "grey wolf"
        assert prompt.replace_clip_text("grey fox")
        assert prompt.json["8"]["inputs"]["value"] == "grey fox"

    def test_the_wildcard_processor_is_the_fallback(self):
        prompt = _workflow({
            "1": {"class_type": "ImpactWildcardProcessor",
                  "inputs": {"wildcard_text": "grey wolf", "populated_text": "grey wolf"}},
        })
        assert prompt.get_clip_text() == "grey wolf"
        assert prompt.replace_clip_text("grey fox")
        assert prompt.json["1"]["inputs"] == {"wildcard_text": "grey fox", "populated_text": "grey fox"}

    def test_no_text_is_none(self):
        prompt = _workflow({"3": {"class_type": "KSampler", "inputs": {"positive": ["9", 0]}}})
        assert prompt.get_clip_text() is None
        assert not prompt.replace_clip_text("grey fox")


class TestFilterRedoPositive:
    @staticmethod
    def _filter(positive):
        from sd_runner.generators.base import BaseImageGenerator
        return BaseImageGenerator.filter_redo_positive(None, "image.png", positive)

    def test_a_blocked_tag_is_removed(self, prevent_execution):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        assert self._filter("grey wolf, meadow") == (False, "meadow")

    def test_fail_prompt_raises_as_for_a_taken_prompt(self, prevent_execution):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        Blacklist.set_blacklist_mode(BlacklistMode.FAIL_PROMPT)
        with pytest.raises(BlacklistException):
            self._filter("grey wolf, meadow")

    def test_missing_text_is_skipped_while_the_blacklist_applies(self, prevent_execution):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        assert self._filter(None) == (True, None)

    def test_without_prevent_execution_the_text_is_unchanged(self, monkeypatch):
        from sd_runner.config import config
        monkeypatch.setattr(config, "blacklist_prevent_execution", False)
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        assert self._filter("grey wolf") == (False, "grey wolf")
        assert self._filter(None) == (False, None)

    def test_an_allowed_prompt_mode_leaves_the_text(self, prevent_execution, monkeypatch):
        Blacklist.set_blacklist([BlacklistItem("wolf")])
        monkeypatch.setattr(Blacklist, "is_allowed_prompt_mode", staticmethod(lambda mode: mode == PromptMode.TAKE))
        assert self._filter("grey wolf") == (False, "grey wolf")
