"""
Prompt conversions: rewriting a prompt from one choice set into another.

Matching is done against the *rendered* prompt text, so no template is needed --
these work on a prompt read back out of an image, typed by hand, or produced by
another tool. The sets pair positionally: A[i] becomes B[i].
"""

import pytest

from sd_runner.prompts.prompter import Prompter


# ---------------------------------------------------------------------------
# choice_set_items — normalising the accepted spellings of a choice set
# ---------------------------------------------------------------------------

class TestChoiceSetItems:
    def test_list_is_taken_as_is(self):
        assert Prompter.choice_set_items(["red", "blue"]) == ["red", "blue"]

    def test_list_entries_are_stripped(self):
        assert Prompter.choice_set_items([" red ", "blue "]) == ["red", "blue"]

    def test_empty_list_entries_are_dropped(self):
        assert Prompter.choice_set_items(["red", "", "  "]) == ["red"]

    def test_bare_comma_string(self):
        assert Prompter.choice_set_items("red,blue") == ["red", "blue"]

    def test_wrapped_choice_set_string(self):
        assert Prompter.choice_set_items("[[red,blue]]") == ["red", "blue"]

    def test_pipe_separator(self):
        assert Prompter.choice_set_items("[[red|blue]]") == ["red", "blue"]

    def test_weights_are_stripped(self):
        assert Prompter.choice_set_items("[[red:3,blue:1]]") == ["red", "blue"]

    def test_colon_with_a_non_numeric_suffix_is_kept(self):
        """Only a numeric suffix reads as a weight."""
        assert Prompter.choice_set_items("[[a:b,square]]") == ["a:b", "square"]

    def test_colon_with_a_numeric_suffix_is_read_as_a_weight(self):
        """Longstanding choice-set behaviour: "ratio 16:9" means "ratio 16" at weight 9.

        Documented rather than fixed -- conversion deliberately reads items the
        same way expansion does, so the two cannot disagree about what an item is.
        """
        assert Prompter.choice_set_items("[[ratio 16:9,square]]") == ["ratio 16", "square"]

    def test_integer_range_is_expanded(self):
        assert Prompter.choice_set_items("[[1--4]]") == ["1", "2", "3", "4"]

    def test_character_range_is_expanded(self):
        assert Prompter.choice_set_items("[[a--d]]") == ["a", "b", "c", "d"]

    def test_none_gives_empty(self):
        assert Prompter.choice_set_items(None) == []

    def test_empty_string_gives_empty(self):
        assert Prompter.choice_set_items("") == []

    def test_empty_wrapped_set_gives_empty(self):
        assert Prompter.choice_set_items("[[]]") == []

    def test_whitespace_around_items_is_trimmed(self):
        assert Prompter.choice_set_items("[[ red , blue ]]") == ["red", "blue"]


# ---------------------------------------------------------------------------
# convert_choices — the core substitution
# ---------------------------------------------------------------------------

class TestConvertChoices:
    def test_single_item_is_converted(self):
        assert Prompter.convert_choices("a red car", ["red"], ["crimson"]) == "a crimson car"

    def test_each_set_position_maps_to_its_counterpart(self):
        result = Prompter.convert_choices(
            "a red car in Paris", ["red", "Paris"], ["crimson", "Kyoto"]
        )
        assert result == "a crimson car in Kyoto"

    def test_surrounding_text_is_untouched(self):
        result = Prompter.convert_choices("a red car, highly detailed", ["red"], ["crimson"])
        assert result == "a crimson car, highly detailed"

    def test_every_occurrence_is_converted(self):
        result = Prompter.convert_choices("red car with red trim", ["red"], ["crimson"])
        assert result == "crimson car with crimson trim"

    def test_unmatched_prompt_is_returned_unchanged(self):
        assert Prompter.convert_choices("a green car", ["red"], ["crimson"]) == "a green car"

    def test_accepts_choice_set_strings(self):
        result = Prompter.convert_choices("a red car", "[[red,blue]]", "[[crimson,azure]]")
        assert result == "a crimson car"

    def test_multi_word_phrases_convert(self):
        result = Prompter.convert_choices(
            "a dark red car", ["dark red"], ["maroon"]
        )
        assert result == "a maroon car"

    def test_whitespace_runs_in_the_prompt_still_match(self):
        result = Prompter.convert_choices("a dark  red car", ["dark red"], ["maroon"])
        assert result == "a maroon car"

    def test_empty_text_is_returned_unchanged(self):
        assert Prompter.convert_choices("", ["red"], ["crimson"]) == ""

    def test_empty_choice_sets_leave_the_text_alone(self):
        assert Prompter.convert_choices("a red car", [], []) == "a red car"

    def test_mismatched_set_lengths_raise(self):
        with pytest.raises(ValueError):
            Prompter.convert_choices("a red car", ["red", "blue"], ["crimson"])


# ---------------------------------------------------------------------------
# Matching rules — the parts that are decisions rather than mechanics
# ---------------------------------------------------------------------------

class TestMatchingRules:
    def test_substring_of_a_longer_word_is_not_matched(self):
        assert Prompter.convert_choices("cardigan", ["car"], ["truck"]) == "cardigan"

    def test_word_inside_another_word_is_not_matched(self):
        assert Prompter.convert_choices("a scared cat", ["red"], ["crimson"]) == "a scared cat"

    def test_longest_matching_item_wins(self):
        """'dark red' must not be converted as if it were 'red'."""
        result = Prompter.convert_choices(
            "a dark red car", ["red", "dark red"], ["crimson", "maroon"]
        )
        assert result == "a maroon car"

    def test_shorter_item_still_converts_on_its_own(self):
        result = Prompter.convert_choices(
            "a red car", ["red", "dark red"], ["crimson", "maroon"]
        )
        assert result == "a crimson car"

    def test_emphasised_item_is_matched(self):
        """The prompter wraps concepts as (item:weight) after choice resolution."""
        result = Prompter.convert_choices("a (red:1.2) car", ["red"], ["crimson"])
        assert result == "a (crimson:1.2) car"

    def test_parenthesised_item_is_matched(self):
        assert Prompter.convert_choices("a (red) car", ["red"], ["crimson"]) == "a (crimson) car"

    def test_item_adjacent_to_a_comma_is_matched(self):
        assert Prompter.convert_choices("blue,red,green", ["red"], ["crimson"]) == "blue,crimson,green"

    def test_matching_is_case_insensitive_by_default(self):
        assert Prompter.convert_choices("a RED car", ["red"], ["crimson"]) == "a crimson car"

    def test_replacement_uses_the_case_as_authored(self):
        assert Prompter.convert_choices("a RED car", ["red"], ["Crimson"]) == "a Crimson car"

    def test_case_sensitive_mode_skips_a_different_casing(self):
        result = Prompter.convert_choices("a RED car", ["red"], ["crimson"], case_sensitive=True)
        assert result == "a RED car"

    def test_case_sensitive_mode_still_matches_exact_casing(self):
        result = Prompter.convert_choices("a red car", ["red"], ["crimson"], case_sensitive=True)
        assert result == "a crimson car"

    def test_regex_characters_in_items_are_literal(self):
        result = Prompter.convert_choices("a red (car) here", ["(car)"], ["truck"])
        assert result == "a red truck here"

    def test_duplicate_source_item_uses_the_first_pairing(self):
        result = Prompter.convert_choices("a red car", ["red", "red"], ["crimson", "azure"])
        assert result == "a crimson car"


# ---------------------------------------------------------------------------
# Single-pass substitution
# ---------------------------------------------------------------------------

class TestSinglePassSubstitution:
    def test_item_present_in_both_sets_is_not_converted_twice(self):
        """red -> blue must stop there, not carry on through blue -> green."""
        result = Prompter.convert_choices("a red car", ["red", "blue"], ["blue", "green"])
        assert result == "a blue car"

    def test_a_full_rotation_converts_each_item_once(self):
        result = Prompter.convert_choices(
            "red and blue and green",
            ["red", "blue", "green"],
            ["blue", "green", "red"],
        )
        assert result == "blue and green and red"

    def test_swapping_two_items_does_not_collapse_them(self):
        result = Prompter.convert_choices("red and blue", ["red", "blue"], ["blue", "red"])
        assert result == "blue and red"


# ---------------------------------------------------------------------------
# find_choice_conversions — what a caller reports on
# ---------------------------------------------------------------------------

class TestFindChoiceConversions:
    def test_no_match_gives_an_empty_list(self):
        assert Prompter.find_choice_conversions("a green car", ["red"], ["crimson"]) == []

    def test_match_reports_position_and_replacement(self):
        conversions = Prompter.find_choice_conversions("a red car", ["red"], ["crimson"])
        assert len(conversions) == 1
        start, end, matched, replacement = conversions[0]
        assert (start, end) == (2, 5)
        assert matched == "red"
        assert replacement == "crimson"

    def test_matched_text_preserves_the_original_casing(self):
        conversions = Prompter.find_choice_conversions("a RED car", ["red"], ["crimson"])
        assert conversions[0][2] == "RED"

    def test_conversions_are_ordered_by_position(self):
        conversions = Prompter.find_choice_conversions(
            "red then blue", ["blue", "red"], ["azure", "crimson"]
        )
        assert [c[0] for c in conversions] == sorted(c[0] for c in conversions)

    def test_conversions_never_overlap(self):
        conversions = Prompter.find_choice_conversions(
            "a dark red car", ["red", "dark red"], ["crimson", "maroon"]
        )
        for earlier, later in zip(conversions, conversions[1:]):
            assert earlier[1] <= later[0]

    def test_count_reflects_every_occurrence(self):
        conversions = Prompter.find_choice_conversions(
            "red car with red trim", ["red"], ["crimson"]
        )
        assert len(conversions) == 2


# ---------------------------------------------------------------------------
# Against a prompt shaped like one the generator actually produces
# ---------------------------------------------------------------------------

class TestRealisticPrompt:
    PROMPT = "a (crimson:1.2) sports car, parked in Paris, golden hour, highly detailed"

    def test_converts_within_a_full_prompt(self):
        result = Prompter.convert_choices(
            self.PROMPT, ["crimson", "Paris"], ["azure", "Kyoto"]
        )
        assert "(azure:1.2)" in result
        assert "Kyoto" in result

    def test_unrelated_text_survives(self):
        result = Prompter.convert_choices(
            self.PROMPT, ["crimson", "Paris"], ["azure", "Kyoto"]
        )
        assert "sports car" in result
        assert "golden hour, highly detailed" in result

    def test_result_still_expands_cleanly(self):
        """A converted prompt must not acquire choice-set syntax of its own."""
        result = Prompter.convert_choices(self.PROMPT, ["crimson"], ["azure"])
        assert not Prompter.contains_choice_set(result)
