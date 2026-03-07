from __future__ import annotations

from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.registry import ImageToPromptProviderRegistry
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class ImageToPromptService:
    """High-level service for one-shot image->prompt generation."""

    def __init__(self, provider: ImageToPromptProvider):
        self._provider = provider

    @classmethod
    def from_backend(cls, backend: ImageToPromptBackend | str, **kwargs) -> "ImageToPromptService":
        provider = ImageToPromptProviderRegistry.create(backend, **kwargs)
        return cls(provider)

    def generate(
        self,
        image_path: str,
        prompt_hint: str = "",
        include_negative: bool = False,
        extra: dict | None = None,
    ) -> ImageToPromptResult:
        request = ImageToPromptRequest(
            image_path=image_path,
            prompt_hint=prompt_hint,
            include_negative=include_negative,
            extra=extra or {},
        )
        return self._provider.generate(request)
