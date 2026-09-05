from __future__ import annotations

from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.negative import resolve_negative
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
        return self._apply_negative_policy(self._provider.generate(request), request)

    @staticmethod
    def _apply_negative_policy(
        result: ImageToPromptResult, request: ImageToPromptRequest,
    ) -> ImageToPromptResult:
        """Settle the result's negative according to ``include_negative``.

        Here rather than in each provider because the rule is the same for all
        three and is not about what a model can see. ``include_negative`` is
        authoritative in both directions: unasked-for, a negative is cleared
        rather than passed on, so a provider that starts producing one cannot
        quietly override the choice.
        """
        if not request.include_negative:
            result.negative_prompt = ""
        elif not result.negative_prompt:
            result.negative_prompt = resolve_negative(request.image_path)
        return result
