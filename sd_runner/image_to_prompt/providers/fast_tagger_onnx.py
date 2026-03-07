from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Any

import numpy as np
from PIL import Image


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

        providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self._session = ort.InferenceSession(self._model_path, providers=providers)
        input_meta = self._session.get_inputs()[0]
        self._input_name = input_meta.name

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
        image = Image.open(image_path).convert("RGB")
        image = image.resize((self._input_hw, self._input_hw), Image.Resampling.BICUBIC)
        arr = np.asarray(image, dtype=np.float32) / 255.0
        if self._channels_first:
            arr = np.transpose(arr, (2, 0, 1))
        arr = np.expand_dims(arr, axis=0).astype(np.float32, copy=False)
        return arr

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
        probs = outputs[0]
        if isinstance(probs, list):
            probs = probs[0]
        if len(probs.shape) == 2:
            probs = probs[0]

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
