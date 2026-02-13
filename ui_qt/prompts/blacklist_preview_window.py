"""
BlacklistPreviewWindow -- preview and test blacklist items (PySide6 port).

Two sections:
1. **Test Text** -- enter arbitrary text and see which blacklist rules
   match, adapted from the muse project's preview window.
2. **Concept Preview** -- browse predefined concept lists filtered by
   a specific blacklist item (or all items).

Both sections require ``REVEAL_BLACKLIST_CONCEPTS`` permission.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QLabel, QListWidget,
    QPlainTextEdit, QPushButton, QTabWidget,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.blacklist import Blacklist, BlacklistItem
from sd_runner.concepts import Concepts
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


class BlacklistPreviewWindow(SmartDialog):
    """Preview blacklist effects: test arbitrary text **and** browse
    matched concepts from predefined concept lists.

    Category checkbox states are persisted at the class level so they
    survive window re-opens within the same session.
    """

    # Class-level persistence for category checkboxes
    _persisted_category_states: dict[str, bool] = {
        "SFW": True,
        "NSFW": False,
        "NSFL": False,
        "Art Styles": True,
        "Dictionary": True,
    }

    def __init__(
        self,
        parent: QWidget,
        app_actions: Optional[AppActions],
        blacklist_item: Optional[BlacklistItem] = None,
    ):
        super().__init__(
            parent=parent,
            title=_("Blacklist Preview"),
            geometry="650x550",
        )
        self._app_actions = app_actions
        self._item = blacklist_item

        root = QVBoxLayout(self)

        # --- Tabs -----------------------------------------------------------
        tabs = QTabWidget()
        test_page = QWidget()
        concepts_page = QWidget()
        tabs.addTab(test_page, _("Test Text"))
        tabs.addTab(concepts_page, _("Concept Preview"))
        root.addWidget(tabs)

        self._build_test_tab(test_page)
        self._build_concepts_tab(concepts_page)

        # --- Close ----------------------------------------------------------
        btn_row = QHBoxLayout()
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        QShortcut(QKeySequence("Escape"), self, self.close)
        self.show()

    # ==================================================================
    # Tab 1 -- Test Text
    # ==================================================================
    def _build_test_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        layout.addWidget(
            QLabel(_("Enter text to test (tags can be comma- or dot-separated):"))
        )

        self._input_text = QPlainTextEdit()
        self._input_text.setPlaceholderText(
            _("Type or paste text here, then click Test...")
        )
        self._input_text.setMinimumHeight(100)
        self._input_text.setMaximumHeight(160)
        self._input_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._input_text)

        test_btn = QPushButton(_("Test against blacklist"))
        test_btn.clicked.connect(self._run_test)
        layout.addWidget(test_btn)

        layout.addWidget(QLabel(_("Result:")))

        self._result_text = QPlainTextEdit()
        self._result_text.setReadOnly(True)
        self._result_text.setMinimumHeight(120)
        self._result_text.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        layout.addWidget(self._result_text, stretch=1)

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _run_test(self) -> None:
        text = self._input_text.toPlainText().strip()
        if not text:
            self._result_text.setPlainText(
                _("Enter some text above, then click Test.")
            )
            return

        filtered = Blacklist.find_blacklisted_items(text)
        if not filtered:
            self._result_text.setPlainText(_("No blacklist items matched."))
            return

        lines = [_("Matched {0} item(s):").format(len(filtered)), ""]
        for tag, rule in sorted(filtered.items(), key=lambda x: (x[1], x[0])):
            lines.append(_("  \"{0}\" -> rule \"{1}\"").format(tag, rule))
        self._result_text.setPlainText("\n".join(lines))

    # ==================================================================
    # Tab 2 -- Concept Preview
    # ==================================================================
    def _build_concepts_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        # Title
        if self._item:
            title_text = _("Concepts filtered by: {0}").format(self._item.string)
            if self._item.use_regex:
                title_text += " [regex]"
        else:
            title_text = _("All filtered concepts")
        title = QLabel(title_text)
        title.setStyleSheet("font-weight: bold; font-size: 10pt;")
        layout.addWidget(title)

        # Category checkboxes
        cb_row = QHBoxLayout()
        self._cat_cbs: dict[str, QCheckBox] = {}
        for cat, checked in self._persisted_category_states.items():
            cb = QCheckBox(cat)
            cb.setChecked(checked)
            cb.stateChanged.connect(self._on_category_changed)
            self._cat_cbs[cat] = cb
            cb_row.addWidget(cb)
        cb_row.addStretch()
        layout.addLayout(cb_row)

        # Count label
        self._count_label = QLabel("")
        layout.addWidget(self._count_label)

        # List
        self._list = QListWidget()
        self._list.setSelectionMode(QListWidget.SelectionMode.NoSelection)
        layout.addWidget(self._list, stretch=1)

        self._load_concepts()

    # ------------------------------------------------------------------
    def _get_category_states(self) -> dict[str, bool]:
        return {name: cb.isChecked() for name, cb in self._cat_cbs.items()}

    def _on_category_changed(self) -> None:
        states = self._get_category_states()
        for cat, val in states.items():
            BlacklistPreviewWindow._persisted_category_states[cat] = val
        self._load_concepts()

    def _load_concepts(self) -> None:
        try:
            states = self._get_category_states()
            filtered = Concepts.get_filtered_concepts_for_preview(
                self._item, states,
            )
            self._count_label.setText(
                _("Found {0} filtered concepts").format(len(filtered))
            )
            self._list.clear()
            for concept in sorted(set(filtered)):
                self._list.addItem(concept)
        except Exception as e:
            msg = _("Error loading concepts: {0}").format(e)
            self._count_label.setText(msg)
            if self._app_actions:
                self._app_actions.alert(_("Error"), msg, kind="error", master=self)
