"""
Concept Editor CRUD through the widgets.

This is the one UI in the app that writes user data files, and it writes them
mid-file: Concepts.save -> ConceptsFile.add_concept inserts in alphabetical
position rather than appending, so a bug reorders lines rather than failing
visibly. concepts/ is mirrored line-for-line by Konzepte/ for translation, so
reordering is silent damage.

The underlying ConceptsFile logic is unit-tested in test_concepts_file_edit.py;
what is exercised here is the path a user actually takes, including the password
gate on the editing actions.
"""

import pytest

from sd_runner.prompts.concepts import Concepts
from tests.utils import install_password_bypass
from sd_runner.ui.prompts.concept_editor_window import ConceptEditorWindow


COLORS_FILE = "colors.txt"
INITIAL_COLORS = ["amber", "cobalt", "emerald"]


class RecordingAppActions:
    """AppActions stand-in that records toasts and answers confirmations."""

    def __init__(self, confirm=True):
        self.toasts = []
        self.alerts = []
        self.warnings = []
        self._confirm = confirm

    def toast(self, message, *args, **kwargs):
        self.toasts.append(message)

    def alert(self, title, message, kind=None, master=None, **kwargs):
        self.alerts.append((title, message, kind))
        return self._confirm

    def warn(self, message, *args, **kwargs):
        self.warnings.append(message)

    def __getattr__(self, name):
        # Any other action the window happens to call is a no-op.
        return lambda *args, **kwargs: None


def read_concepts(path):
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").split("\n")
        if line.strip() and not line.strip().startswith("#")
    ]


@pytest.fixture
def concepts_dir(tmp_path, monkeypatch):
    """A temp concepts directory holding a single known file."""
    (tmp_path / COLORS_FILE).write_text("\n".join(INITIAL_COLORS) + "\n", encoding="utf-8")
    monkeypatch.setattr(Concepts, "CONCEPTS_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture
def editor(qapp, concepts_dir, monkeypatch):
    """An open Concept Editor pointed at the temp directory, password gate open."""
    crossings = install_password_bypass(monkeypatch)
    actions = RecordingAppActions()
    window = ConceptEditorWindow(parent=None, app_actions=actions)
    window._app_actions = actions
    idx = window._file_combo.findText(COLORS_FILE)
    if idx >= 0:
        window._file_combo.setCurrentIndex(idx)
    window._test_actions = actions
    window._test_crossings = crossings
    try:
        yield window
    finally:
        window.close()


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------

class TestConceptEditorOpens:
    def test_file_combo_lists_the_concept_file(self, editor):
        assert editor._file_combo.findText(COLORS_FILE) >= 0

    def test_selected_file_is_the_one_under_test(self, editor):
        assert editor._file_combo.currentText() == COLORS_FILE

    def test_reads_concepts_from_the_temp_directory(self, editor):
        assert editor._get_concepts_from_file(COLORS_FILE) == INITIAL_COLORS


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

class TestSaveConcept:
    def test_new_concept_reaches_disk(self, editor, concepts_dir):
        editor._search_edit.setText("crimson")
        editor._save_concept()
        assert "crimson" in read_concepts(concepts_dir / COLORS_FILE)

    def test_existing_concepts_survive_the_save(self, editor, concepts_dir):
        editor._search_edit.setText("crimson")
        editor._save_concept()
        on_disk = read_concepts(concepts_dir / COLORS_FILE)
        assert set(INITIAL_COLORS) <= set(on_disk)

    def test_concept_is_inserted_in_alphabetical_position(self, editor, concepts_dir):
        """Not appended -- this ordering is what Konzepte/ mirrors."""
        editor._search_edit.setText("crimson")
        editor._save_concept()
        assert read_concepts(concepts_dir / COLORS_FILE) == [
            "amber", "cobalt", "crimson", "emerald",
        ]

    def test_comments_are_preserved(self, editor, concepts_dir):
        path = concepts_dir / COLORS_FILE
        path.write_text("# palette\namber\nemerald\n", encoding="utf-8")
        editor._invalidate_cache(COLORS_FILE)
        editor._search_edit.setText("cobalt")
        editor._save_concept()
        assert "# palette" in path.read_text(encoding="utf-8")

    def test_empty_input_writes_nothing(self, editor, concepts_dir):
        editor._search_edit.setText("   ")
        editor._save_concept()
        assert read_concepts(concepts_dir / COLORS_FILE) == INITIAL_COLORS

    def test_empty_input_tells_the_user(self, editor):
        editor._search_edit.setText("")
        editor._save_concept()
        assert editor._test_actions.toasts

    def test_duplicate_is_not_written_twice(self, editor, concepts_dir):
        editor._search_edit.setText("amber")
        editor._save_concept()
        on_disk = read_concepts(concepts_dir / COLORS_FILE)
        assert on_disk.count("amber") == 1

    def test_save_is_behind_the_password_gate(self, editor):
        editor._search_edit.setText("crimson")
        editor._save_concept()
        assert editor._test_crossings, "_save_concept ran without crossing the gate"

    def test_saved_concept_is_recorded_in_history(self, editor):
        editor._search_edit.setText("crimson")
        editor._save_concept()
        assert "crimson" in ConceptEditorWindow.concept_change_history


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteConcept:
    def _select(self, editor, concept):
        editor._current_concept = concept
        editor._current_file = COLORS_FILE

    def test_confirmed_delete_removes_from_disk(self, editor, concepts_dir):
        self._select(editor, "cobalt")
        editor._delete_concept()
        assert "cobalt" not in read_concepts(concepts_dir / COLORS_FILE)

    def test_other_concepts_are_untouched(self, editor, concepts_dir):
        self._select(editor, "cobalt")
        editor._delete_concept()
        assert read_concepts(concepts_dir / COLORS_FILE) == ["amber", "emerald"]

    def test_declined_confirmation_keeps_the_concept(self, editor, concepts_dir):
        editor._test_actions._confirm = False
        self._select(editor, "cobalt")
        editor._delete_concept()
        assert "cobalt" in read_concepts(concepts_dir / COLORS_FILE)

    def test_nothing_selected_writes_nothing(self, editor, concepts_dir):
        editor._current_concept = None
        editor._current_file = None
        editor._delete_concept()
        assert read_concepts(concepts_dir / COLORS_FILE) == INITIAL_COLORS

    def test_already_removed_concept_warns_rather_than_raising(self, editor, concepts_dir):
        self._select(editor, "not_a_color")
        editor._delete_concept()
        assert editor._test_actions.warnings

    def test_delete_is_behind_the_password_gate(self, editor):
        self._select(editor, "cobalt")
        editor._delete_concept()
        assert editor._test_crossings, "_delete_concept ran without crossing the gate"

    def test_comments_survive_a_delete(self, editor, concepts_dir):
        path = concepts_dir / COLORS_FILE
        path.write_text("# palette\namber\ncobalt\n", encoding="utf-8")
        editor._invalidate_cache(COLORS_FILE)
        self._select(editor, "cobalt")
        editor._delete_concept()
        assert "# palette" in path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Save then delete — the sequence that exposed the stale-index bug
# ---------------------------------------------------------------------------

class TestSaveThenDelete:
    def test_round_trip_restores_the_original_file(self, editor, concepts_dir):
        editor._search_edit.setText("crimson")
        editor._save_concept()
        editor._current_concept = "crimson"
        editor._current_file = COLORS_FILE
        editor._delete_concept()
        assert read_concepts(concepts_dir / COLORS_FILE) == INITIAL_COLORS

    def test_deleting_the_wrong_line_would_show_here(self, editor, concepts_dir):
        """A stale concept index deletes the displaced neighbour instead."""
        editor._search_edit.setText("crimson")
        editor._save_concept()
        editor._current_concept = "crimson"
        editor._current_file = COLORS_FILE
        editor._delete_concept()
        assert "emerald" in read_concepts(concepts_dir / COLORS_FILE)
