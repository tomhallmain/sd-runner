import unittest

from sd_runner.prompter import Prompter


class TestExtractInlineVars(unittest.TestCase):
    def test_no_header(self):
        text = "A red car in the rain"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {})
        self.assertEqual(remaining, text)

    def test_single_var_plain_value(self):
        text = "|||MyVar->hello\nA $$MyVar photo"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"myvar": "hello"})
        self.assertEqual(remaining, "A $$MyVar photo")

    def test_multiple_vars(self):
        text = "|||Color->blue\n|||Style->watercolor\nA $$Color $$Style painting"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"color": "blue", "style": "watercolor"})
        self.assertEqual(remaining, "A $$Color $$Style painting")

    def test_choice_set_value(self):
        text = "|||Hue->[[red,blue,yellow]]\nA $$Hue car"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"hue": "[[red,blue,yellow]]"})
        self.assertEqual(remaining, "A $$Hue car")

    def test_strips_leading_whitespace_from_body(self):
        text = "|||X->foo\n\n  A $$X image"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"x": "foo"})
        self.assertEqual(remaining, "A $$X image")

    def test_name_case_normalised_to_lower(self):
        text = "|||MyBigVar->value\ntest"
        vars_dict, _ = Prompter.extract_inline_vars(text)
        self.assertIn("mybigvar", vars_dict)

    def test_non_matching_first_line_returns_empty(self):
        text = "This is a normal prompt\n|||MyVar->foo"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {})
        self.assertEqual(remaining, text)

    def test_empty_text(self):
        vars_dict, remaining = Prompter.extract_inline_vars("")
        self.assertEqual(vars_dict, {})
        self.assertEqual(remaining, "")

    def test_header_only(self):
        text = "|||A->alpha\n|||B->beta"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"a": "alpha", "b": "beta"})
        self.assertEqual(remaining, "")

    def test_colon_syntax_single_var(self):
        text = "::MyVar = hello\nA $$MyVar photo"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"myvar": "hello"})
        self.assertEqual(remaining, "A $$MyVar photo")

    def test_colon_syntax_multiple_vars(self):
        text = "::Color = blue\n::Style = watercolor\nA $$Color $$Style painting"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"color": "blue", "style": "watercolor"})
        self.assertEqual(remaining, "A $$Color $$Style painting")

    def test_colon_syntax_choice_set(self):
        text = "::Animal = [[cat,dog,bird]]\nA cute $$Animal"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertIn(vars_dict["animal"], ["cat", "dog", "bird"])
        self.assertEqual(remaining, "A cute $$Animal")

    def test_colon_syntax_mixed_with_pipe_syntax(self):
        text = "|||Color->red\n::Style = watercolor\nA $$Color $$Style image"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {"color": "red", "style": "watercolor"})
        self.assertEqual(remaining, "A $$Color $$Style image")

    def test_colon_syntax_no_match_if_not_at_start(self):
        text = "Normal prompt\n::MyVar = foo"
        vars_dict, remaining = Prompter.extract_inline_vars(text)
        self.assertEqual(vars_dict, {})
        self.assertEqual(remaining, text)


class TestApplyExpansionsWithInlineVars(unittest.TestCase):
    def test_plain_value_expansion(self):
        inline_vars = {"myvar": "hello"}
        result = Prompter.apply_expansions("$$MyVar world", inline_vars=inline_vars)
        self.assertEqual(result, "hello world")

    def test_choice_set_value_resolved(self):
        inline_vars = {"hue": "[[red,green,blue]]"}
        result = Prompter.apply_expansions("A $$Hue car", inline_vars=inline_vars)
        self.assertIn(result, ["A red car", "A green car", "A blue car"])

    def test_inline_vars_take_priority_over_nothing(self):
        # A name that isn't in wildcards or expansions should still resolve from inline_vars
        inline_vars = {"customtag": "my custom text"}
        result = Prompter.apply_expansions("$$Customtag", inline_vars=inline_vars)
        self.assertEqual(result, "my custom text")

    def test_multiple_inline_vars(self):
        inline_vars = {"color": "blue", "subject": "car"}
        result = Prompter.apply_expansions("A $$Color $$Subject", inline_vars=inline_vars)
        self.assertEqual(result, "A blue car")

    def test_no_inline_vars_unchanged(self):
        # Without inline_vars, an unknown $$ ref should log an error and be skipped
        # The text should remain with the variable unexpanded (not raise an exception)
        result = Prompter.apply_expansions("$$UnknownVar123xyz", inline_vars=None)
        # Should not raise; result may be unchanged or partially processed
        self.assertIsInstance(result, str)


class TestExtractAndExpandRoundtrip(unittest.TestCase):
    """End-to-end: extract_inline_vars then apply_expansions."""

    def test_plain_value_roundtrip(self):
        raw = "|||Greeting->Hello world\n$$Greeting, this is a test"
        inline_vars, body = Prompter.extract_inline_vars(raw)
        result = Prompter.apply_expansions(body, inline_vars=inline_vars)
        self.assertEqual(result, "Hello world, this is a test")

    def test_choice_set_roundtrip(self):
        raw = "|||Animal->[[cat,dog,bird]]\nA cute $$Animal"
        inline_vars, body = Prompter.extract_inline_vars(raw)
        result = Prompter.apply_expansions(body, inline_vars=inline_vars)
        self.assertIn(result, ["A cute cat", "A cute dog", "A cute bird"])

    def test_header_stripped_from_final_prompt(self):
        raw = "|||Tag->beautiful\nA $$Tag sunset"
        inline_vars, body = Prompter.extract_inline_vars(raw)
        result = Prompter.apply_expansions(body, inline_vars=inline_vars)
        self.assertNotIn("|||", result)
        self.assertNotIn("$$", result)
        self.assertEqual(result, "A beautiful sunset")

    def test_body_without_references_is_clean(self):
        raw = "|||Unused->value\nA plain prompt with no variables"
        inline_vars, body = Prompter.extract_inline_vars(raw)
        # No expansion vars in body, so apply_expansions would not normally be called,
        # but body itself is already stripped of the header.
        self.assertNotIn("|||", body)
        self.assertEqual(body, "A plain prompt with no variables")

    def test_three_vars_from_spec_example(self):
        raw = (
            "|||MyVar1->[[a,b,c]]\n"
            "|||MyVar2->[[d,e,f]]\n"
            "|||MyVar3->my_current_value\n"
            "$$MyVar1 and $$MyVar2 with $$MyVar3"
        )
        inline_vars, body = Prompter.extract_inline_vars(raw)
        self.assertEqual(set(inline_vars.keys()), {"myvar1", "myvar2", "myvar3"})
        self.assertEqual(inline_vars["myvar3"], "my_current_value")
        result = Prompter.apply_expansions(body, inline_vars=inline_vars)
        # MyVar1 and MyVar2 are choice sets, MyVar3 is a plain string
        self.assertIn(result.split(" and ")[0], ["a", "b", "c"])
        parts = result.split(" with ")
        self.assertEqual(parts[1], "my_current_value")
        self.assertIn(parts[0].split(" and ")[1], ["d", "e", "f"])


if __name__ == "__main__":
    unittest.main()
