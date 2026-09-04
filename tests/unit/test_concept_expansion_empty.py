"""
Regression tests for empty concept categories reaching random.choice().

Concept getters can legitimately return an empty list, and _select_concept used
to call random.choice() on the result unguarded, aborting an entire run with
"IndexError: Cannot choose from an empty sequence". get_colors was the one
category that could empty itself: with a single-item draw it would sample one
color and then drop it if it happened to be "rainbow".
"""

import pytest

from sd_runner.prompts.concepts import Concepts, ConceptConfiguration
from sd_runner.prompts.prompter import Prompter
from utils.globals import PromptMode


@pytest.fixture
def concepts(monkeypatch):
    """A Concepts instance whose every category file yields exactly ["rainbow"]."""
    monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: ["rainbow"]))
    monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
    return Concepts(PromptMode.SFW, get_specific_locations=False)


@pytest.fixture
def empty_concepts(monkeypatch):
    """A Concepts instance whose colors category comes back empty."""
    monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
    monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: ["blue", "green"]))
    c = Concepts(PromptMode.SFW, get_specific_locations=False)
    monkeypatch.setattr(
        type(c), "get_colors", lambda self, concept_config, multiplier=1.0: []
    )
    return c


# ---------------------------------------------------------------------------
# get_colors must not empty itself
# ---------------------------------------------------------------------------

class TestGetColorsNeverEmptiesASingleDraw:
    def test_single_draw_of_rainbow_is_kept(self, concepts):
        """A (1, 1) draw that lands on "rainbow" must still return one color."""
        for _ in range(50):
            colors = concepts.get_colors(ConceptConfiguration(1, 1))
            assert colors == ["rainbow"]

    def test_rainbow_still_dropped_from_larger_draws(self, monkeypatch):
        """The frequency-halving behaviour is preserved when more than one is drawn."""
        monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
        palette = ["rainbow", "blue", "green", "red", "gold"]
        monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: list(palette)))
        c = Concepts(PromptMode.SFW, get_specific_locations=False)

        saw_dropped = False
        for _ in range(200):
            colors = c.get_colors(ConceptConfiguration(5, 5))
            assert len(colors) >= 1
            if "rainbow" not in colors:
                saw_dropped = True
        assert saw_dropped, "rainbow was never dropped from a multi-color draw"


# ---------------------------------------------------------------------------
# _select_concept / _choose tolerate an empty category
# ---------------------------------------------------------------------------

class TestChooseHandlesEmpty:
    def test_choose_returns_none_for_empty_list(self):
        assert Prompter._choose([]) is None

    def test_choose_returns_none_for_none(self):
        assert Prompter._choose(None) is None

    def test_choose_returns_the_only_item(self):
        assert Prompter._choose(["solo"]) == "solo"

    def test_choose_returns_a_member(self):
        options = ["a", "b", "c"]
        for _ in range(20):
            assert Prompter._choose(options) in options


class TestSelectConceptWithEmptyCategory:
    def test_returns_none_instead_of_raising(self, empty_concepts):
        assert Prompter._select_concept("color", empty_concepts) is None

    def test_get_concept_expansion_returns_none(self, empty_concepts):
        assert Prompter._get_concept_expansion("color", empty_concepts) is None

    def test_unknown_variable_name_returns_none(self, concepts):
        assert Prompter._select_concept("not_a_category", concepts) is None

    def test_number_variable_does_not_touch_concepts(self, empty_concepts):
        result = Prompter._select_concept("number", empty_concepts)
        assert result is not None
        assert 1 <= int(result) <= 999


# ---------------------------------------------------------------------------
# End to end: expansion leaves the variable in place rather than aborting
# ---------------------------------------------------------------------------

class TestApplyExpansionsWithEmptyCategory:
    def test_does_not_raise(self, empty_concepts):
        result = Prompter.apply_expansions("a $color sunset", concepts=empty_concepts)
        assert isinstance(result, str)

    def test_unexpandable_variable_is_left_alone(self, empty_concepts):
        result = Prompter.apply_expansions("a $color sunset", concepts=empty_concepts)
        assert "$color" in result

    def test_populated_category_still_expands(self, concepts):
        result = Prompter.apply_expansions("a $color sunset", concepts=concepts)
        assert "$color" not in result
        assert "rainbow" in result
