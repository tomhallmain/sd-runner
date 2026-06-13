"""
Tests for Prompter.generate_prompt() and related class-level helpers.

FIXED and LIST prompt modes are used because they don't call mix_concepts(),
avoiding the need for real concept files. stop/return insertion chances are
set to 0 so _apply_random_stops_returns is a no-op and output is deterministic.
"""

import pytest
from sd_runner.prompter import Prompter
from sd_runner.prompter_configuration import PrompterConfiguration
from sd_runner.concepts import Concepts
from utils.globals import PromptMode


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_config(prompt_mode=PromptMode.FIXED, **overrides):
    cfg = PrompterConfiguration()
    cfg.prompt_mode = prompt_mode
    cfg.stop_insertion_chance = 0.0
    cfg.return_insertion_chance = 0.0
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


def make_prompter(prompt_mode=PromptMode.FIXED, prompt_list=None, **config_overrides):
    cfg = make_config(prompt_mode=prompt_mode, **config_overrides)
    kwargs = {}
    if prompt_list is not None:
        kwargs["prompt_list"] = prompt_list
    return Prompter(prompter_config=cfg, **kwargs)


# ---------------------------------------------------------------------------
# Module-level fixture: disable dictionary loading and reset class state
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_prompter_class_state(monkeypatch):
    """Patch out disk-bound dictionary loading and reset Prompter class attributes."""
    monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
    monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "")
    monkeypatch.setattr(Prompter, "NEGATIVE_TAGS", "")
    monkeypatch.setattr(Prompter, "EXCLUSION_TAGS", "")
    monkeypatch.setattr(Prompter, "TAGS_APPLY_TO_START", True)
    monkeypatch.setattr(Prompter, "POSITIVE_TAGS_INLINE_VARS", {})


# ---------------------------------------------------------------------------
# FIXED mode — positive passed through unchanged
# ---------------------------------------------------------------------------

class TestFixedModePassthrough:
    def test_positive_content_preserved(self):
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset, ocean, waves")
        assert "sunset" in pos
        assert "ocean" in pos

    def test_negative_content_preserved(self):
        p = make_prompter()
        _, neg = p.generate_prompt(positive="test", negative="blurry, lowres")
        assert "blurry" in neg

    def test_last_prompt_updated(self):
        p = make_prompter()
        p.generate_prompt(positive="portrait of a warrior")
        assert "portrait" in p.last_prompt

    def test_count_increments_each_call(self):
        p = make_prompter()
        assert p.count == 0
        p.generate_prompt(positive="a")
        assert p.count == 1
        p.generate_prompt(positive="b")
        assert p.count == 2

    def test_empty_positive_returns_empty(self):
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="")
        assert pos.strip() == ""

    def test_returns_tuple(self):
        p = make_prompter()
        result = p.generate_prompt(positive="test")
        assert isinstance(result, tuple) and len(result) == 2


# ---------------------------------------------------------------------------
# POSITIVE_TAGS prepend / append
# ---------------------------------------------------------------------------

class TestPositiveTagApplication:
    def test_tags_prepended_at_start(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "masterpiece, ")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset")
        assert pos.startswith("masterpiece, ")

    def test_tags_appended_at_end(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", ", detailed")
        monkeypatch.setattr(Prompter, "TAGS_APPLY_TO_START", False)
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset")
        assert pos.endswith(", detailed")

    def test_tags_not_duplicated_if_already_at_start(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "masterpiece")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="masterpiece, sunset")
        assert pos.count("masterpiece") == 1

    def test_empty_positive_tags_not_added(self):
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset")
        assert pos == "sunset"

    def test_whitespace_only_tags_not_added(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "   ")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset")
        assert pos == "sunset"


# ---------------------------------------------------------------------------
# NEGATIVE_TAGS prepend / append
# ---------------------------------------------------------------------------

class TestNegativeTagApplication:
    def test_negative_tags_prepended(self, monkeypatch):
        monkeypatch.setattr(Prompter, "NEGATIVE_TAGS", "ugly, ")
        p = make_prompter()
        _, neg = p.generate_prompt(positive="test", negative="lowres")
        assert neg.startswith("ugly, ")

    def test_negative_tags_appended_when_apply_to_end(self, monkeypatch):
        monkeypatch.setattr(Prompter, "NEGATIVE_TAGS", ", deformed")
        monkeypatch.setattr(Prompter, "TAGS_APPLY_TO_START", False)
        p = make_prompter()
        _, neg = p.generate_prompt(positive="test", negative="lowres")
        assert neg.endswith(", deformed")

    def test_negative_tags_not_duplicated(self, monkeypatch):
        monkeypatch.setattr(Prompter, "NEGATIVE_TAGS", "ugly")
        p = make_prompter()
        _, neg = p.generate_prompt(positive="test", negative="ugly, lowres")
        assert neg.count("ugly") == 1


# ---------------------------------------------------------------------------
# EXCLUSION_TAGS — regex filter on positive concepts
# ---------------------------------------------------------------------------

class TestExclusionTags:
    def test_matching_concept_removed(self, monkeypatch):
        monkeypatch.setattr(Prompter, "EXCLUSION_TAGS", "nsfw")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset, nsfw, ocean")
        assert "nsfw" not in pos
        assert "sunset" in pos and "ocean" in pos

    def test_non_matching_concepts_kept(self, monkeypatch):
        monkeypatch.setattr(Prompter, "EXCLUSION_TAGS", "explicit")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset, ocean, waves")
        assert "sunset" in pos and "ocean" in pos and "waves" in pos

    def test_exclusion_is_case_insensitive(self, monkeypatch):
        monkeypatch.setattr(Prompter, "EXCLUSION_TAGS", "nude")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset, Nude beach, ocean")
        assert "Nude" not in pos

    def test_invalid_exclusion_regex_does_not_crash(self, monkeypatch):
        monkeypatch.setattr(Prompter, "EXCLUSION_TAGS", "[invalid(")
        p = make_prompter()
        pos, _ = p.generate_prompt(positive="sunset, ocean")
        # Bad regex is logged as a warning and skipped; prompt comes through unfiltered
        assert "sunset" in pos


# ---------------------------------------------------------------------------
# LIST mode — cycles through prompt_list by count
# ---------------------------------------------------------------------------

class TestListMode:
    def test_first_call_returns_first_item(self):
        p = make_prompter(prompt_mode=PromptMode.LIST,
                          prompt_list=["alpha", "beta", "gamma"])
        pos, _ = p.generate_prompt()
        assert pos == "alpha"

    def test_advances_through_list_in_order(self):
        p = make_prompter(prompt_mode=PromptMode.LIST,
                          prompt_list=["a", "b", "c"])
        results = [p.generate_prompt()[0] for _ in range(3)]
        assert results == ["a", "b", "c"]

    def test_wraps_around_at_list_end(self):
        p = make_prompter(prompt_mode=PromptMode.LIST,
                          prompt_list=["x", "y"])
        results = [p.generate_prompt()[0] for _ in range(4)]
        assert results == ["x", "y", "x", "y"]

    def test_positive_tags_applied_to_list_items(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "quality, ")
        p = make_prompter(prompt_mode=PromptMode.LIST,
                          prompt_list=["sunset"])
        pos, _ = p.generate_prompt()
        assert pos.startswith("quality, ")
        assert "sunset" in pos


# ---------------------------------------------------------------------------
# Choice set expansion inside FIXED mode
# ---------------------------------------------------------------------------

class TestChoiceExpansionInFixedMode:
    def test_choice_resolved_to_one_option(self):
        p = make_prompter()
        for _ in range(30):
            pos, _ = p.generate_prompt(positive="a [[cat,dog]] portrait")
            assert "[[" not in pos
            assert "cat" in pos or "dog" in pos

    def test_all_options_reachable_over_many_draws(self):
        p = make_prompter()
        seen = set()
        for _ in range(100):
            pos, _ = p.generate_prompt(positive="[[red,blue,green]] sky")
            for colour in ("red", "blue", "green"):
                if colour in pos:
                    seen.add(colour)
        assert seen == {"red", "blue", "green"}


# ---------------------------------------------------------------------------
# set_positive_tags / set_negative_tags / set_exclusion_tags class methods
# ---------------------------------------------------------------------------

class TestTagSetters:
    def test_set_positive_tags(self):
        Prompter.set_positive_tags("quality, ")
        assert Prompter.POSITIVE_TAGS == "quality, "

    def test_set_negative_tags(self):
        Prompter.set_negative_tags("blurry")
        assert Prompter.NEGATIVE_TAGS == "blurry"

    def test_set_exclusion_tags(self):
        Prompter.set_exclusion_tags("nude")
        assert Prompter.EXCLUSION_TAGS == "nude"

    def test_set_tags_apply_to_start(self):
        Prompter.set_tags_apply_to_start(False)
        assert Prompter.TAGS_APPLY_TO_START is False
