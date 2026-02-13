"""
PresetsWindow -- manage prompt presets (PySide6 port).

Ported from ``ui/presets_window.py``.  The ``Preset`` data class and all
static class-level data (``recent_presets``, ``preset_history``, etc.) live on
the *original* ``ui.presets_window.PresetsWindow`` and are imported from
there so that persistence and ``CacheController`` continue to work
unchanged.  This module only replaces the **UI** portion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui.preset import Preset
from ui.presets_window import PresetsWindow as _PresetsBackend
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


class PresetsWindow(SmartDialog):
    """PySide6 preset management window.

    The window shows all saved presets in a scrollable list.  Each row has
    a label (the preset description), a **Set** button, and a **Delete**
    button.  A top row allows adding a new preset from the current
    sidebar configuration.
    """

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(
            parent=parent,
            title=_("Presets Window"),
            geometry="700x400",
        )
        self._app_actions = app_actions

        # --- Top bar: new-preset name entry + Add / Clear buttons ----------
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel(_("Set a new preset")))
        self._name_entry = QLineEdit(_("New Preset"))
        self._name_entry.setMinimumWidth(250)
        top_bar.addWidget(self._name_entry)
        add_btn = QPushButton(_("Add preset"))
        add_btn.clicked.connect(self._handle_preset)
        top_bar.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear presets"))
        clear_btn.clicked.connect(self._clear_recent_presets)
        top_bar.addWidget(clear_btn)
        top_bar.addStretch()

        # --- Scroll area for preset rows -----------------------------------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._rows_layout = QVBoxLayout(self._scroll_content)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)

        # --- Root layout ----------------------------------------------------
        root = QVBoxLayout(self)
        root.addLayout(top_bar)
        root.addWidget(self._scroll)

        # --- Shortcuts ------------------------------------------------------
        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Return"), self, self._do_action)

        self._rebuild_rows()
        self.show()

    # ------------------------------------------------------------------
    # Row building
    # ------------------------------------------------------------------
    def _rebuild_rows(self) -> None:
        """Clear and re-populate the preset list from the backend."""
        # Remove existing row widgets
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for preset in _PresetsBackend.recent_presets:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)
            label = QLabel(str(preset))
            label.setWordWrap(True)
            label.setMinimumWidth(400)
            h.addWidget(label, stretch=1)

            set_btn = QPushButton(_("Set"))
            set_btn.setFixedWidth(60)
            set_btn.clicked.connect(lambda _=False, p=preset: self._set_preset(p))
            h.addWidget(set_btn)

            del_btn = QPushButton(_("Delete"))
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(lambda _=False, p=preset: self._delete_preset(p))
            h.addWidget(del_btn)

            self._rows_layout.addWidget(row)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _get_preset(self, preset: Preset | None):
        """Return ``(preset, was_existing)``."""
        if preset and preset.is_valid():
            return preset, True
        if preset and preset in _PresetsBackend.recent_presets:
            _PresetsBackend.recent_presets.remove(preset)
            self._app_actions.toast(_("Invalid preset: {0}").format(preset))
        return self._app_actions.construct_preset(self._name_entry.text()), False

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _handle_preset(self, preset: Preset | None = None):
        preset, was_valid = self._get_preset(preset)
        if was_valid and preset is not None:
            if preset in _PresetsBackend.recent_presets:
                _PresetsBackend.recent_presets.remove(preset)
            _PresetsBackend.recent_presets.insert(0, preset)
            return preset
        if preset in _PresetsBackend.recent_presets:
            _PresetsBackend.recent_presets.remove(preset)
        _PresetsBackend.recent_presets.insert(0, preset)
        self._set_preset(preset)
        return preset

    def _set_preset(self, preset: Preset | None = None) -> None:
        if preset is None:
            preset = self._handle_preset(preset=preset)
        _PresetsBackend.update_history(preset)
        _PresetsBackend.last_set_preset = preset
        self._app_actions.set_widgets_from_preset(preset)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _delete_preset(self, preset: Preset | None = None) -> None:
        if preset is not None and preset in _PresetsBackend.recent_presets:
            _PresetsBackend.recent_presets.remove(preset)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _clear_recent_presets(self) -> None:
        _PresetsBackend.recent_presets.clear()
        self._rebuild_rows()

    def _do_action(self) -> None:
        """Enter key handler: set the first preset, or add a new one."""
        if len(_PresetsBackend.recent_presets) == 0:
            self._handle_preset()
        else:
            preset = (
                _PresetsBackend.last_set_preset
                if _PresetsBackend.last_set_preset
                else _PresetsBackend.recent_presets[0]
            )
            self._set_preset(preset)
