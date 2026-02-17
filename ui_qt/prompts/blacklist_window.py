"""
BlacklistWindow -- Tag / Model blacklist management (PySide6 port).

Ported from ``ui/tags_blacklist_window.py :: BlacklistWindow``.
Static data helpers (``set_blacklist``, ``store_blacklist``,
``mark_user_confirmed_non_default``, ``is_in_default_state``,
``update_history``, ``get_history_item``) remain on the *original*
``ui.tags_blacklist_window.BlacklistWindow`` so that the rest of
the application can call them without importing the PySide6 module.

Each tab uses a ``QTableWidget`` for the item list (much more
efficient than per-row widgets) with selection-based action buttons
underneath (Modify / Remove / Toggle / Preview).  Keyboard-driven
filtering is handled via ``keyPressEvent``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QFileDialog,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QPlainTextEdit, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from lib.tooltip_qt import create_tooltip
from sd_runner.blacklist import Blacklist, BlacklistItem
from ui.tags_blacklist_window import BlacklistWindow as _Backend
from ui_qt.auth.password_utils import require_password
from utils.globals import (
    BlacklistMode, BlacklistPromptMode, ModelBlacklistMode, ProtectedActions,
)
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ======================================================================
# Helpers
# ======================================================================

def _item_display_text(item: BlacklistItem) -> str:
    """Build a human-readable display string for a blacklist item."""
    parts = [str(item)]
    if item.use_regex:
        parts.append(_("[regex]"))
    if not item.use_word_boundary:
        parts.append(_("[no boundary]"))
    if not getattr(item, "use_space_as_optional_nonword", True):
        parts.append(_("[no space conversion]"))
    if getattr(item, "exception_pattern", None):
        parts.append(_("[exception: {0}]").format(item.exception_pattern))
    return " ".join(parts)


# ======================================================================
# BlacklistWindow
# ======================================================================

class BlacklistWindow(SmartDialog):
    """PySide6 Tag / Model blacklist manager with two tabs.

    Item lists use ``QTableWidget`` with selection-based row actions
    (Modify / Remove / Toggle / Preview) below each table.
    """

    _modify_window = None  # singleton reference

    # Cache key constants
    BLACKLIST_CACHE_KEY = "tag_blacklist"
    MODEL_BLACKLIST_CACHE_KEY = "model_blacklist"
    DEFAULT_BLACKLIST_KEY = "blacklist_user_confirmed_non_default"
    BLACKLIST_MODE_KEY = "blacklist_mode"
    BLACKLIST_PROMPT_MODE_KEY = "blacklist_prompt_mode"
    MODEL_BLACKLIST_MODE_KEY = "model_blacklist_mode"
    BLACKLIST_SILENT_KEY = "blacklist_silent_removal"
    MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY = "model_blacklist_all_prompt_modes"
    item_history = []
    MAX_ITEMS = 50

    @staticmethod
    def set_blacklist():
        """Load blacklist from cache, validate items, and load global blacklist settings."""
        from utils.app_info_cache import app_info_cache
        from sd_runner.blacklist import Blacklist
        from utils.globals import BlacklistMode, BlacklistPromptMode, ModelBlacklistMode

        user_confirmed_non_default = app_info_cache.get(BlacklistWindow.DEFAULT_BLACKLIST_KEY, default_val=False)
        mode_str = app_info_cache.get(BlacklistWindow.BLACKLIST_MODE_KEY, default_val=str(Blacklist.get_blacklist_mode()))
        prompt_mode_str = app_info_cache.get(BlacklistWindow.BLACKLIST_PROMPT_MODE_KEY, default_val=str(Blacklist.get_blacklist_prompt_mode()))
        model_mode_str = app_info_cache.get(BlacklistWindow.MODEL_BLACKLIST_MODE_KEY, default_val=str(Blacklist.get_model_blacklist_mode()))
        try:
            mode = BlacklistMode(mode_str)
            prompt_mode = BlacklistPromptMode(prompt_mode_str)
            model_mode = ModelBlacklistMode(model_mode_str)
        except Exception:
            print(f"Invalid blacklist mode: {mode_str} or prompt mode: {prompt_mode_str} or model blacklist mode: {model_mode_str}")
        Blacklist.set_blacklist_mode(mode)
        Blacklist.set_blacklist_prompt_mode(prompt_mode)
        Blacklist.set_model_blacklist_mode(model_mode)
        silent = app_info_cache.get(BlacklistWindow.BLACKLIST_SILENT_KEY, default_val=False)
        Blacklist.set_blacklist_silent_removal(silent)
        all_prompt_modes = app_info_cache.get(BlacklistWindow.MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY, default_val=False)
        Blacklist.set_model_blacklist_all_prompt_modes(all_prompt_modes)

        if not user_confirmed_non_default:
            try:
                Blacklist.decrypt_blacklist()
                print("Loaded default encrypted blacklist for first-time user")
                return
            except Exception as e:
                print(f"Error loading default blacklist: {e}")

        raw_blacklist = app_info_cache.get(BlacklistWindow.BLACKLIST_CACHE_KEY, default_val=[])
        Blacklist.set_blacklist(raw_blacklist)
        raw_model_blacklist = app_info_cache.get(BlacklistWindow.MODEL_BLACKLIST_CACHE_KEY, default_val=[])
        Blacklist.set_model_blacklist(raw_model_blacklist)

    @staticmethod
    def store_blacklist():
        """Store blacklist to cache."""
        from utils.app_info_cache import app_info_cache
        from sd_runner.blacklist import Blacklist

        Blacklist.save_cache()
        blacklist_dicts = [item.to_dict() for item in Blacklist.get_items()]
        app_info_cache.set(BlacklistWindow.BLACKLIST_CACHE_KEY, blacklist_dicts)
        model_blacklist_dicts = [item.to_dict() for item in Blacklist.get_model_items()]
        app_info_cache.set(BlacklistWindow.MODEL_BLACKLIST_CACHE_KEY, model_blacklist_dicts)
        app_info_cache.set(BlacklistWindow.BLACKLIST_MODE_KEY, str(Blacklist.get_blacklist_mode()))
        app_info_cache.set(BlacklistWindow.BLACKLIST_PROMPT_MODE_KEY, str(Blacklist.get_blacklist_prompt_mode()))
        app_info_cache.set(BlacklistWindow.MODEL_BLACKLIST_MODE_KEY, str(Blacklist.get_model_blacklist_mode()))
        app_info_cache.set(BlacklistWindow.BLACKLIST_SILENT_KEY, Blacklist.get_blacklist_silent_removal())
        app_info_cache.set(BlacklistWindow.MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY, Blacklist.get_model_blacklist_all_prompt_modes())
        # Once the blacklist has been persisted at least once, subsequent
        # loads should use the cached items instead of the encrypted default.
        if blacklist_dicts or model_blacklist_dicts:
            app_info_cache.set(BlacklistWindow.DEFAULT_BLACKLIST_KEY, True)

    @staticmethod
    def mark_user_confirmed_non_default():
        """Mark that the user has explicitly confirmed they want a non-default blacklist state."""
        from utils.app_info_cache import app_info_cache
        app_info_cache.set(BlacklistWindow.DEFAULT_BLACKLIST_KEY, True)

    @staticmethod
    def is_in_default_state():
        """Check if the blacklist is in default state."""
        from utils.app_info_cache import app_info_cache
        return not app_info_cache.get(BlacklistWindow.DEFAULT_BLACKLIST_KEY, default_val=False)

    @staticmethod
    def update_history(item):
        if len(BlacklistWindow.item_history) > 0 and item == BlacklistWindow.item_history[0]:
            return
        BlacklistWindow.item_history.insert(0, item)
        if len(BlacklistWindow.item_history) > BlacklistWindow.MAX_ITEMS:
            del BlacklistWindow.item_history[-1]

    @staticmethod
    def get_history_item(start_index=0):
        item = None
        for i in range(len(BlacklistWindow.item_history)):
            if i < start_index:
                continue
            item = BlacklistWindow.item_history[i]
            break
        return item

    warning_text = _Backend.warning_text

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(
            parent=parent,
            title=_("Tags/Models Blacklist"),
            geometry="1000x800",
        )
        self._app_actions = app_actions
        self._concepts_revealed = False
        self._filter_text = ""

        self._filtered_items: list[BlacklistItem] = Blacklist.get_items()[:]
        self._filtered_model_items: list[BlacklistItem] = Blacklist.get_model_items()[:]

        # --- Tabs -----------------------------------------------------------
        self._tabs = QTabWidget()
        self._tabs.currentChanged.connect(self._on_tab_changed)

        tag_page = QWidget()
        model_page = QWidget()
        self._tabs.addTab(tag_page, _("Tag Blacklist"))
        self._tabs.addTab(model_page, _("Model Blacklist"))

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self._tabs)

        self._build_tag_tab(tag_page)
        self._build_model_tab(model_page)

        QShortcut(QKeySequence("Escape"), self, self.close)
        self.show()

    # ==================================================================
    # Tag Blacklist tab
    # ==================================================================
    def _build_tag_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        # --- Global settings row --------------------------------------------
        settings_row = QHBoxLayout()
        lbl = QLabel(_("Global Settings:"))
        create_tooltip(lbl, _("These settings affect how the blacklist is applied globally."))
        settings_row.addWidget(lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(BlacklistMode.display_values())
        self._mode_combo.setCurrentText(Blacklist.get_blacklist_mode().display())
        self._mode_combo.currentTextChanged.connect(self._on_mode_change)
        create_tooltip(self._mode_combo, _("Choose how the blacklist is enforced: block, warn, or allow."))
        settings_row.addWidget(self._mode_combo)

        self._silent_cb = QCheckBox(_("Silent Removal"))
        self._silent_cb.setChecked(Blacklist.get_blacklist_silent_removal())
        self._silent_cb.stateChanged.connect(self._on_silent_change)
        create_tooltip(self._silent_cb, _("If enabled, blacklisted words are removed silently without notification."))
        settings_row.addWidget(self._silent_cb)
        settings_row.addStretch()
        layout.addLayout(settings_row)

        # --- Action buttons row 1 ------------------------------------------
        btn_row1 = QHBoxLayout()
        for text, handler in [
            (_("Import"), self._import_blacklist),
            (_("Export"), self._export_blacklist),
            (_("Preview All"), self._preview_all),
            (_("Load Default"), self._load_default),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            btn_row1.addWidget(b)
        btn_row1.addStretch()
        layout.addLayout(btn_row1)

        # --- Prompt mode + Add / Clear -------------------------------------
        btn_row2 = QHBoxLayout()
        self._prompt_mode_combo = QComboBox()
        self._prompt_mode_combo.addItems(BlacklistPromptMode.display_values())
        self._prompt_mode_combo.setCurrentText(Blacklist.get_blacklist_prompt_mode().display())
        self._prompt_mode_combo.currentTextChanged.connect(self._on_prompt_mode_change)
        create_tooltip(self._prompt_mode_combo, _("Choose how the blacklist is enforced: disallow or allow in NSFW."))
        btn_row2.addWidget(self._prompt_mode_combo)
        add_btn = QPushButton(_("Add to tag blacklist"))
        add_btn.clicked.connect(self._add_new_item)
        btn_row2.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear items"))
        clear_btn.clicked.connect(self._clear_items)
        btn_row2.addWidget(clear_btn)
        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        # --- Content area (reveal gate OR table) ---------------------------
        self._tag_content = QWidget()
        self._tag_content_layout = QVBoxLayout(self._tag_content)
        self._tag_content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tag_content, stretch=1)

        self._tag_table: Optional[QTableWidget] = None
        self._rebuild_tag_content()

    # ==================================================================
    # Model Blacklist tab
    # ==================================================================
    def _build_model_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        # --- Global settings row (mirrors tag tab) -------------------------
        settings_row = QHBoxLayout()
        lbl = QLabel(_("Global Settings:"))
        create_tooltip(lbl, _("These settings affect how the blacklist is applied globally."))
        settings_row.addWidget(lbl)

        self._model_mode_combo_global = QComboBox()
        self._model_mode_combo_global.addItems(BlacklistMode.display_values())
        self._model_mode_combo_global.setCurrentText(Blacklist.get_blacklist_mode().display())
        self._model_mode_combo_global.currentTextChanged.connect(self._on_mode_change)
        create_tooltip(self._model_mode_combo_global, _("Choose how the blacklist is enforced: block, warn, or allow."))
        settings_row.addWidget(self._model_mode_combo_global)

        self._silent_cb_model = QCheckBox(_("Silent Removal"))
        self._silent_cb_model.setChecked(Blacklist.get_blacklist_silent_removal())
        self._silent_cb_model.stateChanged.connect(self._on_silent_change)
        create_tooltip(self._silent_cb_model, _("If enabled, blacklisted words are removed silently without notification."))
        settings_row.addWidget(self._silent_cb_model)
        settings_row.addStretch()
        layout.addLayout(settings_row)

        # --- Action buttons -------------------------------------------------
        btn_row1 = QHBoxLayout()
        for text, handler in [
            (_("Import"), self._import_model_blacklist),
            (_("Export"), self._export_model_blacklist),
            (_("Preview All"), self._preview_all_models),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            btn_row1.addWidget(b)
        btn_row1.addStretch()
        layout.addLayout(btn_row1)

        # --- Model blacklist mode + Add / Clear -----------------------------
        btn_row2 = QHBoxLayout()
        self._model_bl_mode_combo = QComboBox()
        self._model_bl_mode_combo.addItems(ModelBlacklistMode.display_values())
        self._model_bl_mode_combo.setCurrentText(Blacklist.get_model_blacklist_mode().display())
        self._model_bl_mode_combo.currentTextChanged.connect(self._on_model_bl_mode_change)
        create_tooltip(self._model_bl_mode_combo, _("Choose how the model blacklist is enforced: disallow or allow in NSFW."))
        btn_row2.addWidget(self._model_bl_mode_combo)
        add_btn = QPushButton(_("Add to model blacklist"))
        add_btn.clicked.connect(self._add_new_model_item)
        btn_row2.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear items"))
        clear_btn.clicked.connect(self._clear_model_items)
        btn_row2.addWidget(clear_btn)
        btn_row2.addStretch()
        layout.addLayout(btn_row2)

        # --- Content area ---------------------------------------------------
        self._model_content = QWidget()
        self._model_content_layout = QVBoxLayout(self._model_content)
        self._model_content_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._model_content, stretch=1)

        self._model_table: Optional[QTableWidget] = None
        self._rebuild_model_content()

    # ==================================================================
    # Rebuild content areas
    # ==================================================================
    @staticmethod
    def _clear_layout(layout: QVBoxLayout) -> None:
        while layout.count():
            child = layout.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()
            sub = child.layout()
            if sub:
                BlacklistWindow._clear_layout(sub)

    def _rebuild_tag_content(self) -> None:
        self._clear_layout(self._tag_content_layout)
        self._tag_table = None

        if not self._concepts_revealed:
            if Blacklist.is_empty():
                msg = _("No blacklist items found. You can add items by clicking "
                        "the 'Add to tag blacklist' button above, or load the default blacklist.")
            else:
                msg = _("Click below to reveal blacklist concepts.")
            if BlacklistWindow.is_in_default_state():
                msg += "\n\n" + _(
                    "Default blacklist is loaded. You can load your own blacklist by "
                    "editing the existing concepts, clearing the blacklist and adding "
                    "your own, or importing concepts from a file."
                )
            info = QLabel(msg)
            info.setWordWrap(True)
            self._tag_content_layout.addWidget(info)
            if not Blacklist.is_empty():
                reveal_btn = QPushButton(_("Reveal Concepts"))
                reveal_btn.clicked.connect(self._reveal_concepts)
                self._tag_content_layout.addWidget(reveal_btn)
            return

        # --- Filter / count status ------------------------------------------
        total = len(Blacklist.get_items())
        showing = len(self._filtered_items)
        if self._filter_text.strip():
            status = _("Filter: \"{0}\"  ({1} of {2} items)").format(
                self._filter_text, showing, total,
            )
        else:
            status = _("{0} items").format(total)
        self._tag_status_label = QLabel(status)
        self._tag_status_label.setStyleSheet("font-style: italic; font-size: 9pt;")
        self._tag_content_layout.addWidget(self._tag_status_label)

        if showing == 0:
            no_match = QLabel(
                _("No items match the current filter.")
                if self._filter_text.strip()
                else _("The blacklist is empty.")
            )
            no_match.setWordWrap(True)
            self._tag_content_layout.addWidget(no_match)
            self._tag_content_layout.addStretch()
            return

        # --- QTableWidget ---------------------------------------------------
        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([_("Item"), _("Enabled")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_tag_table_dblclick)

        for i, item in enumerate(self._filtered_items):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(_item_display_text(item)))
            table.setItem(i, 1, QTableWidgetItem("✓" if item.enabled else _("Disabled")))

        self._tag_table = table
        self._tag_content_layout.addWidget(table, stretch=1)

        # --- Row actions ----------------------------------------------------
        actions = QHBoxLayout()
        for text, handler in [
            (_("Modify"), self._modify_selected_tag),
            (_("Remove"), self._remove_selected_tag),
            (_("Toggle"), self._toggle_selected_tag),
            (_("Preview"), self._preview_selected_tag),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            actions.addWidget(b)
        actions.addStretch()
        self._tag_content_layout.addLayout(actions)

    def _rebuild_model_content(self) -> None:
        self._clear_layout(self._model_content_layout)
        self._model_table = None

        if Blacklist.is_model_empty():
            info = QLabel(
                _("No model blacklist items found. You can add items by clicking "
                  "the 'Add to model blacklist' button above.")
            )
            info.setWordWrap(True)
            self._model_content_layout.addWidget(info)
            return

        table = QTableWidget()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels([_("Item"), _("Enabled")])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_model_table_dblclick)

        for i, item in enumerate(self._filtered_model_items):
            table.insertRow(i)
            table.setItem(i, 0, QTableWidgetItem(_item_display_text(item)))
            table.setItem(i, 1, QTableWidgetItem("✓" if item.enabled else _("Disabled")))

        self._model_table = table
        self._model_content_layout.addWidget(table, stretch=1)

        actions = QHBoxLayout()
        for text, handler in [
            (_("Modify"), self._modify_selected_model),
            (_("Remove"), self._remove_selected_model),
            (_("Toggle"), self._toggle_selected_model),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            actions.addWidget(b)
        actions.addStretch()
        self._model_content_layout.addLayout(actions)

    # ==================================================================
    # Table helpers
    # ==================================================================
    def _selected_tag_item(self) -> Optional[BlacklistItem]:
        if not self._tag_table:
            return None
        row = self._tag_table.currentRow()
        if 0 <= row < len(self._filtered_items):
            return self._filtered_items[row]
        return None

    def _selected_model_item(self) -> Optional[BlacklistItem]:
        if not self._model_table:
            return None
        row = self._model_table.currentRow()
        if 0 <= row < len(self._filtered_model_items):
            return self._filtered_model_items[row]
        return None

    def _on_tag_table_dblclick(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._filtered_items):
            self._modify_item(self._filtered_items[row])

    def _on_model_table_dblclick(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._filtered_model_items):
            self._modify_model_item(self._filtered_model_items[row])

    # --- Selection-based action wrappers ----------------------------------
    def _modify_selected_tag(self) -> None:
        item = self._selected_tag_item()
        if item:
            self._modify_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _remove_selected_tag(self) -> None:
        item = self._selected_tag_item()
        if item:
            self._remove_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _toggle_selected_tag(self) -> None:
        item = self._selected_tag_item()
        if item:
            self._toggle_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _preview_selected_tag(self) -> None:
        item = self._selected_tag_item()
        if item:
            self._preview_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _modify_selected_model(self) -> None:
        item = self._selected_model_item()
        if item:
            self._modify_model_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _remove_selected_model(self) -> None:
        item = self._selected_model_item()
        if item:
            self._remove_model_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    def _toggle_selected_model(self) -> None:
        item = self._selected_model_item()
        if item:
            self._toggle_model_item(item)
        else:
            self._app_actions.toast(_("Select an item first"))

    # ==================================================================
    # Keyboard filtering
    # ==================================================================
    def keyPressEvent(self, event) -> None:  # noqa: N802
        """Keyboard-driven filtering: type to filter, Backspace to trim,
        Up/Down to rotate the list, Enter to add new, Escape to close."""
        focus = QApplication.focusWidget()
        if focus and isinstance(focus, (QLineEdit, QPlainTextEdit)):
            super().keyPressEvent(event)
            return

        key = event.key()
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            super().keyPressEvent(event)
            return

        if key == Qt.Key.Key_Return or key == Qt.Key.Key_Enter:
            self._add_new_item()
            event.accept()
            return

        # Arrow rotation (tags tab only)
        if key in (Qt.Key.Key_Down, Qt.Key.Key_Up) and self._tabs.currentIndex() == 0:
            if self._filtered_items:
                if key == Qt.Key.Key_Down:
                    self._filtered_items = self._filtered_items[1:] + [self._filtered_items[0]]
                else:
                    self._filtered_items = [self._filtered_items[-1]] + self._filtered_items[:-1]
                self._rebuild_tag_content()
            event.accept()
            return

        if key == Qt.Key.Key_Backspace:
            if self._filter_text:
                self._filter_text = self._filter_text[:-1]
        elif event.text():
            self._filter_text += event.text()
        else:
            super().keyPressEvent(event)
            return

        self._apply_filter()
        event.accept()

    def _apply_filter(self) -> None:
        """Re-filter the tag item list based on ``_filter_text``."""
        if not self._filter_text.strip():
            self._filtered_items = Blacklist.get_items()[:]
        else:
            ft = self._filter_text.lower()
            all_items = Blacklist.get_items()
            exact = [i for i in all_items if i.string.lower() == ft]
            prefix = [i for i in all_items if i not in exact and i.string.lower().startswith(ft)]
            partial = [i for i in all_items if i not in exact and i not in prefix
                       and (f" {ft}" in i.string.lower() or f"_{ft}" in i.string.lower())]
            self._filtered_items = exact + prefix + partial
        self._rebuild_tag_content()

    # ==================================================================
    # Tab changed
    # ==================================================================
    def _on_tab_changed(self, index: int) -> None:
        # Guard: signal fires during addTab() before _build_*_tab() runs
        if not hasattr(self, "_tag_content_layout"):
            return
        if index == 0:
            self._filtered_items = Blacklist.get_items()[:]
            self._rebuild_tag_content()
        else:
            self._filtered_model_items = Blacklist.get_model_items()[:]
            self._rebuild_model_content()

    # ==================================================================
    # Refresh
    # ==================================================================
    def _refresh(self) -> None:
        self._filtered_items = Blacklist.get_items()[:]
        self._filtered_model_items = Blacklist.get_model_items()[:]
        if self._tabs.currentIndex() == 0:
            self._rebuild_tag_content()
        else:
            self._rebuild_model_content()

    # ==================================================================
    # Tag item actions
    # ==================================================================
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _add_new_item(self) -> None:
        self._open_modify_window(None, is_model=False)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _modify_item(self, item: BlacklistItem) -> None:
        self._open_modify_window(item, is_model=False)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _remove_item(self, item: BlacklistItem) -> None:
        Blacklist.remove_item(item)
        BlacklistWindow.mark_user_confirmed_non_default()
        self._app_actions.toast(_("Removed item: {0}").format(item))
        self._refresh()

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _toggle_item(self, item: BlacklistItem) -> None:
        for bl_item in Blacklist.get_items():
            if bl_item == item:
                bl_item.enabled = not bl_item.enabled
                # In-place table cell update if visible
                if self._tag_table and item in self._filtered_items:
                    idx = self._filtered_items.index(item)
                    cell = self._tag_table.item(idx, 1)
                    if cell:
                        cell.setText("✓" if bl_item.enabled else _("Disabled"))
                BlacklistWindow.store_blacklist()
                self._app_actions.toast(
                    _("Item \"{0}\" is now {1}").format(
                        bl_item.string,
                        _("enabled") if bl_item.enabled else _("disabled"),
                    )
                )
                break

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS, custom_text=_Backend.warning_text, allow_unauthenticated=False)
    def _reveal_concepts(self) -> None:
        self._concepts_revealed = True
        self._refresh()
        self._app_actions.toast(_("Concepts revealed"))

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _preview_item(self, item: BlacklistItem) -> None:
        from ui_qt.prompts.blacklist_preview_window import BlacklistPreviewWindow
        BlacklistPreviewWindow(self, self._app_actions, item)

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _preview_all(self) -> None:
        from ui_qt.prompts.blacklist_preview_window import BlacklistPreviewWindow
        BlacklistPreviewWindow(self, self._app_actions, None)

    @require_password(ProtectedActions.EDIT_BLACKLIST, ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _clear_items(self) -> None:
        if not self._app_actions.alert(
            _("Confirm Clear Blacklist"),
            _("Are you sure you want to clear all blacklist items?\n\n"
              "WARNING: This action cannot be undone!\n"
              "All blacklist items will be permanently deleted.\n\n"
              "Do you want to continue?"),
            kind="askyesno",
            master=self,
        ):
            return
        Blacklist.clear()
        BlacklistWindow.mark_user_confirmed_non_default()
        self._app_actions.toast(_("Cleared item blacklist"))
        self._refresh()

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _load_default(self) -> None:
        if not BlacklistWindow.is_in_default_state() and len(Blacklist.get_items()) > 0:
            if not self._app_actions.alert(
                _("Confirm Load Default Blacklist"),
                _("Are you sure you want to load the default blacklist?\n\n"
                  "WARNING: This will erase your current blacklist and replace it "
                  "with the default items.\n\nDo you want to continue?"),
                kind="askyesno",
                master=self,
            ):
                return
        try:
            Blacklist.decrypt_blacklist()
            from utils.app_info_cache import app_info_cache
            app_info_cache.set(BlacklistWindow.DEFAULT_BLACKLIST_KEY, False)
            self._app_actions.toast(_("Loaded default blacklist"))
            self._refresh()
        except Exception as e:
            self._app_actions.alert(
                _("Error loading default blacklist"), str(e), kind="error", master=self,
            )

    # ==================================================================
    # Model item actions
    # ==================================================================
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _add_new_model_item(self) -> None:
        self._open_modify_window(None, is_model=True)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _modify_model_item(self, item: BlacklistItem) -> None:
        self._open_modify_window(item, is_model=True)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _remove_model_item(self, item: BlacklistItem) -> None:
        Blacklist.remove_model_item(item)
        self._app_actions.toast(_("Removed model blacklist item: {0}").format(item.string))
        self._refresh()

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _toggle_model_item(self, item: BlacklistItem) -> None:
        for bl_item in Blacklist.get_model_items():
            if bl_item == item:
                bl_item.enabled = not bl_item.enabled
                if self._model_table and item in self._filtered_model_items:
                    idx = self._filtered_model_items.index(item)
                    cell = self._model_table.item(idx, 1)
                    if cell:
                        cell.setText("✓" if bl_item.enabled else _("Disabled"))
                self._app_actions.toast(
                    _("Model item '{0}' is now {1}").format(
                        bl_item.string,
                        _("enabled") if bl_item.enabled else _("disabled"),
                    )
                )
                break

    @require_password(ProtectedActions.EDIT_BLACKLIST, ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _clear_model_items(self) -> None:
        Blacklist.clear_model_blacklist()
        self._app_actions.toast(_("Cleared model blacklist items"))
        self._refresh()

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _preview_all_models(self) -> None:
        self._app_actions.alert(
            _("Not Implemented"),
            _("Preview all models not implemented yet."),
            kind="warning", master=self,
        )

    # ==================================================================
    # Modify window helpers
    # ==================================================================
    def _open_modify_window(
        self, item: Optional[BlacklistItem], *, is_model: bool
    ) -> None:
        if BlacklistWindow._modify_window is not None:
            try:
                BlacklistWindow._modify_window.close()
            except RuntimeError:
                pass
        from ui_qt.prompts.blacklist_modify_window import BlacklistModifyWindow
        callback = self._refresh_model_bl_item if is_model else self._refresh_tag_bl_item
        BlacklistWindow._modify_window = BlacklistModifyWindow(
            self, callback, item, self._app_actions,
        )
        if is_model and item is None:
            BlacklistWindow._modify_window._item.blacklist_type = "model"

    def _refresh_tag_bl_item(
        self, item: BlacklistItem, is_new: bool, original_string: str
    ) -> None:
        BlacklistWindow.update_history(item)
        BlacklistWindow.mark_user_confirmed_non_default()
        if is_new:
            Blacklist.add_item(item)
        else:
            for existing in Blacklist.get_items():
                if existing.string == original_string:
                    Blacklist.remove_item(existing, do_save=False)
                    break
            Blacklist.add_item(item)
        msg = _("Added item to blacklist: {0}") if is_new else _("Modified blacklist item: {0}")
        self._app_actions.toast(msg.format(item.string))
        self._refresh()

    def _refresh_model_bl_item(
        self, item: BlacklistItem, is_new: bool, original_string: str
    ) -> None:
        BlacklistWindow.update_history(item)
        BlacklistWindow.mark_user_confirmed_non_default()
        if is_new:
            Blacklist.add_model_item(item)
        else:
            for existing in Blacklist.get_model_items():
                if existing.string == original_string:
                    Blacklist.remove_model_item(existing)
                    break
            Blacklist.add_model_item(item)
        self._app_actions.toast(_("Model blacklist updated: {0}").format(item.string))
        self._refresh()

    # ==================================================================
    # Global settings callbacks
    # ==================================================================
    def _on_mode_change(self, text: str) -> None:
        try:
            mode = BlacklistMode.from_display(text)
        except Exception:
            mode = BlacklistMode.REMOVE_WORD_OR_PHRASE
        Blacklist.set_blacklist_mode(mode)
        BlacklistWindow.store_blacklist()
        for combo in (self._mode_combo, self._model_mode_combo_global):
            if combo.currentText() != text:
                combo.blockSignals(True)
                combo.setCurrentText(text)
                combo.blockSignals(False)
        self._app_actions.toast(_("Blacklist mode set to: {0}").format(mode.display()))

    def _on_prompt_mode_change(self, text: str) -> None:
        try:
            mode = BlacklistPromptMode.from_display(text)
        except Exception:
            mode = BlacklistPromptMode.REMOVE_WORD_OR_PHRASE
        Blacklist.set_blacklist_prompt_mode(mode)
        BlacklistWindow.store_blacklist()
        self._app_actions.toast(_("Blacklist prompt mode set to: {0}").format(text))

    def _on_model_bl_mode_change(self, text: str) -> None:
        try:
            mode = ModelBlacklistMode.from_display(text)
        except Exception:
            mode = ModelBlacklistMode.DISALLOW
        Blacklist.set_model_blacklist_mode(mode)
        BlacklistWindow.store_blacklist()
        self._app_actions.toast(_("Model blacklist mode set to: {0}").format(mode.display()))

    def _on_silent_change(self) -> None:
        val = self._silent_cb.isChecked()
        Blacklist.set_blacklist_silent_removal(val)
        for cb in (self._silent_cb, self._silent_cb_model):
            if cb.isChecked() != val:
                cb.blockSignals(True)
                cb.setChecked(val)
                cb.blockSignals(False)
        BlacklistWindow.store_blacklist()
        self._app_actions.toast(_("Silent removal set to: {0}").format(val))

    # ==================================================================
    # Import / Export
    # ==================================================================
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _import_blacklist(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Import Blacklist"), "",
            _("All supported (*.csv *.json *.txt);;CSV (*.csv);;JSON (*.json);;Text (*.txt)"),
        )
        if not path:
            return
        try:
            if path.endswith(".csv"):
                Blacklist.import_blacklist_csv(path)
            elif path.endswith(".json"):
                Blacklist.import_blacklist_json(path)
            else:
                Blacklist.import_blacklist_txt(path)
            BlacklistWindow.mark_user_confirmed_non_default()
            self._app_actions.toast(_("Successfully imported blacklist"))
            self._refresh()
        except Exception as e:
            self._app_actions.alert(_("Import Error"), str(e), kind="error", master=self)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _export_blacklist(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, _("Export Blacklist"), "",
            _("CSV (*.csv);;JSON (*.json);;Text (*.txt)"),
        )
        if not path:
            return
        try:
            if path.endswith(".csv"):
                Blacklist.export_blacklist_csv(path)
            elif path.endswith(".json"):
                Blacklist.export_blacklist_json(path)
            else:
                Blacklist.export_blacklist_txt(path)
            self._app_actions.toast(_("Successfully exported blacklist"))
        except Exception as e:
            self._app_actions.alert(_("Export Error"), str(e), kind="error", master=self)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _import_model_blacklist(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self, _("Import Model Blacklist"), "",
            _("All supported (*.csv *.json *.txt);;CSV (*.csv);;JSON (*.json);;Text (*.txt)"),
        )
        if not path:
            return
        try:
            if path.endswith(".csv"):
                Blacklist.import_model_blacklist_csv(path)
            elif path.endswith(".json"):
                Blacklist.import_model_blacklist_json(path)
            else:
                Blacklist.import_model_blacklist_txt(path)
            BlacklistWindow.mark_user_confirmed_non_default()
            self._app_actions.toast(_("Successfully imported model blacklist"))
            self._refresh()
        except Exception as e:
            self._app_actions.alert(_("Import Error"), str(e), kind="error", master=self)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def _export_model_blacklist(self) -> None:
        path, _filter = QFileDialog.getSaveFileName(
            self, _("Export Model Blacklist"), "",
            _("JSON (*.json)"),
        )
        if not path:
            return
        try:
            Blacklist.export_model_blacklist_json(path)
            self._app_actions.toast(_("Successfully exported model blacklist"))
        except Exception as e:
            self._app_actions.alert(_("Export Error"), str(e), kind="error", master=self)
