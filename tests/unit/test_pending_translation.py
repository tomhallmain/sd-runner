"""
The pending-translation backlog.

Plain JSON in a gitignored location rather than the encrypted app cache, because
the consumer is the concepts/i18n tooling, which has to read it without
decrypting anything. Path resolution honours SD_RUNNER_CACHE_DIR, so these tests
land in the per-test temp directory like every other cache artefact.
"""

import json
import os

import pytest

from sd_runner.prompts import pending_translation as pt


@pytest.fixture(autouse=True)
def empty_backlog(isolated_singletons):
    """Each test starts with no backlog file, inside the per-test temp dir."""
    pt.clear_pending_translations()
    return pt.resolve_pending_translation_file()


# ---------------------------------------------------------------------------
# Where it lives
# ---------------------------------------------------------------------------

class TestFileLocation:
    def test_path_follows_the_cache_dir_override(self, empty_backlog, tmp_path):
        assert str(tmp_path) in empty_backlog

    def test_written_as_readable_json(self):
        pt.stage_for_translation("amber", "colors.txt")
        with open(pt.resolve_pending_translation_file(), encoding="utf-8") as f:
            entries = json.load(f)
        assert entries == [{"concept": "amber", "file": "colors.txt"}]

    def test_non_ascii_concepts_are_not_escaped(self):
        """The file is meant to be read by a translator, so keep it legible."""
        pt.stage_for_translation("café", "objects.txt")
        with open(pt.resolve_pending_translation_file(), encoding="utf-8") as f:
            assert "café" in f.read()


# ---------------------------------------------------------------------------
# Staging
# ---------------------------------------------------------------------------

class TestStaging:
    def test_single_concept_is_staged(self):
        assert pt.stage_for_translation("amber", "colors.txt") == 1
        assert pt.get_pending_translations() == [
            {"concept": "amber", "file": "colors.txt"}
        ]

    def test_batch_is_staged(self):
        assert pt.stage_for_translation(["amber", "cobalt"], "colors.txt") == 2
        assert len(pt.get_pending_translations()) == 2

    def test_entries_accumulate_across_calls(self):
        pt.stage_for_translation("amber", "colors.txt")
        pt.stage_for_translation("cedar", "plants.txt")
        assert len(pt.get_pending_translations()) == 2

    def test_order_is_oldest_first(self):
        pt.stage_for_translation("first", "colors.txt")
        pt.stage_for_translation("second", "colors.txt")
        assert [e["concept"] for e in pt.get_pending_translations()] == ["first", "second"]

    def test_duplicate_pair_is_not_restaged(self):
        pt.stage_for_translation("amber", "colors.txt")
        assert pt.stage_for_translation("amber", "colors.txt") == 0
        assert len(pt.get_pending_translations()) == 1

    def test_same_concept_in_a_different_file_is_a_separate_entry(self):
        pt.stage_for_translation("amber", "colors.txt")
        assert pt.stage_for_translation("amber", "objects.txt") == 1
        assert len(pt.get_pending_translations()) == 2

    def test_source_file_is_recorded(self):
        pt.stage_for_translation("amber", "colors.txt")
        assert pt.get_pending_translations()[0]["file"] == "colors.txt"

    def test_concepts_are_stripped(self):
        pt.stage_for_translation("  amber  ", "colors.txt")
        assert pt.get_pending_translations()[0]["concept"] == "amber"

    def test_blank_concepts_are_skipped(self):
        assert pt.stage_for_translation(["", "   ", "amber"], "colors.txt") == 1

    def test_no_source_file_stages_nothing(self):
        assert pt.stage_for_translation("amber", "") == 0

    def test_dictionary_is_excluded(self):
        """dictionary.txt is outside the gettext export, so it is never staged."""
        assert pt.stage_for_translation("amber", "dictionary.txt") == 0
        assert pt.get_pending_translations() == []


# ---------------------------------------------------------------------------
# No line index — the decision this design turns on
# ---------------------------------------------------------------------------

class TestNoLineIndexIsStored:
    def test_entries_record_only_concept_and_file(self):
        """A position captured now is stale as soon as anything else is inserted.

        add_concept inserts alphabetically, so an index recorded at add time is
        wrong after the next insertion into the same file. It is also redundant:
        Konzepte/ mirrors concepts/ line-for-line, so the insertion point is
        recomputable from the concept's current position when the batch pass runs.
        """
        pt.stage_for_translation("amber", "colors.txt")
        assert set(pt.get_pending_translations()[0].keys()) == {"concept", "file"}

    def test_staging_order_does_not_imply_file_order(self):
        """Staged order is chronological; it says nothing about position in the file."""
        pt.stage_for_translation("zephyr", "colors.txt")
        pt.stage_for_translation("amber", "colors.txt")
        assert [e["concept"] for e in pt.get_pending_translations()] == ["zephyr", "amber"]


# ---------------------------------------------------------------------------
# Clearing
# ---------------------------------------------------------------------------

class TestClearing:
    def test_clear_all(self):
        pt.stage_for_translation(["amber", "cobalt"], "colors.txt")
        pt.clear_pending_translations()
        assert pt.get_pending_translations() == []

    def test_clear_only_the_translated_entries(self):
        pt.stage_for_translation(["amber", "cobalt"], "colors.txt")
        done = [{"concept": "amber", "file": "colors.txt"}]
        pt.clear_pending_translations(done)
        assert pt.get_pending_translations() == [
            {"concept": "cobalt", "file": "colors.txt"}
        ]

    def test_clearing_an_absent_entry_is_harmless(self):
        pt.stage_for_translation("amber", "colors.txt")
        pt.clear_pending_translations([{"concept": "nope", "file": "colors.txt"}])
        assert len(pt.get_pending_translations()) == 1

    def test_cleared_concept_can_be_staged_again(self):
        """A concept re-added after a translation pass is new work again."""
        pt.stage_for_translation("amber", "colors.txt")
        pt.clear_pending_translations()
        assert pt.stage_for_translation("amber", "colors.txt") == 1


# ---------------------------------------------------------------------------
# Degradation — a convenience list must never block a concept edit
# ---------------------------------------------------------------------------

class TestDegradesQuietly:
    def test_missing_file_reads_as_empty(self, empty_backlog):
        if os.path.isfile(empty_backlog):
            os.remove(empty_backlog)
        assert pt.get_pending_translations() == []

    def test_corrupt_file_reads_as_empty(self, empty_backlog):
        with open(empty_backlog, "w", encoding="utf-8") as f:
            f.write("{not json at all")
        assert pt.get_pending_translations() == []

    def test_unexpected_json_shape_reads_as_empty(self, empty_backlog):
        with open(empty_backlog, "w", encoding="utf-8") as f:
            json.dump({"not": "a list"}, f)
        assert pt.get_pending_translations() == []

    def test_staging_over_a_corrupt_file_still_works(self, empty_backlog):
        with open(empty_backlog, "w", encoding="utf-8") as f:
            f.write("{not json at all")
        assert pt.stage_for_translation("amber", "colors.txt") == 1
        assert pt.get_pending_translations() == [
            {"concept": "amber", "file": "colors.txt"}
        ]

    def test_an_unwritable_location_does_not_raise(self, monkeypatch, tmp_path):
        """Staging is a side effect of saving a concept; it must not break it."""
        monkeypatch.setattr(
            pt, "resolve_pending_translation_file",
            lambda: str(tmp_path / "no_such_dir" / "\0bad" / "pending.json"),
        )
        pt.stage_for_translation("amber", "colors.txt")
