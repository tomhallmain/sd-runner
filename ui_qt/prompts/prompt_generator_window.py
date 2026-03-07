"""
PromptGeneratorWindow -- generate one prompt on demand (PySide6 only).

This window intentionally does *not* run image generation. It only:
- generates a single prompt pair (positive/negative) per click
- displays the latest generated prompt
- allows copying prompts to clipboard
- optionally stores the generated prompt in prompt history on demand
"""

from __future__ import annotations

import datetime
from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.prompter import Prompter
from sd_runner.run_config import RunConfig
from ui_qt.app_style import AppStyle
from ui_qt.prompts.prompt_config_window import PromptConfigWindow
from utils.app_info_cache import app_info_cache
from utils.globals import Globals, PromptMode
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions
    from ui_qt.app_window.app_window import AppWindow

_ = I18N._


class PromptGeneratorWindow(SmartDialog):
    """Generate prompts without starting any image generation run."""

    def __init__(
        self,
        parent: AppWindow,
        app_actions: AppActions,
        geometry: str = "980x640",
    ):
        super().__init__(
            parent=parent,
            title=_("Prompt Generator"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._app = parent
        self._app_actions = app_actions
        self._last_positive = ""
        self._last_negative = ""

        self._build_ui()
        self.show()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        info = QLabel(
            _(
                "Generate one prompt at a time using current UI settings. "
                "This does not run image generation and does not modify prompt history "
                "unless you click \"Save to Prompt History\"."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        btn_row = QHBoxLayout()
        self._generate_btn = QPushButton(_("Generate One Prompt"))
        self._generate_btn.clicked.connect(self._generate_once)
        btn_row.addWidget(self._generate_btn)

        self._copy_positive_btn = QPushButton(_("Copy Positive"))
        self._copy_positive_btn.clicked.connect(lambda: self._copy_text(self._positive_box.toPlainText()))
        btn_row.addWidget(self._copy_positive_btn)

        self._copy_negative_btn = QPushButton(_("Copy Negative"))
        self._copy_negative_btn.clicked.connect(lambda: self._copy_text(self._negative_box.toPlainText()))
        btn_row.addWidget(self._copy_negative_btn)

        self._save_history_btn = QPushButton(_("Save to Prompt History"))
        self._save_history_btn.clicked.connect(self._save_to_prompt_history)
        btn_row.addWidget(self._save_history_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        layout.addWidget(QLabel(_("Generated Positive Prompt")))
        self._positive_box = QPlainTextEdit()
        self._positive_box.setReadOnly(True)
        layout.addWidget(self._positive_box)

        layout.addWidget(QLabel(_("Generated Negative Prompt")))
        self._negative_box = QPlainTextEdit()
        self._negative_box.setReadOnly(True)
        layout.addWidget(self._negative_box)

        self._status = QLabel(_("No prompt generated yet."))
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _generate_once(self) -> None:
        try:
            sp = self._app.sidebar_panel
            cfg = self._app.runner_app_config

            # Sync the latest prompt-config window values (if open) into cfg.
            PromptConfigWindow.set_args_from_prompter_config(RunConfig())

            prompt_mode = PromptMode.get(sp.prompt_mode_combo.currentText())
            cfg.prompter_config.prompt_mode = prompt_mode
            cfg.prompter_config.concepts_dir = sp.concepts_dir_combo.currentText()
            cfg.prompter_config.sparse_mixed_tags = cfg.sparse_mixed_tags

            positive_seed = sp.positive_tags_box.toPlainText().strip()
            negative_seed = sp.negative_tags_box.toPlainText().strip()
            positive_seed = positive_seed if positive_seed else str(Globals.DEFAULT_POSITIVE_PROMPT)
            base_negative = "" if Globals.OVERRIDE_BASE_NEGATIVE else str(Globals.DEFAULT_NEGATIVE_PROMPT)
            negative_seed = negative_seed if negative_seed else base_negative

            prev_positive_tags = Prompter.POSITIVE_TAGS
            prev_negative_tags = Prompter.NEGATIVE_TAGS
            prev_tags_apply_to_start = Prompter.TAGS_APPLY_TO_START
            try:
                Prompter.set_positive_tags(positive_seed)
                Prompter.set_negative_tags(negative_seed)
                Prompter.set_tags_apply_to_start(cfg.tags_apply_to_start)

                prompter = Prompter(
                    prompter_config=cfg.get_prompter_config_copy(),
                    get_specific_locations=Globals.PROMPTER_GET_SPECIFIC_LOCATIONS,
                    get_specific_times=Globals.PROMPTER_GET_SPECIFIC_TIMES,
                )
                positive, negative = prompter.generate_prompt(positive_seed, negative_seed)
            finally:
                # Keep this preview flow side-effect free for the rest of the app.
                Prompter.set_positive_tags(prev_positive_tags)
                Prompter.set_negative_tags(prev_negative_tags)
                Prompter.set_tags_apply_to_start(prev_tags_apply_to_start)

            self._last_positive = positive
            self._last_negative = negative
            self._positive_box.setPlainText(positive)
            self._negative_box.setPlainText(negative)
            self._status.setText(_("Generated a new prompt."))
        except Exception as e:
            self._app_actions.alert(_("Prompt Generation Error"), str(e), kind="error", master=self)

    def _copy_text(self, text: str) -> None:
        if not text.strip():
            self._app_actions.toast(_("Nothing to copy. Generate a prompt first."))
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self._app_actions.toast(_("Copied to clipboard"))

    def _save_to_prompt_history(self) -> None:
        if not self._last_positive.strip():
            self._app_actions.toast(_("Generate a prompt first."))
            return
        saved = app_info_cache.add_prompt_history_entry(
            positive_tags=self._last_positive,
            negative_tags=self._last_negative,
            timestamp=datetime.datetime.now().isoformat(),
        )
        if not saved:
            self._app_actions.toast(_("Nothing to save."))
            return
        app_info_cache.store()
        self._app_actions.toast(_("Saved generated prompt to prompt history"))
