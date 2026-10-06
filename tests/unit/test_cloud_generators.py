"""The workflow interface every cloud generator inherits from ``CloudGenBase``.

Only simple generation is routed, LoRA runs included, and it reaches the
backend's own ``queue_prompt``. Every other workflow raises, naming the backend
the user picked -- ``GrokGen`` subclasses ``OpenAIGen``, so it is the case that
shows the name comes from the class actually in use.
"""

import pytest

from sd_runner.generators.bfl import BFLGen
from sd_runner.generators.fal_ai import FalAIGen
from sd_runner.generators.google_imagen import GoogleImagenGen
from sd_runner.generators.grok import GrokGen
from sd_runner.generators.huggingface import HuggingFaceGen
from sd_runner.generators.ideogram import IdeogramGen
from sd_runner.generators.openai_gen import OpenAIGen
from sd_runner.generators.replicate import ReplicateGen
from sd_runner.generators.stability_ai import StabilityAIGen
from sd_runner.globals import WorkflowType
from tests.utils import make_gen_config

DISPLAY_NAMES = {
    BFLGen: "BFL Flux",
    FalAIGen: "Fal.ai",
    GoogleImagenGen: "Google Imagen",
    GrokGen: "Grok",
    HuggingFaceGen: "HuggingFace",
    IdeogramGen: "Ideogram",
    OpenAIGen: "OpenAI",
    ReplicateGen: "Replicate",
    StabilityAIGen: "Stability AI",
}

UNSUPPORTED = [
    "upscale_simple",
    "control_net",
    "ip_adapter",
    "img2img",
    "instant_lora",
    "redo_with_different_parameter",
]

GEN_CLASSES = list(DISPLAY_NAMES)


def _ids(cls):
    return cls.__name__


@pytest.mark.parametrize("gen_class", GEN_CLASSES, ids=_ids)
def test_only_simple_workflows_are_routed(gen_class):
    gen = gen_class(make_gen_config())
    workflows = gen._get_workflows()
    assert set(workflows) == {WorkflowType.SIMPLE_IMAGE_GEN, WorkflowType.SIMPLE_IMAGE_GEN_LORA}
    assert workflows[WorkflowType.SIMPLE_IMAGE_GEN_LORA] == gen.simple_image_gen


@pytest.mark.parametrize("gen_class", GEN_CLASSES, ids=_ids)
def test_constructs_without_a_config(gen_class):
    assert gen_class().gen_config is not None


@pytest.mark.parametrize("gen_class", GEN_CLASSES, ids=_ids)
@pytest.mark.parametrize("method", UNSUPPORTED)
def test_unsupported_workflow_names_the_backend(gen_class, method):
    gen = gen_class(make_gen_config())
    with pytest.raises(NotImplementedError) as exc:
        getattr(gen, method)()
    assert str(exc.value) == f"{method} is not supported for {DISPLAY_NAMES[gen_class]}"


@pytest.mark.parametrize("gen_class", GEN_CLASSES, ids=_ids)
@pytest.mark.parametrize("method", ["simple_image_gen", "simple_image_gen_lora"])
def test_simple_generation_reaches_queue_prompt(gen_class, method, monkeypatch):
    gen = gen_class(make_gen_config())
    calls = []
    monkeypatch.setattr(gen, "queue_prompt", lambda **kw: calls.append(kw))

    getattr(gen, method)(model="m", resolution="r", n_latents=2, positive=None, negative="bad")

    assert calls == [dict(model="m", resolution="r", n_latents=2, positive="", negative="bad")]
