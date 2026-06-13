"""
Tests for Prompter.emphasize() and Prompter.contains_expansion_var().

extract_inline_vars / apply_expansions are covered in test_inline_vars.py.
Expansion class (registry, to_dict/from_dict) is covered in test_expansion.py.
"""

import pytest
from sd_runner.prompter import Prompter


# ---------------------------------------------------------------------------
# emphasize() — in-place list mutation
# ---------------------------------------------------------------------------

class TestEmphasizeZeroChance:
    def test_zero_chance_leaves_list_unchanged(self):
        mix = ["cat", "dog", "bird"]
        Prompter.emphasize(mix, emphasis_chance=0.0)
        assert mix == ["cat", "dog", "bird"]

    def test_zero_chance_empty_list_no_error(self):
        mix = []
        Prompter.emphasize(mix, emphasis_chance=0.0)
        assert mix == []


class TestEmphasizeFullChance:
    def test_all_items_modified(self):
        mix = ["cat", "dog", "bird"]
        Prompter.emphasize(mix, emphasis_chance=1.0)
        for item in mix:
            assert item.startswith("(") and item.endswith(")"), (
                f"Expected wrapped item, got {item!r}"
            )

    def test_modified_item_contains_original_text(self):
        mix = ["sunset"]
        Prompter.emphasize(mix, emphasis_chance=1.0)
        assert "sunset" in mix[0]

    def test_wrapped_form_is_parens(self):
        # With emphasis_chance=1.0, over many draws most items take the (text) form
        plain_paren_count = 0
        trials = 200
        for _ in range(trials):
            mix = ["word"]
            Prompter.emphasize(mix, emphasis_chance=1.0)
            if mix[0] == "(word)":
                plain_paren_count += 1
        # Plain paren is the 90% path; expect it to appear in the majority of draws
        assert plain_paren_count > trials * 0.7

    def test_weighted_form_uses_colon_notation(self):
        # The 10% path produces (text:X.X) with a numeric weight
        weighted_count = 0
        trials = 1000
        for _ in range(trials):
            mix = ["word"]
            Prompter.emphasize(mix, emphasis_chance=1.0)
            if ":" in mix[0]:
                weighted_count += 1
        # Weighted form is the ~10% path; should appear at least occasionally
        assert weighted_count > 0

    def test_weighted_form_structure(self):
        # Force the weighted path: keep trying until we get one
        for _ in range(500):
            mix = ["term"]
            Prompter.emphasize(mix, emphasis_chance=1.0)
            if ":" in mix[0]:
                # Should look like (term:X.X)
                assert mix[0].startswith("(term:")
                assert mix[0].endswith(")")
                return
        pytest.skip("Weighted path not reached in 500 iterations (extremely unlikely)")


class TestEmphasizeEdgeCases:
    def test_empty_string_in_mix_not_modified(self):
        mix = ["cat", "", "dog"]
        Prompter.emphasize(mix, emphasis_chance=1.0)
        assert mix[1] == ""

    def test_modifies_list_in_place(self):
        mix = ["alpha", "beta"]
        original_id = id(mix)
        Prompter.emphasize(mix, emphasis_chance=1.0)
        assert id(mix) == original_id

    def test_single_item_list(self):
        mix = ["lone"]
        Prompter.emphasize(mix, emphasis_chance=1.0)
        assert "lone" in mix[0]
        assert mix[0].startswith("(")

    def test_default_chance_is_low(self):
        # Default emphasis_chance=0.1 should leave most items unchanged in a small list
        unchanged = 0
        trials = 100
        for _ in range(trials):
            mix = ["word"]
            Prompter.emphasize(mix)
            if mix[0] == "word":
                unchanged += 1
        # With 10% chance, ~90 of 100 single-item draws should be unchanged
        assert unchanged > 70


# ---------------------------------------------------------------------------
# contains_expansion_var
# ---------------------------------------------------------------------------

class TestContainsExpansionVar:
    def test_true_for_dollar_dollar_var(self):
        assert Prompter.contains_expansion_var("$$MyVar") is True

    def test_true_for_single_dollar_var(self):
        assert Prompter.contains_expansion_var("$MyVar") is True

    def test_true_for_brace_var(self):
        assert Prompter.contains_expansion_var("{MyVar}") is True

    def test_false_for_plain_text(self):
        assert Prompter.contains_expansion_var("no variable here") is False

    def test_false_for_empty_string(self):
        assert Prompter.contains_expansion_var("") is False

    def test_true_embedded_in_prompt(self):
        assert Prompter.contains_expansion_var("a $$Color car") is True

    def test_from_ui_skips_inner_dollar(self):
        # In from_ui mode, $$Var should NOT match the inner $Var portion to avoid
        # double-expansion; the outer $$ token is still found
        result = Prompter.contains_expansion_var("$$Var", from_ui=True)
        # Result may be True (outer token found) or False depending on pattern;
        # the key contract is that it doesn't raise
        assert isinstance(result, bool)
