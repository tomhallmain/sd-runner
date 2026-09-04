"""
Template selection for an SDWebUI redo.

A1111 metadata records *that* img2img or ControlNet was used, and with what
settings, but never the path of the image fed in. So the template a redo starts
from depends both on what the metadata says and on whether the caller can supply
a source image; without one, the request would go out with no init image and be
rejected by the backend.

These cover the decision itself, which is pure logic over parsed metadata. The
surrounding load-and-populate path needs a real PNG and a backend.
"""

import pytest

from sd_runner.metadata.a1111 import parse_a1111_parameters
from sd_runner.workflow_prompts.sdwebui import WorkflowPromptSDWebUI
from sd_runner.globals import PromptTypeSDWebUI


TXT2IMG = "a cat\nSteps: 20, Sampler: Euler, Seed: 1, Size: 512x512, Model: x"
IMG2IMG = TXT2IMG + ", Denoising strength: 0.65"
CONTROLNET = (
    'a cat\nSteps: 20, Sampler: Euler, Seed: 1, Size: 512x512, '
    'ControlNet 0: "preprocessor: canny, weight: 0.85", Model: x'
)
IMG2IMG_CONTROLNET = CONTROLNET + ", Denoising strength: 0.65"


def select(text, has_source_image):
    return WorkflowPromptSDWebUI._select_template(
        parse_a1111_parameters(text), has_source_image
    )


# ---------------------------------------------------------------------------
# What the metadata asks for
# ---------------------------------------------------------------------------

class TestTemplateFromMetadata:
    def test_plain_generation_is_txt2img(self):
        assert parse_a1111_parameters(TXT2IMG).template_filename() == PromptTypeSDWebUI.TXT2IMG.value

    def test_denoising_strength_means_img2img(self):
        assert parse_a1111_parameters(IMG2IMG).template_filename() == PromptTypeSDWebUI.IMG2IMG.value

    def test_controlnet_block_means_controlnet(self):
        assert parse_a1111_parameters(CONTROLNET).template_filename() == PromptTypeSDWebUI.CONTROLNET.value

    def test_both_means_img2img_controlnet(self):
        assert parse_a1111_parameters(IMG2IMG_CONTROLNET).template_filename() == (
            PromptTypeSDWebUI.IMG2IMG_CONTROLNET.value
        )


class TestRequiresSourceImage:
    def test_txt2img_needs_nothing(self):
        assert parse_a1111_parameters(TXT2IMG).requires_source_image() is False

    def test_img2img_needs_a_source(self):
        assert parse_a1111_parameters(IMG2IMG).requires_source_image() is True

    def test_controlnet_needs_a_source(self):
        assert parse_a1111_parameters(CONTROLNET).requires_source_image() is True


# ---------------------------------------------------------------------------
# Selection, which also weighs whether a source image is available
# ---------------------------------------------------------------------------

class TestTemplateSelection:
    def test_txt2img_unaffected_by_source_availability(self):
        assert select(TXT2IMG, False) == PromptTypeSDWebUI.TXT2IMG.value
        assert select(TXT2IMG, True) == PromptTypeSDWebUI.TXT2IMG.value

    def test_img2img_kept_when_a_source_is_available(self):
        assert select(IMG2IMG, True) == PromptTypeSDWebUI.IMG2IMG.value

    def test_img2img_downgraded_without_a_source(self):
        """Sending img2img with no init image would just be rejected."""
        assert select(IMG2IMG, False) == PromptTypeSDWebUI.TXT2IMG.value

    def test_controlnet_kept_when_a_source_is_available(self):
        assert select(CONTROLNET, True) == PromptTypeSDWebUI.CONTROLNET.value

    def test_controlnet_downgraded_without_a_source(self):
        assert select(CONTROLNET, False) == PromptTypeSDWebUI.TXT2IMG.value

    def test_combined_downgraded_without_a_source(self):
        assert select(IMG2IMG_CONTROLNET, False) == PromptTypeSDWebUI.TXT2IMG.value

    def test_downgrade_still_keeps_the_other_settings(self):
        """The point of downgrading rather than refusing: the redo still runs."""
        params = parse_a1111_parameters(IMG2IMG)
        assert params.steps == 20
        assert params.seed == 1
        assert (params.width, params.height) == (512, 512)
        assert select(IMG2IMG, False) == PromptTypeSDWebUI.TXT2IMG.value

    def test_selected_templates_all_exist_on_disk(self):
        """A selected template is loaded immediately, so a bad name is fatal."""
        import os
        for text in (TXT2IMG, IMG2IMG, CONTROLNET, IMG2IMG_CONTROLNET):
            for has_source in (True, False):
                name = select(text, has_source)
                path = os.path.join(WorkflowPromptSDWebUI.PROMPTS_LOC, name)
                assert os.path.isfile(path), f"missing template: {path}"
