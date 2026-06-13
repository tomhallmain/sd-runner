import pytest
from unittest.mock import patch

from sd_runner.prompter import Prompter


# ---------------------------------------------------------------------------
# contains_choice_set
# ---------------------------------------------------------------------------

class TestContainsChoiceSet:
    def test_true_for_comma_separated(self):
        assert Prompter.contains_choice_set("[[a,b,c]]") is True

    def test_true_for_pipe_separated(self):
        assert Prompter.contains_choice_set("[[x|y|z]]") is True

    def test_true_for_integer_range(self):
        assert Prompter.contains_choice_set("[[1--5]]") is True

    def test_true_for_float_range(self):
        assert Prompter.contains_choice_set("[[0.0--1.0--0.25]]") is True

    def test_true_for_char_range(self):
        assert Prompter.contains_choice_set("[[a--e]]") is True

    def test_true_embedded_in_longer_text(self):
        assert Prompter.contains_choice_set("a beautiful [[red,blue]] sky") is True

    def test_false_for_single_brackets(self):
        assert Prompter.contains_choice_set("[a,b,c]") is False

    def test_false_for_plain_text(self):
        assert Prompter.contains_choice_set("no brackets here") is False

    def test_false_for_empty_string(self):
        assert Prompter.contains_choice_set("") is False

    def test_false_for_unmatched_open(self):
        assert Prompter.contains_choice_set("[[a,b") is False

    def test_false_for_unmatched_close(self):
        assert Prompter.contains_choice_set("a,b]]") is False


# ---------------------------------------------------------------------------
# apply_choices — basic selection
# ---------------------------------------------------------------------------

class TestApplyChoicesSelection:
    def test_result_is_one_of_the_options(self):
        result = Prompter.apply_choices("[[alpha,beta,gamma]]")
        assert result in ("alpha", "beta", "gamma")

    def test_pipe_separated_options(self):
        result = Prompter.apply_choices("[[red|green|blue]]")
        assert result in ("red", "green", "blue")

    def test_all_options_reachable(self):
        options = {"cat", "dog", "bird"}
        seen = set()
        for _ in range(200):
            seen.add(Prompter.apply_choices("[[cat,dog,bird]]"))
        assert seen == options

    def test_text_outside_brackets_preserved(self):
        result = Prompter.apply_choices("prefix [[a,b]] suffix")
        assert result.startswith("prefix ")
        assert result.endswith(" suffix")
        assert result[7:-7] in ("a", "b")

    def test_single_option_returns_that_option(self):
        assert Prompter.apply_choices("[[only]]") == "only"

    def test_no_choice_set_unchanged(self):
        text = "a plain prompt with no brackets"
        assert Prompter.apply_choices(text) == text

    def test_two_option_whitespace_stripped(self):
        result = Prompter.apply_choices("[[ cat , dog ]]")
        assert result in ("cat", "dog")


# ---------------------------------------------------------------------------
# apply_choices — weighted choices
# ---------------------------------------------------------------------------

class TestApplyChoicesWeighted:
    def test_weighted_option_more_frequent(self):
        counts = {"a": 0, "b": 0}
        for _ in range(1000):
            counts[Prompter.apply_choices("[[a:3,b:1]]")] += 1
        # a has 3× the weight; expect it to appear >60% of the time
        assert counts["a"] > counts["b"] * 1.5

    def test_equal_weights_uniform(self):
        seen = set()
        for _ in range(200):
            seen.add(Prompter.apply_choices("[[x:1,y:1,z:1]]"))
        assert seen == {"x", "y", "z"}


# ---------------------------------------------------------------------------
# apply_choices — integer range expansion
# ---------------------------------------------------------------------------

class TestApplyChoicesRangeInt:
    def test_basic_int_range_in_bounds(self):
        for _ in range(100):
            result = Prompter.apply_choices("[[1--5]]")
            assert result in ("1", "2", "3", "4", "5")

    def test_int_range_all_values_reachable(self):
        seen = set()
        for _ in range(500):
            seen.add(Prompter.apply_choices("[[1--5]]"))
        assert seen == {"1", "2", "3", "4", "5"}

    def test_int_range_with_step_evens_only(self):
        for _ in range(100):
            result = Prompter.apply_choices("[[0--10--2]]")
            assert int(result) % 2 == 0
            assert 0 <= int(result) <= 10

    def test_int_range_with_step_all_values(self):
        seen = set()
        for _ in range(500):
            seen.add(Prompter.apply_choices("[[0--10--2]]"))
        assert seen == {"0", "2", "4", "6", "8", "10"}

    def test_single_value_range(self):
        assert Prompter.apply_choices("[[3--3]]") == "3"


# ---------------------------------------------------------------------------
# apply_choices — float range expansion
# ---------------------------------------------------------------------------

class TestApplyChoicesRangeFloat:
    _EXPECTED_FLOATS = {"0.00", "0.25", "0.50", "0.75", "1.00"}

    def test_float_range_produces_valid_value(self):
        for _ in range(100):
            result = Prompter.apply_choices("[[0.00--1.00--0.25]]")
            assert result in self._EXPECTED_FLOATS

    def test_float_range_all_values_reachable(self):
        seen = set()
        for _ in range(500):
            seen.add(Prompter.apply_choices("[[0.00--1.00--0.25]]"))
        assert seen == self._EXPECTED_FLOATS

    def test_float_range_decimal_precision_preserved(self):
        for _ in range(50):
            result = Prompter.apply_choices("[[0.0--1.0--0.25]]")
            # Must have at least one decimal place
            assert "." in result


# ---------------------------------------------------------------------------
# apply_choices — character range expansion
# ---------------------------------------------------------------------------

class TestApplyChoicesRangeChar:
    def test_char_range_in_set(self):
        for _ in range(100):
            result = Prompter.apply_choices("[[a--e]]")
            assert result in ("a", "b", "c", "d", "e")

    def test_char_range_all_values_reachable(self):
        seen = set()
        for _ in range(500):
            seen.add(Prompter.apply_choices("[[a--e]]"))
        assert seen == {"a", "b", "c", "d", "e"}

    def test_single_char_range(self):
        assert Prompter.apply_choices("[[z--z]]") == "z"


# ---------------------------------------------------------------------------
# apply_choices — range ambiguity (comma/pipe must block range parsing)
# ---------------------------------------------------------------------------

class TestApplyChoicesRangeAmbiguity:
    def test_comma_in_brackets_not_a_range(self):
        # [[1--5,x]] has a comma so the range parser must reject it;
        # the whole thing is treated as a choice set with two options.
        result = Prompter.apply_choices("[[1--5,x]]")
        assert result in ("1--5", "x")

    def test_pipe_in_brackets_not_a_range(self):
        result = Prompter.apply_choices("[[a--z|q]]")
        assert result in ("a--z", "q")


# ---------------------------------------------------------------------------
# apply_choices — nested and multiple sets
# ---------------------------------------------------------------------------

class TestApplyChoicesNested:
    def test_nested_double_brackets_all_leaf_values(self):
        # [[a,[[b,c]]]] — inner [[b,c]] becomes b or c; outer selects from {a,b,c}
        seen = set()
        for _ in range(500):
            seen.add(Prompter.apply_choices("[[a,[[b,c]]]]"))
        assert seen == {"a", "b", "c"}

    def test_nested_result_is_leaf_not_brackets(self):
        for _ in range(50):
            result = Prompter.apply_choices("[[a,[[b,c]]]]")
            assert "[[" not in result and "]]" not in result

    def test_multiple_disjoint_sets_both_expand(self):
        result = Prompter.apply_choices("[[x,y]] and [[1,2]]")
        left, right = result.split(" and ")
        assert left in ("x", "y")
        assert right in ("1", "2")

    def test_multiple_sets_all_combinations_reachable(self):
        seen = set()
        for _ in range(500):
            result = Prompter.apply_choices("[[x,y]]|[[1,2]]")
            seen.add(result)
        assert seen == {"x|1", "x|2", "y|1", "y|2"}


# ---------------------------------------------------------------------------
# apply_file_choices
# ---------------------------------------------------------------------------

class TestApplyFileChoices:
    def test_file_token_replaced_with_line(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.concepts.Concepts.load",
            lambda path: ["line_a", "line_b", "line_c"],
        )
        for _ in range(50):
            result = Prompter.apply_file_choices("@@choices.txt")
            assert result in ("line_a", "line_b", "line_c")

    def test_all_lines_reachable(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.concepts.Concepts.load",
            lambda path: ["alpha", "beta", "gamma"],
        )
        seen = set()
        for _ in range(300):
            seen.add(Prompter.apply_file_choices("@@words.txt"))
        assert seen == {"alpha", "beta", "gamma"}

    def test_text_outside_token_preserved(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.concepts.Concepts.load",
            lambda path: ["chosen"],
        )
        result = Prompter.apply_file_choices("before @@file.txt after")
        assert result == "before chosen after"

    def test_no_token_unchanged(self, monkeypatch):
        text = "no file reference here"
        # Concepts.load should not be called
        result = Prompter.apply_file_choices(text)
        assert result == text

    def test_file_not_found_raises(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.concepts.Concepts.load",
            lambda path: [],
        )
        with pytest.raises(ValueError, match="could not be resolved"):
            Prompter.apply_file_choices("@@missing.txt")
