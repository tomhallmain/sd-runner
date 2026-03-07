"""
ImageToPromptWindow -- generate prompt text from an image (PySide6 only).

Uses the pluggable backends in ``sd_runner.image_to_prompt``:
- fast_tagger
- captioner
- vlm
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.image_to_prompt import ImageToPromptBackend, ImageToPromptService
from ui_qt.app_style import AppStyle
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions
    from ui_qt.app_window.app_window import AppWindow

_ = I18N._


class ImageToPromptWindow(SmartDialog):
    """One-shot image description/tagging -> prompt generation."""

    def __init__(
        self,
        parent: AppWindow,
        app_actions: AppActions,
        geometry: str = "1000x700",
    ):
        super().__init__(
            parent=parent,
            title=_("Image to Prompt"),
            geometry=geometry,
        )
        self.setStyleSheet(AppStyle.get_stylesheet())
        self._app = parent
        self._app_actions = app_actions
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
                "Generate prompt text from an image using selectable backends. "
                "This does not start image generation."
            )
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        # Image selection
        image_row = QHBoxLayout()
        image_row.addWidget(QLabel(_("Image")))
        self._image_path = QLineEdit()
        image_row.addWidget(self._image_path)
        browse_btn = QPushButton(_("Browse"))
        browse_btn.clicked.connect(self._browse_image)
        image_row.addWidget(browse_btn)
        layout.addLayout(image_row)

        # Backend + options
        opts_row = QHBoxLayout()
        opts_row.addWidget(QLabel(_("Backend")))
        self._backend_combo = QComboBox()
        self._backend_combo.addItem(_("Captioner (BLIP)"), ImageToPromptBackend.CAPTIONER.value)
        self._backend_combo.addItem(_("Fast Tagger"), ImageToPromptBackend.FAST_TAGGER.value)
        self._backend_combo.addItem(_("VLM"), ImageToPromptBackend.VLM.value)
        opts_row.addWidget(self._backend_combo)

        self._include_negative_cb = QCheckBox(_("Include Negative Prompt"))
        self._include_negative_cb.setChecked(False)
        opts_row.addWidget(self._include_negative_cb)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # Prompt hint
        hint_row = QHBoxLayout()
        hint_row.addWidget(QLabel(_("Prompt Hint (optional)")))
        self._hint_edit = QLineEdit()
        hint_row.addWidget(self._hint_edit)
        layout.addLayout(hint_row)

        # Action buttons
        btn_row = QHBoxLayout()
        gen_btn = QPushButton(_("Generate Prompt from Image"))
        gen_btn.clicked.connect(self._generate)
        btn_row.addWidget(gen_btn)

        copy_pos_btn = QPushButton(_("Copy Positive"))
        copy_pos_btn.clicked.connect(lambda: self._copy_text(self._positive_box.toPlainText()))
        btn_row.addWidget(copy_pos_btn)

        copy_neg_btn = QPushButton(_("Copy Negative"))
        copy_neg_btn.clicked.connect(lambda: self._copy_text(self._negative_box.toPlainText()))
        btn_row.addWidget(copy_neg_btn)

        apply_btn = QPushButton(_("Apply Positive to Main UI"))
        apply_btn.clicked.connect(self._apply_positive_to_main_ui)
        btn_row.addWidget(apply_btn)

        btn_row.addStretch()
        layout.addLayout(btn_row)

        # Outputs
        layout.addWidget(QLabel(_("Positive Prompt")))
        self._positive_box = QPlainTextEdit()
        self._positive_box.setReadOnly(True)
        layout.addWidget(self._positive_box)

        layout.addWidget(QLabel(_("Negative Prompt")))
        self._negative_box = QPlainTextEdit()
        self._negative_box.setReadOnly(True)
        layout.addWidget(self._negative_box)

        self._status = QLabel(_("No output yet."))
        layout.addWidget(self._status)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _browse_image(self) -> None:
        path, _file_filter = QFileDialog.getOpenFileName(
            self,
            _("Select Image"),
            "",
            _("Images (*.png *.jpg *.jpeg *.webp *.bmp);;All files (*.*)"),
        )
        if path:
            self._image_path.setText(path)

    def _selected_backend(self) -> ImageToPromptBackend:
        data = self._backend_combo.currentData()
        return ImageToPromptBackend(str(data))

    def _generate(self) -> None:
        image_path = self._image_path.text().strip()
        if not image_path:
            self._app_actions.toast(_("Select an image first."))
            return

        backend = self._selected_backend()
        include_negative = self._include_negative_cb.isChecked()
        prompt_hint = self._hint_edit.text().strip()

        try:
            service = ImageToPromptService.from_backend(backend)
            result = service.generate(
                image_path=image_path,
                prompt_hint=prompt_hint,
                include_negative=include_negative,
            )
            self._positive_box.setPlainText(result.positive_prompt or "")
            self._negative_box.setPlainText(result.negative_prompt or "")
            self._status.setText(
                _("Generated using backend: {0}").format(backend.value)
            )
        except NotImplementedError as e:
            self._app_actions.alert(
                _("Backend Not Configured"),
                str(e),
                kind="warning",
                master=self,
            )
        except Exception as e:
            self._app_actions.alert(
                _("Image to Prompt Error"),
                str(e),
                kind="error",
                master=self,
            )

    def _copy_text(self, text: str) -> None:
        if not text.strip():
            self._app_actions.toast(_("Nothing to copy."))
            return
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)
            self._app_actions.toast(_("Copied to clipboard"))

    def _apply_positive_to_main_ui(self) -> None:
        text = self._positive_box.toPlainText().strip()
        if not text:
            self._app_actions.toast(_("No positive prompt to apply."))
            return
        self._app.sidebar_panel.positive_tags_box.setPlainText(text)
        self._app_actions.toast(_("Applied positive prompt to main UI"))
