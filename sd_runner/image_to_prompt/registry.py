from __future__ import annotations

from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.providers.captioner_provider import CaptionerProvider
from sd_runner.image_to_prompt.providers.fast_tagger_provider import FastTaggerProvider
from sd_runner.image_to_prompt.providers.vlm_provider import VLMProvider
from sd_runner.image_to_prompt.types import ImageToPromptBackend


class ImageToPromptProviderRegistry:
    """Factory/registry for image->prompt providers."""

    @staticmethod
    def create(
        backend: ImageToPromptBackend | str,
        **kwargs,
    ) -> ImageToPromptProvider:
        backend_enum = (
            backend if isinstance(backend, ImageToPromptBackend)
            else ImageToPromptBackend(str(backend))
        )
        if backend_enum == ImageToPromptBackend.CAPTIONER:
            return CaptionerProvider(repo_id=kwargs.get("captioner_repo_id"))
        if backend_enum == ImageToPromptBackend.FAST_TAGGER:
            return FastTaggerProvider(
                tagger_impl=kwargs.get("tagger_impl"),
                repo_id=kwargs.get("fast_tagger_repo_id"),
            )
        if backend_enum == ImageToPromptBackend.VLM:
            return VLMProvider(vlm_impl=kwargs.get("vlm_impl"))
        raise ValueError(f"Unhandled image-to-prompt backend: {backend_enum}")
