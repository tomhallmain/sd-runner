"""
ConceptEditorWindow -- browse, search, add, delete, and import concepts (PySide6 port).

Ported from ``ui/concept_editor_window.py``.

**Status: Shell only** -- UI skeleton and static helpers are wired but the
full implementation still needs to be completed.

Key widgets (planned):
    - Search ``QLineEdit`` at top
    - Category ``QCheckBox`` row (SFW, NSFW, NSFL, Art Styles, Dictionary)
    - ``QListWidget`` for concept results
    - File ``QComboBox`` for target file selection
    - Save / Delete / Import buttons
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.concepts import Concepts, SFW, NSFW, NSFL, ArtStyles
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ---------------------------------------------------------------------------
# Re-export static helpers from the Tkinter backend
# ---------------------------------------------------------------------------
from ui.concept_editor_window import ConceptEditorWindow as _Backend  # noqa: E402

load_concept_changes = _Backend.load_concept_changes
store_concept_changes = _Backend.store_concept_changes
get_history_concept_change = _Backend.get_history_concept_change
update_history = _Backend.update_history


# ======================================================================
# ConceptEditorWindow
# ======================================================================
class ConceptEditorWindow(SmartDialog):
    """Browse and edit concept lists across multiple category files."""

    # Category definitions: name -> (class_obj | None, default_checked)
    FILE_CATEGORIES: Dict[str, tuple] = {
        "SFW": (SFW, True),
        "NSFW": (NSFW, False),
        "NSFL": (NSFL, False),
        "Art Styles": (ArtStyles, True),
        "Dictionary": (None, False),
    }

    def __init__(
        self,
        parent: QWidget,
        app_actions: AppActions,
        geometry: str = "500x400",
    ):
        super().__init__(
            parent=parent,
            title=_("Concept Editor"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.apply_stylesheet())
        self._app_actions = app_actions

        self._search_text = ""
        self._filtered_concepts: list[str] = []
        self._concept_files: list[str] = []
        self._loaded_concepts: Dict[str, list[str]] = {}
        self._current_concept: Optional[str] = None
        self._current_file: Optional[str] = None
        self._category_checks: Dict[str, QCheckBox] = {}

        self._build_ui()
        self._load_concept_files()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        self.show()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Search row
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_("Search/Add Concept:")))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_("Type to search concepts..."))
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_edit, stretch=1)
        root.addLayout(search_row)

        # Category checkboxes
        cb_row = QHBoxLayout()
        for name, (cls_obj, default_checked) in self.FILE_CATEGORIES.items():
            cb = QCheckBox(name)
            cb.setChecked(default_checked)
            cb.stateChanged.connect(self._refresh)
            self._category_checks[name] = cb
            cb_row.addWidget(cb)
        cb_row.addStretch()
        root.addLayout(cb_row)

        # Concept list
        self._concept_list = QListWidget()
        self._concept_list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._concept_list.currentRowChanged.connect(self._on_concept_select)
        root.addWidget(self._concept_list, stretch=1)

        # File combo
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(_("File:")))
        self._file_combo = QComboBox()
        self._file_combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        file_row.addWidget(self._file_combo, stretch=1)
        root.addLayout(file_row)

        help_label = QLabel(_("(Target file for saving new concepts and importing)"))
        help_label.setStyleSheet("font-size: 8pt;")
        root.addWidget(help_label)

        # Action buttons
        btn_row = QHBoxLayout()
        save_btn = QPushButton(_("Save"))
        save_btn.clicked.connect(self._save_concept)
        btn_row.addWidget(save_btn)
        delete_btn = QPushButton(_("Delete"))
        delete_btn.clicked.connect(self._delete_concept)
        btn_row.addWidget(delete_btn)
        import_btn = QPushButton(_("Import"))
        import_btn.clicked.connect(self._import_concepts)
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _get_category_states(self) -> Dict[str, bool]:
        return {name: cb.isChecked() for name, cb in self._category_checks.items()}

    def _load_concept_files(self) -> None:
        category_states = self._get_category_states()
        self._concept_files = Concepts.get_concept_files(category_states)
        self._file_combo.clear()
        self._file_combo.addItems(sorted(self._concept_files))

    def _get_concepts_from_file(self, filename: str) -> list[str]:
        if filename not in self._loaded_concepts:
            self._loaded_concepts[filename] = Concepts.load(filename)
        return self._loaded_concepts[filename]

    # ------------------------------------------------------------------
    # Refresh / search
    # ------------------------------------------------------------------
    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.lower()
        self._refresh()

    def _refresh(self) -> None:
        """Refresh concept list from current search + category state."""
        self._load_concept_files()
        self._concept_list.clear()
        self._filtered_concepts = []

        if not self._search_text:
            self._concept_list.addItem(_("Enter search text to see concepts..."))
            return

        tier1, tier2, tier3 = [], [], []
        for filename in self._concept_files:
            concepts = self._get_concepts_from_file(filename)
            for concept in concepts:
                cl = concept.lower()
                if self._search_text in cl:
                    if cl.startswith(self._search_text):
                        tier1.append(concept)
                    elif any(self._search_text in word for word in cl.split()):
                        tier2.append(concept)
                    else:
                        tier3.append(concept)

        self._filtered_concepts = tier1 + tier2 + tier3
        for c in self._filtered_concepts:
            self._concept_list.addItem(c)

    def _on_concept_select(self, row: int) -> None:
        if row < 0 or row >= len(self._filtered_concepts):
            return
        self._current_concept = self._filtered_concepts[row]
        for filename in self._concept_files:
            if self._current_concept in self._get_concepts_from_file(filename):
                self._current_file = filename
                idx = self._file_combo.findText(filename)
                if idx >= 0:
                    self._file_combo.setCurrentIndex(idx)
                break

    # ------------------------------------------------------------------
    # CRUD (shells -- TODO: complete implementation)
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _save_concept(self) -> None:
        new_concept = self._search_edit.text().strip()
        if not new_concept:
            return
        selected_file = self._file_combo.currentText()
        if not selected_file:
            self._app_actions.alert(
                _("Error"), _("Please select a file to save to"),
                kind="error", master=self,
            )
            return
        concepts = self._get_concepts_from_file(selected_file)
        if new_concept not in concepts:
            concepts.append(new_concept)
            concepts.sort()
            Concepts.save(selected_file, concepts)
            self._app_actions.toast(_("Saved concept: {0}").format(new_concept))
            self._refresh()

    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _delete_concept(self) -> None:
        if not self._current_concept or not self._current_file:
            return
        if self._app_actions.alert(
            _("Confirm"),
            _("Delete concept: {0}?").format(self._current_concept),
            kind="askyesno",
            master=self,
        ):
            concepts = self._get_concepts_from_file(self._current_file)
            if self._current_concept in concepts:
                concepts.remove(self._current_concept)
                Concepts.save(self._current_file, concepts)
                self._app_actions.toast(
                    _("Deleted concept: {0}").format(self._current_concept)
                )
                self._current_concept = None
                self._current_file = None
                self._search_edit.clear()
                self._refresh()

    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _import_concepts(self) -> None:
        target_file = self._file_combo.currentText()
        if not target_file:
            self._app_actions.alert(
                _("Error"), _("Please select a target file first"),
                kind="error", master=self,
            )
            return
        import_file, _ = QFileDialog.getOpenFileName(
            self,
            _("Select concepts file to import"),
            "",
            _("Text files (*.txt);;All files (*.*)"),
        )
        if not import_file:
            return
        category_states = self._get_category_states()
        try:
            imported, failed = Concepts.import_concepts(import_file, target_file, category_states)
        except Exception as e:
            self._app_actions.alert(_("Error"), str(e), kind="error", master=self)
            return
        if imported or failed:
            msg = []
            if imported:
                msg.append(_("Successfully imported {0} concepts").format(len(imported)))
            if failed:
                from pathlib import Path
                msg.append(
                    _("{0} concepts were not imported (see {1}_failed_import.txt for details)").format(
                        len(failed), Path(import_file).stem,
                    )
                )
            msg.append(
                _("Tip: You can prepend '!' to any concept line to force importation, "
                  "or use simply use the concept name as a search term to force import.")
            )
            self._app_actions.alert(
                _("Import Results"), "\n\n".join(msg), kind="info", master=self,
            )
            self._refresh()
