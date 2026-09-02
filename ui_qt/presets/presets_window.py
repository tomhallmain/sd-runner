"""
PresetsWindow -- manage prompt presets and stashed run configs.

Two tabs over two complementary stores. A ``Preset`` holds the four prompt
fields; a ``StashedConfig`` holds everything else about a run. Both are named
and recalled the same way, so they share a window and differ only in which half
of the config they own.

The data classes live in ``ui_qt.presets.preset`` and
``ui_qt.presets.stashed_config``; static class-level list state lives on this
class for persistence via ``CacheController``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QTabWidget,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from ui_qt.presets.preset import Preset
from ui_qt.presets.stashed_config import StashedConfig
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_actions import AppActions

_ = I18N._


class PresetsWindow(SmartDialog):
    """PySide6 preset management window.

    The window shows all saved presets in a scrollable list.  Each row has
    a label (the preset description), a **Set** button, and a **Delete**
    button.  A top row allows adding a new preset from the current
    sidebar configuration.
    """

    _instance = None
    recent_presets = []
    last_set_preset = None
    preset_history = []
    MAX_PRESETS = 50

    STASHED_CONFIGS_KEY = "stashed_configs"
    stashed_configs = []
    MAX_STASHED_CONFIGS = 50

    @staticmethod
    def set_recent_presets():
        from utils.app_info_cache import app_info_cache
        from ui_qt.presets.preset import Preset
        for preset_dict in list(app_info_cache.get("recent_presets", default_val=[])):
            PresetsWindow.recent_presets.append(Preset.from_dict(preset_dict))

    @staticmethod
    def store_recent_presets(persist: bool = True):
        """Store recent presets to cache.

        Writes through to disk unless *persist* is False. The write is skipped
        when nothing actually changed, so calling this from an edit handler is
        cheap even when the edit was a no-op. store_info_cache passes False
        because it writes once itself after collecting every subsystem.
        """
        from utils.app_info_cache import app_info_cache
        preset_dicts = []
        for preset in PresetsWindow.recent_presets:
            preset_dicts.append(preset.to_dict())
        app_info_cache.set("recent_presets", preset_dicts)

        if persist:
            app_info_cache.store(only_if_changed=True)

    @staticmethod
    def set_stashed_configs():
        """Load stashed configs from cache, replacing whatever is held."""
        from utils.app_info_cache import app_info_cache
        PresetsWindow.stashed_configs.clear()
        for stash_dict in list(app_info_cache.get(PresetsWindow.STASHED_CONFIGS_KEY, default_val=[])):
            stash = StashedConfig.from_dict(stash_dict)
            if stash.is_valid():
                PresetsWindow.stashed_configs.append(stash)

    @staticmethod
    def store_stashed_configs(persist: bool = True):
        """Store stashed configs to cache.

        Writes through to disk unless *persist* is False, on the same terms as
        ``store_recent_presets``.
        """
        from utils.app_info_cache import app_info_cache
        app_info_cache.set(
            PresetsWindow.STASHED_CONFIGS_KEY,
            [stash.to_dict() for stash in PresetsWindow.stashed_configs],
        )
        if persist:
            app_info_cache.store(only_if_changed=True)

    @staticmethod
    def get_stashed_config_by_name(name) -> 'StashedConfig | None':
        for stash in PresetsWindow.stashed_configs:
            if stash.name == name:
                return stash
        return None

    @staticmethod
    def get_stashed_config_names():
        return sorted(stash.name for stash in PresetsWindow.stashed_configs)

    @staticmethod
    def get_preset_by_name(name):
        for preset in PresetsWindow.recent_presets:
            if name == preset.name:
                return preset
        raise Exception(f"No preset found with name: {name}. Set it on the Presets Window.")

    @staticmethod
    def get_preset_by_suffix(suffix: str) -> 'Preset | None':
        """Return the first preset whose edit_suffix matches *suffix*, or None.

        A preset matches if its edit_suffix equals the incoming suffix or is a
        prefix of it (e.g. preset "_cher" matches incoming "_cherry").
        """
        for preset in PresetsWindow.recent_presets:
            if preset.edit_suffix and suffix.startswith(preset.edit_suffix):
                return preset
        return None

    @staticmethod
    def get_preset_names():
        return sorted(list(map(lambda x: x.name, PresetsWindow.recent_presets)))

    @staticmethod
    def get_most_recent_preset_name():
        return (
            PresetsWindow.recent_presets[0].name
            if len(PresetsWindow.recent_presets) > 0
            else _("New Preset (ERROR no presets found)")
        )

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
            title=_("Presets and Stashed Configs"),
            geometry="700x400",
        )
        PresetsWindow._instance = self
        self._app_actions = app_actions

        self._tabs = QTabWidget()
        presets_page = QWidget()
        stash_page = QWidget()
        self._tabs.addTab(presets_page, _("Presets"))
        self._tabs.addTab(stash_page, _("Stashed Configs"))

        root = QVBoxLayout(self)
        root.addWidget(self._tabs)

        self._build_presets_tab(presets_page)
        self._build_stash_tab(stash_page)

        # --- Shortcuts ------------------------------------------------------
        QShortcut(QKeySequence("Escape"), self, self.close)
        QShortcut(QKeySequence("Return"), self, self._do_action)

        self._rebuild_rows()
        self._rebuild_stash_rows()
        self.show()

    # ------------------------------------------------------------------
    # Tab construction
    # ------------------------------------------------------------------
    def _build_presets_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

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

        layout.addLayout(top_bar)
        layout.addWidget(self._scroll)

    def _build_stash_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel(_("Stash the current run config")))
        self._stash_name_entry = QLineEdit(_("New Stash"))
        self._stash_name_entry.setMinimumWidth(250)
        top_bar.addWidget(self._stash_name_entry)
        add_btn = QPushButton(_("Stash config"))
        add_btn.clicked.connect(self._add_stash)
        top_bar.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear stashes"))
        clear_btn.clicked.connect(self._clear_stashed_configs)
        top_bar.addWidget(clear_btn)
        top_bar.addStretch()

        hint = QLabel(_("Prompt mode, prompt tags and edit suffix are left "
                        "untouched when a stash is applied -- those belong to "
                        "presets."))
        hint.setWordWrap(True)

        self._stash_scroll = QScrollArea()
        self._stash_scroll.setWidgetResizable(True)
        self._stash_scroll_content = QWidget()
        self._stash_rows_layout = QVBoxLayout(self._stash_scroll_content)
        self._stash_rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._stash_scroll.setWidget(self._stash_scroll_content)

        layout.addLayout(top_bar)
        layout.addWidget(hint)
        layout.addWidget(self._stash_scroll)

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

    def _rebuild_stash_rows(self) -> None:
        """Clear and re-populate the stashed-config list from the backend."""
        while self._stash_rows_layout.count():
            item = self._stash_rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for stash in PresetsWindow.stashed_configs:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)
            label = QLabel(str(stash))
            label.setWordWrap(True)
            label.setMinimumWidth(400)
            h.addWidget(label, stretch=1)

            set_btn = QPushButton(_("Set"))
            set_btn.setFixedWidth(60)
            set_btn.clicked.connect(lambda _=False, s=stash: self._set_stashed_config(s))
            h.addWidget(set_btn)

            del_btn = QPushButton(_("Delete"))
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(lambda _=False, s=stash: self._delete_stashed_config(s))
            h.addWidget(del_btn)

            self._stash_rows_layout.addWidget(row)

    # ------------------------------------------------------------------
    # Stashed config actions
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_PRESETS)
    def _add_stash(self) -> None:
        name = self._stash_name_entry.text().strip()
        if not name:
            self._app_actions.toast(_("Enter a name for the stash"))
            return
        existing = PresetsWindow.get_stashed_config_by_name(name)
        if existing is not None:
            if not self._app_actions.alert(
                _("Confirm Overwrite Stash"),
                _("A stashed config named \"{0}\" already exists.\n\n"
                  "Replace it with the current run config?").format(name),
                kind="askyesno",
                master=self,
            ):
                return
            PresetsWindow.stashed_configs.remove(existing)
        stash = self._app_actions.construct_stashed_config(name)
        PresetsWindow.stashed_configs.insert(0, stash)
        while len(PresetsWindow.stashed_configs) > PresetsWindow.MAX_STASHED_CONFIGS:
            del PresetsWindow.stashed_configs[-1]
        PresetsWindow.store_stashed_configs()
        self._app_actions.toast(_("Stashed run config: {0}").format(name))
        self._rebuild_stash_rows()

    def _set_stashed_config(self, stash: StashedConfig) -> None:
        self._app_actions.set_widgets_from_stash(stash)
        self._app_actions.toast(_("Applied stashed config: {0}").format(stash.name))

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _delete_stashed_config(self, stash: StashedConfig | None = None) -> None:
        if stash is not None and stash in PresetsWindow.stashed_configs:
            PresetsWindow.stashed_configs.remove(stash)
            PresetsWindow.store_stashed_configs()
        self._rebuild_stash_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _clear_stashed_configs(self) -> None:
        if PresetsWindow.stashed_configs and not self._app_actions.alert(
            _("Confirm Clear Stashes"),
            _("Delete all stashed run configs?\n\n"
              "WARNING: This action cannot be undone!\n\n"
              "Do you want to continue?"),
            kind="askyesno",
            master=self,
        ):
            return
        PresetsWindow.stashed_configs.clear()
        PresetsWindow.store_stashed_configs()
        self._rebuild_stash_rows()

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
            PresetsWindow.store_recent_presets()
            return preset
        if preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        PresetsWindow.recent_presets.insert(0, preset)
        PresetsWindow.store_recent_presets()
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
            PresetsWindow.store_recent_presets()
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_PRESETS)
    def _clear_recent_presets(self) -> None:
        PresetsWindow.recent_presets.clear()
        PresetsWindow.store_recent_presets()
        self._rebuild_rows()

    def _do_action(self) -> None:
        """Enter key handler, acting on whichever tab is showing."""
        if self._tabs.currentIndex() == 1:
            self._add_stash()
            return
        if len(PresetsWindow.recent_presets) == 0:
            self._handle_preset()
        else:
            preset = (
                PresetsWindow.last_set_preset
                if PresetsWindow.last_set_preset
                else PresetsWindow.recent_presets[0]
            )
            self._set_preset(preset)

    def closeEvent(self, event) -> None:  # noqa: N802
        PresetsWindow._instance = None
        super().closeEvent(event)
