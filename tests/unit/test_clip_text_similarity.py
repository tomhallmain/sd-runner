"""Tests for sd_runner/clip_text_similarity.py and Blacklist similarity integration."""

from __future__ import annotations

import importlib
import os
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from sd_runner.prompts.clip_text_similarity import NGramBackend, TextSimilarityEngine
from sd_runner.prompts.blacklist import Blacklist, SimilarityPhrase


# ---------------------------------------------------------------------------
# Integration-test skip helpers
#
# Set these env vars to opt-in to backend integration tests:
#   SD_RUNNER_TEST_CLIP_ONNX_MODEL  — absolute path to a CLIP text encoder
#                                     exported as .onnx
#   SD_RUNNER_TEST_CLIP_TORCH_MODEL — CLIP model name or path accepted by
#                                     clip.load(), e.g. "ViT-B/32"
# ---------------------------------------------------------------------------

def _importable(name: str) -> bool:
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


_ONNX_MODEL_ENV = "SD_RUNNER_TEST_CLIP_ONNX_MODEL"
_TORCH_MODEL_ENV = "SD_RUNNER_TEST_CLIP_TORCH_MODEL"


def _onnx_model_path() -> str:
    return os.environ.get(_ONNX_MODEL_ENV, "")


def _torch_model_name() -> str:
    return os.environ.get(_TORCH_MODEL_ENV, "")


def _has_onnx_tokenizer() -> bool:
    return _importable("clip") or _importable("transformers")


_skip_onnx = pytest.mark.skipif(
    not _importable("onnxruntime")
    or not _has_onnx_tokenizer()
    or not os.path.isfile(_onnx_model_path()),
    reason=(
        "ONNX CLIP integration test requires: onnxruntime, a tokenizer "
        "(pip install clip or transformers), and "
        f"{_ONNX_MODEL_ENV}=<path to .onnx text-encoder file>"
    ),
)

_skip_torch = pytest.mark.skipif(
    not _importable("clip")
    or not _importable("torch")
    or not _torch_model_name(),
    reason=(
        "Torch CLIP integration test requires: clip, torch, and "
        f"{_TORCH_MODEL_ENV}=<model name or path, e.g. ViT-B/32>"
    ),
)


# ---------------------------------------------------------------------------
# SimilarityPhrase — unit tests
# ---------------------------------------------------------------------------

class TestSimilarityPhrase:
    def test_defaults_to_enabled(self):
        item = SimilarityPhrase("violent content")
        assert item.enabled is True

    def test_disabled_flag_stored(self):
        item = SimilarityPhrase("violent content", enabled=False)
        assert item.enabled is False

    def test_to_dict_roundtrip(self):
        item = SimilarityPhrase("test phrase", enabled=False)
        d = item.to_dict()
        assert d == {"phrase": "test phrase", "enabled": False}

    def test_from_dict_restores_enabled_false(self):
        item = SimilarityPhrase.from_dict({"phrase": "test phrase", "enabled": False})
        assert item.phrase == "test phrase"
        assert item.enabled is False

    def test_from_dict_backward_compat_plain_string(self):
        item = SimilarityPhrase.from_dict("  violent content  ")
        assert item.phrase == "violent content"
        assert item.enabled is True

    def test_from_dict_blank_string_returns_none(self):
        assert SimilarityPhrase.from_dict("   ") is None

    def test_from_dict_non_bool_enabled_defaults_true(self):
        item = SimilarityPhrase.from_dict({"phrase": "test", "enabled": "yes"})
        assert item.enabled is True

    def test_from_dict_missing_phrase_returns_none(self):
        assert SimilarityPhrase.from_dict({"enabled": True}) is None

    def test_from_dict_invalid_type_returns_none(self):
        assert SimilarityPhrase.from_dict(42) is None


# ---------------------------------------------------------------------------
# NGramBackend — unit tests
# ---------------------------------------------------------------------------

class TestNGramBackend:
    def test_identical_string_scores_one(self):
        b = NGramBackend()
        b.precompute(["bad content"])
        score, phrase = b.max_similarity("bad content")
        assert score == pytest.approx(1.0, abs=1e-5)
        assert phrase == "bad content"

    def test_dissimilar_string_scores_low(self):
        b = NGramBackend()
        b.precompute(["explicit violence"])
        score, _ = b.max_similarity("fluffy bunny rabbit")
        assert score < 0.30

    def test_similar_misspelling_scores_higher_than_unrelated(self):
        b = NGramBackend()
        b.precompute(["violence"])
        score_misspelled, _ = b.max_similarity("v1olence")
        score_unrelated, _ = b.max_similarity("rainbow butterfly")
        assert score_misspelled > score_unrelated

    def test_returns_best_matching_phrase(self):
        b = NGramBackend()
        b.precompute(["apple pie", "violent content"])
        score, phrase = b.max_similarity("violent content here")
        assert phrase == "violent content"
        assert score > 0.5

    def test_empty_phrases_returns_zero(self):
        b = NGramBackend()
        b.precompute([])
        score, phrase = b.max_similarity("anything")
        assert score == 0.0
        assert phrase is None

    def test_empty_query_returns_zero(self):
        b = NGramBackend()
        b.precompute(["something"])
        score, phrase = b.max_similarity("")
        assert score == 0.0
        assert phrase is None

    def test_single_char_query_returns_zero(self):
        b = NGramBackend()
        b.precompute(["abc"])
        # A single character produces no trigrams or 4-grams.
        score, _ = b.max_similarity("a")
        assert score == 0.0

    def test_case_insensitive(self):
        b = NGramBackend()
        b.precompute(["VIOLENT"])
        score_lower, _ = b.max_similarity("violent")
        score_upper, _ = b.max_similarity("VIOLENT")
        assert score_lower == pytest.approx(score_upper, abs=1e-5)

    def test_multiple_precompute_calls_reset_state(self):
        b = NGramBackend()
        b.precompute(["first phrase"])
        b.precompute(["second phrase"])
        _, phrase = b.max_similarity("second phrase")
        assert phrase == "second phrase"

    def test_scores_in_unit_range(self):
        b = NGramBackend()
        b.precompute(["test reference phrase"])
        for text in ["test", "reference", "completely different", "xyz123"]:
            score, _ = b.max_similarity(text)
            assert 0.0 <= score <= 1.0 + 1e-6

    def test_custom_n_sizes(self):
        b = NGramBackend(n_sizes=(2,))
        b.precompute(["ab"])
        score, _ = b.max_similarity("ab")
        assert score == pytest.approx(1.0, abs=1e-5)

    def test_backend_name(self):
        assert NGramBackend().name == "ngram"


# ---------------------------------------------------------------------------
# TextSimilarityEngine — build() and facade
# ---------------------------------------------------------------------------

class TestTextSimilarityEngineBuild:
    def test_build_no_path_returns_ngram(self):
        engine = TextSimilarityEngine.build(None)
        assert engine.backend_name == "ngram"

    def test_build_empty_string_returns_ngram(self):
        engine = TextSimilarityEngine.build("")
        assert engine.backend_name == "ngram"

    def test_build_onnx_path_falls_back_to_ngram_when_ort_missing(self):
        with patch.dict("sys.modules", {"onnxruntime": None}):
            engine = TextSimilarityEngine.build("model.onnx")
        assert engine.backend_name == "ngram"

    def test_build_torch_path_falls_back_to_ngram_when_clip_missing(self):
        with patch.dict("sys.modules", {"clip": None, "torch": None}):
            engine = TextSimilarityEngine.build("/some/clip_model")
        assert engine.backend_name == "ngram"

    def test_facade_delegates_precompute_and_max_similarity(self):
        mock_backend = MagicMock()
        mock_backend.name = "mock"
        mock_backend.max_similarity.return_value = (0.9, "test phrase")
        engine = TextSimilarityEngine(mock_backend)
        engine.precompute(["test phrase"])
        mock_backend.precompute.assert_called_once_with(["test phrase"])
        score, phrase = engine.max_similarity("something")
        mock_backend.max_similarity.assert_called_once_with("something")
        assert score == pytest.approx(0.9)
        assert phrase == "test phrase"

    def test_backend_name_property(self):
        engine = TextSimilarityEngine.build(None)
        assert engine.backend_name == "ngram"


# ---------------------------------------------------------------------------
# Blacklist similarity integration
# ---------------------------------------------------------------------------

class TestBlacklistSimilarity:
    def test_disabled_by_default(self):
        assert Blacklist.get_similarity_enabled() is False

    def test_check_similarity_disabled_returns_false(self):
        Blacklist.set_similarity_enabled(False)
        Blacklist.set_similarity_phrases(["violent content"])
        violated, score, phrase = Blacklist.check_similarity("violent content")
        assert violated is False
        assert score == 0.0
        assert phrase == ""

    def test_check_similarity_no_phrases_returns_false(self):
        Blacklist.set_similarity_enabled(True)
        Blacklist.set_similarity_phrases([])
        violated, score, phrase = Blacklist.check_similarity("violent content")
        assert violated is False
        assert score == 0.0

    def test_check_similarity_exact_match_violates(self):
        Blacklist.set_similarity_threshold(0.85)
        Blacklist.set_similarity_enabled(True)
        Blacklist.set_similarity_phrases(["violent content"])
        violated, score, phrase = Blacklist.check_similarity("violent content")
        assert violated is True
        assert score == pytest.approx(1.0, abs=1e-5)
        assert phrase == "violent content"

    def test_check_similarity_unrelated_does_not_violate(self):
        Blacklist.set_similarity_threshold(0.85)
        Blacklist.set_similarity_enabled(True)
        Blacklist.set_similarity_phrases(["violent content"])
        violated, score, _ = Blacklist.check_similarity("fluffy bunny sunshine")
        assert violated is False
        assert score < 0.85

    def test_threshold_setter_clamps_to_range(self):
        Blacklist.set_similarity_threshold(2.5)
        assert Blacklist.get_similarity_threshold() == pytest.approx(1.0)
        Blacklist.set_similarity_threshold(-0.1)
        assert Blacklist.get_similarity_threshold() == pytest.approx(0.0)

    def test_set_phrases_strips_whitespace_and_blanks(self):
        Blacklist.set_similarity_phrases(["  hello  ", "", "   ", "world"])
        assert Blacklist.get_similarity_phrases() == ["hello", "world"]

    def test_rebuild_engine_clears_engine_when_phrases_empty(self):
        Blacklist.set_similarity_phrases(["something"])
        assert Blacklist._similarity_engine is not None
        Blacklist.set_similarity_phrases([])
        assert Blacklist._similarity_engine is None

    def test_engine_uses_ngram_by_default(self):
        Blacklist.set_similarity_phrases(["test phrase"])
        assert Blacklist._similarity_engine is not None
        assert Blacklist._similarity_engine.backend_name == "ngram"

    def test_similarity_respects_threshold(self):
        Blacklist.set_similarity_enabled(True)
        Blacklist.set_similarity_phrases(["violent content"])
        Blacklist.set_similarity_threshold(1.0)
        # Only an exact match (score == 1.0) should trigger at max threshold.
        violated_exact, _, _ = Blacklist.check_similarity("violent content")
        violated_partial, _, _ = Blacklist.check_similarity("violent")
        assert violated_exact is True
        assert violated_partial is False

    def test_set_phrase_items_preserves_enabled_state(self):
        items = [
            SimilarityPhrase("active phrase", enabled=True),
            SimilarityPhrase("inactive phrase", enabled=False),
        ]
        Blacklist.set_similarity_phrase_items(items)
        stored = Blacklist.get_similarity_phrase_items()
        assert stored[0].enabled is True
        assert stored[1].enabled is False

    def test_get_similarity_phrases_returns_all_including_disabled(self):
        items = [
            SimilarityPhrase("phrase a", enabled=True),
            SimilarityPhrase("phrase b", enabled=False),
        ]
        Blacklist.set_similarity_phrase_items(items)
        assert Blacklist.get_similarity_phrases() == ["phrase a", "phrase b"]

    def test_disabled_phrase_not_fed_to_engine(self):
        # Engine should only precompute enabled phrases; a disabled exact match
        # should not trigger violation.
        Blacklist.set_similarity_enabled(True)
        Blacklist.set_similarity_threshold(0.85)
        Blacklist.set_similarity_phrase_items([
            SimilarityPhrase("violent content", enabled=False),
        ])
        # Engine should be None (no enabled phrases → no engine).
        assert Blacklist._similarity_engine is None
        violated, score, _ = Blacklist.check_similarity("violent content")
        assert violated is False
        assert score == 0.0

    def test_engine_built_only_for_enabled_phrases(self):
        Blacklist.set_similarity_phrase_items([
            SimilarityPhrase("active", enabled=True),
            SimilarityPhrase("inactive", enabled=False),
        ])
        assert Blacklist._similarity_engine is not None
        # The engine's precomputed phrases should only include "active".
        score_active, phrase = Blacklist._similarity_engine.max_similarity("active")
        assert phrase == "active"
        # "inactive" should not be in the engine at all.
        score_inactive, matched = Blacklist._similarity_engine.max_similarity("inactive")
        assert matched != "inactive" or score_inactive < 0.99


# ---------------------------------------------------------------------------
# ONNX CLIP backend — integration tests (skipped without deps + model file)
# ---------------------------------------------------------------------------

@_skip_onnx
class TestOnnxClipBackendIntegration:
    """Requires onnxruntime, a tokenizer, and SD_RUNNER_TEST_CLIP_ONNX_MODEL."""

    def _backend(self):
        from sd_runner.prompts.clip_text_similarity import OnnxClipBackend
        return OnnxClipBackend(_onnx_model_path())

    def test_backend_name(self):
        assert self._backend().name == "onnx_clip"

    def test_identical_string_scores_near_one(self):
        b = self._backend()
        b.precompute(["violent content"])
        score, phrase = b.max_similarity("violent content")
        assert score == pytest.approx(1.0, abs=0.02)
        assert phrase == "violent content"

    def test_semantically_similar_scores_higher_than_unrelated(self):
        b = self._backend()
        b.precompute(["violent content"])
        score_similar, _ = b.max_similarity("graphic violence")
        score_unrelated, _ = b.max_similarity("fluffy bunny sunshine")
        assert score_similar > score_unrelated

    def test_scores_in_unit_range(self):
        b = self._backend()
        b.precompute(["test reference phrase"])
        for text in ["test", "reference", "completely different", "xyz123"]:
            score, _ = b.max_similarity(text)
            assert 0.0 <= score <= 1.0 + 1e-5

    def test_empty_phrases_returns_zero(self):
        b = self._backend()
        b.precompute([])
        score, phrase = b.max_similarity("anything")
        assert score == 0.0
        assert phrase is None

    def test_returns_best_matching_phrase(self):
        b = self._backend()
        b.precompute(["apple pie", "violent content"])
        _, phrase = b.max_similarity("violent content")
        assert phrase == "violent content"

    def test_engine_build_selects_onnx_backend(self):
        engine = TextSimilarityEngine.build(_onnx_model_path())
        assert engine.backend_name == "onnx_clip"

    def test_engine_max_similarity_via_facade(self):
        engine = TextSimilarityEngine.build(_onnx_model_path())
        engine.precompute(["violent content"])
        score, phrase = engine.max_similarity("violent content")
        assert score == pytest.approx(1.0, abs=0.02)
        assert phrase == "violent content"


# ---------------------------------------------------------------------------
# Torch CLIP backend — integration tests (skipped without deps + model name)
# ---------------------------------------------------------------------------

@_skip_torch
class TestTorchClipBackendIntegration:
    """Requires clip, torch, and SD_RUNNER_TEST_CLIP_TORCH_MODEL."""

    def _backend(self):
        from sd_runner.prompts.clip_text_similarity import TorchClipBackend
        return TorchClipBackend(_torch_model_name())

    def test_backend_name(self):
        assert self._backend().name == "torch_clip"

    def test_identical_string_scores_near_one(self):
        b = self._backend()
        b.precompute(["violent content"])
        score, phrase = b.max_similarity("violent content")
        assert score == pytest.approx(1.0, abs=0.02)
        assert phrase == "violent content"

    def test_semantically_similar_scores_higher_than_unrelated(self):
        b = self._backend()
        b.precompute(["violent content"])
        score_similar, _ = b.max_similarity("graphic violence")
        score_unrelated, _ = b.max_similarity("fluffy bunny sunshine")
        assert score_similar > score_unrelated

    def test_scores_in_unit_range(self):
        b = self._backend()
        b.precompute(["test reference phrase"])
        for text in ["test", "reference", "completely different", "xyz123"]:
            score, _ = b.max_similarity(text)
            assert 0.0 <= score <= 1.0 + 1e-5

    def test_empty_phrases_returns_zero(self):
        b = self._backend()
        b.precompute([])
        score, phrase = b.max_similarity("anything")
        assert score == 0.0
        assert phrase is None

    def test_returns_best_matching_phrase(self):
        b = self._backend()
        b.precompute(["apple pie", "violent content"])
        _, phrase = b.max_similarity("violent content")
        assert phrase == "violent content"

    def test_engine_build_selects_torch_backend(self):
        engine = TextSimilarityEngine.build(_torch_model_name())
        assert engine.backend_name == "torch_clip"

    def test_engine_max_similarity_via_facade(self):
        engine = TextSimilarityEngine.build(_torch_model_name())
        engine.precompute(["violent content"])
        score, phrase = engine.max_similarity("violent content")
        assert score == pytest.approx(1.0, abs=0.02)
        assert phrase == "violent content"
