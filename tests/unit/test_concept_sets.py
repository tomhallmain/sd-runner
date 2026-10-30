"""Tests for reading a concept set's manifest and pairing a translated set's lines."""

import json
import os

import pytest

from sd_runner.prompts.concept_sets import (
    MANIFEST_FILENAME, SourceAnchors, concept_set_info, read_concept_lines,
)


def write_manifest(folder, data):
    folder.mkdir(exist_ok=True)
    (folder / MANIFEST_FILENAME).write_text(json.dumps(data), encoding="utf-8")


def test_the_manifest_is_read(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    translated = tmp_path / "translated"
    write_manifest(translated, {"language": "de", "source_set": str(source)})
    info = concept_set_info(str(translated))
    assert info.language == "de"
    assert info.source_path == str(source)


def test_english_normalises_to_no_language(tmp_path):
    write_manifest(tmp_path, {"language": "en", "source_set": None})
    info = concept_set_info(str(tmp_path))
    assert info.language is None
    assert info.source_path is None


def test_a_missing_manifest_gives_no_language_and_no_source(tmp_path):
    info = concept_set_info(str(tmp_path))
    assert info.language is None
    assert info.source_path is None


def test_an_unreadable_manifest_counts_as_missing(tmp_path):
    (tmp_path / MANIFEST_FILENAME).write_text("not json", encoding="utf-8")
    assert concept_set_info(str(tmp_path)).source_path is None


def test_a_source_set_that_does_not_exist_is_dropped(tmp_path):
    write_manifest(tmp_path, {"language": "de", "source_set": str(tmp_path / "gone")})
    info = concept_set_info(str(tmp_path))
    assert info.language == "de"
    assert info.source_path is None


def write_lines(folder, name, lines):
    folder.mkdir(exist_ok=True)
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")


@pytest.fixture
def sets(tmp_path):
    """An English source set and a German translation of it."""
    source = tmp_path / "source"
    translated = tmp_path / "translated"
    write_manifest(source, {"language": "en", "source_set": None})
    write_manifest(translated, {"language": "de", "source_set": str(source)})
    return source, translated


def anchors_for(translated):
    return SourceAnchors.for_set(concept_set_info(str(translated)))


class TestReadConceptLines:
    def test_it_drops_blanks_and_comments(self, tmp_path):
        path = tmp_path / "list.txt"
        path.write_text("red\n\n# heading\nblue # a note\n", encoding="utf-8")
        assert read_concept_lines(str(path)) == ["red", "blue"]


class TestSourceAnchors:
    def test_a_set_with_no_source_has_none(self, tmp_path):
        write_manifest(tmp_path, {"language": "en", "source_set": None})
        assert anchors_for(tmp_path) is None

    def test_lines_pair_by_position(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss", "river"])
        write_lines(translated, "a.txt", ["Kuss", "Fluss"])
        assert anchors_for(translated).sources("Kuss") == frozenset({"kiss"})
        assert anchors_for(translated).sources("Fluss") == frozenset({"river"})

    def test_comments_do_not_shift_the_pairing(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["# heading", "kiss # a note", "river"])
        write_lines(translated, "a.txt", ["Kuss", "Fluss"])
        assert anchors_for(translated).sources("Fluss") == frozenset({"river"})

    def test_a_line_from_two_sources_maps_to_both(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss", "smooch"])
        write_lines(translated, "a.txt", ["Kuss", "Kuss"])
        write_lines(source, "b.txt", ["peck"])
        write_lines(translated, "b.txt", ["Kuss"])
        assert anchors_for(translated).sources("Kuss") == frozenset({"kiss", "smooch", "peck"})

    def test_an_untranslated_line_has_no_entry(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["Berlin"])
        write_lines(translated, "a.txt", ["Berlin"])
        assert anchors_for(translated).sources("Berlin") == frozenset()

    def test_an_unknown_line_has_no_sources(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss"])
        write_lines(translated, "a.txt", ["Kuss"])
        assert anchors_for(translated).sources("Fluss") == frozenset()

    def test_a_file_whose_counts_differ_is_skipped(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss", "river"])
        write_lines(translated, "a.txt", ["Kuss"])
        write_lines(source, "b.txt", ["stone"])
        write_lines(translated, "b.txt", ["Stein"])
        anchors = anchors_for(translated)
        assert anchors.sources("Kuss") == frozenset()
        assert anchors.sources("Stein") == frozenset({"stone"})

    def test_a_file_that_drifted_with_equal_counts_is_skipped(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["Berlin", "Paris", "Rom", "kiss"])
        write_lines(translated, "a.txt", ["Kuss", "Berlin", "Paris", "Rom"])
        assert anchors_for(translated).sources("Kuss") == frozenset()

    def test_a_translation_that_equals_another_line_does_not_skip_the_file(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["Berlin", "Paris", "hand", "Hand"])
        write_lines(translated, "a.txt", ["Berlin", "Paris", "Hand", "Hand"])
        assert anchors_for(translated).sources("Hand") == frozenset({"hand"})

    def test_the_dictionary_is_not_paired(self, sets):
        source, translated = sets
        write_lines(source, "dictionary.txt", ["kiss"])
        write_lines(translated, "dictionary.txt", ["Kuss"])
        assert anchors_for(translated).sources("Kuss") == frozenset()

    def test_a_file_in_one_set_only_is_ignored(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss"])
        write_lines(translated, "a.txt", ["Kuss"])
        write_lines(source, "extra.txt", ["river"])
        assert anchors_for(translated).sources("Kuss") == frozenset({"kiss"})

    def test_an_english_source_is_checked_in_an_empty_basket(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss"])
        write_lines(translated, "a.txt", ["Kuss"])
        assert anchors_for(translated).source_languages == frozenset()

    def test_a_saved_edit_rebuilds_the_map(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss"])
        write_lines(translated, "a.txt", ["Kuss"])
        before = anchors_for(translated)
        write_lines(translated, "a.txt", ["Schmatzer"])
        os.utime(translated / "a.txt", (9_000_000_000, 9_000_000_000))
        after = anchors_for(translated)
        assert after.sources("Schmatzer") == frozenset({"kiss"})
        assert after.fingerprint != before.fingerprint

    def test_an_unchanged_set_reuses_the_map(self, sets):
        source, translated = sets
        write_lines(source, "a.txt", ["kiss"])
        write_lines(translated, "a.txt", ["Kuss"])
        assert anchors_for(translated) is anchors_for(translated)
