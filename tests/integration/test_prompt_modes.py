"""
Runs generate_prompt() for every PromptMode against the real concepts/ tree.

The point is the data, not the logic: these exercise the actual concept files a
run would read, so a category file that has gone missing, gone empty, or can
empty itself mid-sample surfaces here rather than aborting a real run. Assertions
are deliberately shallow -- the prompt content is random by design.

Modes excluded and why:
  IMPROVE -- shells out to an LLM
  TAKE    -- needs a source image with embedded metadata (its no-image guard is
             covered below)
"""

import pytest

from sd_runner.concepts import ConceptConfiguration, Concepts
from tests.utils import make_prompter
from utils.globals import PromptMode


GENERATIVE_MODES = [
    PromptMode.SFW,
    PromptMode.RANDOM,
    PromptMode.NONSENSE,
    PromptMode.ANY_ART,
    PromptMode.PAINTERLY,
    PromptMode.ANIME,
    PromptMode.GLITCH,
]

# Modes whose default category ranges guarantee at least one concept. RANDOM and
# NONSENSE are excluded on purpose: the shipped defaults are random_words (0, 5)
# and nonsense (0, 0), so with no category override they can (and for NONSENSE
# always do) produce an empty prompt. They are covered with explicit ranges in
# TestConfiguredRandomAndNonsense below.
ALWAYS_POPULATED_MODES = [
    PromptMode.SFW,
    PromptMode.ANY_ART,
    PromptMode.PAINTERLY,
    PromptMode.ANIME,
    PromptMode.GLITCH,
]


# ---------------------------------------------------------------------------
# Every generative mode produces a usable prompt from the real concept files
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("mode", GENERATIVE_MODES, ids=lambda m: m.value)
class TestGenerativeModes:
    def test_returns_a_string_pair(self, mode):
        positive, negative = make_prompter(mode).generate_prompt()
        assert isinstance(positive, str)
        assert isinstance(negative, str)

    def test_repeated_generation_does_not_raise(self, mode):
        """Repeats to give the random sampling paths a workout."""
        prompter = make_prompter(mode)
        for _ in range(10):
            prompter.generate_prompt()

    def test_no_unresolved_choice_set(self, mode):
        prompter = make_prompter(mode)
        for _ in range(5):
            positive, _negative = prompter.generate_prompt()
            assert "[[" not in positive
            assert "]]" not in positive

    def test_count_increments(self, mode):
        prompter = make_prompter(mode)
        prompter.generate_prompt()
        prompter.generate_prompt()
        assert prompter.count == 2


@pytest.mark.parametrize("mode", ALWAYS_POPULATED_MODES, ids=lambda m: m.value)
class TestModesThatAlwaysProduceContent:
    def test_positive_is_not_empty(self, mode):
        positive, _negative = make_prompter(mode).generate_prompt()
        assert positive.strip() != ""

    def test_stays_non_empty_across_repeats(self, mode):
        prompter = make_prompter(mode)
        for _ in range(10):
            positive, _negative = prompter.generate_prompt()
            assert positive.strip() != ""


class TestConfiguredRandomAndNonsense:
    """RANDOM and NONSENSE with category ranges that guarantee output."""

    def test_random_mode_produces_words(self):
        prompter = make_prompter(
            PromptMode.RANDOM,
            categories={"random_words": ConceptConfiguration(3, 5)},
        )
        for _ in range(5):
            positive, _negative = prompter.generate_prompt()
            assert positive.strip() != ""

    def test_random_mode_appends_to_the_negative(self):
        prompter = make_prompter(
            PromptMode.RANDOM,
            categories={"random_words": ConceptConfiguration(3, 5)},
        )
        _positive, negative = prompter.generate_prompt(negative="ugly")
        assert "boring" in negative
        assert "dull" in negative

    def test_nonsense_mode_produces_words(self):
        prompter = make_prompter(
            PromptMode.NONSENSE,
            categories={"nonsense": ConceptConfiguration(2, 3)},
        )
        for _ in range(5):
            positive, _negative = prompter.generate_prompt()
            assert positive.strip() != ""

    def test_nonsense_words_are_not_real_words(self):
        prompter = make_prompter(
            PromptMode.NONSENSE,
            categories={"nonsense": ConceptConfiguration(2, 3)},
            emphasis_chance=0.0,
        )
        positive, _negative = prompter.generate_prompt()
        dictionary = set(Concepts.ALL_WORDS_LIST)
        for word in [w.strip() for w in positive.split(",") if w.strip()]:
            assert word not in dictionary


# ---------------------------------------------------------------------------
# Colors: the category that could empty itself on a single-item draw
# ---------------------------------------------------------------------------

class TestColorExpansionAgainstRealData:
    def test_repeated_color_expansion_never_raises(self):
        """Smoke pass over the real color list.

        $color draws a single item, and get_colors used to be able to return
        none of them. Hitting that needed a specific draw, so this is a broad
        pass rather than the guard -- the deterministic regression test lives in
        tests/unit/test_concept_expansion_empty.py.
        """
        prompter = make_prompter(PromptMode.FIXED)
        for _ in range(100):
            positive, _negative = prompter.generate_prompt(positive="a $color sky")
            assert positive.strip() != ""

    def test_color_variable_is_expanded(self):
        prompter = make_prompter(PromptMode.FIXED)
        for _ in range(25):
            positive, _negative = prompter.generate_prompt(positive="a $color sky")
            assert "$color" not in positive


# ---------------------------------------------------------------------------
# Modes with specific contracts
# ---------------------------------------------------------------------------

class TestFixedMode:
    def test_passes_the_prompt_through(self):
        positive, _negative = make_prompter(PromptMode.FIXED).generate_prompt(
            positive="a lighthouse at dawn"
        )
        assert positive == "a lighthouse at dawn"

    def test_empty_prompt_stays_empty(self):
        positive, _negative = make_prompter(PromptMode.FIXED).generate_prompt(positive="")
        assert positive == ""


class TestListMode:
    def test_cycles_through_the_list(self):
        items = ["first item", "second item", "third item"]
        prompter = make_prompter(PromptMode.LIST, prompt_list=items)
        assert [prompter.generate_prompt()[0] for _ in range(3)] == items

    def test_wraps_around(self):
        items = ["first item", "second item"]
        prompter = make_prompter(PromptMode.LIST, prompt_list=items)
        results = [prompter.generate_prompt()[0] for _ in range(4)]
        assert results == items + items


class TestTakeMode:
    def test_missing_image_path_raises(self):
        prompter = make_prompter(PromptMode.TAKE)
        with pytest.raises(Exception):
            prompter.generate_prompt(related_image_path="")


# ---------------------------------------------------------------------------
# set_prompt_mode keeps the Prompter and its Concepts in step
# ---------------------------------------------------------------------------

class TestSetPromptMode:
    def test_updates_both_prompter_and_concepts(self):
        prompter = make_prompter(PromptMode.SFW)
        prompter.set_prompt_mode(PromptMode.NONSENSE)
        assert prompter.prompt_mode == PromptMode.NONSENSE
        assert prompter.concepts.prompt_mode == PromptMode.NONSENSE

    def test_generation_follows_the_new_mode(self):
        """The nonsense range has to be set explicitly: the default is (0, 0).

        Asserts the output is nonsense rather than merely non-empty, so this
        actually shows generate_prompt took the new mode's branch.
        """
        prompter = make_prompter(
            PromptMode.SFW,
            categories={"nonsense": ConceptConfiguration(2, 3)},
            emphasis_chance=0.0,
        )
        prompter.set_prompt_mode(PromptMode.NONSENSE)
        positive, _negative = prompter.generate_prompt()
        assert positive.strip() != ""
        dictionary = set(Concepts.ALL_WORDS_LIST)
        for word in [w.strip() for w in positive.split(",") if w.strip()]:
            assert word not in dictionary
