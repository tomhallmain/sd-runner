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

    recent_presets = []
    last_set_preset = None
    preset_history = []
    MAX_PRESETS = 50

    @staticmethod
    def set_recent_presets():
        from utils.app_info_cache import app_info_cache
        from ui.preset import Preset
        for preset_dict in list(app_info_cache.get("recent_presets", default_val=[])):
            PresetsWindow.recent_presets.append(Preset.from_dict(preset_dict))

    @staticmethod
    def store_recent_presets():
        from utils.app_info_cache import app_info_cache
        preset_dicts = []
        for preset in PresetsWindow.recent_presets:
            preset_dicts.append(preset.to_dict())
        app_info_cache.set("recent_presets", preset_dicts)

    @staticmethod
    def get_preset_by_name(name):
        for preset in PresetsWindow.recent_presets:
            if name == preset.name:
                return preset
        raise Exception(f"No preset found with name: {name}. Set it on the Presets Window.")

    @staticmethod
    def get_preset_names():
        return sorted(list(map(lambda x: x.name, PresetsWindow.recent_presets)))

    @staticmethod
    def next_preset(alert_callback):
        from utils.translations import I18N
        _ = I18N._
        if len(PresetsWindow.recent_presets) == 0:
            alert_callback(_("Not enough presets found."))
        next_preset = PresetsWindow.recent_presets[-1]
        PresetsWindow.recent_presets.remove(next_preset)
        PresetsWindow.recent_presets.insert(0, next_preset)
        return next_preset

    @staticmethod
    def update_history(preset):
        if len(PresetsWindow.preset_history) > 0 and preset == PresetsWindow.preset_history[0]:
            return
        PresetsWindow.preset_history.insert(0, preset)
        if len(PresetsWindow.preset_history) > PresetsWindow.MAX_PRESETS:
            del PresetsWindow.preset_history[-1]

    @staticmethod
    def get_history_preset(start_index=0):
        preset = None
        for i in range(len(PresetsWindow.preset_history)):
            if i < start_index:
                continue
            preset = PresetsWindow.preset_history[i]
            break
        return preset

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

        for preset in PresetsWindow.recent_presets:
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
        if preset and preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
            self._app_actions.toast(_("Invalid preset: {0}").format(preset))
        return self._app_actions.construct_preset(self._name_entry.text()), False

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _handle_preset(self, preset: Preset | None = None):
        preset, was_valid = self._get_preset(preset)
        if was_valid and preset is not None:
            if preset in PresetsWindow.recent_presets:
                PresetsWindow.recent_presets.remove(preset)
            PresetsWindow.recent_presets.insert(0, preset)
            return preset
        if preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        PresetsWindow.recent_presets.insert(0, preset)
        self._set_preset(preset)
        return preset

    def _set_preset(self, preset: Preset | None = None) -> None:
        if preset is None:
            preset = self._handle_preset(preset=preset)
        PresetsWindow.update_history(preset)
        PresetsWindow.last_set_preset = preset
        self._app_actions.set_widgets_from_preset(preset)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _delete_preset(self, preset: Preset | None = None) -> None:
        if preset is not None and preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _clear_recent_presets(self) -> None:
        PresetsWindow.recent_presets.clear()
        self._rebuild_rows()

    def _do_action(self) -> None:
        """Enter key handler: set the first preset, or add a new one."""
        if len(PresetsWindow.recent_presets) == 0:
            self._handle_preset()
        else:
            preset = (
                PresetsWindow.last_set_preset
                if PresetsWindow.last_set_preset
                else PresetsWindow.recent_presets[0]
            )
            self._set_preset(preset)
