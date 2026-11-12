"""``[[~a,b,c]]`` choice sets, resolved by CLIP similarity to a reference image.

No CLIP model is loaded: the engine is driven by a fake backend that maps each
text and image to a fixed vector.
"""

import numpy as np
import pytest

from sd_runner.prompts import similarity_choices as sc
from sd_runner.prompts.concepts import Concepts
from sd_runner.prompts.prompter import Prompter
from sd_runner.prompts.reference_similarity import ReferenceSimilarityEngine
from sd_runner.prompts.similarity_choices import SimilarityChoice
from sd_runner.models.model_adapters import ControlNet, IPAdapter
from tests.utils import make_prompter


@pytest.fixture(autouse=True)
def stub_dictionary_loading(monkeypatch):
    monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))


AXES = {"woman": 0, "man": 1, "child": 2}


class FakeBackend:
    """Texts and images are one-hot along AXES; an image's axis is set by path."""

    name = "fake"

    def __init__(self, image_axes):
        self.image_axes = image_axes
        self.text_calls = 0
        self.image_calls = 0

    @staticmethod
    def _vec(axis):
        v = np.zeros(len(AXES), dtype=np.float32)
        v[axis] = 1.0
        return v

    def encode_texts(self, texts):
        self.text_calls += 1
        rows = []
        for t in texts:
            word = next((w for w in AXES if t.endswith(" " + w) or t == w), None)
            rows.append(self._vec(AXES[word]) if word else np.full(len(AXES), 0.1, np.float32))
        return np.stack(rows)

    def encode_images(self, images):
        self.image_calls += 1
        return np.stack([self._vec(self.image_axes[img.size[0]]) for img in images])


def write_image(path, width):
    from PIL import Image
    Image.new("RGB", (width, 4)).save(path)
    return str(path)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    # Images are told apart by width: 4 px shows a child, 5 px a man.
    backend = FakeBackend({4: AXES["child"], 5: AXES["man"]})
    eng = ReferenceSimilarityEngine(backend, "a photo of {0}")
    monkeypatch.setattr(ReferenceSimilarityEngine, "get", classmethod(lambda cls: eng))
    eng.child_image = write_image(tmp_path / "child.png", 4)
    eng.man_image = write_image(tmp_path / "man.png", 5)
    return eng


# ---------------------------------------------------------------------------
# Parsing and placeholders
# ---------------------------------------------------------------------------

class TestExtract:
    def test_set_becomes_placeholder(self):
        choices = []
        text = sc.extract_similarity_sets("a [[~woman,man,child]] in a park", choices)
        assert text == "a " + sc.PLACEHOLDER.format(0) + " in a park"
        assert choices == [SimilarityChoice("[[~woman,man,child]]", ["woman", "man", "child"])]

    def test_weights_are_dropped_without_error(self):
        choices = []
        sc.extract_similarity_sets("[[~woman:2,man]]", choices)
        assert choices[0].options == ["woman", "man"]

    def test_nested_groups_are_flattened(self):
        choices = []
        sc.extract_similarity_sets("[[~[red,blue] car,bike]]", choices)
        assert choices[0].options == ["red car", "blue car", "bike"]

    def test_normal_choice_set_untouched(self):
        choices = []
        assert sc.extract_similarity_sets("[[a,b]] [[~c,d]]", choices).startswith("[[a,b]] ")
        assert len(choices) == 1

    def test_range_loses_marker(self):
        choices = []
        assert sc.extract_similarity_sets("[[~1--5]]", choices) == "[[1--5]]"
        assert choices == []

    def test_same_set_shares_index(self):
        choices = []
        text = sc.extract_similarity_sets("[[~a,b]] and [[~a,b]]", choices)
        assert text == sc.PLACEHOLDER.format(0) + " and " + sc.PLACEHOLDER.format(0)
        assert len(choices) == 1

    def test_restore_puts_source_back(self):
        choices = []
        text = sc.extract_similarity_sets("x, [[~a,b]], y", choices)
        assert sc.restore_similarity_sets(text, choices) == "x, [[~a,b]], y"


class TestApplyChoicesSkipsSimilaritySets:
    def test_left_as_written(self):
        assert Prompter.apply_choices("[[~a,b]] and [[c]]") == "[[~a,b]] and c"

    def test_inline_var_keeps_set(self):
        inline_vars, _rest = Prompter.extract_inline_vars("::Who = [[~woman,man]]\nphoto of $$Who")
        assert inline_vars["who"] == "[[~woman,man]]"


class TestGeneratePrompt:
    def test_placeholder_survives_and_options_recorded(self):
        p = make_prompter()
        pos, _neg = p.generate_prompt(positive="photo, [[~woman,man,child]], park")
        assert sc.PLACEHOLDER.format(0) in pos
        assert "[[" not in pos
        assert p.last_similarity_choices[0].options == ["woman", "man", "child"]

    def test_positive_tags_already_present_not_duplicated(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "[[~woman,man]], ")
        p = make_prompter()
        pos, _neg = p.generate_prompt(positive="[[~woman,man]], sunset")
        assert pos.count(sc.PLACEHOLDER.format(0)) == 1

    def test_set_in_positive_tags_survives_sparse_mix(self, monkeypatch):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "[[~woman,man,child]], masterpiece")
        p = make_prompter(sparse_mixed_tags=True)
        for _i in range(10):
            pos, _neg = p.generate_prompt(positive="sunset")
            assert "[[" not in pos and "~woman" not in pos
            assert p.last_similarity_choices[0].options == ["woman", "man", "child"]

    @pytest.mark.parametrize("negative", ["", "ugly"])
    def test_sparse_mix_keeps_all_negative_tags(self, monkeypatch, negative):
        monkeypatch.setattr(Prompter, "POSITIVE_TAGS", "masterpiece, best quality, sharp")
        monkeypatch.setattr(Prompter, "NEGATIVE_TAGS", "blurry, lowres, watermark")
        p = make_prompter(sparse_mixed_tags=True)
        for _i in range(10):
            _pos, neg = p.generate_prompt(positive="sunset", negative=negative)
            assert negative in neg
            assert all(t in neg for t in ("blurry", "lowres", "watermark"))
            assert not any(t in neg for t in ("masterpiece", "best quality", "sharp"))

    def test_blacklisted_option_dropped(self, monkeypatch):
        from sd_runner.prompts.blacklist import Blacklist

        def fake_filter(concepts, **_kw):
            return [c for c in concepts if c != "man"], ({"man": "x"} if "man" in concepts else {})

        p = make_prompter()
        pos, _neg = p.generate_prompt(positive="[[~woman,man,child]]")
        monkeypatch.setattr(Blacklist, "filter_concepts", staticmethod(fake_filter))
        p._filter_similarity_options(p.last_similarity_choices)
        assert p.last_similarity_choices[0].options == ["woman", "child"]


class TestConceptTemplateTexts:
    def test_marker_stripped(self):
        from sd_runner.prompts.concepts import _template_texts
        texts = _template_texts("[[~woman,man]] portrait")
        assert "woman portrait" in texts and "man portrait" in texts


# ---------------------------------------------------------------------------
# Reference image and resolution
# ---------------------------------------------------------------------------

class TestReferenceImagePath:
    def test_ip_adapter_first(self):
        assert sc.reference_image_path(IPAdapter("/a.png"), ControlNet("/b.png"), "/c.png") == "/a.png"

    def test_control_net_second(self):
        assert sc.reference_image_path(None, ControlNet("/b.png"), "/c.png") == "/b.png"

    def test_prompt_image_last(self):
        assert sc.reference_image_path(None, None, "/c.png") == "/c.png"

    def test_none(self):
        assert sc.reference_image_path(None, None, "") is None


class TestResolve:
    def test_picks_most_similar(self, engine):
        choices = [SimilarityChoice("[[~woman,man,child]]", ["woman", "man", "child"])]
        pos, _neg = sc.resolve_prompts(sc.PLACEHOLDER.format(0), "", choices,
                                       engine.child_image, lambda r: None)
        assert pos == "child"

    def test_same_placeholder_same_pick_in_both_prompts(self, engine):
        choices = [SimilarityChoice("[[~woman,man,child]]", ["woman", "man", "child"])]
        ph = sc.PLACEHOLDER.format(0)
        pos, neg = sc.resolve_prompts(ph, ph, choices, engine.man_image, lambda r: None)
        assert pos == neg == "man"

    def test_no_image_falls_back(self, engine):
        reasons = []
        choices = [SimilarityChoice("s", ["woman", "man"])]
        pos, _neg = sc.resolve_prompts(sc.PLACEHOLDER.format(0), "", choices, None, reasons.append)
        assert pos in ("woman", "man") and len(reasons) == 1

    def test_no_engine_falls_back(self, monkeypatch, tmp_path):
        monkeypatch.setattr(ReferenceSimilarityEngine, "get", classmethod(lambda cls: None))
        reasons = []
        choices = [SimilarityChoice("s", ["woman", "man"])]
        pos, _neg = sc.resolve_prompts(sc.PLACEHOLDER.format(0), "", choices,
                                       str(tmp_path / "x.png"), reasons.append)
        assert pos in ("woman", "man") and reasons

    def test_empty_options_removed(self, engine):
        pos, _neg = sc.resolve_prompts("a " + sc.PLACEHOLDER.format(0), "",
                                       [SimilarityChoice("s", [])], engine.man_image, lambda r: None)
        assert pos == "a "


class TestEngine:
    def test_embeddings_cached(self, engine):
        engine.best_match(engine.child_image, ["woman", "child"])
        engine.best_match(engine.child_image, ["woman", "child"])
        assert engine._backend.image_calls == 1
        assert engine._backend.text_calls == 1

    def test_unreadable_image(self, engine, tmp_path):
        assert engine.best_match(str(tmp_path / "missing.png"), ["woman"]) is None

    def test_tie_goes_to_first(self, engine):
        index, _scores = engine.best_match(engine.child_image, ["child", "child"])
        assert index == 0

    def test_device_passed_through(self):
        from sd_runner.prompts.reference_similarity import resolve_device
        assert resolve_device(None) == "cpu"
        assert resolve_device(" CUDA ") == "cuda"

    def test_failed_build_not_retried(self, monkeypatch):
        calls = []

        def failing(*_a):
            calls.append(1)
            raise RuntimeError("no model")

        monkeypatch.setattr(ReferenceSimilarityEngine, "_build_backend", staticmethod(failing))
        assert ReferenceSimilarityEngine.get() is None
        assert ReferenceSimilarityEngine.get() is None
        assert len(calls) == 1


# ---------------------------------------------------------------------------
# Generator: one resolution per iteration
# ---------------------------------------------------------------------------

class TestGeneratorResolution:
    def _generator(self):
        from tests.unit.test_intermediate_pass import StubGenerator
        from tests.utils import make_gen_config
        gen_config = make_gen_config()
        gen_config.similarity_choices = [
            SimilarityChoice("[[~woman,man,child]]", ["woman", "man", "child"])
        ]
        return StubGenerator(gen_config)

    def test_each_adapter_gets_its_own_option(self, engine):
        gen = self._generator()
        ph = sc.PLACEHOLDER.format(0)
        pos_child, _ = gen.resolve_similarity_choices(ph, "", None, IPAdapter(engine.child_image))
        pos_man, _ = gen.resolve_similarity_choices(ph, "", None, IPAdapter(engine.man_image))
        assert (pos_child, pos_man) == ("child", "man")

    def test_set_in_adapter_modifiers(self, engine):
        gen = self._generator()
        gen.gen_config.similarity_choices = []
        pos, _ = gen.resolve_similarity_choices("x, [[~woman,child]]", "", None,
                                                IPAdapter(engine.child_image))
        assert pos == "x, child"

    def test_fallback_warns_once(self, monkeypatch):
        gen = self._generator()
        gen._warned_similarity_fallback = False
        warnings = []
        monkeypatch.setattr("sd_runner.generators.base.logger.warning", warnings.append)
        ph = sc.PLACEHOLDER.format(0)
        gen.resolve_similarity_choices(ph, "", None, None)
        gen.resolve_similarity_choices(ph, "", None, None)
        assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class TestConfig:
    def test_keys_saved_and_blank_model_turns_comparison_off(self):
        import sd_runner.config as cfg_module
        c = cfg_module.config
        errors = c.apply_and_persist({
            "reference_similarity_model": "  ",
            "reference_similarity_prompt_template": " a picture of {0} ",
            "reference_similarity_device": "auto",
        })
        assert errors == []
        assert c.reference_similarity_model is None
        assert c.reference_similarity_prompt_template == "a picture of {0}"
        assert c.dict["reference_similarity_device"] == "auto"

    def test_keys_loaded_from_config_file(self, tmp_path):
        import json
        from sd_runner.config import Config
        config_path = tmp_path / "configs" / "config.json"
        data = json.loads(config_path.read_text(encoding="utf-8"))
        data["reference_similarity_model"] = "google/siglip-base-patch16-224"
        data["reference_similarity_device"] = "cuda"
        config_path.write_text(json.dumps(data), encoding="utf-8")
        c = Config()
        assert c.reference_similarity_model == "google/siglip-base-patch16-224"
        assert c.reference_similarity_device == "cuda"

    def test_blank_template_uses_default(self):
        eng = ReferenceSimilarityEngine(FakeBackend({}), "")
        assert eng._prompt_text("child") == "a photo of child"
