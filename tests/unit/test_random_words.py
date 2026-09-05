"""``Concepts.get_random_words`` -- the one category that builds its own phrases.

Every other category returns what ``sample_whitelisted`` gave it, so the
blacklist check there is the whole story and
``tests/integration/test_concepts_blacklist_pipeline.py`` covers it. This one
joins sampled words into multi-word phrases afterwards, which is a term the
blacklist never saw: both words can be whitelisted while the phrase they form
is not. Only that part is asserted here.

``random.random`` decides where a phrase ends, so it is pinned per test rather
than left to chance -- an assertion about which words joined is otherwise a
coin flip, and seeding the module would shift global state for whatever runs
next.
"""

import random

import pytest

from sd_runner.globals import PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concepts import Concepts, ConceptConfiguration


VOCABULARY = [
    "amber", "azure", "beacon", "bramble", "canyon", "cedar", "cinder",
    "clover", "cobalt", "copper", "crimson", "dusk", "ember", "fern",
]


@pytest.fixture
def vocabulary(monkeypatch):
    """One known word list, however the dictionary is reached.

    ``Concepts.__init__`` re-reads the dictionary from disk when it finds the
    list empty, and empties it whenever the concepts directory has moved, so
    setting the attribute alone leaves an opening for the real file.
    """
    monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: list(VOCABULARY)))
    monkeypatch.setattr(Concepts, "ALL_WORDS_LIST", list(VOCABULARY))
    monkeypatch.setattr(Concepts, "URBAN_DICTIONARY_CORPUS", [])


@pytest.fixture
def never_splits(monkeypatch):
    """Above the combine chance, so every sampled word joins one phrase."""
    monkeypatch.setattr(random, "random", lambda: 0.99)


@pytest.fixture
def always_splits(monkeypatch):
    """Below the combine chance, so a phrase ends before every word."""
    monkeypatch.setattr(random, "random", lambda: 0.0)


def words(count, prompt_mode=PromptMode.SFW):
    concepts = Concepts(prompt_mode, get_specific_locations=False)
    return concepts.get_random_words(ConceptConfiguration(count, count))


class TestPhraseBuilding:
    def test_it_joins_the_sample_into_one_phrase(self, vocabulary, never_splits):
        result = words(4)

        assert len(result) == 1
        assert len(result[0].split(" ")) == 4

    def test_it_returns_single_words_when_nothing_joins(self, vocabulary, always_splits):
        result = words(4)

        assert len(result) == 4
        assert all(" " not in word for word in result)

    def test_an_empty_range_is_empty(self, vocabulary, never_splits):
        assert words(0) == []


class TestABlacklistedPhrase:
    """The reason this category filters at all: the blacklist is applied to
    single words when the sample is drawn, and a phrase is not a word."""

    def test_the_words_are_individually_allowed(self, vocabulary):
        Blacklist.add_item(BlacklistItem("amber azure"))

        assert Blacklist.get_violation_item("amber") is None
        assert Blacklist.get_violation_item("azure") is None
        assert Blacklist.get_violation_item("amber azure") is not None

    def test_the_phrase_they_form_is_dropped(self, vocabulary, never_splits, monkeypatch):
        monkeypatch.setattr(
            Concepts, "sample_whitelisted",
            staticmethod(lambda concepts, low, high, prompt_mode: ["amber", "azure"]),
        )
        Blacklist.add_item(BlacklistItem("amber azure"))

        assert "amber azure" not in words(2)

    def test_a_clean_phrase_survives(self, vocabulary, never_splits, monkeypatch):
        """Control: the phrase above is absent because it is blacklisted, not
        because a two-word sample produces nothing."""
        monkeypatch.setattr(
            Concepts, "sample_whitelisted",
            staticmethod(lambda concepts, low, high, prompt_mode: ["amber", "azure"]),
        )

        assert words(2) == ["amber azure"]

    def test_a_single_word_is_not_re_checked(self, vocabulary, always_splits, monkeypatch):
        """It came from sample_whitelisted, so it has already passed."""
        checked = []
        monkeypatch.setattr(
            Blacklist, "get_violation_item",
            staticmethod(lambda string: checked.append(string)),
        )

        words(4)

        assert checked == []


class TestResampling:
    """A dropped phrase is replaced rather than leaving the caller short."""

    def test_replacements_are_drawn_for_what_was_dropped(self, vocabulary, never_splits, monkeypatch):
        samples = [["amber", "azure"], ["cedar", "cinder"]]
        monkeypatch.setattr(
            Concepts, "sample_whitelisted",
            staticmethod(lambda concepts, low, high, prompt_mode: samples.pop(0)),
        )
        Blacklist.add_item(BlacklistItem("amber azure"))

        assert words(2) == ["cedar cinder"]

    def test_it_stops_once_an_attempt_comes_back_clean(self, vocabulary, never_splits, monkeypatch):
        """The violation record is per-attempt. Were it cumulative the loop
        could not tell a successful retry from the failure that started it, and
        would run to its limit appending words each time."""
        draws = []

        def fake_sample(concepts, low, high, prompt_mode):
            draws.append(low)
            return ["amber", "azure"] if len(draws) == 1 else ["cedar", "cinder"]

        monkeypatch.setattr(Concepts, "sample_whitelisted", staticmethod(fake_sample))
        Blacklist.add_item(BlacklistItem("amber azure"))

        words(2)

        assert len(draws) == 2

    def test_it_gives_up_rather_than_looping_forever(self, vocabulary, never_splits, monkeypatch):
        """Every draw violates, so the attempt cap is the only thing that ends
        it. Ten attempts after the first draw."""
        draws = []

        def fake_sample(concepts, low, high, prompt_mode):
            draws.append(low)
            return ["amber", "azure"]

        monkeypatch.setattr(Concepts, "sample_whitelisted", staticmethod(fake_sample))
        Blacklist.add_item(BlacklistItem("amber azure"))

        assert words(2) == []
        assert len(draws) == 11
