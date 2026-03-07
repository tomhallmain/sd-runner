from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image

from utils.logging_setup import get_logger

logger = get_logger("image_to_prompt.fast_tagger_onnx")


@dataclass(slots=True)
class _TagMeta:
    name: str
    category: int


class FastTaggerOnnx:
    """ONNX runtime wrapper for WD-style fast tagger models."""

    RATING_CATEGORY = 9
    GENERAL_CATEGORY = 0
    CHARACTER_CATEGORY = 4

    def __init__(self, model_path: str, tags_csv_path: str):
        self._model_path = model_path
        self._tags_csv_path = tags_csv_path
        self._session = None
        self._input_name = ""
        self._input_hw = 448
        self._channels_first = False
        self._tags: list[_TagMeta] = []

    def _ensure_loaded(self) -> None:
        if self._session is not None:
            return

        import onnxruntime as ort

        available = set(ort.get_available_providers())
        providers = [p for p in ("CUDAExecutionProvider", "CPUExecutionProvider") if p in available]
        if not providers:
            providers = ["CPUExecutionProvider"]
        self._session = ort.InferenceSession(self._model_path, providers=providers)
        input_meta = self._session.get_inputs()[0]
        self._input_name = input_meta.name
        logger.info("FastTagger ONNX loaded: input=%s shape=%s providers=%s", self._input_name, input_meta.shape, providers)

        # WD-style models are typically NCHW or NHWC.
        shape = list(input_meta.shape)
        # Replace dynamic dims with defaults.
        shape = [1 if (d is None or isinstance(d, str)) else int(d) for d in shape]
        if len(shape) != 4:
            raise ValueError(f"Unexpected fast tagger input shape: {input_meta.shape}")
        if shape[1] == 3:
            self._channels_first = True
            self._input_hw = shape[2]
        else:
            self._channels_first = False
            self._input_hw = shape[1]

        self._tags = self._load_tags(self._tags_csv_path)
        logger.info(f"Loaded {len(self._tags)} tags from CSV")

    @staticmethod
    def _load_tags(csv_path: str) -> list[_TagMeta]:
        tags: list[_TagMeta] = []
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = str(row.get("name", "")).strip()
                if not name:
                    continue
                try:
                    category = int(str(row.get("category", "0")).strip())
                except Exception:
                    category = 0
                tags.append(_TagMeta(name=name, category=category))
        return tags

    def _preprocess(self, image_path: str) -> np.ndarray:
        image = Image.open(image_path).convert("RGBA")
        # Match SmilingWolf Space preprocessing:
        # alpha composite on white -> pad to square -> resize -> RGB->BGR.
        canvas = Image.new("RGBA", image.size, (255, 255, 255))
        canvas.alpha_composite(image)
        image = canvas.convert("RGB")

        width, height = image.size
        max_dim = max(width, height)
        pad_left = (max_dim - width) // 2
        pad_top = (max_dim - height) // 2
        padded = Image.new("RGB", (max_dim, max_dim), (255, 255, 255))
        padded.paste(image, (pad_left, pad_top))

        if max_dim != self._input_hw:
            padded = padded.resize((self._input_hw, self._input_hw), Image.Resampling.BICUBIC)

        arr = np.asarray(padded, dtype=np.float32)
        # Convert PIL-native RGB to BGR, as used by the official wd-tagger Space.
        arr = arr[:, :, ::-1]
        if self._channels_first:
            arr = np.transpose(arr, (2, 0, 1))
        arr = np.expand_dims(arr, axis=0).astype(np.float32, copy=False)
        return arr

    def _select_probs_output(self, outputs: list[Any]) -> np.ndarray:
        """Select the tensor that most likely contains per-tag scores."""
        if not outputs:
            return np.asarray([])

        logger.debug(f"Total outputs: {len(outputs)}")
        for i, out in enumerate(outputs):
            arr = np.asarray(out)
            logger.debug(
                "Output %s: shape=%s, dtype=%s, min=%.4f, max=%.4f, mean=%.4f",
                i,
                arr.shape,
                arr.dtype,
                float(arr.min()),
                float(arr.max()),
                float(arr.mean()),
            )

        target_len = len(self._tags)
        exact_match: np.ndarray | None = None
        best = None
        best_last_dim = -1
        for out in outputs:
            arr = np.asarray(out)
            if arr.size == 0:
                continue
            if arr.ndim == 0:
                continue
            last_dim = int(arr.shape[-1]) if arr.shape else 0
            if last_dim == target_len:
                exact_match = arr
                break
            if last_dim > best_last_dim:
                best_last_dim = last_dim
                best = arr
        return exact_match if exact_match is not None else (best if best is not None else np.asarray(outputs[0]))

    def predict_tags(
        self,
        image_path: str,
        *,
        general_threshold: float = 0.35,
        character_threshold: float = 0.85,
        include_ratings: bool = False,
        include_characters: bool = True,
        replace_underscores: bool = True,
        top_k: int = 80,
    ) -> list[str]:
        self._ensure_loaded()
        assert self._session is not None

        inp = self._preprocess(image_path)
        outputs = self._session.run(None, {self._input_name: inp})
        if not outputs:
            return []
        probs = self._select_probs_output(outputs)
        if probs.ndim >= 2:
            probs = probs[0]
        probs = np.ravel(probs)
        # Some exports emit logits; convert to probabilities if needed.
        if np.min(probs) < 0.0 or np.max(probs) > 1.0:
            probs = 1.0 / (1.0 + np.exp(-probs))
        logger.debug(
            "FastTagger output stats: len=%s min=%.4f max=%.4f mean=%.4f",
            len(probs),
            float(np.min(probs)),
            float(np.max(probs)),
            float(np.mean(probs)),
        )

        probs_flat = probs.flatten()
        top_indices = np.argsort(probs_flat)[-20:][::-1]  # top 20 indices
        logger.debug("Top 20 scores and tags:")
        for idx in top_indices:
            if idx < len(self._tags):
                logger.debug(
                    "  %s (cat=%s): %.4f",
                    self._tags[idx].name,
                    self._tags[idx].category,
                    float(probs_flat[idx]),
                )

        scored: list[tuple[str, float]] = []
        max_len = min(len(self._tags), int(probs.shape[0]))
        for idx in range(max_len):
            meta = self._tags[idx]
            score = float(probs[idx])

            if meta.category == self.RATING_CATEGORY:
                if include_ratings and score >= general_threshold:
                    scored.append((meta.name, score))
                continue

            if meta.category == self.CHARACTER_CATEGORY:
                if include_characters and score >= character_threshold:
                    scored.append((meta.name, score))
                continue

            if score >= general_threshold:
                scored.append((meta.name, score))

        scored.sort(key=lambda x: x[1], reverse=True)
        selected = scored[:top_k] if top_k > 0 else scored

        tags = [name.replace("_", " ") if replace_underscores else name for name, _ in selected]
        return tags
