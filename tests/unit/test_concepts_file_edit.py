"""
Tests for the write side of concept files: ConceptsFile.add_concept /
remove_concept / save, and the Concepts.save diffing wrapper on top of them.

These are the paths the Concept Editor window uses. They matter more than most
because add_concept inserts *mid-file* in alphabetical position rather than
appending, so an off-by-one corrupts line ordering rather than failing loudly --
and concepts/ is mirrored line-for-line by Konzepte/ for translation.
"""

import pytest

from sd_runner.prompts.concepts import Concepts, ConceptsFile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def write_file(tmp_path, name="fruit.txt", text="apple\ncherry\n"):
    f = tmp_path / name
    f.write_text(text, encoding="utf-8")
    return f


def concept_lines(path):
    """Non-comment, non-blank lines of a file, in order."""
    text = path.read_text(encoding="utf-8")
    return [ln.strip() for ln in text.split("\n")
            if ln.strip() and not ln.strip().startswith("#")]


def assert_indices_consistent(cf):
    """Every recorded index must point at the line holding that concept.

    concept_indices is what remove_concept uses to pick the line to delete, so
    a stale entry here deletes the wrong line.
    """
    for concept, idx in cf.concept_indices.items():
        assert 0 <= idx < len(cf.lines), (
            f"index {idx} for {concept!r} is out of range (lines={len(cf.lines)})"
        )
        assert cf.lines[idx].strip() == concept, (
            f"index {idx} for {concept!r} points at {cf.lines[idx].strip()!r}"
        )


# ---------------------------------------------------------------------------
# add_concept
# ---------------------------------------------------------------------------

class TestAddConcept:
    def test_inserts_in_alphabetical_position_not_appended(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        assert cf.add_concept("banana") is True
        assert [ln.strip() for ln in cf.lines] == ["apple", "banana", "cherry"]

    def test_insert_before_first_concept(self, tmp_path):
        f = write_file(tmp_path, text="banana\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("apple")
        assert [ln.strip() for ln in cf.lines] == ["apple", "banana", "cherry"]

    def test_appends_when_alphabetically_last(self, tmp_path):
        f = write_file(tmp_path, text="apple\nbanana\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("cherry")
        assert [ln.strip() for ln in cf.lines] == ["apple", "banana", "cherry"]

    def test_duplicate_rejected(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        assert cf.add_concept("apple") is False
        assert [ln.strip() for ln in cf.lines] == ["apple", "cherry"]

    def test_empty_file_appends(self, tmp_path):
        f = write_file(tmp_path, text="")
        cf = ConceptsFile(str(f))
        assert cf.add_concept("apple") is True
        assert cf.concepts == ["apple"]

    def test_comment_only_file_appends(self, tmp_path):
        f = write_file(tmp_path, text="# header comment\n# another\n")
        cf = ConceptsFile(str(f))
        assert cf.add_concept("apple") is True
        assert "apple" in cf.concepts
        assert cf.lines[0].strip() == "# header comment"

    def test_leading_comments_preserved_above_insertion(self, tmp_path):
        f = write_file(tmp_path, text="# fruit list\napple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        assert [ln.strip() for ln in cf.lines] == [
            "# fruit list", "apple", "banana", "cherry",
        ]

    def test_concept_added_to_concepts_list(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        assert set(cf.concepts) == {"apple", "banana", "cherry"}

    def test_indices_consistent_after_insert(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        assert_indices_consistent(cf)

    def test_indices_consistent_after_several_inserts(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        for c in ("banana", "blueberry", "apricot", "date"):
            cf.add_concept(c)
        assert_indices_consistent(cf)

    def test_new_concept_index_is_its_own_line(self, tmp_path):
        """Regression: the shift loop used to bump the new concept's own index."""
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        assert cf.concept_indices["banana"] == 1
        assert cf.lines[cf.concept_indices["banana"]].strip() == "banana"


# ---------------------------------------------------------------------------
# remove_concept
# ---------------------------------------------------------------------------

class TestRemoveConcept:
    def test_removes_the_named_line(self, tmp_path):
        f = write_file(tmp_path, text="apple\nbanana\ncherry\n")
        cf = ConceptsFile(str(f))
        assert cf.remove_concept("banana") is True
        assert [ln.strip() for ln in cf.lines] == ["apple", "cherry"]

    def test_unknown_concept_returns_false(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        assert cf.remove_concept("durian") is False
        assert [ln.strip() for ln in cf.lines] == ["apple", "cherry"]

    def test_concept_dropped_from_lists(self, tmp_path):
        f = write_file(tmp_path, text="apple\nbanana\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.remove_concept("banana")
        assert "banana" not in cf.concepts
        assert "banana" not in cf.concept_indices

    def test_indices_consistent_after_removal(self, tmp_path):
        f = write_file(tmp_path, text="apple\nbanana\ncherry\ndate\n")
        cf = ConceptsFile(str(f))
        cf.remove_concept("banana")
        assert_indices_consistent(cf)

    def test_comments_preserved_around_removal(self, tmp_path):
        f = write_file(tmp_path, text="# head\napple\nbanana\n# tail\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.remove_concept("banana")
        assert [ln.strip() for ln in cf.lines] == ["# head", "apple", "# tail", "cherry"]

    def test_add_then_remove_restores_original(self, tmp_path):
        """Regression: a stale index made this delete the displaced line instead."""
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        assert cf.remove_concept("banana") is True
        assert [ln.strip() for ln in cf.lines] == ["apple", "cherry"]
        assert set(cf.concepts) == {"apple", "cherry"}
        assert_indices_consistent(cf)


# ---------------------------------------------------------------------------
# save / round-trip
# ---------------------------------------------------------------------------

class TestSaveRoundTrip:
    def test_save_reload_preserves_concepts(self, tmp_path):
        f = write_file(tmp_path, text="apple\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        cf.save()
        assert concept_lines(f) == ["apple", "banana", "cherry"]
        assert ConceptsFile(str(f)).concepts == ["apple", "banana", "cherry"]

    def test_save_preserves_comments(self, tmp_path):
        f = write_file(tmp_path, text="# fruit\napple # a note\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.add_concept("banana")
        cf.save()
        text = f.read_text(encoding="utf-8")
        assert "# fruit" in text
        assert "apple # a note" in text

    def test_inline_comment_survives_round_trip(self, tmp_path):
        f = write_file(tmp_path, text="apple # juicy\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.save()
        reloaded = ConceptsFile(str(f))
        assert reloaded.concepts == ["apple", "cherry"]
        assert "# juicy" in f.read_text(encoding="utf-8")

    def test_removal_persisted(self, tmp_path):
        f = write_file(tmp_path, text="apple\nbanana\ncherry\n")
        cf = ConceptsFile(str(f))
        cf.remove_concept("banana")
        cf.save()
        assert ConceptsFile(str(f)).concepts == ["apple", "cherry"]

    def test_save_resolves_bare_name_against_concepts_dir(self, tmp_path, monkeypatch):
        """A filename that isn't an existing path is resolved under CONCEPTS_DIR.

        Documented because it is a footgun: saving a ConceptsFile built from a
        path that does not exist yet writes into the concepts directory rather
        than the intended location.
        """
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        target = tmp_path / "veg.txt"
        target.write_text("carrot\n", encoding="utf-8")
        cf = ConceptsFile("veg.txt")
        cf.add_concept("beet")
        cf.save()
        assert concept_lines(target) == ["beet", "carrot"]


# ---------------------------------------------------------------------------
# Concepts.save — diffs the incoming list against the file
# ---------------------------------------------------------------------------

class TestConceptsSave:
    def test_adds_new_concepts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="apple\ncherry\n")
        Concepts.save(str(f), ["apple", "banana", "cherry"])
        assert sorted(concept_lines(f)) == ["apple", "banana", "cherry"]

    def test_removes_absent_concepts(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="apple\nbanana\ncherry\n")
        Concepts.save(str(f), ["apple", "cherry"])
        assert concept_lines(f) == ["apple", "cherry"]

    def test_simultaneous_add_and_remove(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="apple\nbanana\ncherry\n")
        Concepts.save(str(f), ["apple", "cherry", "date"])
        assert sorted(concept_lines(f)) == ["apple", "cherry", "date"]

    def test_no_change_is_a_noop(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="# head\napple\ncherry\n")
        before = f.read_text(encoding="utf-8")
        Concepts.save(str(f), ["apple", "cherry"])
        assert f.read_text(encoding="utf-8") == before

    def test_empty_list_clears_concepts_but_keeps_comments(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="# head\napple\ncherry\n")
        Concepts.save(str(f), [])
        assert concept_lines(f) == []
        assert "# head" in f.read_text(encoding="utf-8")

    def test_round_trip_through_concepts_load(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
        f = write_file(tmp_path, text="apple\ncherry\n")
        Concepts.save(str(f), ["apple", "banana", "cherry"])
        assert sorted(Concepts.load(str(f))) == ["apple", "banana", "cherry"]
