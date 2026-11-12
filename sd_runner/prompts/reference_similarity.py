"""CLIP image-text similarity, used to resolve ``[[~a,b,c]]`` choice sets.

Text and image are encoded by the same model, so their embeddings share one
space and a cosine between them is meaningful. Backends:

  1. ``transformers`` ``AutoModel``: ``reference_similarity_model`` is a Hugging
     Face id or a local directory, loaded with ``local_files_only`` so a
     generation never starts a download. Any model with ``get_image_features``
     and ``get_text_features`` works: CLIP, SigLIP, MetaCLIP, LAION CLIP.
  2. The ``clip`` package: used when ``reference_similarity_model`` is a ``.pt``
     file, which is read without downloading.

There is no fallback that works without a model; ``get()`` returns ``None``
and the caller picks at random.
"""

from __future__ import annotations

from collections import OrderedDict
import os
import threading

import numpy as np

from lib.logging_setup import get_logger
from lib.translations import _

logger = get_logger("prompts.reference_similarity")


def _normalized(rows: np.ndarray) -> np.ndarray:
    rows = np.asarray(rows, dtype=np.float32)
    if rows.ndim == 1:
        rows = rows[np.newaxis, :]
    norms = np.linalg.norm(rows, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return rows / norms


def resolve_device(device: str | None) -> str:
    """*device* as configured; ``"auto"`` is CUDA when available, else CPU."""
    device = (device or "cpu").strip().lower()
    if device != "auto":
        return device
    import torch  # noqa: PLC0415
    return "cuda" if torch.cuda.is_available() else "cpu"


class TransformersClipBackend:
    name = "transformers"

    def __init__(self, model_ref: str, device: str) -> None:
        import torch  # noqa: PLC0415
        from transformers import AutoModel, AutoProcessor  # noqa: PLC0415

        self._torch = torch
        self._device = device
        self._model = AutoModel.from_pretrained(model_ref, local_files_only=True).to(device)
        self._model.eval()
        self._processor = AutoProcessor.from_pretrained(model_ref, local_files_only=True)
        # SigLIP was trained on text padded to the full length; shorter
        # padding gives it embeddings it never saw.
        model_type = str(getattr(self._model.config, "model_type", "")).lower()
        self._text_padding = "max_length" if model_type.startswith("siglip") else True

    @staticmethod
    def _features(out, embeds_attr: str) -> np.ndarray:
        # get_*_features returns a tensor in transformers 4.x and a model
        # output carrying the projected features in later versions.
        if not hasattr(out, "detach"):
            features = getattr(out, embeds_attr, None)
            out = features if features is not None else out.pooler_output
        return out.detach().float().cpu().numpy()

    def encode_images(self, images: list) -> np.ndarray:
        inputs = self._processor(images=images, return_tensors="pt").to(self._device)
        with self._torch.no_grad():
            out = self._model.get_image_features(**inputs)
        return self._features(out, "image_embeds")

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        inputs = self._processor(
            text=texts, padding=self._text_padding, truncation=True, return_tensors="pt"
        ).to(self._device)
        with self._torch.no_grad():
            out = self._model.get_text_features(**inputs)
        return self._features(out, "text_embeds")


class ClipPackageBackend:
    name = "clip"

    def __init__(self, model_path: str, device: str) -> None:
        import clip  # noqa: PLC0415
        import torch  # noqa: PLC0415

        self._clip = clip
        self._torch = torch
        self._device = device
        from lib.clip_loader import load_clip_file  # noqa: PLC0415
        self._model, self._preprocess = load_clip_file(clip, torch, model_path, device)
        self._model.eval()

    def encode_images(self, images: list) -> np.ndarray:
        batch = self._torch.stack([self._preprocess(img) for img in images]).to(self._device)
        with self._torch.no_grad():
            return self._model.encode_image(batch).float().cpu().numpy()

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        tokens = self._clip.tokenize(texts, truncate=True).to(self._device)
        with self._torch.no_grad():
            return self._model.encode_text(tokens).float().cpu().numpy()


class ReferenceSimilarityEngine:
    """Scores text options against a reference image.

    One instance per process, built on first use. Embeddings are cached:
    images by path and modification time, texts by the encoded string.
    """

    IMAGE_CACHE_SIZE = 64
    TEXT_CACHE_SIZE = 1024
    DEFAULT_PROMPT_TEMPLATE = "a photo of {0}"

    _instance: "ReferenceSimilarityEngine | None" = None
    _build_failed = False
    _build_lock = threading.Lock()

    def __init__(self, backend, prompt_template: str | None = None) -> None:
        self._backend = backend
        self._prompt_template = prompt_template or self.DEFAULT_PROMPT_TEMPLATE
        self._lock = threading.Lock()
        self._image_cache: OrderedDict = OrderedDict()
        self._text_cache: OrderedDict = OrderedDict()

    @property
    def backend_name(self) -> str:
        return self._backend.name

    @classmethod
    def get(cls) -> "ReferenceSimilarityEngine | None":
        """The shared engine, or ``None`` if no backend could be built.

        A failed build is not retried until ``reset()``, so a missing model
        costs one attempt per process rather than one per image.
        """
        if cls._instance is not None or cls._build_failed:
            return cls._instance
        with cls._build_lock:
            if cls._instance is None and not cls._build_failed:
                from sd_runner.config import config  # noqa: PLC0415
                try:
                    backend = cls._build_backend(
                        getattr(config, "reference_similarity_model", None),
                        resolve_device(getattr(config, "reference_similarity_device", None)),
                    )
                    cls._instance = cls(
                        backend, getattr(config, "reference_similarity_prompt_template", None)
                    )
                    logger.info(_("Reference similarity: using the {0} backend").format(backend.name))
                except Exception as e:
                    cls._build_failed = True
                    logger.warning(_(
                        "Reference similarity is unavailable, so [[~...]] choice sets "
                        "are resolved at random: {0}"
                    ).format(e))
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Drop the shared engine so the next ``get()`` rebuilds it from config."""
        with cls._build_lock:
            cls._instance = None
            cls._build_failed = False

    @staticmethod
    def _build_backend(model_ref: str | None, device: str):
        if not model_ref:
            raise ValueError(_("reference_similarity_model is not set"))
        if model_ref.lower().endswith(".pt") and os.path.isfile(model_ref):
            return ClipPackageBackend(model_ref, device)
        return TransformersClipBackend(model_ref, device)

    def _prompt_text(self, option: str) -> str:
        try:
            return self._prompt_template.format(option)
        except (IndexError, KeyError, ValueError):
            return option

    @staticmethod
    def _cache_put(cache: OrderedDict, key, value, limit: int) -> None:
        cache[key] = value
        cache.move_to_end(key)
        while len(cache) > limit:
            cache.popitem(last=False)

    def image_embedding(self, path: str) -> np.ndarray | None:
        """Normalized embedding of the image at *path*, or ``None`` if unreadable."""
        try:
            key = (os.path.abspath(path), os.stat(path).st_mtime_ns)
        except OSError as e:
            logger.warning(_("Reference similarity: cannot read image {0}: {1}").format(path, e))
            return None
        with self._lock:
            cached = self._image_cache.get(key)
            if cached is not None:
                self._image_cache.move_to_end(key)
                return cached
            try:
                from PIL import Image  # noqa: PLC0415
                from lib.image_converter import convert_image_if_needed  # noqa: PLC0415
                from lib.pillow_plugins import ensure_pillow_plugins_registered  # noqa: PLC0415
                ensure_pillow_plugins_registered()
                # Formats Pillow cannot open (video, PDF, SVG, RAW) are read
                # through the converter the generation itself uses.
                with Image.open(convert_image_if_needed(path) or path) as img:
                    rgb = img.convert("RGB")
                embedding = _normalized(self._backend.encode_images([rgb]))[0]
            except Exception as e:
                logger.warning(_("Reference similarity: cannot read image {0}: {1}").format(path, e))
                return None
            self._cache_put(self._image_cache, key, embedding, self.IMAGE_CACHE_SIZE)
            return embedding

    def text_embeddings(self, texts: list[str]) -> np.ndarray:
        """Normalized embeddings of *texts*, one row each, in order."""
        with self._lock:
            missing = [t for t in dict.fromkeys(texts) if t not in self._text_cache]
            if missing:
                encoded = _normalized(self._backend.encode_texts(missing))
                for text, row in zip(missing, encoded):
                    self._cache_put(self._text_cache, text, row, self.TEXT_CACHE_SIZE)
            rows = []
            for text in texts:
                row = self._text_cache.get(text)
                if row is None:
                    # Evicted by this same call: only when texts outnumber the cache.
                    row = _normalized(self._backend.encode_texts([text]))[0]
                rows.append(row)
            return np.stack(rows)

    def best_match(self, image_path: str, options: list[str]) -> tuple[int, list[float]] | None:
        """Index of the option closest to the image, and every option's score.

        On equal scores the first option wins. ``None`` if the image cannot
        be read or there are no options.
        """
        if not options:
            return None
        image = self.image_embedding(image_path)
        if image is None:
            return None
        scores = self.text_embeddings([self._prompt_text(o) for o in options]) @ image
        return int(np.argmax(scores)), [float(s) for s in scores]
