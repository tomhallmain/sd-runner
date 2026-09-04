"""
ImageToPromptWindow -- generate prompt text from an image (PySide6 only).

Uses the pluggable backends in ``sd_runner.image_to_prompt``:
- fast_tagger
- captioner
- vlm
"""

from __future__ import annotations

import datetime
import os
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
from sd_runner.ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N

if TYPE_CHECKING:
    from sd_runner.ui.app_actions import AppActions
    from sd_runner.ui.app_window.app_window import AppWindow

_ = I18N._


class ImageToPromptWindow(SmartDialog):
    """One-shot image description/tagging -> prompt generation."""
    LAST_IMAGE_TO_PROMPT_CACHE_KEY = "last_image_to_prompt"
    _instance = None
    _last_cached_payload: dict = {}

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
        ImageToPromptWindow._instance = self
        self._app = parent
        self._app_actions = app_actions
        # Keyed by backend *and* its options: changing the VLM model has to
        # build a new service, or the previously loaded one keeps answering.
        self._service_cache: dict[tuple, ImageToPromptService] = {}
        self._build_ui()
        self._restore_last_values()
        self._sync_backend_options()
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

        self._backend_combo.currentIndexChanged.connect(self._sync_backend_options)

        self._include_negative_cb = QCheckBox(_("Include Negative Prompt"))
        self._include_negative_cb.setChecked(False)
        opts_row.addWidget(self._include_negative_cb)
        opts_row.addStretch()
        layout.addLayout(opts_row)

        # VLM model — shown only for the VLM backend, which is the only one
        # whose model is worth choosing per use. The others have a single
        # sensible default and no reason to expose it here.
        self._vlm_row = QWidget()
        vlm_row = QHBoxLayout(self._vlm_row)
        vlm_row.setContentsMargins(0, 0, 0, 0)
        self._vlm_repo_label = QLabel(_("VLM Model"))
        vlm_row.addWidget(self._vlm_repo_label)
        self._vlm_repo_edit = QLineEdit()
        self._vlm_repo_edit.setPlaceholderText(config.vlm_repo_id)
        vlm_row.addWidget(self._vlm_repo_edit)
        self._vlm_unload_btn = QPushButton(_("Unload Model"))
        self._vlm_unload_btn.setToolTip(
            _("Free the VLM's video memory for image generation. It reloads on next use.")
        )
        self._vlm_unload_btn.clicked.connect(self._unload_vlm)
        vlm_row.addWidget(self._vlm_unload_btn)
        layout.addWidget(self._vlm_row)

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
    def _initial_image_dir(self) -> str:
        current = self._image_path.text().strip()
        cached = str(self.__class__._last_cached_payload.get("image_path", "") or "")
        candidate = current or cached
        if not candidate:
            return ""
        if os.path.isdir(candidate):
            return candidate
        parent = os.path.dirname(candidate)
        if parent and os.path.isdir(parent):
            return parent
        return ""

    def _browse_image(self) -> None:
        path, _file_filter = QFileDialog.getOpenFileName(
            self,
            _("Select Image"),
            self._initial_image_dir(),
            _("Images (*.png *.jpg *.jpeg *.webp *.bmp *.avif *.heic *.heif *.jxl);;All files (*.*)"),
        )
        if path:
            self._image_path.setText(path)

    def _selected_backend(self) -> ImageToPromptBackend:
        data = self._backend_combo.currentData()
        return ImageToPromptBackend(str(data))

    def _selected_vlm_repo_id(self) -> str:
        """The model to run, from the field or the configured default."""
        return self._vlm_repo_edit.text().strip() or config.vlm_repo_id

    def _sync_backend_options(self) -> None:
        """Show the options that belong to the selected backend."""
        self._vlm_row.setVisible(self._selected_backend() == ImageToPromptBackend.VLM)

    def _unload_vlm(self) -> None:
        """Release the VLM's memory back to the image-generation backend.

        Also drops the cached services, so the next generate rebuilds rather
        than handing back a provider holding a reference to the unloaded model.
        """
        from sd_runner.image_to_prompt.providers.llava_transformers import (
            LlavaTransformersImpl,
        )
        LlavaTransformersImpl.unload_shared()
        self._service_cache = {
            key: service for key, service in self._service_cache.items()
            if key[0] != ImageToPromptBackend.VLM
        }
        self._app_actions.toast(_("VLM model unloaded."))

    def _service_for_backend(self, backend: ImageToPromptBackend) -> ImageToPromptService:
        kwargs = {}
        if backend == ImageToPromptBackend.VLM:
            kwargs = {
                "vlm_repo_id": self._selected_vlm_repo_id(),
                "vlm_load_in_4bit": config.vlm_load_in_4bit,
            }
        key = (backend, tuple(sorted(kwargs.items())))
        service = self._service_cache.get(key)
        if service is None:
            service = ImageToPromptService.from_backend(backend, **kwargs)
            self._service_cache[key] = service
        return service

    @classmethod
    def _normalize_cached_payload(cls, data) -> dict:
        if not isinstance(data, dict):
            return {}
        return {
            "image_path": str(data.get("image_path", "") or ""),
            "prompt_value": str(data.get("prompt_value", "") or ""),
            "negative_prompt": str(data.get("negative_prompt", "") or ""),
            "method": str(data.get("method", "") or ""),
            # Absent in payloads written before the VLM backend was usable;
            # those restore blank, which falls back to the configured default.
            "vlm_repo_id": str(data.get("vlm_repo_id", "") or ""),
        }

    @classmethod
    def load_last_from_cache(cls) -> dict:
        data = app_info_cache.get(cls.LAST_IMAGE_TO_PROMPT_CACHE_KEY, default_val={})
        cls._last_cached_payload = cls._normalize_cached_payload(data)
        return cls._last_cached_payload

    @classmethod
    def save_last_to_cache(
        cls,
        image_path: str,
        prompt_value: str,
        method: str,
        negative_prompt: str = "",
        vlm_repo_id: str = "",
    ) -> dict:
        payload = {
            "image_path": str(image_path or ""),
            "prompt_value": str(prompt_value or ""),
            "negative_prompt": str(negative_prompt or ""),
            "method": str(method or ""),
            "vlm_repo_id": str(vlm_repo_id or ""),
        }
        app_info_cache.set(cls.LAST_IMAGE_TO_PROMPT_CACHE_KEY, payload)
        app_info_cache.store()
        cls._last_cached_payload = cls._normalize_cached_payload(payload)
        return cls._last_cached_payload

    def _restore_last_values(self) -> None:
        data = self.__class__._last_cached_payload or self.load_last_from_cache()
        if not isinstance(data, dict):
            return
        image_path = str(data.get("image_path", "") or "")
        prompt_value = str(data.get("prompt_value", "") or "")
        negative_prompt = str(data.get("negative_prompt", "") or "")
        method = str(data.get("method", "") or "")
        if image_path:
            self._image_path.setText(image_path)
        if prompt_value:
            self._positive_box.setPlainText(prompt_value)
        if negative_prompt:
            self._negative_box.setPlainText(negative_prompt)
        if method:
            idx = self._backend_combo.findData(method)
            if idx >= 0:
                self._backend_combo.setCurrentIndex(idx)
        vlm_repo_id = str(data.get("vlm_repo_id", "") or "")
        if vlm_repo_id:
            self._vlm_repo_edit.setText(vlm_repo_id)

    def _generate(self) -> None:
        image_path = self._image_path.text().strip()
        if not image_path:
            self._app_actions.toast(_("Select an image first."))
            return

        backend = self._selected_backend()
        include_negative = self._include_negative_cb.isChecked()
        prompt_hint = self._hint_edit.text().strip()
        previous_positive = self._positive_box.toPlainText()
        previous_negative = self._negative_box.toPlainText()

        try:
            service = self._service_for_backend(backend)
            result = service.generate(
                image_path=image_path,
                prompt_hint=prompt_hint,
                include_negative=include_negative,
            )
            self._positive_box.setPlainText(result.positive_prompt or "")
            self._negative_box.setPlainText(result.negative_prompt or "")
            positive_text = result.positive_prompt or ""
            negative_text = result.negative_prompt or ""
            changed = (positive_text != previous_positive) or (negative_text != previous_negative)
            state_label = _("updated") if changed else _("unchanged")
            image_name = os.path.basename(image_path) or image_path
            timestamp = datetime.datetime.now().strftime("%H:%M:%S")
            self._status.setText(
                _("Generated ({0}: {1}) using backend: {2} [{3}]").format(
                    state_label,
                    image_name,
                    backend.value,
                    timestamp,
                )
            )
            self.save_last_to_cache(
                image_path=image_path,
                prompt_value=positive_text,
                negative_prompt=negative_text,
                method=backend.value,
                vlm_repo_id=self._vlm_repo_edit.text().strip(),
            )
            if backend == ImageToPromptBackend.FAST_TAGGER and not positive_text.strip():
                self._app_actions.toast(_("Fast tagger returned no tags; try a lower threshold."))
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

    def closeEvent(self, event) -> None:  # noqa: N802
        ImageToPromptWindow._instance = None
        super().closeEvent(event)
