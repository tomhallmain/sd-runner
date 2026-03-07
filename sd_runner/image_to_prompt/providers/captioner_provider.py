from __future__ import annotations

import os
import threading
import warnings

from extensions.hf_hub_api import ensure_hf_snapshot
from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class CaptionerProvider(ImageToPromptProvider):
    """BLIP caption-based provider.

    Uses Transformers BLIP with automatic HF download.
    """

    DEFAULT_REPO_ID = "Salesforce/blip-image-captioning-base"
    _load_lock = threading.Lock()
    _shared_processor = None
    _shared_model = None
    _shared_device = "cpu"
    _shared_repo_id = None

    def __init__(self, repo_id: str | None = None):
        self._repo_id = repo_id or self.DEFAULT_REPO_ID
        self._processor = None
        self._model = None
        self._device = "cpu"

    @property
    def name(self) -> str:
        return "BLIP Captioner"

    def _ensure_transformers_blip(self) -> None:
        if self._processor is not None and self._model is not None:
            return
        with self.__class__._load_lock:
            if (
                self.__class__._shared_processor is not None
                and self.__class__._shared_model is not None
                and self.__class__._shared_repo_id == self._repo_id
            ):
                self._processor = self.__class__._shared_processor
                self._model = self.__class__._shared_model
                self._device = self.__class__._shared_device
                return

            try:
                import torch
                from transformers import BlipForConditionalGeneration, BlipProcessor, logging as transformers_logging
            except Exception as e:
                raise RuntimeError(
                    "Captioner backend requires torch + transformers. "
                    "Install optional deps (e.g. `pip install -r requirements-optional.txt`)."
                ) from e

            # Reduce HF/Transformers console noise for known cache/progress and model-load warnings.
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")

            # Trigger/download local cache via HF Hub explicitly.
            ensure_hf_snapshot(
                self._repo_id,
                allow_patterns=[
                    "config.json",
                    "preprocessor_config.json",
                    "tokenizer_config.json",
                    "special_tokens_map.json",
                    "vocab.txt",
                    "pytorch_model.bin",
                    "model.safetensors",
                ],
            )

            prev_verbosity = transformers_logging.get_verbosity()
            try:
                transformers_logging.set_verbosity_error()
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r".*loaded as a fast processor by default.*",
                        category=UserWarning,
                    )
                    processor = BlipProcessor.from_pretrained(self._repo_id, use_fast=False)
                    model = BlipForConditionalGeneration.from_pretrained(self._repo_id)
            finally:
                transformers_logging.set_verbosity(prev_verbosity)

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model.to(device)
            model.eval()

            self.__class__._shared_processor = processor
            self.__class__._shared_model = model
            self.__class__._shared_device = device
            self.__class__._shared_repo_id = self._repo_id
            self._processor = processor
            self._model = model
            self._device = device

    def _generate_transformers(self, image_path: str) -> str:
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=64, num_beams=4)
        return self._processor.decode(out[0], skip_special_tokens=True).strip()

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        try:
            self._ensure_transformers_blip()
            caption = self._generate_transformers(request.image_path)
            provider_name = f"{self.name} (Transformers)"
        except Exception as e:
            raise RuntimeError(
                "Failed to initialize BLIP captioner backend. "
                "Ensure optional captioner dependencies are installed."
            ) from e

        if request.prompt_hint:
            positive = f"{request.prompt_hint.strip()}, {caption}" if caption else request.prompt_hint.strip()
        else:
            positive = caption
        return ImageToPromptResult(
            backend=ImageToPromptBackend.CAPTIONER,
            positive_prompt=positive,
            negative_prompt="",
            tags=[],
            metadata={"provider": provider_name, "repo_id": self._repo_id},
        )
