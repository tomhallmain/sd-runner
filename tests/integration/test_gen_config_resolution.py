"""
Resolution tag strings driven through to a prepared GenConfig.

The unit tests cover Resolution and GenConfig separately with pre-built objects.
This covers the join: the user types "square,portrait2*" in the sidebar, and what
comes out has to be the right pixel dimensions for the model's architecture and
the right generation count. A mistake here is a silently wrong-size image.
"""

import pytest

from sd_runner.models.resolution import Resolution
from tests.utils import make_gen_config, make_model, make_run_config
from utils.globals import ArchitectureType, ResolutionGroup


def resolutions_for(tag_str, architecture_type, resolution_group):
    return Resolution.get_resolutions(
        tag_str,
        architecture_type=architecture_type,
        resolution_group=resolution_group,
    )


def gen_config_for(tag_str, architecture_type, resolution_group, **kwargs):
    model = make_model()
    model.architecture_type = architecture_type
    config = make_gen_config(
        models=[model],
        resolutions=resolutions_for(tag_str, architecture_type, resolution_group),
        **kwargs,
    )
    config.prepare()
    return config


# ---------------------------------------------------------------------------
# Tag string -> resolutions
# ---------------------------------------------------------------------------

class TestTagStringParsing:
    def test_single_tag_gives_one_resolution(self):
        config = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert len(config.resolutions) == 1

    def test_comma_separated_tags_give_one_each(self):
        config = gen_config_for(
            "square,portrait1,landscape1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        assert len(config.resolutions) == 3

    def test_whitespace_around_tags_tolerated(self):
        config = gen_config_for(
            " square , portrait1 ", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        assert len(config.resolutions) == 2

    def test_square_tag_is_square(self):
        config = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].width == config.resolutions[0].height

    def test_portrait_tag_is_taller_than_wide(self):
        config = gen_config_for("portrait1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].height > config.resolutions[0].width

    def test_landscape_tag_is_wider_than_tall(self):
        config = gen_config_for("landscape1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].width > config.resolutions[0].height


# ---------------------------------------------------------------------------
# Architecture drives the pixel dimensions
# ---------------------------------------------------------------------------

class TestArchitectureSpecificDimensions:
    def test_sd15_square_is_sd15_sized(self):
        config = gen_config_for("square", ArchitectureType.SD_15, ResolutionGroup.FIVE_ONE_TWO)
        assert not config.resolutions[0].is_xl()

    def test_sdxl_square_is_xl_sized(self):
        config = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].is_xl()

    def test_illustrious_square_is_illustrious_sized(self):
        config = gen_config_for(
            "square", ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX
        )
        assert config.resolutions[0].is_illustrious()

    def test_sdxl_is_larger_than_sd15_for_the_same_tag(self):
        sd15 = gen_config_for("portrait1", ArchitectureType.SD_15, ResolutionGroup.FIVE_ONE_TWO)
        sdxl = gen_config_for("portrait1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        sd15_pixels = sd15.resolutions[0].width * sd15.resolutions[0].height
        sdxl_pixels = sdxl.resolutions[0].width * sdxl.resolutions[0].height
        assert sdxl_pixels > sd15_pixels

    def test_orientation_survives_the_architecture_change(self):
        for group, architecture in (
            (ResolutionGroup.FIVE_ONE_TWO, ArchitectureType.SD_15),
            (ResolutionGroup.TEN_TWENTY_FOUR, ArchitectureType.SDXL),
            (ResolutionGroup.FIFTEEN_THIRTY_SIX, ArchitectureType.ILLUSTRIOUS),
        ):
            config = gen_config_for("portrait2", architecture, group)
            assert config.resolutions[0].height > config.resolutions[0].width

    def test_resolution_group_is_carried_onto_the_objects(self):
        config = gen_config_for(
            "square", ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX
        )
        assert config.resolutions[0].resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX


# ---------------------------------------------------------------------------
# The '*' random-skip suffix
# ---------------------------------------------------------------------------

class TestRandomSkipSuffix:
    def test_suffix_sets_the_flag(self):
        config = gen_config_for("square*", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].random_skip is True

    def test_absent_suffix_leaves_the_flag_clear(self):
        config = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert config.resolutions[0].random_skip is False

    def test_suffix_applies_per_tag(self):
        config = gen_config_for(
            "square*,portrait1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        assert [r.random_skip for r in config.resolutions] == [True, False]

    def test_suffix_does_not_change_the_dimensions(self):
        plain = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        starred = gen_config_for("square*", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert (plain.resolutions[0].width, plain.resolutions[0].height) == (
            starred.resolutions[0].width, starred.resolutions[0].height
        )

    def test_flagged_resolution_is_sometimes_skipped(self):
        config = gen_config_for("square*", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        results = {config.resolutions[0].should_be_randomly_skipped(0.5) for _ in range(200)}
        assert results == {True, False}

    def test_unflagged_resolution_is_never_skipped(self):
        config = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        assert not any(
            config.resolutions[0].should_be_randomly_skipped(1.0) for _ in range(50)
        )


# ---------------------------------------------------------------------------
# Generation counts derived from the parsed resolutions
# ---------------------------------------------------------------------------

class TestGenerationCounts:
    def test_count_scales_with_the_number_of_tags(self):
        one = gen_config_for("square", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        three = gen_config_for(
            "square,portrait1,landscape1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        assert three.maximum_gens() == 3 * one.maximum_gens()

    def test_count_scales_with_n_latents(self):
        config = gen_config_for(
            "square,portrait1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR,
            n_latents=3,
        )
        assert config.maximum_gens() == 6

    def test_skipped_resolutions_reduce_the_count(self):
        config = gen_config_for(
            "square,portrait1,landscape1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        config.resolutions_skipped = 1
        assert config.maximum_gens(exclude_skipped=True) == 2
        assert config.maximum_gens(exclude_skipped=False) == 3

    def test_prepare_resets_the_skipped_counter(self):
        config = gen_config_for(
            "square,portrait1", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        config.resolutions_skipped = 2
        config.prepare()
        assert config.resolutions_skipped == 0


# ---------------------------------------------------------------------------
# Empty and default tag strings
# ---------------------------------------------------------------------------

class TestDefaults:
    # Deliberately not asserting a count: the fallback is
    # Globals.DEFAULT_RESOLUTION_TAG, which comes from config and is not the
    # behaviour under test here.
    def test_empty_string_falls_back_to_the_default_tag(self):
        assert resolutions_for("", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)

    def test_none_falls_back_to_the_default_tag(self):
        assert resolutions_for(None, ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)

    def test_fallback_produces_a_usable_resolution(self):
        resolution = resolutions_for("", ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)[0]
        assert resolution.width > 0 and resolution.height > 0
