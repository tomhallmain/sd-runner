"""The selected concept set has no bearing on what the blacklist blocks."""

import os

import pytest

from sd_runner.prompts import concepts as concepts_module
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concepts import Concepts


@pytest.fixture
def concept_sets(tmp_path, monkeypatch):
    """Two configured sets, each with a word the other lacks."""
    paths = {}
    for name, word in (("english", "random"), ("german", "wald")):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "dictionary.txt").write_text(f"{word}\n", encoding="utf-8")
        paths[name] = str(directory)
    config = concepts_module.config
    monkeypatch.setattr(config, "concepts_dirs", paths)
    monkeypatch.setattr(config, "override_dictionary_path", None)
    monkeypatch.setattr(config, "override_dictionary_append", False)
    return paths


def _select(monkeypatch, path: str) -> None:
    monkeypatch.setattr(Concepts, "CONCEPTS_DIR", path)
    Concepts.ALL_WORDS_LIST = []


class TestDictionarySet:
    @pytest.mark.parametrize("selected", ["english", "german"])
    def test_every_configured_set_counts_whichever_is_selected(self, concept_sets, monkeypatch, selected):
        _select(monkeypatch, concept_sets[selected])
        assert Concepts.get_dictionary_set() == {"random", "wald"}

    def test_an_appended_override_adds_to_the_sets(self, concept_sets, monkeypatch, tmp_path):
        override = tmp_path / "extra.txt"
        override.write_text("extra\n", encoding="utf-8")
        monkeypatch.setattr(concepts_module.config, "override_dictionary_path", str(override))
        monkeypatch.setattr(concepts_module.config, "override_dictionary_append", True)
        _select(monkeypatch, concept_sets["english"])
        assert Concepts.get_dictionary_set() == {"random", "wald", "extra"}

    def test_a_replacing_override_stands_alone(self, concept_sets, monkeypatch, tmp_path):
        override = tmp_path / "only.txt"
        override.write_text("only\n", encoding="utf-8")
        monkeypatch.setattr(concepts_module.config, "override_dictionary_path", str(override))
        _select(monkeypatch, concept_sets["english"])
        assert Concepts.get_dictionary_set() == {"only"}

    def test_an_edited_dictionary_is_read_again(self, concept_sets, monkeypatch):
        _select(monkeypatch, concept_sets["english"])
        Concepts.get_dictionary_set()
        german = os.path.join(concept_sets["german"], "dictionary.txt")
        with open(german, "w", encoding="utf-8") as f:
            f.write("haus\n")
        os.utime(german, (1, 1))
        assert "haus" in Concepts.get_dictionary_set()

    def test_a_set_without_a_dictionary_adds_nothing(self, concept_sets, monkeypatch, tmp_path):
        paths = dict(concept_sets, empty=str(tmp_path))
        monkeypatch.setattr(concepts_module.config, "concepts_dirs", paths)
        _select(monkeypatch, concept_sets["english"])
        assert Concepts.get_dictionary_set() == {"random", "wald"}


class TestSuffixCheck:
    @pytest.mark.parametrize("selected", ["english", "german"])
    def test_a_word_of_another_set_is_not_truncated_into_a_match(self, concept_sets, monkeypatch, selected):
        _select(monkeypatch, concept_sets[selected])
        Blacklist.TAG_BLACKLIST.append(BlacklistItem(r"dom($|\W|inatio)", use_regex=True))
        assert Blacklist.check_user_prompt_detailed("random") == {}


class TestConceptsDirName:
    @pytest.fixture
    def config(self, monkeypatch):
        config = concepts_module.config
        monkeypatch.setattr(config, "concepts_dirs", {"concepts": "concepts", "Konzepte": "/app/Konzepte"})
        return config

    @pytest.mark.parametrize("path, expected", [
        ("concepts", "concepts"),
        ("Konzepte", "Konzepte"),
        ("/app/Konzepte", "Konzepte"),
        ("/elsewhere/Konzepte", "Konzepte"),
        ("/elsewhere/Konzepte/", "Konzepte"),
        ("/elsewhere/other", None),
        ("", None),
        (None, None),
    ])
    def test_name(self, config, path, expected):
        assert config.concepts_dir_name(path) == expected
