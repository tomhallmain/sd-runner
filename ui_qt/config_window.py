"""ConfigWindow -- editable application settings dialog (PySide6)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui_qt.app_style import AppStyle
from utils.config import config
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_actions import AppActions

_ = I18N._


class ConfigWindow(SmartDialog):
    """Editable config settings dialog — config-only, no help tab."""

    _instance: Optional["ConfigWindow"] = None

    def __init__(self, parent=None, app_actions: Optional["AppActions"] = None) -> None:
        super().__init__(
            parent=parent,
            position_parent=parent,
            title=_("Config"),
            geometry="700x620",
        )
        ConfigWindow._instance = self

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet(
            f"QScrollArea {{ background: {AppStyle.BG_COLOR}; border: none; }}"
        )

        viewport = QWidget()
        viewport.setStyleSheet(f"background: {AppStyle.BG_COLOR};")
        self._grid = QGridLayout(viewport)
        self._grid.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._grid.setColumnStretch(0, 2)
        self._grid.setColumnStretch(1, 3)
        self._grid.setContentsMargins(8, 8, 8, 8)
        self._grid.setVerticalSpacing(4)
        self._row = 0

        scroll.setWidget(viewport)
        outer.addWidget(scroll, stretch=1)

        # ── Backend URLs ──────────────────────────────────────────────
        self._add_section(_("Backend URLs"))
        self._le_comfyui_url = self._add_entry(
            _("ComfyUI URL"), str(config.comfyui_url or ""),
        )
        self._le_sd_webui_url = self._add_entry(
            _("SD WebUI URL"), str(config.sd_webui_url or ""),
        )
        self._le_forge_url = self._add_entry(
            _("Forge URL"), str(config.forge_url or ""),
        )
        self._le_sdnext_url = self._add_entry(
            _("SDNext URL"), str(config.sdnext_url or ""),
        )
        self._le_swarmui_url = self._add_entry(
            _("SwarmUI URL"), str(config.swarmui_url or ""),
        )
        self._le_invokeai_url = self._add_entry(
            _("InvokeAI URL"), str(config.invokeai_url or ""),
        )
        self._le_fooocus_url = self._add_entry(
            _("Fooocus URL"), str(config.fooocus_url or ""),
        )

        # ── Save Paths ────────────────────────────────────────────────
        self._add_section(_("Save Paths"))
        self._le_sd_webui_save_path = self._add_entry(
            _("SD WebUI Save Path"), config.sd_webui_save_path,
        )
        self._le_forge_save_path = self._add_entry(
            _("Forge Save Path"), config.forge_save_path,
        )
        self._le_sdnext_save_path = self._add_entry(
            _("SDNext Save Path"), config.sdnext_save_path,
        )
        self._le_swarmui_save_path = self._add_entry(
            _("SwarmUI Save Path"), config.swarmui_save_path,
        )
        self._le_invokeai_save_path = self._add_entry(
            _("InvokeAI Save Path"), config.invokeai_save_path,
        )
        self._le_fooocus_save_path = self._add_entry(
            _("Fooocus Save Path"), config.fooocus_save_path,
        )

        # ── Directories ───────────────────────────────────────────────
        self._add_section(_("Directories"))
        self._le_models_dir = self._add_entry(
            _("Models Directory"), str(config.models_dir or ""),
        )
        self._le_img_dir = self._add_entry(
            _("Image Output Directory"), str(config.img_dir or ""),
        )
        self._le_img_temps_dir = self._add_entry(
            _("Image Temps Directory"), str(config.img_temps_dir or ""),
        )
        self._le_ipadapter_dir = self._add_entry(
            _("IPAdapter Directory"), str(config.ipadapter_dir or ""),
        )
        self._le_comfyui_loc = self._add_entry(
            _("ComfyUI Location"), str(config.comfyui_loc or ""),
        )
        self._le_sd_webui_loc = self._add_entry(
            _("SD WebUI Location"), str(config.sd_webui_loc or ""),
        )
        self._le_sd_prompt_reader_loc = self._add_entry(
            _("SD Prompt Reader Location"), str(config.sd_prompt_reader_loc or ""),
        )
        self._le_image_searcher_dir2 = self._add_entry(
            _("Image Searcher Directory 2"), str(config.image_searcher_dir2 or ""),
        )

        # ── UI ────────────────────────────────────────────────────────
        self._add_section(_("UI"))
        self._le_foreground_color = self._add_entry(
            _("Foreground Color"), str(config.foreground_color or ""),
        )
        self._le_background_color = self._add_entry(
            _("Background Color"), str(config.background_color or ""),
        )
        self._le_ui_scale_factor = self._add_entry(
            _("UI Scale Factor"), str(config.ui_scale_factor),
        )
        self._le_locale = self._add_entry(
            _("Locale"), str(config.locale or ""),
        )

        # ── Behavior ──────────────────────────────────────────────────
        self._add_section(_("Behavior"))
        self._cb_blacklist_prevent = self._add_checkbox(
            _("Blacklist Prevents Execution"), config.blacklist_prevent_execution,
        )
        self._cb_purge_blacklisted = self._add_checkbox(
            _("Purge Blacklisted Prompts from History"), config.purge_blacklisted_prompt_history,
        )
        self._cb_save_last_prompt = self._add_checkbox(
            _("Save Last Prompt"), config.save_last_prompt,
        )
        self._cb_delay_after_single = self._add_checkbox(
            _("Delay After Single Run"), config.delay_after_single_run,
        )
        self._cb_debug = self._add_checkbox(
            _("Debug Mode"), config.debug,
        )
        self._cb_print_settings = self._add_checkbox(
            _("Print Settings on Start"), config.print_settings,
        )
        self._le_max_threads = self._add_entry(
            _("Max Executor Threads"), str(config.max_executor_threads),
        )

        # ── Server ────────────────────────────────────────────────────
        self._add_section(_("Server"))
        self._le_server_host = self._add_entry(
            _("Server Host"), str(config.server_host or ""),
        )
        self._le_server_port = self._add_entry(
            _("Server Port"), str(config.server_port),
        )
        self._le_server_password = self._add_entry(
            _("Server Password"), str(config.server_password or ""),
        )

        # ── Dictionary Override ───────────────────────────────────────
        self._add_section(_("Dictionary Override"))
        self._le_override_dict_path = self._add_entry(
            _("Override Dictionary Path"), str(config.override_dictionary_path or ""),
        )
        self._cb_override_dict_append = self._add_checkbox(
            _("Append to Default Dictionary"), config.override_dictionary_append,
        )

        # ── Save bar (always visible) ─────────────────────────────────
        save_bar = QWidget()
        save_bar.setStyleSheet(
            f"background: {AppStyle.BG_COLOR}; "
            f"border-top: 1px solid {AppStyle.BORDER_COLOR};"
        )
        save_layout = QHBoxLayout(save_bar)
        save_layout.setContentsMargins(8, 6, 8, 6)

        path_label = QLabel(config.config_path)
        path_label.setStyleSheet(
            f"color: {AppStyle.FG_COLOR}; font-size: 10px; border: none;"
        )
        save_layout.addWidget(path_label, stretch=1)

        self._save_btn = QPushButton(_("Save Config"))
        self._save_btn.setStyleSheet(
            f"QPushButton {{ color: {AppStyle.FG_COLOR}; background: {AppStyle.BG_INPUT}; "
            f"border: 1px solid {AppStyle.BORDER_COLOR}; padding: 4px 16px; }}"
            f"QPushButton:hover {{ background: {AppStyle.BG_BUTTON_HOVER}; }}"
        )
        self._save_btn.clicked.connect(self._save_config)
        save_layout.addWidget(self._save_btn)

        outer.addWidget(save_bar)

        shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        shortcut.activated.connect(self.close)

    def closeEvent(self, event) -> None:
        ConfigWindow._instance = None
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Save logic
    # ------------------------------------------------------------------
    def _save_config(self) -> None:
        """Collect widget values and delegate validation + persistence."""
        checkbox_fields: list[tuple[str, str]] = [
            ("_cb_blacklist_prevent",     "blacklist_prevent_execution"),
            ("_cb_purge_blacklisted",     "purge_blacklisted_prompt_history"),
            ("_cb_save_last_prompt",      "save_last_prompt"),
            ("_cb_delay_after_single",    "delay_after_single_run"),
            ("_cb_debug",                 "debug"),
            ("_cb_print_settings",        "print_settings"),
            ("_cb_override_dict_append",  "override_dictionary_append"),
        ]
        entry_fields: list[tuple[str, str]] = [
            ("_le_comfyui_url",           "comfyui_url"),
            ("_le_sd_webui_url",          "sd_webui_url"),
            ("_le_forge_url",             "forge_url"),
            ("_le_sdnext_url",            "sdnext_url"),
            ("_le_swarmui_url",           "swarmui_url"),
            ("_le_invokeai_url",          "invokeai_url"),
            ("_le_fooocus_url",           "fooocus_url"),
            ("_le_sd_webui_save_path",    "sd_webui_save_path"),
            ("_le_forge_save_path",       "forge_save_path"),
            ("_le_sdnext_save_path",      "sdnext_save_path"),
            ("_le_swarmui_save_path",     "swarmui_save_path"),
            ("_le_invokeai_save_path",    "invokeai_save_path"),
            ("_le_fooocus_save_path",     "fooocus_save_path"),
            ("_le_models_dir",            "models_dir"),
            ("_le_img_dir",               "img_dir"),
            ("_le_img_temps_dir",         "img_temps_dir"),
            ("_le_ipadapter_dir",         "ipadapter_dir"),
            ("_le_comfyui_loc",           "comfyui_loc"),
            ("_le_sd_webui_loc",          "sd_webui_loc"),
            ("_le_sd_prompt_reader_loc",  "sd_prompt_reader_loc"),
            ("_le_image_searcher_dir2",   "image_searcher_dir2"),
            ("_le_foreground_color",      "foreground_color"),
            ("_le_background_color",      "background_color"),
            ("_le_ui_scale_factor",       "ui_scale_factor"),
            ("_le_locale",                "locale"),
            ("_le_max_threads",           "max_executor_threads"),
            ("_le_server_host",           "server_host"),
            ("_le_server_port",           "server_port"),
            ("_le_server_password",       "server_password"),
            ("_le_override_dict_path",    "override_dictionary_path"),
        ]

        raw: dict[str, object] = {}
        for widget_attr, config_key in checkbox_fields:
            raw[config_key] = getattr(self, widget_attr).isChecked()
        for widget_attr, config_key in entry_fields:
            raw[config_key] = getattr(self, widget_attr).text()

        try:
            errors = config.apply_and_persist(raw)
        except Exception as exc:
            QMessageBox.critical(
                self,
                _("Save Failed"),
                _("Could not write config file:\n\n") + str(exc),
            )
            return

        if errors:
            QMessageBox.warning(
                self,
                _("Config Validation Error"),
                _("Fix these fields before saving:\n\n") + "\n".join(errors),
            )
            return

        QMessageBox.information(
            self,
            _("Config Saved"),
            _("Settings saved successfully.\n\n"
              "Some changes (directories, URLs, UI scale, locale) "
              "require restarting the application to take full effect."),
        )

    # ------------------------------------------------------------------
    # Widget builders
    # ------------------------------------------------------------------
    def _add_section(self, text: str) -> None:
        title = QLabel(text)
        title.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        title.setStyleSheet(
            f"color: {AppStyle.FG_COLOR}; background: {AppStyle.BG_COLOR}; "
            f"font-weight: bold; padding-top: 10px; padding-bottom: 2px;"
        )
        self._grid.addWidget(title, self._row, 0, 1, 2)
        self._row += 1

    def _add_entry(self, label_text: str, initial: str) -> QLineEdit:
        lbl = QLabel(label_text)
        lbl.setFixedWidth(220)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {AppStyle.FG_COLOR}; background: {AppStyle.BG_COLOR};"
        )
        entry = QLineEdit(initial)
        entry.setStyleSheet(
            f"QLineEdit {{ color: {AppStyle.FG_COLOR}; "
            f"background: {AppStyle.BG_INPUT}; "
            f"border: 1px solid {AppStyle.BORDER_COLOR}; "
            f"padding: 2px 4px; }}"
        )
        self._grid.addWidget(
            lbl, self._row, 0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self._grid.addWidget(
            entry, self._row, 1,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self._row += 1
        return entry

    def _add_checkbox(self, label_text: str, initial: bool) -> QCheckBox:
        lbl = QLabel(label_text)
        lbl.setFixedWidth(220)
        lbl.setWordWrap(True)
        lbl.setStyleSheet(
            f"color: {AppStyle.FG_COLOR}; background: {AppStyle.BG_COLOR};"
        )
        cb = QCheckBox()
        cb.setChecked(initial)
        cb.setStyleSheet(
            f"QCheckBox {{ color: {AppStyle.FG_COLOR}; background: {AppStyle.BG_COLOR}; }}"
        )
        self._grid.addWidget(
            lbl, self._row, 0,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self._grid.addWidget(
            cb, self._row, 1,
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        self._row += 1
        return cb
