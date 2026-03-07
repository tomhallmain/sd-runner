from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ImageToPromptBackend(str, Enum):
    """Supported image->prompt backend types."""

    FAST_TAGGER = "fast_tagger"
    CAPTIONER = "captioner"
    VLM = "vlm"


@dataclass(slots=True)
class ImageToPromptRequest:
    """Request payload for image->prompt generation."""

    image_path: str
    prompt_hint: str = ""
    include_negative: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ImageToPromptResult:
    """Normalized output from any image->prompt backend."""

    backend: ImageToPromptBackend
    positive_prompt: str
    negative_prompt: str = ""
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
