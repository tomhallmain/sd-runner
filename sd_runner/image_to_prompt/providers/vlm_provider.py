from __future__ import annotations

from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class VLMProvider(ImageToPromptProvider):
    """Vision-language-model provider placeholder (e.g. LLaVA/Qwen-VL)."""

    def __init__(self, vlm_impl=None):
        self._vlm_impl = vlm_impl

    @property
    def name(self) -> str:
        return "VLM"

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        # TODO: Flesh out VLM integration once memory/runtime constraints are
        # acceptable for concurrent use with image generation workloads.
        if self._vlm_impl is None:
            raise NotImplementedError(
                "VLM backend is not configured yet. "
                "Inject a vlm_impl with a `describe_image(image_path, prompt_hint='')` method."
            )
        text = self._vlm_impl.describe_image(
            request.image_path,
            prompt_hint=request.prompt_hint or "",
        )
        positive = str(text).strip()
        return ImageToPromptResult(
            backend=ImageToPromptBackend.VLM,
            positive_prompt=positive,
            negative_prompt="",
            tags=[],
            metadata={"provider": self.name},
        )
