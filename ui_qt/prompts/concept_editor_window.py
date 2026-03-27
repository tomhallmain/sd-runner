"""
ConceptEditorWindow -- browse, search, add, delete, and import concepts (PySide6 port).

Ported from ``ui/concept_editor_window.py``.

Key safety properties:
    - **Save** only writes to the file selected in the file combo.
    - **Delete** only removes the concept from the file it was found in
      (displayed in the combo after selection).
    - **Import** only writes to the combo-selected target file; duplicate
      checks are performed across all enabled categories before writing.
    - Every mutating action invalidates the in-memory cache for the
      affected file so subsequent operations always read from disk.
    - All mutating actions are password-protected via
      ``@require_password(EDIT_CONCEPTS)``.
"""

from __future__ import annotations

from pathlib import Path
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
    """Browse and edit concept lists across multiple category files.

    The window presents a search box, category checkboxes, a results list,
    a file-target combo, and Save / Delete / Import buttons.

    **Data-flow safety:**

    *  An in-memory ``_loaded_concepts`` cache is maintained per-file.
       It is explicitly **invalidated** for a file whenever that file is
       written (save, delete, import) so that every subsequent access
       re-reads from disk.
    *  The ``_current_file`` field is set when the user selects a concept
       from the list (from ``_concept_to_file``). The target file combo is
       only for Save / Import and is not updated by list selection; the
       selected concept's source file and category are shown on a label.
    """

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
        geometry: str = "600x500",
    ):
        super().__init__(
            parent=parent,
            title=_("Concept Editor"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._app_actions = app_actions

        self._search_text: str = ""
        self._filtered_concepts: list[str] = []
        # Map concept -> source filename (rebuilt on every refresh)
        self._concept_to_file: Dict[str, str] = {}
        self._concept_files: list[str] = []
        # Per-file concept cache.  Invalidated after any write.
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

        # --- Search row ---------------------------------------------------
        search_row = QHBoxLayout()
        search_row.addWidget(QLabel(_("Search/Add Concept:")))
        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_("Type to search concepts..."))
        self._search_edit.textChanged.connect(self._on_search_changed)
        search_row.addWidget(self._search_edit, stretch=1)
        root.addLayout(search_row)

        # --- Category checkboxes ------------------------------------------
        cb_row = QHBoxLayout()
        for name, (_cls_obj, default_checked) in self.FILE_CATEGORIES.items():
            cb = QCheckBox(name)
            cb.setChecked(default_checked)
            cb.stateChanged.connect(self._on_category_changed)
            self._category_checks[name] = cb
            cb_row.addWidget(cb)
        cb_row.addStretch()
        root.addLayout(cb_row)

        # --- Status label -------------------------------------------------
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-style: italic; font-size: 9pt;")
        root.addWidget(self._status_label)

        # --- Concept list -------------------------------------------------
        self._concept_list = QListWidget()
        self._concept_list.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self._concept_list.currentRowChanged.connect(self._on_concept_select)
        root.addWidget(self._concept_list, stretch=1)

        # --- Selected concept (source file / category) --------------------
        self._selected_concept_label = QLabel("")
        self._selected_concept_label.setWordWrap(True)
        self._selected_concept_label.setStyleSheet("font-size: 9pt;")
        self._update_selected_concept_label()
        root.addWidget(self._selected_concept_label)

        # --- File combo ---------------------------------------------------
        file_row = QHBoxLayout()
        file_row.addWidget(QLabel(_("File:")))
        self._file_combo = QComboBox()
        self._file_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )
        file_row.addWidget(self._file_combo, stretch=1)
        root.addLayout(file_row)

        help_label = QLabel(
            _("(Target file for saving new concepts and importing)")
        )
        help_label.setStyleSheet("font-size: 8pt;")
        root.addWidget(help_label)

        # --- Action buttons -----------------------------------------------
        btn_row = QHBoxLayout()
        save_btn = QPushButton(_("Save"))
        save_btn.clicked.connect(self._save_concept)
        save_btn.setToolTip(
            _("Add the search text as a new concept to the selected file")
        )
        btn_row.addWidget(save_btn)

        delete_btn = QPushButton(_("Delete"))
        delete_btn.clicked.connect(self._delete_concept)
        delete_btn.setToolTip(
            _("Delete the selected concept from the file it belongs to")
        )
        btn_row.addWidget(delete_btn)

        import_btn = QPushButton(_("Import"))
        import_btn.clicked.connect(self._import_concepts)
        import_btn.setToolTip(
            _("Import concepts from an external text file into the selected file")
        )
        btn_row.addWidget(import_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _get_category_states(self) -> Dict[str, bool]:
        return {name: cb.isChecked() for name, cb in self._category_checks.items()}

    def _category_for_file(self, filename: str) -> str:
        """Return the category display name that owns *filename*, or ''."""
        for cat_name, (cls_obj, _) in self.FILE_CATEGORIES.items():
            if cls_obj is None:
                if cat_name == "Dictionary" and filename == Concepts.ALL_WORDS_LIST_FILENAME:
                    return cat_name
                continue
            for attr_name in dir(cls_obj):
                if attr_name.startswith("_"):
                    continue
                attr_value = getattr(cls_obj, attr_name)
                if isinstance(attr_value, str) and attr_value == filename:
                    return cat_name
        return ""

    def _load_concept_files(self) -> None:
        """Reload the list of concept files based on current category state.

        Preserves the combo's selected file when it remains valid (e.g. after
        search refresh) so unrelated UI updates do not reset the target file.
        """
        previous = (self._file_combo.currentText() or "").strip()
        category_states = self._get_category_states()
        self._concept_files = Concepts.get_concept_files(category_states)
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        self._file_combo.addItems(sorted(self._concept_files))
        if previous and previous in self._concept_files:
            idx = self._file_combo.findText(previous)
            if idx >= 0:
                self._file_combo.setCurrentIndex(idx)
        self._file_combo.blockSignals(False)

    def _update_selected_concept_label(self) -> None:
        """Show the selected list concept's source file and category (not the combo)."""
        if not self._current_concept or not self._current_file:
            self._selected_concept_label.setText(_("Selected concept: —"))
            return
        cat = self._category_for_file(self._current_file)
        if cat:
            self._selected_concept_label.setText(
                _("Selected concept: \"{0}\" — {1} ({2})").format(
                    self._current_concept, self._current_file, cat
                )
            )
        else:
            self._selected_concept_label.setText(
                _("Selected concept: \"{0}\" — {1}").format(
                    self._current_concept, self._current_file
                )
            )

    def _get_concepts_from_file(self, filename: str) -> list[str]:
        """Return concepts from *filename*, using in-memory cache if available."""
        if filename not in self._loaded_concepts:
            self._loaded_concepts[filename] = Concepts.load(filename)
        return self._loaded_concepts[filename]

    def _invalidate_cache(self, filename: str) -> None:
        """Remove *filename* from the concept cache so the next access re-reads disk."""
        self._loaded_concepts.pop(filename, None)

    # ------------------------------------------------------------------
    # Refresh / search
    # ------------------------------------------------------------------
    def _on_category_changed(self) -> None:
        """Category checkbox toggled -- invalidate all caches and refresh."""
        self._loaded_concepts.clear()
        self._refresh()

    def _on_search_changed(self, text: str) -> None:
        self._search_text = text.lower().strip()
        self._refresh()

    def _refresh(self) -> None:
        """Refresh concept list from current search + category state."""
        previous_concept = self._current_concept
        self._load_concept_files()
        self._concept_list.blockSignals(True)
        self._concept_list.clear()
        self._filtered_concepts = []
        self._concept_to_file.clear()

        if not self._search_text:
            self._status_label.setText("")
            self._concept_list.addItem(
                _("Enter search text to see concepts...")
            )
            self._concept_list.setCurrentRow(-1)
            self._concept_list.blockSignals(False)
            self._current_concept = None
            self._current_file = None
            self._update_selected_concept_label()
            return

        tier1: list[tuple[str, str]] = []  # starts-with
        tier2: list[tuple[str, str]] = []  # word-boundary
        tier3: list[tuple[str, str]] = []  # partial

        for filename in self._concept_files:
            concepts = self._get_concepts_from_file(filename)
            for concept in concepts:
                cl = concept.lower()
                if self._search_text in cl:
                    entry = (concept, filename)
                    if cl.startswith(self._search_text):
                        tier1.append(entry)
                    elif any(self._search_text in word for word in cl.split()):
                        tier2.append(entry)
                    else:
                        tier3.append(entry)

        all_matches = tier1 + tier2 + tier3
        for concept, filename in all_matches:
            self._filtered_concepts.append(concept)
            # If the same concept appears in multiple files, the first
            # match (highest-priority tier / alphabetically-first file)
            # wins in the map.  This is consistent with the original.
            if concept not in self._concept_to_file:
                self._concept_to_file[concept] = filename

        for c in self._filtered_concepts:
            self._concept_list.addItem(c)

        self._status_label.setText(
            _("{0} concepts found").format(len(self._filtered_concepts))
        )
        self._concept_list.setCurrentRow(-1)
        self._concept_list.blockSignals(False)
        if previous_concept and previous_concept in self._filtered_concepts:
            self._select_concept_in_list(previous_concept)
        else:
            self._current_concept = None
            self._current_file = None
            self._update_selected_concept_label()

    def _on_concept_select(self, row: int) -> None:
        if row < 0 or row >= len(self._filtered_concepts):
            self._current_concept = None
            self._current_file = None
            self._update_selected_concept_label()
            return
        concept = self._filtered_concepts[row]
        self._current_concept = concept
        self._current_file = self._concept_to_file.get(concept)
        self._update_selected_concept_label()

    def _select_concept_in_list(self, concept: str) -> None:
        """Scroll to and select *concept* in the list widget (if present)."""
        for i in range(self._concept_list.count()):
            if self._concept_list.item(i).text() == concept:
                self._concept_list.setCurrentRow(i)
                self._concept_list.scrollToItem(self._concept_list.item(i))
                break

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _save_concept(self) -> None:
        """Add the search-box text as a new concept to the selected file.

        Safety:
            - Only the file shown in the combo is written to.
            - ``Concepts.save`` uses ``ConceptsFile`` which does a
              diff-based write, preserving comments and line structure.
            - Cache is invalidated for the target file after write.
        """
        new_concept = self._search_edit.text().strip()
        if not new_concept:
            self._app_actions.toast(_("Enter a concept name first"))
            return

        selected_file = self._file_combo.currentText()
        if not selected_file:
            self._app_actions.alert(
                _("Error"),
                _("Please select a file to save to"),
                kind="error",
                master=self,
            )
            return

        # Work from a fresh load to avoid stale-cache issues
        self._invalidate_cache(selected_file)
        concepts = self._get_concepts_from_file(selected_file)

        if new_concept in concepts:
            self._app_actions.toast(
                _("Concept \"{0}\" already exists in {1}").format(
                    new_concept, selected_file
                )
            )
            # Still refresh so user can see it in the list
            self._search_text = new_concept.lower()
            self._search_edit.setText(new_concept)
            self._refresh()
            self._select_concept_in_list(new_concept)
            return

        # Mutate the cached list *and* persist to disk
        concepts.append(new_concept)
        concepts.sort()
        Concepts.save(selected_file, concepts)

        # Invalidate cache so next load picks up the disk state
        self._invalidate_cache(selected_file)

        # Record in history
        _Backend.update_history(new_concept)

        self._app_actions.toast(
            _("Saved concept: {0} → {1}").format(new_concept, selected_file)
        )

        # Refresh and select the new concept
        self._current_file = selected_file
        self._refresh()
        self._select_concept_in_list(new_concept)

    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _delete_concept(self) -> None:
        """Delete the currently selected concept from its source file.

        Safety:
            - The file written to is ``_current_file``, which was set when
              the user clicked a concept in the list.  This is the *source*
              file where the concept was found, **not** the combo selection.
            - A confirmation dialog is shown before deletion.
            - Cache is invalidated for the affected file after write.
        """
        if not self._current_concept or not self._current_file:
            self._app_actions.toast(_("Select a concept first"))
            return

        concept = self._current_concept
        source_file = self._current_file

        if not self._app_actions.alert(
            _("Confirm"),
            _("Delete concept \"{0}\" from {1}?").format(concept, source_file),
            kind="askyesno",
            master=self,
        ):
            return

        # Fresh load to avoid stale-cache issues
        self._invalidate_cache(source_file)
        concepts = self._get_concepts_from_file(source_file)

        if concept not in concepts:
            self._app_actions.warn(
                _("Concept \"{0}\" was not found in {1} -- it may have "
                  "already been removed.").format(concept, source_file)
            )
            self._refresh()
            return

        concepts.remove(concept)
        Concepts.save(source_file, concepts)

        # Invalidate cache
        self._invalidate_cache(source_file)

        # Record in history
        _Backend.update_history(concept)

        self._app_actions.toast(
            _("Deleted concept: {0} from {1}").format(concept, source_file)
        )

        self._current_concept = None
        self._current_file = None
        self._refresh()

    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def _import_concepts(self) -> None:
        """Import concepts from an external text file into the combo-selected file.

        Safety:
            - Only the file shown in the combo is written to.
            - ``Concepts.import_concepts`` checks for duplicates across
              *all* enabled categories before writing.
            - Force-import (``!`` prefix in the import file) bypasses the
              duplicate check but still only writes to the target file.
            - Cache is invalidated for the target file after import.
        """
        target_file = self._file_combo.currentText()
        if not target_file:
            self._app_actions.alert(
                _("Error"),
                _("Please select a target file first"),
                kind="error",
                master=self,
            )
            return

        import_path, _filter = QFileDialog.getOpenFileName(
            self,
            _("Select concepts file to import"),
            "",
            _("Text files (*.txt);;All files (*.*)"),
        )
        if not import_path:
            return

        category_states = self._get_category_states()

        try:
            imported, failed = Concepts.import_concepts(
                import_path, target_file, category_states
            )
        except Exception as e:
            self._app_actions.alert(
                _("Error"), str(e), kind="error", master=self
            )
            return

        # Invalidate cache for the target file
        self._invalidate_cache(target_file)

        # Build results message
        if imported or failed:
            msg_parts: list[str] = []
            if imported:
                msg_parts.append(
                    _("Successfully imported {0} concepts into {1}").format(
                        len(imported), target_file
                    )
                )
            if failed:
                msg_parts.append(
                    _("{0} concepts were not imported (see "
                      "{1}_failed_import.txt for details)").format(
                        len(failed), Path(import_path).stem
                    )
                )
            msg_parts.append(
                _("Tip: You can prepend '!' to any concept line to force "
                  "importation, or simply use the concept name as a search "
                  "term to force import.")
            )
            self._app_actions.alert(
                _("Import Results"),
                "\n\n".join(msg_parts),
                kind="info",
                master=self,
            )

            self._refresh()
        else:
            self._app_actions.toast(
                _("No new concepts to import from {0}").format(
                    Path(import_path).name
                )
            )
