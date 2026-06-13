import pytest
from sd_runner.expansion import Expansion


@pytest.fixture(autouse=True)
def clear_expansions():
    """Reset the class-level expansions list before and after each test."""
    Expansion.expansions = []
    yield
    Expansion.expansions = []


class TestExpansionValidity:
    def test_valid_with_id_and_text(self):
        e = Expansion(id="greeting", text="hello world")
        assert e.is_valid() is True

    def test_invalid_with_empty_id(self):
        e = Expansion(id="", text="some text")
        assert e.is_valid() is False

    def test_invalid_with_none_id(self):
        e = Expansion(id=None, text="some text")
        assert e.is_valid() is False

    def test_invalid_with_empty_text(self):
        e = Expansion(id="myid", text="")
        assert e.is_valid() is False

    def test_invalid_with_none_text(self):
        e = Expansion(id="myid", text=None)
        assert e.is_valid() is False


class TestExpansionSerialization:
    def test_to_dict_preserves_fields(self):
        e = Expansion(id="style", text="oil painting")
        d = e.to_dict()
        assert d == {"id": "style", "text": "oil painting"}

    def test_from_dict_round_trip(self):
        original = Expansion(id="mood", text="melancholic")
        restored = Expansion.from_dict(original.to_dict())
        assert restored.id == original.id
        assert restored.text == original.text


class TestExpansionRegistry:
    def test_contains_expansion_false_when_empty(self):
        assert Expansion.contains_expansion("anything") is False

    def test_contains_expansion_true_after_adding(self):
        Expansion.expansions.append(Expansion(id="art", text="impressionist"))
        assert Expansion.contains_expansion("art") is True

    def test_contains_expansion_false_for_different_id(self):
        Expansion.expansions.append(Expansion(id="art", text="impressionist"))
        assert Expansion.contains_expansion("style") is False

    def test_get_expansion_text_by_id_returns_text(self):
        Expansion.expansions.append(Expansion(id="color", text="vivid red"))
        assert Expansion.get_expansion_text_by_id("color") == "vivid red"

    def test_get_expansion_text_by_id_raises_for_unknown(self):
        with pytest.raises(Exception, match="No expansion found"):
            Expansion.get_expansion_text_by_id("nonexistent")

    def test_multiple_expansions_independent_lookup(self):
        Expansion.expansions.append(Expansion(id="a", text="alpha"))
        Expansion.expansions.append(Expansion(id="b", text="beta"))
        assert Expansion.get_expansion_text_by_id("a") == "alpha"
        assert Expansion.get_expansion_text_by_id("b") == "beta"
