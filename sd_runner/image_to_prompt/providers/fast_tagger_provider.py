from __future__ import annotations

from extensions.hf_hub_api import ensure_hf_file
from sd_runner.image_to_prompt.base import ImageToPromptProvider
from sd_runner.image_to_prompt.providers.fast_tagger_onnx import FastTaggerOnnx
from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptRequest,
    ImageToPromptResult,
)


class FastTaggerProvider(ImageToPromptProvider):
    """Fast tagger provider (WD-style ONNX with HF auto-download)."""

    DEFAULT_REPO_ID = "SmilingWolf/wd-vit-tagger-v3"
    DEFAULT_MODEL_FILE = "model.onnx"
    DEFAULT_TAGS_FILE = "selected_tags.csv"

    def __init__(self, tagger_impl=None, repo_id: str | None = None):
        self._tagger_impl = tagger_impl
        self._repo_id = repo_id or self.DEFAULT_REPO_ID
        self._model_path = None
        self._tags_path = None

    @property
    def name(self) -> str:
        return "Fast Tagger"

    def _ensure_assets(self) -> None:
        if self._model_path and self._tags_path:
            return
        self._model_path = ensure_hf_file(self._repo_id, self.DEFAULT_MODEL_FILE)
        self._tags_path = ensure_hf_file(self._repo_id, self.DEFAULT_TAGS_FILE)

    def generate(self, request: ImageToPromptRequest) -> ImageToPromptResult:
        # Always ensure assets are downloaded even if tagger_impl is injected later.
        self._ensure_assets()
        if self._tagger_impl is None:
            self._tagger_impl = FastTaggerOnnx(
                model_path=self._model_path,
                tags_csv_path=self._tags_path,
            )

        tags = self._tagger_impl.predict_tags(
            request.image_path,
            general_threshold=float(request.extra.get("general_threshold", 0.35)),
            character_threshold=float(request.extra.get("character_threshold", 0.85)),
            include_ratings=bool(request.extra.get("include_ratings", False)),
            include_characters=bool(request.extra.get("include_characters", True)),
            top_k=int(request.extra.get("top_k", 80)),
        )
        if not isinstance(tags, list):
            raise ValueError("tagger_impl.predict_tags(image_path) must return list[str]")
        tags = [str(t).strip() for t in tags if str(t).strip()]
        positive = ", ".join(tags)
        if request.prompt_hint:
            positive = f"{request.prompt_hint.strip()}, {positive}" if positive else request.prompt_hint.strip()
        return ImageToPromptResult(
            backend=ImageToPromptBackend.FAST_TAGGER,
            positive_prompt=positive,
            negative_prompt="",
            tags=tags,
            metadata={
                "provider": self.name,
                "repo_id": self._repo_id,
                "model_path": self._model_path,
                "tags_path": self._tags_path,
            },
        )
