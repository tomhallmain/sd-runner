"""Prompt graph traversal in ImageDataExtractor.extract().

The positive and negative strings are not always sitting on the CLIP node the
sampler points at. The graphs live in tests/fixtures/prompt_graphs.
"""

import json
import tempfile
from pathlib import Path

from PIL import Image
from PIL.PngImagePlugin import PngInfo

from extensions.image_data_extractor import ImageDataExtractor

_PROMPT_GRAPHS = Path(__file__).resolve().parents[1] / "fixtures" / "prompt_graphs"


def _load_prompt(name: str) -> dict:
    return json.loads((_PROMPT_GRAPHS / f"{name}.json").read_text(encoding="utf-8"))


def _make_png_with_prompt(tmp_dir: str, prompt: dict) -> str:
    path = Path(tmp_dir) / "test.png"
    pnginfo = PngInfo()
    pnginfo.add_text("prompt", json.dumps(prompt))
    Image.new("RGB", (8, 8)).save(str(path), pnginfo=pnginfo)
    return str(path)


def _extract(prompt: dict):
    with tempfile.TemporaryDirectory() as tmp:
        path = _make_png_with_prompt(tmp, prompt)
        return ImageDataExtractor().extract(path)


def test_extract_direct_ksampler():
    positive, negative = _extract(_load_prompt("direct_ksampler"))
    assert positive == "a photo of a cat"
    assert negative == "blurry, low quality"


def test_extract_conditioning_via_reference_latent():
    """CFGGuider → ReferenceLatent → CLIPTextEncode chains are resolved correctly."""
    positive, negative = _extract(_load_prompt("reference_latent"))
    assert positive == "positive prompt via reference latent"
    assert negative == "negative prompt via reference latent"


def test_extract_conditioning_via_reference_latent_empty_negative():
    """Empty negative prompt is returned as an empty string, not None."""
    positive, negative = _extract(_load_prompt("reference_latent_empty_negative"))
    assert positive == "detailed scene description"
    assert negative == ""


def test_extract_positive_via_switch_to_primitive_string():
    """LoRA switch off: positive prompt is the primitive string behind the switch."""
    prompt = _load_prompt("krea2_switch")
    positive, negative = _extract(prompt)
    assert positive == prompt["19"]["inputs"]["value"]
    assert negative == "blurry, low quality"


def test_extract_positive_via_switch_to_string_concatenate():
    """LoRA switch on: positive prompt is string_a + delimiter + string_b."""
    prompt = _load_prompt("krea2_switch")
    prompt["23"]["inputs"]["value"] = True
    prompt["27"]["inputs"]["string_b"] = "darkbrush"
    positive, negative = _extract(prompt)
    assert positive == prompt["19"]["inputs"]["value"] + ", darkbrush"
    assert negative == "blurry, low quality"


def test_extract_clip_text_linked_directly_to_primitive_string():
    """A one-hop link from CLIPTextEncode to PrimitiveStringMultiline still resolves."""
    positive, negative = _extract(_load_prompt("primitive_string_link"))
    assert positive == "hello from primitive"
    assert negative == ""


def test_extract_clip_text_via_preview_any_and_switch():
    """PreviewAny forwards ``source``; the switch then selects the primitive string."""
    positive, negative = _extract(_load_prompt("preview_switch"))
    assert positive == "prompt before upsampling"
    assert negative == "negative stays literal"


def test_extract_krea_template_refine_on_uses_user_prompt():
    """Prompt enhancement output is not in the graph; the typed prompt is."""
    prompt = _load_prompt("krea2_template")
    positive, negative = _extract(prompt)
    assert positive == prompt["19"]["inputs"]["value"]
    assert prompt["18"]["inputs"]["value"] not in positive
    assert negative == ""


def test_extract_krea_template_refine_on_with_lora_trigger():
    prompt = _load_prompt("krea2_template")
    prompt["23"]["inputs"]["value"] = True
    prompt["27"]["inputs"]["string_b"] = "rainy window style"
    positive, negative = _extract(prompt)
    assert positive == prompt["19"]["inputs"]["value"] + ", rainy window style"
    assert negative == ""


def test_extract_krea_template_refine_off():
    prompt = _load_prompt("krea2_template")
    prompt["24"]["inputs"]["value"] = False
    positive, negative = _extract(prompt)
    assert positive == prompt["19"]["inputs"]["value"]
    assert negative == ""


def test_empty_selected_switch_branch_does_not_use_the_other_branch():
    """An empty typed prompt stays empty. Only an unstored generator falls back."""
    prompt = _load_prompt("krea2_switch")
    prompt["19"]["inputs"]["value"] = ""
    prompt["27"]["inputs"]["string_b"] = "darkbrush"
    positive, negative = _extract(prompt)
    assert positive == ""
    assert negative == "blurry, low quality"


def test_extract_reference_multi_latent_slots():
    """KSampler positive and negative are two outputs of the same ReferenceMultiLatent node."""
    positive, negative = _extract(_load_prompt("reference_multi_latent"))
    assert positive == "Make the cat into a dragon instead."
    assert negative == ""


def test_extract_reference_multi_latent_negative_echoes_positive_when_unconnected():
    positive, negative = _extract(_load_prompt("reference_multi_latent_positive_only"))
    assert positive == "shared conditioning"
    assert negative == "shared conditioning"
