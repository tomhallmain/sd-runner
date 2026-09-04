"""
Parsing the SDWebUI ``parameters`` metadata string.

This is the piece that makes redo possible for SDWebUI at all: ComfyUI embeds a
complete API payload in the PNG, while SDWebUI embeds a human-readable summary
that has to be parsed back into values. Everything here is pure text in, values
out -- no file access and no backend.

Real metadata is messy across SDWebUI versions, so the shapes exercised below
are drawn from what the format actually emits rather than one idealised sample.
"""

import pytest

from sd_runner.metadata.a1111 import (
    A1111Parameters,
    extract_loras,
    parse_a1111_parameters,
    resolve_sampler,
    split_settings,
)
from sd_runner.globals import Sampler, Scheduler


TYPICAL = """beautiful woman, red dress, outdoor setting
Negative prompt: ugly, blurry, bad anatomy
Steps: 25, Sampler: DPM++ 2M Karras, CFG scale: 7.0, Seed: 3845129017, Size: 768x512, \
Model hash: 4bdfc29c, Model: realisticVisionV60B1_v60B1VAE, Clip skip: 2, Version: v1.9.4"""


# ---------------------------------------------------------------------------
# split_settings — commas inside quotes and parens belong to their value
# ---------------------------------------------------------------------------

class TestSplitSettings:
    def test_plain_pairs(self):
        assert split_settings("Steps: 25, Seed: 1") == ["Steps: 25", "Seed: 1"]

    def test_empty_string(self):
        assert split_settings("") == []

    def test_trailing_comma_ignored(self):
        assert split_settings("Steps: 25,") == ["Steps: 25"]

    def test_quoted_value_keeps_its_commas(self):
        line = 'Steps: 20, ControlNet 0: "model: canny, weight: 0.85", Model: x'
        parts = split_settings(line)
        assert len(parts) == 3
        assert parts[1] == 'ControlNet 0: "model: canny, weight: 0.85"'

    def test_parenthesised_value_keeps_its_commas(self):
        parts = split_settings("Steps: 20, Range: (0.0, 1.0), Model: x")
        assert parts == ["Steps: 20", "Range: (0.0, 1.0)", "Model: x"]

    def test_quoted_parens_together(self):
        """A real ControlNet block nests both."""
        line = 'Steps: 20, ControlNet 0: "preprocessor: canny, starting/ending: (0.0, 1.0)", Model: x'
        parts = split_settings(line)
        assert len(parts) == 3
        assert parts[1].endswith('(0.0, 1.0)"')


# ---------------------------------------------------------------------------
# Sampler and scheduler names
# ---------------------------------------------------------------------------

class TestResolveSampler:
    @pytest.mark.parametrize("name,expected", [
        ("Euler", Sampler.EULER),
        ("Euler a", Sampler.EULER_ANCESTRAL),
        ("DPM++ 2M", Sampler.DPMPP_2M),
        ("DPM++ 2M SDE", Sampler.DPMPP_2M_SDE),
        ("DPM++ 3M SDE", Sampler.DPMPP_3M_SDE),
        ("DPM++ SDE", Sampler.DPMPP_SDE),
        ("DPM2", Sampler.DPM_2),
        ("DPM2 a", Sampler.DPM_2_ANCESTRAL),
        ("DDIM", Sampler.DDIM),
        ("LCM", Sampler.LCM),
    ])
    def test_known_names(self, name, expected):
        assert resolve_sampler(name)[0] is expected

    def test_case_insensitive(self):
        assert resolve_sampler("euler A")[0] is Sampler.EULER_ANCESTRAL

    def test_scheduler_suffix_is_split_off(self):
        """Older builds fold the scheduler into the sampler name."""
        sampler, scheduler = resolve_sampler("DPM++ 2M Karras")
        assert sampler is Sampler.DPMPP_2M
        assert scheduler is Scheduler.KARRAS

    def test_scheduler_suffix_on_a_compound_name(self):
        sampler, scheduler = resolve_sampler("DPM++ 2M SDE Karras")
        assert sampler is Sampler.DPMPP_2M_SDE
        assert scheduler is Scheduler.KARRAS

    def test_exponential_suffix(self):
        assert resolve_sampler("DPM++ 3M SDE Exponential")[1] is Scheduler.EXPONENTIAL

    def test_no_suffix_leaves_scheduler_unset(self):
        assert resolve_sampler("Euler")[1] is None

    def test_unknown_name_is_not_fatal(self):
        assert resolve_sampler("Restart") == (None, None)

    def test_empty_name(self):
        assert resolve_sampler("") == (None, None)


# ---------------------------------------------------------------------------
# LoRA tags
# ---------------------------------------------------------------------------

class TestExtractLoras:
    def test_tag_with_strength(self):
        assert extract_loras("a cat <lora:detail:0.8>") == [("detail", 0.8)]

    def test_tag_without_strength_defaults_to_one(self):
        assert extract_loras("<lora:detail>") == [("detail", 1.0)]

    def test_multiple_tags(self):
        assert extract_loras("<lora:a:0.5> and <lora:b:1.2>") == [("a", 0.5), ("b", 1.2)]

    def test_no_tags(self):
        assert extract_loras("just a prompt") == []

    def test_empty_prompt(self):
        assert extract_loras("") == []

    def test_case_insensitive_tag(self):
        assert extract_loras("<LoRA:detail:0.8>") == [("detail", 0.8)]


# ---------------------------------------------------------------------------
# Whole-string parsing
# ---------------------------------------------------------------------------

class TestParseTypical:
    @pytest.fixture
    def parsed(self):
        return parse_a1111_parameters(TYPICAL)

    def test_positive_prompt(self, parsed):
        assert parsed.positive == "beautiful woman, red dress, outdoor setting"

    def test_negative_prompt(self, parsed):
        assert parsed.negative == "ugly, blurry, bad anatomy"

    def test_steps(self, parsed):
        assert parsed.steps == 25

    def test_cfg_scale(self, parsed):
        assert parsed.cfg_scale == 7.0

    def test_seed(self, parsed):
        assert parsed.seed == 3845129017

    def test_size_becomes_width_and_height(self, parsed):
        assert (parsed.width, parsed.height) == (768, 512)

    def test_model_name(self, parsed):
        assert parsed.model_name == "realisticVisionV60B1_v60B1VAE"

    def test_model_hash(self, parsed):
        assert parsed.model_hash == "4bdfc29c"

    def test_clip_skip(self, parsed):
        assert parsed.clip_skip == 2

    def test_sampler_and_scheduler(self, parsed):
        assert parsed.sampler is Sampler.DPMPP_2M
        assert parsed.scheduler is Scheduler.KARRAS

    def test_original_sampler_name_is_kept(self, parsed):
        """Useful for diagnostics when the mapping does not recognise a name."""
        assert parsed.sampler_name == "DPM++ 2M Karras"

    def test_unrecognised_keys_are_kept_raw(self, parsed):
        assert parsed.raw_settings.get("Version") == "v1.9.4"

    def test_txt2img_by_default(self, parsed):
        assert parsed.is_img2img() is False

    def test_has_a_usable_prompt(self, parsed):
        assert parsed.has_usable_prompt() is True


class TestParseVariants:
    def test_no_negative_prompt(self):
        parsed = parse_a1111_parameters("a cat\nSteps: 20, Seed: 1")
        assert parsed.positive == "a cat"
        assert parsed.negative == ""

    def test_multiline_positive_prompt(self):
        parsed = parse_a1111_parameters("a cat,\nwearing a hat\nSteps: 20, Seed: 1")
        assert "a cat" in parsed.positive
        assert "wearing a hat" in parsed.positive

    def test_multiline_negative_prompt(self):
        text = "a cat\nNegative prompt: ugly,\nblurry\nSteps: 20, Seed: 1"
        parsed = parse_a1111_parameters(text)
        assert "ugly" in parsed.negative
        assert "blurry" in parsed.negative

    def test_denoising_strength_marks_img2img(self):
        parsed = parse_a1111_parameters("a cat\nSteps: 20, Denoising strength: 0.65")
        assert parsed.denoising_strength == 0.65
        assert parsed.is_img2img() is True

    def test_separate_schedule_type_field(self):
        """Newer builds emit the scheduler separately rather than as a suffix."""
        parsed = parse_a1111_parameters(
            "a cat\nSteps: 20, Sampler: DPM++ 2M, Schedule type: Karras"
        )
        assert parsed.sampler is Sampler.DPMPP_2M
        assert parsed.scheduler is Scheduler.KARRAS

    def test_controlnet_block_is_flagged(self):
        text = ('a cat\nSteps: 20, ControlNet 0: "preprocessor: canny, '
                'weight: 0.85, starting/ending: (0.0, 1.0)", Model: x')
        parsed = parse_a1111_parameters(text)
        assert parsed.has_control_net is True
        assert parsed.model_name == "x"

    def test_loras_are_collected_from_the_prompt(self):
        parsed = parse_a1111_parameters("a cat <lora:detail:0.8>\nSteps: 20")
        assert parsed.loras == [("detail", 0.8)]

    def test_lora_tags_stay_in_the_prompt(self):
        """SDWebUI parses the tags itself, so stripping them would drop the LoRA."""
        parsed = parse_a1111_parameters("a cat <lora:detail:0.8>\nSteps: 20")
        assert "<lora:detail:0.8>" in parsed.positive

    def test_prompt_containing_a_colon_is_not_mistaken_for_settings(self):
        parsed = parse_a1111_parameters("style: painterly, a cat\nSteps: 20, Seed: 1")
        assert "a cat" in parsed.positive
        assert parsed.steps == 20

    def test_colon_prompt_with_no_settings_line_survives(self):
        """Shape alone cannot identify the settings line -- a prompt can look
        just like one, so detection keys on names SDWebUI actually emits."""
        parsed = parse_a1111_parameters("style: painterly, a cat")
        assert parsed.positive == "style: painterly, a cat"

    def test_settings_wrapped_across_lines_are_all_read(self):
        parsed = parse_a1111_parameters(
            "a cat\nSteps: 25, Sampler: Euler,\nSize: 768x512, Model: x"
        )
        assert parsed.positive == "a cat"
        assert parsed.steps == 25
        assert (parsed.width, parsed.height) == (768, 512)
        assert parsed.model_name == "x"


# ---------------------------------------------------------------------------
# Degradation — odd metadata must not abort a run
# ---------------------------------------------------------------------------

class TestDegradesQuietly:
    def test_empty_string(self):
        parsed = parse_a1111_parameters("")
        assert isinstance(parsed, A1111Parameters)
        assert parsed.has_usable_prompt() is False

    def test_none(self):
        assert parse_a1111_parameters(None).has_usable_prompt() is False

    def test_whitespace_only(self):
        assert parse_a1111_parameters("   \n  ").has_usable_prompt() is False

    def test_prompt_with_no_settings_line(self):
        parsed = parse_a1111_parameters("just a prompt with no settings")
        assert parsed.positive == "just a prompt with no settings"
        assert parsed.steps is None

    def test_non_numeric_values_become_none(self):
        parsed = parse_a1111_parameters("a cat\nSteps: many, CFG scale: high, Seed: none")
        assert parsed.steps is None
        assert parsed.cfg_scale is None
        assert parsed.seed is None

    def test_malformed_size_leaves_dimensions_unset(self):
        parsed = parse_a1111_parameters("a cat\nSteps: 20, Size: enormous")
        assert parsed.width is None
        assert parsed.height is None

    def test_unknown_sampler_leaves_the_field_unset(self):
        parsed = parse_a1111_parameters("a cat\nSteps: 20, Sampler: Restart")
        assert parsed.sampler is None
        assert parsed.sampler_name == "Restart"

    def test_completely_unrelated_text(self):
        parsed = parse_a1111_parameters("this is not metadata at all")
        assert parsed.steps is None
        assert parsed.has_usable_prompt() is True
