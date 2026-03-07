from __future__ import annotations

from abc import ABC, abstractmethod

from sd_runner.image_to_prompt.types import ImageToPromptRequest, ImageToPromptResult


class ImageToPromptProvider(ABC):
    """Common interface for image->prompt providers."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name."""

    @abstractmethod
    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        """Generate prompt output for a single image request."""
