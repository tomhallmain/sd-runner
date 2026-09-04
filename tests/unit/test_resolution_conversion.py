"""
Tests for the Resolution helpers that translate a resolution into something a
backend can consume: aspect-ratio strings for the cloud APIs, and conversion
between architecture families.

to_aspect_ratio_string is what the cloud generators use to express a resolution
to APIs that take a ratio rather than pixel dimensions, so a wrong mapping is a
silently wrong-size image on every cloud backend.
"""

import pytest

from sd_runner.models.resolution import Resolution
from sd_runner.globals import ArchitectureType, Globals, ResolutionGroup


# Ratios accepted by the Stability AI API, used here as a representative set.
RATIOS = ["16:9", "1:1", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21"]


# ---------------------------------------------------------------------------
# to_aspect_ratio_string
# ---------------------------------------------------------------------------

class TestToAspectRatioString:
    def test_square_maps_to_one_to_one(self):
        assert Resolution(1024, 1024).to_aspect_ratio_string(RATIOS) == "1:1"

    def test_exact_sixteen_nine(self):
        assert Resolution(1920, 1080).to_aspect_ratio_string(RATIOS) == "16:9"

    def test_exact_nine_sixteen(self):
        assert Resolution(1080, 1920).to_aspect_ratio_string(RATIOS) == "9:16"

    def test_landscape_sdxl_picks_landscape_ratio(self):
        # 1216x832 -> 1.462, closest to 3:2 (1.5)
        assert Resolution(1216, 832).to_aspect_ratio_string(RATIOS) == "3:2"

    def test_portrait_sdxl_picks_portrait_ratio(self):
        assert Resolution(832, 1216).to_aspect_ratio_string(RATIOS) == "2:3"

    def test_orientation_is_not_collapsed(self):
        """A resolution and its inverse must not map to the same ratio."""
        landscape = Resolution(1216, 832).to_aspect_ratio_string(RATIOS)
        portrait = Resolution(832, 1216).to_aspect_ratio_string(RATIOS)
        assert landscape != portrait

    def test_extreme_landscape_picks_widest(self):
        assert Resolution(2520, 1080).to_aspect_ratio_string(RATIOS) == "21:9"

    def test_returns_a_member_of_the_input_list(self):
        for w, h in [(512, 512), (768, 512), (512, 768), (1344, 768), (640, 1536)]:
            assert Resolution(w, h).to_aspect_ratio_string(RATIOS) in RATIOS

    def test_single_ratio_list_always_returns_it(self):
        assert Resolution(1920, 1080).to_aspect_ratio_string(["1:1"]) == "1:1"

    def test_empty_ratio_list_raises(self):
        with pytest.raises(ValueError):
            Resolution(1024, 1024).to_aspect_ratio_string([])

    def test_malformed_ratio_raises(self):
        with pytest.raises(ValueError):
            Resolution(1024, 1024).to_aspect_ratio_string(["16-9"])


# ---------------------------------------------------------------------------
# find_matching_aspect_ratio_resolution
# ---------------------------------------------------------------------------

class TestFindMatchingAspectRatioResolution:
    def test_square_target_matches_the_square_preset(self):
        res = Resolution.find_matching_aspect_ratio_resolution(
            ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, 1024, 1024
        )
        assert res is not None
        assert res.aspect_ratio() == 1.0

    def test_returns_none_for_an_unmatched_ratio(self):
        res = Resolution.find_matching_aspect_ratio_resolution(
            ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, 1000, 333
        )
        assert res is None

    def test_match_is_by_ratio_not_by_size(self):
        """A square target of any size matches the square preset."""
        res = Resolution.find_matching_aspect_ratio_resolution(
            ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, 64, 64
        )
        assert res is not None
        assert res.width == res.height


# ---------------------------------------------------------------------------
# get_closest
# ---------------------------------------------------------------------------

class TestGetClosest:
    def test_dimensions_are_multiples_of_round_to(self):
        base = Resolution(1024, 1024)
        res = base.get_closest(
            1000, 333,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        assert res.width % 4 == 0
        assert res.height % 4 == 0

    def test_custom_round_to_respected(self):
        base = Resolution(1024, 1024)
        res = base.get_closest(
            1000, 333, round_to=16,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        assert res.width % 16 == 0
        assert res.height % 16 == 0

    def test_undersized_input_is_scaled_up_into_tolerance(self):
        base = Resolution(1024, 1024)
        lo, hi = Resolution.get_tolerance_range(
            ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        res = base.get_closest(
            100, 33,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        assert res.width * res.height >= lo

    def test_oversized_input_is_scaled_down_into_tolerance(self):
        base = Resolution(1024, 1024)
        lo, hi = Resolution.get_tolerance_range(
            ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR
        )
        res = base.get_closest(
            10000, 3333,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        # Rounding up to the grid can nudge slightly past the ceiling.
        assert res.width * res.height <= hi * 1.05

    def test_matching_ratio_short_circuits_to_a_preset(self):
        base = Resolution(1024, 1024)
        res = base.get_closest(
            2048, 2048,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        assert res.width == res.height

    def test_orientation_is_preserved(self):
        base = Resolution(1024, 1024)
        res = base.get_closest(
            1000, 333,
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        assert res.width > res.height


# ---------------------------------------------------------------------------
# convert_for_model_type / convert_to
# ---------------------------------------------------------------------------

class TestConvertForModelType:
    def test_sd15_sized_input_is_upconverted_for_sdxl(self):
        res = Resolution(512, 512, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR)
        converted = res.convert_for_model_type(ArchitectureType.SDXL)
        assert converted.is_xl()

    def test_xl_sized_input_is_left_alone_for_sdxl(self):
        res = Resolution(1024, 1024, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR)
        assert res.convert_for_model_type(ArchitectureType.SDXL) is res

    def test_xl_sized_input_is_downconverted_for_sd15(self):
        res = Resolution(1216, 832, resolution_group=ResolutionGroup.FIVE_ONE_TWO)
        converted = res.convert_for_model_type(ArchitectureType.SD_15)
        assert not converted.is_xl()

    def test_sd15_sized_input_is_left_alone_for_sd15(self):
        res = Resolution(512, 768, resolution_group=ResolutionGroup.FIVE_ONE_TWO)
        assert res.convert_for_model_type(ArchitectureType.SD_15) is res

    def test_illustrious_conversion_produces_illustrious_dimensions(self):
        res = Resolution(1024, 1024, resolution_group=ResolutionGroup.FIFTEEN_THIRTY_SIX)
        converted = res.convert_for_model_type(ArchitectureType.ILLUSTRIOUS)
        assert converted.is_illustrious()

    def test_illustrious_sized_input_is_left_alone(self):
        res = Resolution(1536, 1536, resolution_group=ResolutionGroup.FIFTEEN_THIRTY_SIX)
        assert res.convert_for_model_type(ArchitectureType.ILLUSTRIOUS) is res

    def test_conversion_roughly_preserves_orientation(self):
        res = Resolution(512, 768, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR)
        converted = res.convert_for_model_type(ArchitectureType.SDXL)
        assert converted.height > converted.width


# ---------------------------------------------------------------------------
# get_closest_to_image — reads dimensions off a file, then delegates to get_closest
# ---------------------------------------------------------------------------

class _FakeExtractor:
    def __init__(self, size):
        self.size = size
        self.asked_for = []

    def get_image_size(self, path):
        self.asked_for.append(path)
        return self.size


@pytest.fixture
def fake_image(monkeypatch):
    """Stub the image data extractor so no real image file is needed."""
    def install(width, height):
        extractor = _FakeExtractor((width, height))
        monkeypatch.setattr(Globals, "get_image_data_extractor", classmethod(lambda cls: extractor))
        return extractor
    return install


class TestGetClosestToImage:
    def test_reads_the_given_path(self, fake_image):
        extractor = fake_image(1216, 832)
        Resolution(1024, 1024).get_closest_to_image("C:/img/ref.png")
        assert extractor.asked_for == ["C:/img/ref.png"]

    def test_returns_a_resolution(self, fake_image):
        fake_image(1216, 832)
        assert isinstance(Resolution(1024, 1024).get_closest_to_image("ref.png"), Resolution)

    def test_matching_ratio_returns_a_preset(self, fake_image):
        """A square source matches the square preset exactly."""
        fake_image(640, 640)
        result = Resolution(1024, 1024).get_closest_to_image("ref.png")
        assert result.width == result.height

    def test_orientation_follows_the_image(self, fake_image):
        fake_image(1000, 333)
        result = Resolution(1024, 1024).get_closest_to_image("ref.png")
        assert result.width > result.height

    def test_portrait_image_gives_portrait_resolution(self, fake_image):
        fake_image(333, 1000)
        result = Resolution(1024, 1024).get_closest_to_image("ref.png")
        assert result.height > result.width

    def test_dimensions_are_rounded(self, fake_image):
        fake_image(1000, 333)
        result = Resolution(1024, 1024).get_closest_to_image("ref.png")
        assert result.width % 4 == 0
        assert result.height % 4 == 0

    def test_custom_round_to_respected(self, fake_image):
        fake_image(1000, 333)
        result = Resolution(1024, 1024).get_closest_to_image("ref.png", round_to=16)
        assert result.width % 16 == 0
        assert result.height % 16 == 0

    def test_uses_the_receivers_resolution_group(self, fake_image):
        fake_image(640, 640)
        base = Resolution(1024, 1024, resolution_group=ResolutionGroup.FIFTEEN_THIRTY_SIX)
        result = base.get_closest_to_image("ref.png")
        assert result.resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX
