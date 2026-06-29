"""
Text similarity engine for prompt safety checking.

Backend selection (priority order):
  1. ONNX CLIP  — real semantic embeddings.
                  Requires ``onnxruntime`` and either the ``clip`` package or
                  ``transformers`` (with a locally-cached tokenizer) for
                  tokenization.  Activated when ``clip_model_path`` ends in
                  ``.onnx`` and ``onnxruntime`` is importable.
  2. Torch CLIP — real semantic embeddings via the ``clip`` package + torch.
                  Activated when ``clip_model_path`` is set (no ``.onnx``
                  extension) and both packages are importable.
  3. N-gram     — character n-gram cosine similarity; pure ``numpy``, always
                  available.  Catches character-level evasion (substitutions,
                  spacing tricks) not covered by the regex blacklist, but is
                  not semantically aware.

Call ``TextSimilarityEngine.build(model_path)`` to get the best available
engine.  ``None`` or a missing/broken path always falls back to n-gram.
"""

from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Backends
# ---------------------------------------------------------------------------

class NGramBackend:
    """Character n-gram cosine similarity — pure numpy, no optional deps."""

    def __init__(self, n_sizes: tuple[int, ...] = (3, 4)) -> None:
        self._n_sizes = n_sizes
        self._vocab_idx: dict[str, int] = {}
        self._ref_matrix: np.ndarray | None = None
        self._ref_phrases: list[str] = []

    @staticmethod
    def _ngrams(text: str, n_sizes: tuple[int, ...]) -> set[str]:
        t = text.lower()
        out: set[str] = set()
        for n in n_sizes:
            for i in range(len(t) - n + 1):
                out.add(t[i : i + n])
        return out

    def precompute(self, phrases: list[str]) -> None:
        self._ref_phrases = list(phrases)
        all_ng: set[str] = set()
        for p in phrases:
            all_ng |= self._ngrams(p, self._n_sizes)
        vocab = sorted(all_ng)
        self._vocab_idx = {ng: i for i, ng in enumerate(vocab)}
        n, v = len(phrases), len(vocab)
        if n == 0 or v == 0:
            self._ref_matrix = None
            return
        mat = np.zeros((n, v), dtype=np.float32)
        for i, phrase in enumerate(phrases):
            for ng in self._ngrams(phrase, self._n_sizes):
                j = self._vocab_idx.get(ng)
                if j is not None:
                    mat[i, j] = 1.0
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._ref_matrix = mat / norms

    def max_similarity(self, text: str) -> tuple[float, str | None]:
        if self._ref_matrix is None or not self._ref_phrases:
            return 0.0, None
        q = np.zeros(len(self._vocab_idx), dtype=np.float32)
        for ng in self._ngrams(text, self._n_sizes):
            j = self._vocab_idx.get(ng)
            if j is not None:
                q[j] = 1.0
        norm = float(np.linalg.norm(q))
        if norm == 0.0:
            return 0.0, None
        q /= norm
        sims = self._ref_matrix @ q
        best = int(np.argmax(sims))
        return float(sims[best]), self._ref_phrases[best]

    @property
    def name(self) -> str:
        return "ngram"


class OnnxClipBackend:
    """ONNX Runtime CLIP text encoder.

    Requires ``onnxruntime`` + either ``clip`` or a locally-cached
    ``transformers`` CLIPTokenizer for tokenization.
    """

    def __init__(self, model_path: str) -> None:
        import onnxruntime as ort  # noqa: PLC0415
        self._session = ort.InferenceSession(
            model_path, providers=["CPUExecutionProvider"]
        )
        self._tokenize = self._resolve_tokenizer()
        self._input_name: str = self._session.get_inputs()[0].name
        self._ref_embeddings: np.ndarray | None = None
        self._ref_phrases: list[str] = []

    @staticmethod
    def _resolve_tokenizer():
        # Prefer the dedicated clip package (tiny install, correct BPE).
        try:
            import clip  # noqa: PLC0415

            def _tok_clip(texts: list[str]) -> np.ndarray:
                return clip.tokenize(texts).numpy().astype(np.int32)

            return _tok_clip
        except ImportError:
            pass

        # Fall back to transformers CLIPTokenizer — local cache only so we
        # never trigger a silent HuggingFace download at inference time.
        try:
            from transformers import CLIPTokenizer  # noqa: PLC0415

            tok = CLIPTokenizer.from_pretrained(
                "openai/clip-vit-base-patch32", local_files_only=True
            )

            def _tok_hf(texts: list[str]) -> np.ndarray:
                enc = tok(
                    texts,
                    padding="max_length",
                    max_length=77,
                    truncation=True,
                    return_tensors="np",
                )
                return enc["input_ids"].astype(np.int32)

            return _tok_hf
        except Exception:
            pass

        raise ImportError(
            "ONNX CLIP backend needs a tokenizer.  Install one of:\n"
            "  pip install git+https://github.com/openai/CLIP.git\n"
            "  pip install transformers  (then cache openai/clip-vit-base-patch32)"
        )

    def precompute(self, phrases: list[str]) -> None:
        self._ref_phrases = list(phrases)
        if not phrases:
            self._ref_embeddings = None
            return
        tokens = self._tokenize(phrases)
        emb = self._session.run(None, {self._input_name: tokens})[0]
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._ref_embeddings = (emb / norms).astype(np.float32)

    def max_similarity(self, text: str) -> tuple[float, str | None]:
        if self._ref_embeddings is None or not self._ref_phrases:
            return 0.0, None
        tokens = self._tokenize([text])
        emb = self._session.run(None, {self._input_name: tokens})[0][0]
        norm = float(np.linalg.norm(emb))
        if norm == 0.0:
            return 0.0, None
        emb = emb / norm
        sims = self._ref_embeddings @ emb
        best = int(np.argmax(sims))
        return float(sims[best]), self._ref_phrases[best]

    @property
    def name(self) -> str:
        return "onnx_clip"


class TorchClipBackend:
    """PyTorch CLIP text encoder via the ``clip`` package."""

    def __init__(self, model_name_or_path: str | None = None) -> None:
        import clip  # noqa: PLC0415
        import torch  # noqa: PLC0415

        self._device = "cpu"
        name = model_name_or_path or "ViT-B/32"
        self._model, _ = clip.load(name, device=self._device)
        self._model.eval()
        self._clip = clip
        self._torch = torch
        self._ref_embeddings: np.ndarray | None = None
        self._ref_phrases: list[str] = []

    def precompute(self, phrases: list[str]) -> None:
        self._ref_phrases = list(phrases)
        if not phrases:
            self._ref_embeddings = None
            return
        tokens = self._clip.tokenize(phrases).to(self._device)
        with self._torch.no_grad():
            emb = self._model.encode_text(tokens).float().cpu().numpy()
        norms = np.linalg.norm(emb, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self._ref_embeddings = (emb / norms).astype(np.float32)

    def max_similarity(self, text: str) -> tuple[float, str | None]:
        if self._ref_embeddings is None or not self._ref_phrases:
            return 0.0, None
        token = self._clip.tokenize([text]).to(self._device)
        with self._torch.no_grad():
            emb = self._model.encode_text(token).float().cpu().numpy()[0]
        norm = float(np.linalg.norm(emb))
        if norm == 0.0:
            return 0.0, None
        emb = emb / norm
        sims = self._ref_embeddings @ emb
        best = int(np.argmax(sims))
        return float(sims[best]), self._ref_phrases[best]

    @property
    def name(self) -> str:
        return "torch_clip"


# ---------------------------------------------------------------------------
# Engine facade
# ---------------------------------------------------------------------------

class TextSimilarityEngine:
    """Thin facade over whichever backend was selected at construction time."""

    def __init__(self, backend: NGramBackend | OnnxClipBackend | TorchClipBackend) -> None:
        self._backend = backend

    @property
    def backend_name(self) -> str:
        return self._backend.name

    def precompute(self, phrases: list[str]) -> None:
        """Pre-encode *phrases* so ``max_similarity`` queries are fast."""
        self._backend.precompute(phrases)

    def max_similarity(self, text: str) -> tuple[float, str | None]:
        """Return ``(score, best_matching_phrase)`` — score in ``[0, 1]``."""
        score, phrase = self._backend.max_similarity(text)
        return min(1.0, max(0.0, score)), phrase

    @classmethod
    def build(cls, model_path: str | None = None) -> "TextSimilarityEngine":
        """Return the best available engine for *model_path*.

        *model_path* ending in ``.onnx`` → ONNX backend.
        *model_path* set to anything else → Torch CLIP backend.
        ``None`` or any backend failure → n-gram fallback.
        """
        if model_path:
            if model_path.lower().endswith(".onnx"):
                try:
                    backend: NGramBackend | OnnxClipBackend | TorchClipBackend = OnnxClipBackend(model_path)
                    logger.info("Similarity: using ONNX CLIP backend (%s)", model_path)
                    return cls(backend)
                except Exception as exc:
                    logger.warning(
                        "ONNX CLIP backend unavailable (%s) — falling back to n-gram", exc
                    )
            else:
                try:
                    backend = TorchClipBackend(model_path)
                    logger.info("Similarity: using Torch CLIP backend (%s)", model_path)
                    return cls(backend)
                except Exception as exc:
                    logger.warning(
                        "Torch CLIP backend unavailable (%s) — falling back to n-gram", exc
                    )
        backend = NGramBackend()
        logger.info("Similarity: using n-gram backend")
        return cls(backend)
