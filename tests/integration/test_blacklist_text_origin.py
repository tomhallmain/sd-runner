"""Each item scope, held through the whole prompt pipeline.

The user's tags join the generated ones before the assembled prompt is filtered,
so a check of one method alone cannot show a scope holding. These go through
Prompter.generate_prompt and the checks around it.
"""

from types import SimpleNamespace

import pytest

from sd_runner.generators.base import BaseImageGenerator
from sd_runner.globals import BlacklistMode, PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.prompter import Prompter
from tests.utils import make_prompter


GENERATED_ONLY = {"apply_to_prompt_tags": False}
USER_ONLY = {"apply_to_generated": False}


def add_term(**scope):
    Blacklist.add_item(BlacklistItem("forbidden", **scope))


def user_prompt(text):
    """A FIXED prompt: all of *text* is what the user wrote."""
    return make_prompter(PromptMode.FIXED).generate_prompt(positive=text)[0]


def generated_prompt(monkeypatch, text):
    """A prompt where all of *text* came from concept mixing."""
    prompter = make_prompter(PromptMode.SFW, emphasis_chance=0.0)
    monkeypatch.setattr(prompter, "mix_concepts", lambda: text)
    return prompter.generate_prompt()[0]


class TestAssembledPrompt:
    def test_an_item_for_everything_removes_both(self, monkeypatch):
        add_term()
        assert "forbidden" not in user_prompt("calm lake, forbidden")
        assert "forbidden" not in generated_prompt(monkeypatch, "calm lake, forbidden")

    def test_a_generated_only_item_leaves_the_users_tag(self):
        add_term(**GENERATED_ONLY)
        assert "forbidden" in user_prompt("calm lake, forbidden")

    def test_a_generated_only_item_removes_a_generated_tag(self, monkeypatch):
        add_term(**GENERATED_ONLY)
        assert "forbidden" not in generated_prompt(monkeypatch, "calm lake, forbidden")

    def test_a_user_only_item_leaves_a_generated_tag(self, monkeypatch):
        add_term(**USER_ONLY)
        assert "forbidden" in generated_prompt(monkeypatch, "calm lake, forbidden")

    def test_a_user_only_item_removes_the_users_tag(self):
        add_term(**USER_ONLY)
        assert "forbidden" not in user_prompt("calm lake, forbidden")

    def test_a_tag_is_the_users_when_it_comes_from_positive_tags(self, monkeypatch):
        add_term(**GENERATED_ONLY)
        Prompter.set_positive_tags("forbidden, ")
        assert "forbidden" in generated_prompt(monkeypatch, "calm lake")

    def test_emphasis_does_not_change_whose_tag_it_is(self):
        add_term(**GENERATED_ONLY)
        assert "forbidden" in user_prompt("calm lake, (forbidden:1.2)")

    def test_list_mode_entries_are_the_users(self):
        add_term(**GENERATED_ONLY)
        prompter = make_prompter(PromptMode.LIST, prompt_list=["calm lake, forbidden"])
        assert "forbidden" in prompter.generate_prompt()[0]


class TestFinalCheck:
    def validate(self, prompt, user_tags):
        generator = SimpleNamespace(gen_config=SimpleNamespace(
            get_prompt_mode=lambda: PromptMode.SFW, user_tags=user_tags,
        ))
        return BaseImageGenerator.validate_prompt_against_blacklist(generator, prompt)

    def test_a_generated_only_item_leaves_the_users_tag(self):
        add_term(**GENERATED_ONLY)
        assert "forbidden" in self.validate("calm lake, forbidden", frozenset({"forbidden"}))

    def test_a_generated_only_item_removes_a_generated_tag(self):
        add_term(**GENERATED_ONLY)
        assert "forbidden" not in self.validate("calm lake, forbidden", frozenset())

    def test_a_user_only_item_leaves_a_generated_tag(self):
        add_term(**USER_ONLY)
        assert "forbidden" in self.validate("calm lake, forbidden", frozenset())


class TestUserTagStripping:
    @pytest.fixture(autouse=True)
    def removal_mode(self, monkeypatch):
        monkeypatch.setattr(
            "sd_runner.prompts.concepts.Concepts.get_dictionary_set", lambda: {"calm", "lake", "forbidden"}
        )
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_ENTIRE_TAG)

    def test_a_generated_only_item_leaves_the_users_tag(self):
        add_term(**GENERATED_ONLY)
        text, removed = Blacklist.strip_user_positive_tags("calm lake, forbidden")
        assert removed == {}
        assert "forbidden" in text

    def test_a_user_only_item_removes_the_users_tag(self):
        add_term(**USER_ONLY)
        text, removed = Blacklist.strip_user_positive_tags("calm lake, forbidden")
        assert "forbidden" in removed
        assert "forbidden" not in text


class TestPromptsTakenFromAnImage:
    @pytest.fixture(autouse=True)
    def enforcement_on(self, monkeypatch):
        monkeypatch.setattr("sd_runner.prompts.prompter.config.blacklist_prevent_execution", True)

    @pytest.mark.parametrize("scope", [GENERATED_ONLY, USER_ONLY])
    def test_every_item_applies(self, scope):
        add_term(**scope)
        positive, _negative = Prompter.filter_taken_prompt("calm lake, forbidden", "")
        assert "forbidden" not in positive


class TestGeneratedChecks:
    def test_a_user_only_item_is_no_violation_for_a_generated_string(self):
        add_term(**USER_ONLY)
        assert Blacklist.get_violation_item("forbidden") is None

    def test_a_user_only_item_passes_concept_filtering(self):
        add_term(**USER_ONLY)
        _whitelist, filtered = Blacklist.filter_concepts(["forbidden"], do_cache=False, user_prompt=False)
        assert filtered == {}
