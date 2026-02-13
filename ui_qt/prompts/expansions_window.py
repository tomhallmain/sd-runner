"""
ExpansionsWindow / ExpansionModifyWindow -- manage prompt expansions (PySide6 port).

Ported from ``ui/expansions_window.py``.

Static data helpers (``set_expansions``, ``store_expansions``, ``get_expansion_names``,
``get_most_recent_expansion_name``, ``get_history_expansion``, ``update_history``,
``next_expansion``) are re-exported from the original Tkinter backend so that
call-sites can keep using one import path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui.expansion import Expansion
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N
from utils.utils import Utils

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ---------------------------------------------------------------------------
# Re-export static helpers from the Tkinter backend
# ---------------------------------------------------------------------------
from ui.expansions_window import ExpansionsWindow as _Backend  # noqa: E402

set_expansions = _Backend.set_expansions
store_expansions = _Backend.store_expansions
get_expansion_names = _Backend.get_expansion_names
get_most_recent_expansion_name = _Backend.get_most_recent_expansion_name
get_history_expansion = _Backend.get_history_expansion
update_history = _Backend.update_history
next_expansion = _Backend.next_expansion


# ======================================================================
# ExpansionModifyWindow
# ======================================================================
class ExpansionModifyWindow(SmartDialog):
    """Create or edit a single :class:`Expansion`."""

    def __init__(
        self,
        parent: QWidget,
        refresh_callback: Callable,
        expansion: Optional[Expansion],
        app_actions: AppActions,
        geometry: str = "600x350",
    ):
        self._is_new = expansion is None
        self._expansion = expansion if expansion is not None else Expansion("", "")
        self._refresh_callback = refresh_callback
        self._app_actions = app_actions

        super().__init__(
            parent=parent,
            title=_("Modify Expansion: {0}").format(self._expansion.id),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.apply_stylesheet())
        self._build_ui()
        self._check_wildcard_clash()
        self.show()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        # Expansion ID
        layout.addWidget(QLabel(_("Expansion ID")))
        self._name_edit = QLineEdit(
            "NewExp" if self._is_new else self._expansion.id
        )
        self._name_edit.textChanged.connect(self._check_wildcard_clash)
        layout.addWidget(self._name_edit)

        # Expansion Text
        layout.addWidget(QLabel(_("Expansion Text")))
        self._text_edit = QLineEdit(
            _("New Expansion Text") if self._is_new else self._expansion.text
        )
        layout.addWidget(self._text_edit)

        # Warning label for wildcard clashes
        self._warning_label = QLabel("")
        self._warning_label.setWordWrap(True)
        self._warning_label.setStyleSheet("color: red;")
        layout.addWidget(self._warning_label)

        layout.addStretch()

        # Done button
        btn_row = QHBoxLayout()
        done_btn = QPushButton(_("Done"))
        done_btn.clicked.connect(self._finalize_expansion)
        btn_row.addWidget(done_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Escape to close
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)

    # ------------------------------------------------------------------
    def _check_wildcard_clash(self) -> bool:
        """Return True if the expansion name clashes with a config wildcard."""
        from utils.config import config
        name = self._name_edit.text().strip()
        if name in config.wildcards:
            self._warning_label.setText(
                _("Warning: This expansion ID matches a wildcard in config.json. "
                  "Changes will not take effect until the wildcard is removed or renamed.")
            )
            return True
        self._warning_label.setText("")
        return False

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def _finalize_expansion(self) -> None:
        if self._check_wildcard_clash():
            if not self._app_actions.alert(
                _("Warning"),
                _("This expansion ID matches a wildcard in config.json. "
                  "Changes will not take effect until the wildcard is removed "
                  "or renamed.\n\nDo you want to save anyway?"),
                kind="askyesno",
                master=self,
            ):
                return

        self._expansion.id = self._name_edit.text().strip()
        self._expansion.text = self._text_edit.text().strip()
        self.close()
        self._refresh_callback(self._expansion)


# ======================================================================
# ExpansionsWindow
# ======================================================================
class ExpansionsWindow(SmartDialog):
    """Manage the list of prompt expansions."""

    _modify_window: Optional[ExpansionModifyWindow] = None

    def __init__(
        self,
        parent: QWidget,
        app_actions: AppActions,
        geometry: str = "700x400",
    ):
        super().__init__(
            parent=parent,
            title=_("Expansions Window"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.apply_stylesheet())
        self._app_actions = app_actions
        self._filter_text = ""
        self._filtered_expansions: list[Expansion] = Expansion.expansions[:]
        self._table: Optional[QTableWidget] = None

        self._build_ui()
        self._rebuild_table()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        self.show()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # Header row
        header = QHBoxLayout()
        header.addWidget(QLabel(_("Add or update expansions")))
        header.addStretch()
        add_btn = QPushButton(_("Add expansion"))
        add_btn.clicked.connect(self._add_empty_expansion)
        header.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear expansions"))
        clear_btn.clicked.connect(self._clear_expansions)
        header.addWidget(clear_btn)
        root.addLayout(header)

        # Status / filter label
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-style: italic; font-size: 9pt;")
        root.addWidget(self._status_label)

        # Table placeholder
        self._table_container = QVBoxLayout()
        root.addLayout(self._table_container, stretch=1)

        # Action buttons
        actions = QHBoxLayout()
        for text, handler in [
            (_("Modify"), self._modify_selected),
            (_("Delete"), self._delete_selected),
            (_("Copy"), self._copy_selected),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            actions.addWidget(b)
        actions.addStretch()
        root.addLayout(actions)

    # ------------------------------------------------------------------
    # Table rebuild
    # ------------------------------------------------------------------
    def _rebuild_table(self) -> None:
        # Clear old table
        if self._table is not None:
            self._table_container.removeWidget(self._table)
            self._table.deleteLater()
            self._table = None

        # Remove any "no items" label
        while self._table_container.count():
            child = self._table_container.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        total = len(Expansion.expansions)
        showing = len(self._filtered_expansions)

        # Status line
        if self._filter_text.strip():
            self._status_label.setText(
                _("Filter: \"{0}\"  ({1} of {2} expansions)").format(
                    self._filter_text, showing, total,
                )
            )
        else:
            self._status_label.setText(
                _("{0} expansions").format(total)
            )

        if showing == 0:
            msg = (
                _("No expansions match the current filter.")
                if self._filter_text.strip()
                else _("No expansions defined. Click 'Add expansion' to create one.")
            )
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            self._table_container.addWidget(lbl)
            return

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([_("ID"), _("Text")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().resizeSection(0, 180)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_dblclick)

        for i, exp in enumerate(self._filtered_expansions):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(exp.id))
            table.setItem(
                i, 1,
                QTableWidgetItem(Utils.get_centrally_truncated_string(exp.text, 80)),
            )

        self._table = table
        self._table_container.addWidget(table)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    def _selected_expansion(self) -> Optional[Expansion]:
        if self._table is None:
            return None
        row = self._table.currentRow()
        if 0 <= row < len(self._filtered_expansions):
            return self._filtered_expansions[row]
        return None

    def _on_dblclick(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._filtered_expansions):
            self._open_modify_window(self._filtered_expansions[row])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _modify_selected(self) -> None:
        exp = self._selected_expansion()
        if exp:
            self._open_modify_window(exp)
        else:
            self._app_actions.toast(_("Select an expansion first"))

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def _open_modify_window(self, expansion: Optional[Expansion] = None) -> None:
        if ExpansionsWindow._modify_window is not None:
            try:
                ExpansionsWindow._modify_window.close()
            except RuntimeError:
                pass
        ExpansionsWindow._modify_window = ExpansionModifyWindow(
            self, self._refresh_after_modify, expansion, self._app_actions,
        )

    def _refresh_after_modify(self, expansion: Expansion) -> None:
        _Backend.update_history(expansion)
        if expansion in Expansion.expansions:
            Expansion.expansions.remove(expansion)
        Expansion.expansions.insert(0, expansion)
        self._filtered_expansions = Expansion.expansions[:]
        self._filter_text = ""
        _Backend.store_expansions()
        self._rebuild_table()

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def _add_empty_expansion(self) -> None:
        Expansion.expansions.insert(0, Expansion("", ""))
        self._filtered_expansions = Expansion.expansions[:]
        self._filter_text = ""
        _Backend.store_expansions()
        self._rebuild_table()

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def _delete_selected(self) -> None:
        exp = self._selected_expansion()
        if exp is None:
            self._app_actions.toast(_("Select an expansion first"))
            return
        if exp in Expansion.expansions:
            Expansion.expansions.remove(exp)
        self._filtered_expansions = Expansion.expansions[:]
        _Backend.store_expansions()
        self._rebuild_table()

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def _clear_expansions(self) -> None:
        Expansion.expansions.clear()
        self._filtered_expansions.clear()
        self._filter_text = ""
        _Backend.store_expansions()
        self._rebuild_table()

    def _copy_selected(self) -> None:
        exp = self._selected_expansion()
        if exp is None:
            self._app_actions.toast(_("Select an expansion first"))
            return
        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard and exp.text:
            clipboard.setText(exp.text)
            self._app_actions.toast(_("Copied expansion text to clipboard"))

    # ------------------------------------------------------------------
    # Keyboard filter
    # ------------------------------------------------------------------
    def keyPressEvent(self, event) -> None:  # noqa: N802
        # Don't intercept when a text widget has focus
        fw = self.focusWidget()
        if isinstance(fw, (QLineEdit, QPlainTextEdit)):
            super().keyPressEvent(event)
            return

        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            super().keyPressEvent(event)
            return

        key = event.key()

        # Arrow keys: rotate the filtered list
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._filtered_expansions:
            if key == Qt.Key.Key_Down:
                self._filtered_expansions = (
                    self._filtered_expansions[1:] + [self._filtered_expansions[0]]
                )
            else:
                self._filtered_expansions = (
                    [self._filtered_expansions[-1]] + self._filtered_expansions[:-1]
                )
            self._rebuild_table()
            return

        if key == Qt.Key.Key_Backspace:
            if self._filter_text:
                self._filter_text = self._filter_text[:-1]
            else:
                return
        else:
            text = event.text()
            if not text or not text.isprintable():
                super().keyPressEvent(event)
                return
            self._filter_text += text

        self._apply_filter()

    def _apply_filter(self) -> None:
        if not self._filter_text.strip():
            self._filtered_expansions = Expansion.expansions[:]
        else:
            ft = self._filter_text.lower()
            tier1, tier2, tier3 = [], [], []
            for exp in Expansion.expansions:
                combined = f"{exp.id} {exp.text}".lower()
                if combined.startswith(ft) or exp.id.lower().startswith(ft):
                    tier1.append(exp)
                elif f" {ft}" in combined or f"_{ft}" in combined:
                    tier2.append(exp)
                elif ft in combined:
                    tier3.append(exp)
            self._filtered_expansions = tier1 + tier2 + tier3
        self._rebuild_table()
