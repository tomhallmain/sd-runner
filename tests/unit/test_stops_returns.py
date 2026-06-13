import random
import unittest

from sd_runner.prompter import Prompter
from sd_runner.prompter_configuration import PrompterConfiguration


def _prompter(
    *,
    stop_insertion_chance: float = 0.0,
    return_insertion_chance: float = 0.0,
) -> Prompter:
    return Prompter(
        prompter_config=PrompterConfiguration(
            stop_insertion_chance=stop_insertion_chance,
            return_insertion_chance=return_insertion_chance,
        )
    )


class TestParenDepth(unittest.TestCase):
    def test_depth_outside_and_inside(self):
        text = "a, (b, c), d"
        comma_in_emphasis = text.index(", c")
        comma_outside = text.index("a,")
        self.assertEqual(Prompter._paren_depth_before(text, 0), 0)
        self.assertEqual(Prompter._paren_depth_before(text, comma_outside + 1), 0)
        self.assertEqual(Prompter._paren_depth_before(text, comma_in_emphasis), 1)
        self.assertEqual(Prompter._paren_depth_before(text, len(text)), 0)

    def test_nested_emphasis(self):
        text = "(outer (inner, deep), rest)"
        inner_comma = text.index(", deep")
        self.assertEqual(Prompter._paren_depth_before(text, inner_comma), 2)

    def test_unclosed_paren_treated_as_inside(self):
        text = "before, (no close, still inside"
        comma_inside = text.index(", still")
        self.assertGreater(Prompter._paren_depth_before(text, comma_inside), 0)


class TestRandomStopsReturns(unittest.TestCase):
    def test_no_change_when_chances_zero(self):
        prompter = _prompter()
        text = "a, b, c"
        self.assertEqual(prompter._apply_random_stops_returns(text), text)

    def test_all_returns_with_seed(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        self.assertEqual(
            prompter._apply_random_stops_returns("one, two, three"),
            "one.\n\ntwo.\n\nthree",
        )

    def test_all_stops_with_seed(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        random.seed(0)
        self.assertEqual(
            prompter._apply_random_stops_returns("one, two, three"),
            "one. two. three",
        )

    def test_preserves_user_whitespace_when_unchanged(self):
        prompter = _prompter()
        text = "line one,\tline two,\nline three"
        self.assertEqual(prompter._apply_random_stops_returns(text), text)

    def test_stop_keeps_whitespace_after_comma(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        random.seed(0)
        self.assertEqual(
            prompter._apply_random_stops_returns("one,\ttwo"),
            "one.\ttwo",
        )

    def test_period_pass_preserves_existing_period_whitespace(self):
        prompter = _prompter()
        text = "first.\nsecond, third"
        self.assertEqual(prompter._apply_random_stops_returns(text), text)

    def test_config_round_trip(self):
        cfg = PrompterConfiguration(stop_insertion_chance=0.05, return_insertion_chance=0.03)
        data = cfg.to_dict()
        restored = PrompterConfiguration()
        restored.set_from_dict(data)
        self.assertEqual(restored.stop_insertion_chance, 0.05)
        self.assertEqual(restored.return_insertion_chance, 0.03)

    def test_empty_and_single_segment_unchanged(self):
        prompter = _prompter(return_insertion_chance=1.0)
        self.assertEqual(prompter._apply_random_stops_returns(""), "")
        self.assertEqual(prompter._apply_random_stops_returns("solo tag"), "solo tag")

    def test_no_whitespace_after_comma_unchanged(self):
        prompter = _prompter(return_insertion_chance=1.0)
        text = "tag1,tag2, tag3"
        random.seed(0)
        result = prompter._apply_random_stops_returns(text)
        self.assertTrue(result.startswith("tag1,tag2"))
        self.assertIn("\n", result)

    def test_emphasis_commas_preserved_on_return(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "scene, (prompt tags1, prompt tags2), after"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(prompt tags1, prompt tags2)", result)
        self.assertNotIn("(prompt tags1.\n\n prompt tags2)", result)

    def test_emphasis_commas_preserved_on_stop(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        random.seed(0)
        text = "base, (prompt tags1, prompt tags2), tail"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(prompt tags1, prompt tags2)", result)
        self.assertNotIn("(prompt tags1. prompt tags2)", result)

    def test_outer_emphasis_boundaries_still_transform(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "before, (inner one, inner two), after"
        result = prompter._apply_random_stops_returns(text)
        self.assertEqual(
            result,
            "before.\n\n(inner one, inner two).\n\nafter",
        )

    def test_weighted_emphasis_inside_parens(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        random.seed(0)
        text = "wide, (detailed face:1.3, sharp eyes:1.1), soft"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(detailed face:1.3, sharp eyes:1.1)", result)

    def test_nested_emphasis_inner_commas_unchanged(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "start, (layer (deep one, deep two), mid), end"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(deep one, deep two)", result)

    def test_period_inside_emphasis_unchanged_on_return(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "hdr, (clause one. clause two), flat"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(clause one. clause two)", result)

    def test_period_outside_emphasis_can_still_return(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "first. second, third"
        result = prompter._apply_random_stops_returns(text)
        self.assertEqual(result, "first.\n\nsecond.\n\nthird")

    def test_multiple_emphasis_groups(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        random.seed(0)
        text = "(a, b), middle, (c, d), end"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(a, b)", result)
        self.assertIn("(c, d)", result)
        self.assertIn("middle.", result)
        self.assertTrue(result.endswith("end"))
        self.assertNotIn("(a. b)", result)
        self.assertNotIn("(c. d)", result)

    def test_leading_emphasis(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "(first, second), third"
        result = prompter._apply_random_stops_returns(text)
        self.assertEqual(result, "(first, second).\n\nthird")

    def test_trailing_emphasis(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "first, (second, third)"
        result = prompter._apply_random_stops_returns(text)
        self.assertEqual(result, "first.\n\n(second, third)")

    def test_delimiter_pass_comma_only(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "x, (y, z)"
        result = Prompter._apply_random_stops_returns_delimiter_pass(
            text, ",", 0.0, 1.0
        )
        self.assertEqual(result, "x.\n\n(y, z)")

    def test_delimiter_pass_skips_inside_parens(self):
        prompter = _prompter(stop_insertion_chance=1.0)
        text = "(keep, this)"
        result = Prompter._apply_random_stops_returns_delimiter_pass(
            text, ",", 1.0, 0.0
        )
        self.assertEqual(result, text)

    def test_mixed_newlines_outside_emphasis_only(self):
        prompter = _prompter(return_insertion_chance=1.0)
        random.seed(0)
        text = "top,\n(para one, para two),\nbottom"
        result = prompter._apply_random_stops_returns(text)
        self.assertIn("(para one, para two)", result)
        self.assertIn("top.\n\n", result)
        self.assertTrue(result.endswith("bottom"))


if __name__ == "__main__":
    unittest.main()
