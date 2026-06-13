"""
ModelPresetsWindow / PresetModifyWindow -- manage model presets.

Presets live in config.json under "model_presets" and are applied to
Model instances by Model.set_model_presets() on each generation.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui_qt.app_style import AppStyle
from utils.config import config
from utils.globals import ArchitectureType, PromptMode
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_actions import AppActions

_ = I18N._

_WILDCARD_KEY = "*"
_WILDCARD_LABEL = "* (All modes)"


def _prompt_modes_summary(preset: dict) -> str:
    """Short label listing which prompt modes have tag overrides."""
    pt = preset.get("prompt_tags", {})
    if not pt:
        return "—"
    labels = [_WILDCARD_LABEL if k == _WILDCARD_KEY else k for k in pt]
    return ", ".join(labels)


def _save_presets_to_disk() -> None:
    """Write config.model_presets back into config.json, preserving all other keys."""
    with open(config.config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data["model_presets"] = config.model_presets
    with open(config.config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


# ======================================================================
# PresetModifyWindow
# ======================================================================

class PresetModifyWindow(SmartDialog):
    """Create or edit a single model preset entry."""

    def __init__(
        self,
        parent: QWidget,
        refresh_callback: Callable,
        preset: Optional[dict],
        app_actions: AppActions,
        geometry: str = "700x580",
    ):
        self._original = preset          # original dict reference; None when adding new
        self._refresh_callback = refresh_callback
        self._app_actions = app_actions

        title = (
            _("New Model Preset")
            if preset is None
            else _("Modify Preset: {0}").format(preset.get("model_tags", ""))
        )
        super().__init__(parent=parent, title=title, geometry=geometry)
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._build_ui(preset or {})
        self.show()

    # ------------------------------------------------------------------
    def _build_ui(self, preset: dict) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # Model tags
        root.addWidget(QLabel(_("Model Tags (comma-separated substrings, matched against model names)")))
        self._tags_edit = QLineEdit(preset.get("model_tags", ""))
        self._tags_edit.setPlaceholderText(_("e.g. ponyDiffusion,everclear"))
        root.addWidget(self._tags_edit)

        # Architecture + CLIP row
        arch_clip_row = QHBoxLayout()

        arch_col = QVBoxLayout()
        arch_col.addWidget(QLabel(_("Architecture Override")))
        self._arch_combo = QComboBox()
        self._arch_combo.addItem(_("— auto-detect —"), "")
        for arch in ArchitectureType:
            self._arch_combo.addItem(arch.display(), arch.value)
        saved_arch = preset.get("architecture_type", "")
        idx = self._arch_combo.findData(saved_arch)
        self._arch_combo.setCurrentIndex(idx if idx >= 0 else 0)
        arch_col.addWidget(self._arch_combo)
        arch_clip_row.addLayout(arch_col)

        clip_col = QVBoxLayout()
        clip_col.addWidget(QLabel(_("CLIP Req (optional)")))
        clip_val = preset.get("clip_req", "")
        self._clip_edit = QLineEdit("" if clip_val == "" else str(clip_val))
        self._clip_edit.setPlaceholderText(_("e.g. -2"))
        self._clip_edit.setFixedWidth(100)
        clip_col.addWidget(self._clip_edit)
        clip_col.addStretch()
        arch_clip_row.addLayout(clip_col)
        arch_clip_row.addStretch()
        root.addLayout(arch_clip_row)

        # Prompt tags tabs
        root.addWidget(QLabel(_("Prompt Tags (per mode)")))
        self._tabs = QTabWidget()
        root.addWidget(self._tabs, stretch=1)

        for key, tag_dict in preset.get("prompt_tags", {}).items():
            self._add_mode_tab(key, tag_dict.get("positive", ""), tag_dict.get("negative", ""))

        # Add / remove tab controls
        tab_ctrl_row = QHBoxLayout()
        self._mode_combo = QComboBox()
        self._mode_combo.addItem(_WILDCARD_LABEL, _WILDCARD_KEY)
        for mode in PromptMode:
            self._mode_combo.addItem(mode.value, mode.value)
        tab_ctrl_row.addWidget(self._mode_combo)
        add_tab_btn = QPushButton(_("Add mode tab"))
        add_tab_btn.clicked.connect(self._add_selected_mode_tab)
        tab_ctrl_row.addWidget(add_tab_btn)
        remove_tab_btn = QPushButton(_("Remove current tab"))
        remove_tab_btn.clicked.connect(self._remove_current_tab)
        tab_ctrl_row.addWidget(remove_tab_btn)
        tab_ctrl_row.addStretch()
        root.addLayout(tab_ctrl_row)

        # Done
        btn_row = QHBoxLayout()
        done_btn = QPushButton(_("Done"))
        done_btn.clicked.connect(self._finalize)
        btn_row.addWidget(done_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)

    # ------------------------------------------------------------------
    def _add_mode_tab(self, key: str, positive: str = "", negative: str = "") -> None:
        label = _WILDCARD_LABEL if key == _WILDCARD_KEY else key
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        layout.addWidget(QLabel(_("Positive tags")))
        pos_edit = QPlainTextEdit(positive)
        pos_edit.setFixedHeight(80)
        layout.addWidget(pos_edit)

        layout.addWidget(QLabel(_("Negative tags")))
        neg_edit = QPlainTextEdit(negative)
        neg_edit.setFixedHeight(80)
        layout.addWidget(neg_edit)
        layout.addStretch()

        # Store mode metadata on the page widget itself
        page._mode_key = key
        page._pos_edit = pos_edit
        page._neg_edit = neg_edit

        self._tabs.addTab(page, label)

    def _add_selected_mode_tab(self) -> None:
        key = self._mode_combo.currentData()
        for i in range(self._tabs.count()):
            if self._tabs.widget(i)._mode_key == key:
                self._tabs.setCurrentIndex(i)
                return
        self._add_mode_tab(key)
        self._tabs.setCurrentIndex(self._tabs.count() - 1)

    def _remove_current_tab(self) -> None:
        idx = self._tabs.currentIndex()
        if idx >= 0:
            self._tabs.removeTab(idx)

    # ------------------------------------------------------------------
    def _finalize(self) -> None:
        model_tags = self._tags_edit.text().strip()
        if not model_tags:
            self._app_actions.alert(
                _("Invalid Preset"),
                _("Model Tags must be non-empty."),
                kind="showwarning",
                master=self,
            )
            return

        clip_text = self._clip_edit.text().strip()
        clip_val = None
        if clip_text:
            try:
                clip_val = float(clip_text)
            except ValueError:
                self._app_actions.alert(
                    _("Invalid Preset"),
                    _("CLIP Req must be a number (e.g. -2) or left blank."),
                    kind="showwarning",
                    master=self,
                )
                return

        arch_data = self._arch_combo.currentData()

        prompt_tags = {}
        for i in range(self._tabs.count()):
            page = self._tabs.widget(i)
            key = page._mode_key
            pos = page._pos_edit.toPlainText()
            neg = page._neg_edit.toPlainText()
            if pos or neg:
                entry = {}
                if pos:
                    entry["positive"] = pos
                if neg:
                    entry["negative"] = neg
                prompt_tags[key] = entry

        result: dict = {"model_tags": model_tags}
        if arch_data:
            result["architecture_type"] = arch_data
        if clip_val is not None:
            result["clip_req"] = clip_val
        if prompt_tags:
            result["prompt_tags"] = prompt_tags

        self.close()
        self._refresh_callback(self._original, result)


# ======================================================================
# ModelPresetsWindow
# ======================================================================

class ModelPresetsWindow(SmartDialog):
    """Browse and edit the model_presets list from config.json."""

    _modify_window: Optional[PresetModifyWindow] = None

    def __init__(self, parent: QWidget, app_actions: AppActions, geometry: str = "780x440"):
        super().__init__(parent=parent, title=_("Model Presets"), geometry=geometry)
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._app_actions = app_actions
        self._filtered: list[dict] = list(config.model_presets)
        self._table: Optional[QTableWidget] = None

        self._build_ui()
        self._rebuild_table()
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.close)
        self.show()

    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        header = QHBoxLayout()
        header.addWidget(QLabel(_("Model presets (saved to config.json)")))
        header.addStretch()
        add_btn = QPushButton(_("Add preset"))
        add_btn.clicked.connect(self._add_preset)
        header.addWidget(add_btn)
        root.addLayout(header)

        self._search_edit = QLineEdit()
        self._search_edit.setPlaceholderText(_("Filter by model tags…"))
        self._search_edit.textChanged.connect(self._apply_filter)
        root.addWidget(self._search_edit)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("font-style: italic; font-size: 9pt;")
        root.addWidget(self._status_label)

        self._table_container = QVBoxLayout()
        root.addLayout(self._table_container, stretch=1)

        actions = QHBoxLayout()
        for text, handler in [
            (_("Modify"), self._modify_selected),
            (_("Delete"), self._delete_selected),
        ]:
            b = QPushButton(text)
            b.clicked.connect(handler)
            actions.addWidget(b)
        actions.addStretch()
        root.addLayout(actions)

    # ------------------------------------------------------------------
    def _rebuild_table(self) -> None:
        if self._table is not None:
            self._table_container.removeWidget(self._table)
            self._table.deleteLater()
            self._table = None

        while self._table_container.count():
            child = self._table_container.takeAt(0)
            w = child.widget()
            if w:
                w.deleteLater()

        total = len(config.model_presets)
        showing = len(self._filtered)
        search = self._search_edit.text()

        if search.strip():
            self._status_label.setText(
                _("Filter: \"{0}\"  ({1} of {2} presets)").format(search, showing, total)
            )
        else:
            self._status_label.setText(_("{0} presets").format(total))

        if showing == 0:
            msg = (
                _("No presets match the current filter.")
                if search.strip()
                else _("No presets defined. Click 'Add preset' to create one.")
            )
            lbl = QLabel(msg)
            lbl.setWordWrap(True)
            self._table_container.addWidget(lbl)
            return

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels([
            _("Model Tags"), _("Architecture"), _("CLIP Req"), _("Prompt Modes"),
        ])
        hdr = table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Interactive)
        hdr.resizeSection(1, 130)
        hdr.resizeSection(2, 80)
        hdr.resizeSection(3, 140)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.cellDoubleClicked.connect(self._on_dblclick)

        for i, preset in enumerate(self._filtered):
            table.insertRow(i)
            clip = preset.get("clip_req", "")
            table.setItem(i, 0, QTableWidgetItem(preset.get("model_tags", "")))
            table.setItem(i, 1, QTableWidgetItem(preset.get("architecture_type", "")))
            table.setItem(i, 2, QTableWidgetItem("" if clip == "" else str(clip)))
            table.setItem(i, 3, QTableWidgetItem(_prompt_modes_summary(preset)))

        self._table = table
        self._table_container.addWidget(table)

    # ------------------------------------------------------------------
    def _apply_filter(self) -> None:
        ft = self._search_edit.text().lower()
        if not ft.strip():
            self._filtered = list(config.model_presets)
        else:
            self._filtered = [
                p for p in config.model_presets
                if ft in p.get("model_tags", "").lower()
            ]
        self._rebuild_table()

    def _selected_preset(self) -> Optional[dict]:
        if self._table is None:
            return None
        row = self._table.currentRow()
        if 0 <= row < len(self._filtered):
            return self._filtered[row]
        return None

    def _on_dblclick(self, row: int, _col: int) -> None:
        if 0 <= row < len(self._filtered):
            self._open_modify_window(self._filtered[row])

    # ------------------------------------------------------------------
    def _add_preset(self) -> None:
        self._open_modify_window(None)

    def _modify_selected(self) -> None:
        preset = self._selected_preset()
        if preset:
            self._open_modify_window(preset)
        else:
            self._app_actions.toast(_("Select a preset first"))

    def _open_modify_window(self, preset: Optional[dict]) -> None:
        if ModelPresetsWindow._modify_window is not None:
            try:
                ModelPresetsWindow._modify_window.close()
            except RuntimeError:
                pass
        ModelPresetsWindow._modify_window = PresetModifyWindow(
            self, self._refresh_after_modify, preset, self._app_actions,
        )

    def _refresh_after_modify(self, original: Optional[dict], new_preset: dict) -> None:
        if original is not None:
            # Replace in-place using identity comparison to handle duplicate tag strings
            for i, p in enumerate(config.model_presets):
                if p is original:
                    config.model_presets[i] = new_preset
                    break
        else:
            config.model_presets.insert(0, new_preset)
        self._save()
        self._apply_filter()

    def _delete_selected(self) -> None:
        preset = self._selected_preset()
        if preset is None:
            self._app_actions.toast(_("Select a preset first"))
            return
        if not self._app_actions.alert(
            _("Delete preset?"),
            _("Delete preset for \"{0}\"?").format(preset.get("model_tags", "")),
            kind="askyesno",
            master=self,
        ):
            return
        for i, p in enumerate(config.model_presets):
            if p is preset:
                config.model_presets.pop(i)
                break
        self._save()
        self._apply_filter()

    def _save(self) -> None:
        try:
            _save_presets_to_disk()
            self._app_actions.toast(_("Presets saved to config.json"))
        except Exception as e:
            self._app_actions.alert(
                _("Save Error"), str(e), kind="error", master=self,
            )
