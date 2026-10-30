"""Tests for working out a prompt's language basket.

A stub stands in for Lingua through detector_hook, so these run without it
installed. The two tests at the end use the real package when it is there.
"""

import pytest

from sd_runner.prompts import language_detection
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concepts import Concepts
from sd_runner.prompts.language_detection import detect_basket, supported_languages

ENGLISH = (("en", 0.95), ("de", 0.05))


def add_languages(*codes):
    for code in codes:
        Blacklist.add_item(BlacklistItem(f"item {code}", language=code))


def use_stub(table):
    """Score text from *table*, and anything else as confidently English."""
    def hook(codes):
        return lambda text: table.get(text, ENGLISH)
    language_detection.detector_hook = hook


def forbid_detector():
    def hook(codes):
        raise AssertionError("the detector should not have been needed")
    language_detection.detector_hook = hook


class TestNoLanguageItems:
    def test_the_basket_is_empty_and_the_detector_is_not_called(self):
        forbid_detector()
        Blacklist.add_item(BlacklistItem("global item"))
        basket = detect_basket(["eine alte Steinbrücke"])
        assert basket.languages == frozenset()
        assert basket.widened is False


class TestSupportedLanguages:
    def test_only_enabled_items_count(self):
        Blacklist.add_item(BlacklistItem("on", language="de"))
        Blacklist.add_item(BlacklistItem("off", enabled=False, language="fr"))
        Blacklist.add_item(BlacklistItem("global"))
        assert supported_languages() == frozenset({"de"})

    def test_a_new_item_is_seen(self):
        add_languages("de")
        assert supported_languages() == frozenset({"de"})
        add_languages("fr")
        assert supported_languages() == frozenset({"de", "fr"})


class TestScriptPass:
    @pytest.mark.parametrize("tag, code", [
        ("старый дом", "ru"),
        ("오래된 집", "ko"),
        ("ふるいいえ", "ja"),
    ])
    def test_a_script_places_its_language_without_a_detector(self, tag, code):
        add_languages("ru", "ko", "ja")
        forbid_detector()
        assert detect_basket([tag]).languages == frozenset({code})

    def test_a_script_adds_only_supported_languages(self):
        add_languages("ko")
        forbid_detector()
        assert detect_basket(["старый дом"]).languages == frozenset()

    def test_han_with_kana_is_japanese(self):
        add_languages("zh", "ja")
        forbid_detector()
        assert detect_basket(["古い家"]).languages == frozenset({"ja"})

    def test_han_without_kana_follows_the_detector(self):
        add_languages("zh", "ja")
        use_stub({"一座房子": (("zh", 0.9), ("ja", 0.1))})
        assert detect_basket(["一座房子"]).languages == frozenset({"zh"})

    def test_han_the_detector_cannot_separate_adds_both(self):
        add_languages("zh", "ja")
        use_stub({"日本": (("ja", 0.55), ("zh", 0.45))})
        basket = detect_basket(["日本"])
        assert basket.languages == frozenset({"zh", "ja"})
        assert basket.widened is True

    def test_han_with_one_supported_language_needs_no_detector(self):
        add_languages("zh")
        forbid_detector()
        assert detect_basket(["一座房子"]).languages == frozenset({"zh"})


class TestLatinDetection:
    def test_an_english_tag_adds_nothing(self):
        add_languages("de", "fr")
        use_stub({})
        basket = detect_basket(["a lighthouse on the shore"])
        assert basket.languages == frozenset()
        assert basket.widened is False

    def test_a_low_confidence_tag_widens_to_every_latin_language(self):
        add_languages("de", "fr", "ru")
        use_stub({"a tag nobody can place": (("en", 0.4), ("de", 0.35), ("fr", 0.25))})
        basket = detect_basket(["a tag nobody can place"])
        assert basket.languages == frozenset({"de", "fr"})
        assert basket.widened is True

    def test_short_tags_are_pooled_and_detected_together(self):
        add_languages("de")
        use_stub({"Haus, Baum": (("de", 0.9), ("en", 0.1))})
        assert detect_basket(["Haus", "Baum"]).languages == frozenset({"de"})

    def test_a_second_language_above_the_minimum_joins(self):
        add_languages("de", "fr")
        use_stub({"a longer tag with mixed words": (("de", 0.7), ("fr", 0.2), ("en", 0.1))})
        assert detect_basket(["a longer tag with mixed words"]).languages == frozenset({"de", "fr"})

    def test_a_mixed_prompt_gives_each_language(self):
        add_languages("de", "fr", "ja")
        use_stub({
            "eine alte Steinbrücke": (("de", 0.95), ("en", 0.05)),
            "une vieille maison blanche": (("fr", 0.95), ("en", 0.05)),
        })
        basket = detect_basket([
            "a lighthouse on the shore", "eine alte Steinbrücke", "une vieille maison blanche", "古い家",
        ])
        assert basket.languages == frozenset({"de", "fr", "ja"})

    def test_emphasis_is_removed_before_detection(self):
        add_languages("de")
        use_stub({"eine alte Steinbrücke": (("de", 0.95), ("en", 0.05))})
        assert detect_basket(["((eine alte Steinbrücke))"]).languages == frozenset({"de"})

    def test_a_tag_with_no_letters_is_skipped(self):
        add_languages("de")
        forbid_detector()
        assert detect_basket(["1234, 5678"]).languages == frozenset()


class TestDetectorUnavailable:
    def test_a_missing_detector_widens_to_every_supported_language(self):
        add_languages("de", "ru")

        def hook(codes):
            raise ImportError("no lingua")
        language_detection.detector_hook = hook
        basket = detect_basket(["a lighthouse on the shore"])
        assert basket.languages == frozenset({"de", "ru"})
        assert basket.widened is True


class TestConceptSetHasNoBearing:
    def test_a_chinese_prompt_gives_chinese_with_german_concepts_loaded(self, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", "Konzepte")
        add_languages("de", "zh", "ja")
        use_stub({"一座房子": (("zh", 0.9), ("ja", 0.1))})
        assert detect_basket(["一座房子"]).languages == frozenset({"zh"})


class TestRealLingua:
    def test_a_restricted_detector_picks_german(self):
        pytest.importorskip("lingua")
        add_languages("de", "fr")
        assert "de" in detect_basket(["Die Katze schläft auf dem warmen Sofa"]).languages

    def test_a_language_with_no_model_is_always_in_the_basket(self):
        pytest.importorskip("lingua")
        add_languages("de", "tlh")
        assert "tlh" in detect_basket(["a lighthouse on the shore at dusk"]).languages
