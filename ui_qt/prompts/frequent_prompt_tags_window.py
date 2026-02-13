"""
FrequentPromptTagsWindow -- browse and apply frequently-used prompt tags (PySide6 port).

Ported from ``ui/frequent_prompt_tags_window.py``.

.. note::

    **Not yet exposed in the UI.**  A launcher method exists in
    ``WindowLauncher.open_frequent_tags_window`` but no button or
    keybinding invokes it yet.  ``app_actions.add_tags`` must also be
    wired in ``AppWindow._build_app_actions`` before this window is
    functional.

Static data helpers (``set_recent_tags``, ``get_history_tag``,
``update_history``) are re-exported from the original Tkinter backend.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
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
from ui_qt.app_style import AppStyle
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ---------------------------------------------------------------------------
# Re-export the FrequentTags data holder and static helpers
# ---------------------------------------------------------------------------
from ui.frequent_prompt_tags_window import FrequentTags  # noqa: E402
from ui.frequent_prompt_tags_window import (  # noqa: E402
    FrequentPromptTagsWindow as _Backend,
)

set_recent_tags = _Backend.set_recent_tags
get_history_tag = _Backend.get_history_tag
update_history = _Backend.update_history


# ======================================================================
# FrequentPromptTagsWindow
# ======================================================================
class FrequentPromptTagsWindow(SmartDialog):
    """Display, filter, and apply frequently-used prompt tags."""

    MAX_TAGS = _Backend.MAX_TAGS

    last_set_tag: Optional[str] = None

    def __init__(
        self,
        parent: QWidget,
        app_actions: AppActions,
        geometry: str = "600x400",
    ):
        super().__init__(
            parent=parent,
            title=_("Frequent Prompt Tags"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.apply_stylesheet())
        self._app_actions = app_actions
        self._filter_text = ""
        self._filtered_tags: list[str] = FrequentTags.tags[:]
        self._table: Optional[QTableWidget] = None

        self._build_ui()
        self._rebuild_table()

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        QShortcut(QKeySequence(Qt.Key.Key_Return), self).activated.connect(self._do_action)
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
        header.addWidget(QLabel(_("Select or add prompt tags")))
        header.addStretch()
        add_btn = QPushButton(_("Add tag"))
        add_btn.clicked.connect(self._add_tag_dialog)
        header.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear tags"))
        clear_btn.clicked.connect(self._clear_tags)
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
        set_btn = QPushButton(_("Set"))
        set_btn.clicked.connect(self._set_selected)
        actions.addWidget(set_btn)
        actions.addStretch()
        root.addLayout(actions)

    # ------------------------------------------------------------------
    # Table rebuild
    # ------------------------------------------------------------------
    def _rebuild_table(self) -> None:
        # Remove previous content
        while self._table_container.count():
            child = self._table_container.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
        self._table = None

        total = len(FrequentTags.tags)
        showing = len(self._filtered_tags)

        # Status line
        if self._filter_text.strip():
            self._status_label.setText(
                _("Filter: \"{0}\"  ({1} of {2} tags)").format(
                    self._filter_text, showing, total,
                )
            )
        else:
            self._status_label.setText(
                _("{0} tags").format(total)
            )

        if showing == 0:
            msg = (
                _("No tags match the current filter.")
                if self._filter_text.strip()
                else _("No frequent tags yet. Click 'Add tag' to create one.")
            )
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            self._table_container.addWidget(lbl)
            return

        table = QTableWidget()
        table.setColumnCount(1)
        table.setHorizontalHeaderLabels([_("Tag")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_dblclick)

        for i, tag in enumerate(self._filtered_tags):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(tag))

        self._table = table
        self._table_container.addWidget(table)

    # ------------------------------------------------------------------
    # Selection helpers
    # ------------------------------------------------------------------
    def _selected_tag(self) -> Optional[str]:
        if self._table is None:
            return None
        row = self._table.currentRow()
        if 0 <= row < len(self._filtered_tags):
            return self._filtered_tags[row]
        return None

    def _on_dblclick(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._filtered_tags):
            self._apply_tag(self._filtered_tags[row])

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _set_selected(self) -> None:
        tag = self._selected_tag()
        if tag:
            self._apply_tag(tag)
        else:
            self._app_actions.toast(_("Select a tag first"))

    def _apply_tag(self, tag: str) -> None:
        """Apply the tag via app_actions callback, update history, close."""
        _Backend.update_history(tag)
        # Move to front of the tags list
        if tag in FrequentTags.tags:
            FrequentTags.tags.remove(tag)
        FrequentTags.tags.insert(0, tag)
        FrequentPromptTagsWindow.last_set_tag = tag
        try:
            self._app_actions.add_tags(tag)
        except AttributeError:
            # add_tags not yet wired -- toast instead of crashing
            self._app_actions.toast(
                _("add_tags callback not wired yet. Tag: {0}").format(tag)
            )
        self.close()

    def _add_tag_dialog(self) -> None:
        """Prompt the user for a new tag string."""
        text, ok = QInputDialog.getText(
            self, _("Add Tag"), _("Enter tag text:"),
        )
        if ok and text and text.strip():
            tag = text.strip()
            if tag in FrequentTags.tags:
                FrequentTags.tags.remove(tag)
            FrequentTags.tags.insert(0, tag)
            self._filtered_tags = FrequentTags.tags[:]
            self._filter_text = ""
            self._rebuild_table()

    def _clear_tags(self) -> None:
        FrequentTags.tags.clear()
        self._filtered_tags.clear()
        self._filter_text = ""
        self._rebuild_table()

    def _do_action(self) -> None:
        """
        Enter-key handler.  Apply the first visible tag (or the last-set
        tag if the list is unfiltered with more than one entry).
        """
        if not self._filtered_tags:
            return
        if len(self._filtered_tags) == 1 or self._filter_text.strip():
            tag = self._filtered_tags[0]
        else:
            tag = FrequentPromptTagsWindow.last_set_tag or self._filtered_tags[0]
        self._apply_tag(tag)

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
        if key in (Qt.Key.Key_Up, Qt.Key.Key_Down) and self._filtered_tags:
            if key == Qt.Key.Key_Down:
                self._filtered_tags = (
                    self._filtered_tags[1:] + [self._filtered_tags[0]]
                )
            else:
                self._filtered_tags = (
                    [self._filtered_tags[-1]] + self._filtered_tags[:-1]
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
            self._filtered_tags = FrequentTags.tags[:]
        else:
            ft = self._filter_text.lower()
            tier1, tier2, tier3 = [], [], []
            for tag in FrequentTags.tags:
                tl = tag.lower()
                if tl == ft:
                    tier1.append(tag)
                elif tl.startswith(ft):
                    tier1.append(tag)
                elif f" {ft}" in tl or f"_{ft}" in tl:
                    tier2.append(tag)
                elif ft in tl:
                    tier3.append(tag)
            self._filtered_tags = tier1 + tier2 + tier3
        self._rebuild_table()
