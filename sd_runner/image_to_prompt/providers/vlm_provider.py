from __future__ import annotations

from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class VLMProvider(ImageToPromptProvider):
    """Vision-language-model provider (LLaVA family, via Transformers).

    The model itself lives behind a ``vlm_impl`` -- anything exposing
    ``describe_image(image_path, prompt_hint="") -> str``. One is built on
    first use when none is injected, so the backend works out of the box while
    a caller that wants a different model runtime can still supply its own.
    """

    def __init__(
        self,
        vlm_impl=None,
        repo_id: str | None = None,
        load_in_4bit: bool = False,
    ):
        self._vlm_impl = vlm_impl
        self._repo_id = repo_id
        self._load_in_4bit = load_in_4bit

    @property
    def name(self) -> str:
        return "VLM"

    def _ensure_impl(self):
        """Build the default impl on first use.

        Deferred rather than built in ``__init__`` because constructing the
        provider must stay cheap: the window builds one per backend to populate
        its dropdown, and importing torch alone costs seconds.
        """
        if self._vlm_impl is None:
            from sd_runner.image_to_prompt.providers.llava_transformers import (
                LlavaTransformersImpl,
            )
            self._vlm_impl = LlavaTransformersImpl(
                repo_id=self._repo_id,
                load_in_4bit=self._load_in_4bit,
            )
        return self._vlm_impl

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        impl = self._ensure_impl()
        text = impl.describe_image(
            request.image_path,
            prompt_hint=request.prompt_hint or "",
        )
        positive = str(text).strip()
        metadata = {"provider": self.name}
        repo_id = getattr(impl, "_repo_id", None) or self._repo_id
        if repo_id:
            metadata["repo_id"] = repo_id
        return ImageToPromptResult(
            backend=ImageToPromptBackend.VLM,
            positive_prompt=positive,
            negative_prompt="",
            tags=[],
            metadata=metadata,
        )
