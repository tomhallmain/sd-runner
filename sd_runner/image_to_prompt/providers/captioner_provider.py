from __future__ import annotations

from extensions.model_download import ensure_hf_snapshot
from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class CaptionerProvider(ImageToPromptProvider):
    """BLIP caption-based provider.

    Preferred path uses Transformers BLIP with automatic HF download.
    Falls back to the legacy in-repo captioner if Transformers is unavailable.
    """

    DEFAULT_REPO_ID = "Salesforce/blip-image-captioning-base"

    def __init__(self, repo_id: str | None = None):
        self._repo_id = repo_id or self.DEFAULT_REPO_ID
        self._processor = None
        self._model = None
        self._device = "cpu"
        self._legacy_captioner = None

    @property
    def name(self) -> str:
        return "BLIP Captioner"

    def _ensure_transformers_blip(self) -> bool:
        if self._processor is not None and self._model is not None:
            return True
        try:
            import torch
            from transformers import BlipForConditionalGeneration, BlipProcessor
        except Exception:
            return False

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

        self._device = "cuda" if torch.cuda.is_available() else "cpu"
        self._processor = BlipProcessor.from_pretrained(self._repo_id)
        self._model = BlipForConditionalGeneration.from_pretrained(self._repo_id)
        self._model.to(self._device)
        self._model.eval()
        return True

    def _generate_transformers(self, image_path: str) -> str:
        import torch
        from PIL import Image

        image = Image.open(image_path).convert("RGB")
        inputs = self._processor(images=image, return_tensors="pt")
        inputs = {k: v.to(self._device) for k, v in inputs.items()}
        with torch.no_grad():
            out = self._model.generate(**inputs, max_new_tokens=64, num_beams=4)
        return self._processor.decode(out[0], skip_special_tokens=True).strip()

    def _generate_legacy(self, image_path: str) -> str:
        if self._legacy_captioner is None:
            from sd_runner.captioner import Captioner

            self._legacy_captioner = Captioner()
        return self._legacy_captioner.caption(image_path).strip()

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        if self._ensure_transformers_blip():
            caption = self._generate_transformers(request.image_path)
            provider_name = f"{self.name} (Transformers)"
        else:
            caption = self._generate_legacy(request.image_path)
            provider_name = f"{self.name} (Legacy)"

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
