"""
End-to-end check that blacklisted terms cannot reach a generated prompt.

Blacklist filtering happens at two points -- Concepts.sample_whitelisted when a
category is sampled, and Blacklist.filter_concepts on the assembled prompt in
generate_prompt. Both are unit-tested in isolation; this asserts the property
that actually matters, that nothing blacklisted survives the whole pipeline.

Every category file is backed by one controlled vocabulary so the assertions can
be exact. tests/integration/test_prompt_modes.py covers the real concepts/ tree.
"""

import pytest

from sd_runner.blacklist import Blacklist, BlacklistItem
from sd_runner.concepts import Concepts, ConceptConfiguration
from tests.utils import make_prompter
from utils.globals import PromptMode


BLOCKED = ["forbidden", "banned", "verboten"]

VOCABULARY = [
    "amber", "azure", "beacon", "bramble", "canyon", "cedar", "cinder",
    "clover", "cobalt", "copper", "crimson", "dusk", "ember", "fern",
    "flint", "garnet", "glacier", "granite", "harbor", "hollow", "indigo",
    "ivory", "juniper", "lantern", "lichen", "marble", "meadow", "mesa",
    "obsidian", "onyx", "pebble", "quartz", "ridge", "saffron", "sable",
    "thicket", "tundra", "umber", "willow", "zephyr",
] + BLOCKED


@pytest.fixture
def vocabulary(monkeypatch):
    """Back every concept file with one known vocabulary."""
    monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: list(VOCABULARY)))
    monkeypatch.setattr(Concepts, "ALL_WORDS_LIST", list(VOCABULARY))
    monkeypatch.setattr(Concepts, "URBAN_DICTIONARY_CORPUS", [])


@pytest.fixture
def blocked(vocabulary):
    for term in BLOCKED:
        Blacklist.add_item(BlacklistItem(term))
    yield BLOCKED


def make_sfw_prompter(prompt_mode=PromptMode.SFW):
    """No emphasis wrapping, so a blocked term cannot hide inside "(term:1.2)"."""
    return make_prompter(prompt_mode, emphasis_chance=0.0)


# ---------------------------------------------------------------------------
# Category sampling
# ---------------------------------------------------------------------------

class TestSamplingExcludesBlacklisted:
    def test_colors_never_yield_a_blocked_term(self, blocked):
        concepts = Concepts(PromptMode.SFW, get_specific_locations=False)
        for _ in range(50):
            for term in concepts.get_colors(ConceptConfiguration(1, 3)):
                assert term not in blocked

    def test_objects_never_yield_a_blocked_term(self, blocked):
        concepts = Concepts(PromptMode.SFW, get_specific_locations=False)
        for _ in range(50):
            for term in concepts.get_objects(ConceptConfiguration(1, 3)):
                assert term not in blocked

    def test_sampling_still_returns_the_requested_count(self, blocked):
        concepts = Concepts(PromptMode.SFW, get_specific_locations=False)
        for _ in range(25):
            assert 2 <= len(concepts.get_objects(ConceptConfiguration(2, 4))) <= 4

    def test_all_returned_terms_are_from_the_vocabulary(self, blocked):
        concepts = Concepts(PromptMode.SFW, get_specific_locations=False)
        for _ in range(25):
            for term in concepts.get_plants(ConceptConfiguration(1, 3)):
                assert term in VOCABULARY

    def test_no_blacklist_means_blocked_terms_are_reachable(self, vocabulary):
        """Control: the terms are only absent above because they are blacklisted."""
        concepts = Concepts(PromptMode.SFW, get_specific_locations=False)
        seen = set()
        for _ in range(200):
            seen.update(concepts.get_colors(ConceptConfiguration(3, 5)))
        assert seen & set(BLOCKED)


# ---------------------------------------------------------------------------
# Full prompt generation
# ---------------------------------------------------------------------------

class TestGeneratedPromptExcludesBlacklisted:
    def test_no_blocked_term_in_generated_prompt(self, blocked):
        prompter = make_sfw_prompter()
        for _ in range(25):
            positive, _negative = prompter.generate_prompt()
            for term in blocked:
                assert term not in positive

    def test_generated_prompt_is_not_empty(self, blocked):
        prompter = make_sfw_prompter()
        for _ in range(10):
            positive, _negative = prompter.generate_prompt()
            assert positive.strip() != ""

    def test_user_supplied_blocked_term_is_stripped(self, blocked):
        prompter = make_sfw_prompter(PromptMode.FIXED)
        positive, _negative = prompter.generate_prompt(positive="a calm lake, forbidden, dusk")
        assert "forbidden" not in positive
        assert "dusk" in positive

    def test_clean_user_prompt_survives_intact(self, blocked):
        prompter = make_sfw_prompter(PromptMode.FIXED)
        positive, _negative = prompter.generate_prompt(positive="a calm lake, dusk")
        assert "a calm lake" in positive
        assert "dusk" in positive

    def test_expansions_are_resolved(self, blocked):
        prompter = make_sfw_prompter(PromptMode.FIXED)
        for _ in range(20):
            positive, _negative = prompter.generate_prompt(positive="a $color sky")
            assert "$color" not in positive

    def test_expanded_value_is_never_blocked(self, blocked):
        prompter = make_sfw_prompter(PromptMode.FIXED)
        for _ in range(50):
            positive, _negative = prompter.generate_prompt(positive="a $color sky")
            for term in blocked:
                assert term not in positive

    def test_choice_sets_are_resolved(self, blocked):
        prompter = make_sfw_prompter(PromptMode.FIXED)
        for _ in range(20):
            positive, _negative = prompter.generate_prompt(positive="a [[red,blue]] sky")
            assert "[[" not in positive
            assert "]]" not in positive


# ---------------------------------------------------------------------------
# Prompt-mode gating of the blacklist
# ---------------------------------------------------------------------------

class TestAllowInNsfwGating:
    def test_disallow_mode_filters_in_nsfw(self, blocked):
        from utils.globals import BlacklistPromptMode
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.DISALLOW
        whitelist, filtered = Blacklist.filter_concepts(
            ["dusk", "forbidden"], prompt_mode=PromptMode.NSFW
        )
        assert "forbidden" not in whitelist
        assert filtered

    def test_allow_in_nsfw_mode_bypasses_filtering(self, blocked):
        from utils.globals import BlacklistPromptMode
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
        whitelist, filtered = Blacklist.filter_concepts(
            ["dusk", "forbidden"], prompt_mode=PromptMode.NSFW
        )
        assert whitelist == ["dusk", "forbidden"]
        assert filtered == {}

    def test_allow_in_nsfw_still_filters_sfw(self, blocked):
        from utils.globals import BlacklistPromptMode
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
        whitelist, _filtered = Blacklist.filter_concepts(
            ["dusk", "forbidden"], prompt_mode=PromptMode.SFW
        )
        assert "forbidden" not in whitelist
