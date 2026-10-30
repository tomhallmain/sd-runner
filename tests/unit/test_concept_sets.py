"""Tests for reading a concept set's manifest."""

import json

from sd_runner.prompts.concept_sets import MANIFEST_FILENAME, concept_set_info


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
