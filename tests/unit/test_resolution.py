import math
import random
import unittest

from sd_runner.resolution import Resolution
from utils.globals import ArchitectureType, ResolutionGroup


class TestResolutionScaleHelpers(unittest.TestCase):
    """Unit tests for the static scale-lookup methods."""

    # ── SD 1.5 ────────────────────────────────────────────────────────────────

    def test_get_long_scale_sd15(self):
        self.assertEqual(Resolution.get_long_scale(1), 512)
        self.assertEqual(Resolution.get_long_scale(2), 768)
        self.assertEqual(Resolution.get_long_scale(3), 960)
        self.assertEqual(Resolution.get_long_scale(0), 512)  # scale < 2

    def test_get_short_scale_sd15(self):
        self.assertEqual(Resolution.get_short_scale(1), 704)
        self.assertEqual(Resolution.get_short_scale(2), 640)
        self.assertEqual(Resolution.get_short_scale(3), 512)

    # ── SDXL ──────────────────────────────────────────────────────────────────

    def test_get_xl_long_scale(self):
        self.assertEqual(Resolution.get_xl_long_scale(1), 1152)
        self.assertEqual(Resolution.get_xl_long_scale(2), 1216)
        self.assertEqual(Resolution.get_xl_long_scale(3), 1344)
        self.assertEqual(Resolution.get_xl_long_scale(4), 1536)

    def test_get_xl_short_scale(self):
        self.assertEqual(Resolution.get_xl_short_scale(1), 896)
        self.assertEqual(Resolution.get_xl_short_scale(2), 832)
        self.assertEqual(Resolution.get_xl_short_scale(3), 768)
        self.assertEqual(Resolution.get_xl_short_scale(4), 640)

    # ── Illustrious ───────────────────────────────────────────────────────────

    def test_get_illustrious_long_scale(self):
        self.assertEqual(Resolution.get_illustrious_long_scale(1), 1664)
        self.assertEqual(Resolution.get_illustrious_long_scale(2), 1792)
        self.assertEqual(Resolution.get_illustrious_long_scale(3), 2048)
        self.assertEqual(Resolution.get_illustrious_long_scale(0), 1536)  # default

    def test_get_illustrious_short_scale(self):
        self.assertEqual(Resolution.get_illustrious_short_scale(1), 1344)
        self.assertEqual(Resolution.get_illustrious_short_scale(2), 1216)
        self.assertEqual(Resolution.get_illustrious_short_scale(3), 1152)
        self.assertEqual(Resolution.get_illustrious_short_scale(0), 1536)  # default

    # ── Qwen ──────────────────────────────────────────────────────────────────

    def test_get_qwen_long_scale(self):
        self.assertEqual(Resolution.get_qwen_long_scale(1), 1472)
        self.assertEqual(Resolution.get_qwen_long_scale(2), 1664)
        self.assertEqual(Resolution.get_qwen_long_scale(3), 1792)
        self.assertEqual(Resolution.get_qwen_long_scale(4), 1328)  # default fallback

    def test_get_qwen_short_scale(self):
        self.assertEqual(Resolution.get_qwen_short_scale(1), 1200)
        self.assertEqual(Resolution.get_qwen_short_scale(2), 1072)
        self.assertEqual(Resolution.get_qwen_short_scale(3), 992)
        self.assertEqual(Resolution.get_qwen_short_scale(4), 1328)  # default fallback

    def test_qwen_pixel_counts_are_close(self):
        """Long × short should be within ~1 % of the 1328×1328 square target."""
        target = 1328 * 1328
        for scale in (1, 2, 3):
            pixels = Resolution.get_qwen_long_scale(scale) * Resolution.get_qwen_short_scale(scale)
            self.assertAlmostEqual(pixels / target, 1.0, delta=0.02,
                                   msg=f"Qwen scale={scale} pixel count deviates too far from square target")


class TestRoundInt(unittest.TestCase):
    def test_already_divisible(self):
        self.assertEqual(Resolution.round_int(8, 4), 8)

    def test_rounds_to_nearest_multiple(self):
        result = Resolution.round_int(9, 4)
        self.assertEqual(result % 4, 0)

    def test_default_multiplier_is_4(self):
        result = Resolution.round_int(13)
        self.assertEqual(result % 4, 0)


class TestResolutionClassMethods(unittest.TestCase):
    """Tests for SQUARE / PORTRAIT / LANDSCAPE factory class methods."""

    def _assert_square(self, res: Resolution):
        self.assertEqual(res.width, res.height, "Square resolution must have equal sides")

    def _assert_portrait(self, res: Resolution):
        self.assertGreater(res.height, res.width, "Portrait resolution must be taller than wide")

    def _assert_landscape(self, res: Resolution):
        self.assertGreater(res.width, res.height, "Landscape resolution must be wider than tall")

    # ── SD 1.5 ────────────────────────────────────────────────────────────────

    def test_square_sd15(self):
        res = Resolution.SQUARE(ArchitectureType.SD_15, ResolutionGroup.FIVE_ONE_TWO)
        self._assert_square(res)

    def test_portrait_sd15(self):
        res = Resolution.PORTRAIT(ArchitectureType.SD_15, ResolutionGroup.FIVE_ONE_TWO)
        self._assert_portrait(res)

    def test_landscape_sd15(self):
        res = Resolution.LANDSCAPE(ArchitectureType.SD_15, ResolutionGroup.FIVE_ONE_TWO)
        self._assert_landscape(res)

    # ── SDXL ──────────────────────────────────────────────────────────────────

    def test_square_sdxl(self):
        res = Resolution.SQUARE(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        self._assert_square(res)

    def test_portrait_sdxl(self):
        res = Resolution.PORTRAIT(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        self._assert_portrait(res)

    def test_landscape_sdxl(self):
        res = Resolution.LANDSCAPE(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        self._assert_landscape(res)

    # ── Illustrious ───────────────────────────────────────────────────────────

    def test_square_illustrious(self):
        res = Resolution.SQUARE(ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX)
        self._assert_square(res)

    def test_portrait_illustrious(self):
        res = Resolution.PORTRAIT(ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX)
        self._assert_portrait(res)

    def test_landscape_illustrious(self):
        res = Resolution.LANDSCAPE(ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX)
        self._assert_landscape(res)

    # ── Qwen ──────────────────────────────────────────────────────────────────

    def test_square_qwen(self):
        res = Resolution.SQUARE(ArchitectureType.QWEN, ResolutionGroup.THIRTEEN_TWENTY_EIGHT)
        self._assert_square(res)

    def test_portrait_qwen(self):
        res = Resolution.PORTRAIT(ArchitectureType.QWEN, ResolutionGroup.THIRTEEN_TWENTY_EIGHT)
        self._assert_portrait(res)

    def test_landscape_qwen(self):
        res = Resolution.LANDSCAPE(ArchitectureType.QWEN, ResolutionGroup.THIRTEEN_TWENTY_EIGHT)
        self._assert_landscape(res)

    # ── Landscape is portrait inverted ────────────────────────────────────────

    def test_landscape_is_portrait_inverted(self):
        for arch, group in [
            (ArchitectureType.SD_15,       ResolutionGroup.FIVE_ONE_TWO),
            (ArchitectureType.SDXL,        ResolutionGroup.TEN_TWENTY_FOUR),
            (ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX),
            (ArchitectureType.QWEN,        ResolutionGroup.THIRTEEN_TWENTY_EIGHT),
        ]:
            with self.subTest(arch=arch, group=group):
                p = Resolution.PORTRAIT(arch, group)
                ls = Resolution.LANDSCAPE(arch, group)
                self.assertEqual(p.width, ls.height)
                self.assertEqual(p.height, ls.width)


class TestGetResolution(unittest.TestCase):
    """Tests for Resolution.get_resolution() tag parsing."""

    def test_square_tag(self):
        res = Resolution.get_resolution("square", ArchitectureType.SDXL)
        self.assertEqual(res.width, res.height)

    def test_portrait_tag(self):
        res = Resolution.get_resolution("portrait", ArchitectureType.SDXL)
        self.assertGreater(res.height, res.width)

    def test_landscape_tag(self):
        res = Resolution.get_resolution("landscape", ArchitectureType.SDXL)
        self.assertGreater(res.width, res.height)

    def test_portrait_with_numeric_scale(self):
        res1 = Resolution.get_resolution("portrait1", ArchitectureType.SDXL)
        res2 = Resolution.get_resolution("portrait2", ArchitectureType.SDXL)
        # Different scales should produce different dimensions
        self.assertNotEqual(str(res1), str(res2))

    def test_random_skip_flag_set(self):
        res = Resolution.get_resolution("portrait*", ArchitectureType.SDXL)
        self.assertTrue(res.random_skip)

    def test_no_random_skip_without_asterisk(self):
        res = Resolution.get_resolution("portrait", ArchitectureType.SDXL)
        self.assertFalse(res.random_skip)

    def test_uppercase_tag_is_not_supported_directly(self):
        # get_resolution lowercases internally via get_resolutions; calling directly
        # with uppercase falls through to None because startswith won't match.
        # Verify get_resolutions handles it via .lower().strip()
        resolutions = Resolution.get_resolutions("PORTRAIT", architecture_type=ArchitectureType.SDXL)
        self.assertEqual(len(resolutions), 1)
        self.assertGreater(resolutions[0].height, resolutions[0].width)


class TestGetResolutions(unittest.TestCase):
    """Tests for Resolution.get_resolutions() parsing of comma-separated strings."""

    def test_single_tag(self):
        resolutions = Resolution.get_resolutions("square", architecture_type=ArchitectureType.SDXL)
        self.assertEqual(len(resolutions), 1)

    def test_multiple_tags(self):
        resolutions = Resolution.get_resolutions(
            "square, portrait, landscape", architecture_type=ArchitectureType.SDXL
        )
        self.assertEqual(len(resolutions), 3)

    def test_empty_string_uses_default(self):
        resolutions = Resolution.get_resolutions("", architecture_type=ArchitectureType.SDXL)
        self.assertGreaterEqual(len(resolutions), 1)

    def test_none_uses_default(self):
        resolutions = Resolution.get_resolutions(None, architecture_type=ArchitectureType.SDXL)
        self.assertGreaterEqual(len(resolutions), 1)

    def test_whitespace_stripped(self):
        resolutions = Resolution.get_resolutions(
            "  portrait  ,  landscape  ", architecture_type=ArchitectureType.SDXL
        )
        self.assertEqual(len(resolutions), 2)

    def test_random_skip_preserved_in_list(self):
        resolutions = Resolution.get_resolutions(
            "portrait*, landscape", architecture_type=ArchitectureType.SDXL
        )
        self.assertTrue(resolutions[0].random_skip)
        self.assertFalse(resolutions[1].random_skip)


class TestAspectRatioAndClassification(unittest.TestCase):

    def test_aspect_ratio_square(self):
        res = Resolution(512, 512)
        self.assertAlmostEqual(res.aspect_ratio(), 1.0)

    def test_aspect_ratio_landscape(self):
        res = Resolution(1024, 512)
        self.assertAlmostEqual(res.aspect_ratio(), 2.0)

    def test_is_xl_true(self):
        res = Resolution(1024, 1024)
        self.assertTrue(res.is_xl())

    def test_is_xl_false_for_sd15(self):
        res = Resolution(512, 512)
        self.assertFalse(res.is_xl())

    def test_is_xl_false_at_boundary(self):
        res = Resolution(768, 768)
        self.assertFalse(res.is_xl())  # must be strictly greater

    def test_is_illustrious_square_over_1024(self):
        res = Resolution(1536, 1536)
        self.assertTrue(res.is_illustrious())

    def test_is_illustrious_mixed_one_side_exactly_1024(self):
        res = Resolution(1024, 1216)
        self.assertTrue(res.is_illustrious())

    def test_is_illustrious_false_for_sdxl(self):
        res = Resolution(1024, 1024)
        self.assertFalse(res.is_illustrious())


class TestInvert(unittest.TestCase):

    def test_invert_swaps_dimensions(self):
        res = Resolution(800, 600)
        res.invert()
        self.assertEqual(res.width, 600)
        self.assertEqual(res.height, 800)

    def test_invert_twice_restores_original(self):
        res = Resolution(1216, 832)
        res.invert()
        res.invert()
        self.assertEqual(res.width, 1216)
        self.assertEqual(res.height, 832)

    def test_invert_square_unchanged(self):
        res = Resolution(1024, 1024)
        res.invert()
        self.assertEqual(res.width, 1024)
        self.assertEqual(res.height, 1024)


class TestShouldBeRandomlySkipped(unittest.TestCase):

    def test_no_skip_when_random_skip_false(self):
        res = Resolution(1024, 1024, random_skip=False)
        for _ in range(50):
            self.assertFalse(res.should_be_randomly_skipped(skip_chance=1.0))

    def test_always_skipped_when_chance_is_1(self):
        res = Resolution(1024, 1024, random_skip=True)
        for _ in range(50):
            self.assertTrue(res.should_be_randomly_skipped(skip_chance=1.0))

    def test_never_skipped_when_chance_is_0(self):
        res = Resolution(1024, 1024, random_skip=True)
        for _ in range(50):
            self.assertFalse(res.should_be_randomly_skipped(skip_chance=0.0))

    def test_probabilistic_skip_at_half_chance(self):
        random.seed(42)
        res = Resolution(1024, 1024, random_skip=True)
        results = [res.should_be_randomly_skipped(skip_chance=0.5) for _ in range(1000)]
        skipped = sum(results)
        # Expect roughly 50 % ± 5 %
        self.assertGreater(skipped, 400)
        self.assertLess(skipped, 600)


class TestEqualityAndStr(unittest.TestCase):

    def test_equal_same_dimensions(self):
        self.assertEqual(Resolution(512, 512), Resolution(512, 512))

    def test_not_equal_different_dimensions(self):
        self.assertNotEqual(Resolution(512, 512), Resolution(512, 768))

    def test_not_equal_to_non_resolution(self):
        self.assertNotEqual(Resolution(512, 512), "512x512")

    def test_str_format(self):
        self.assertEqual(str(Resolution(1216, 832)), "1216x832")

    def test_hash_consistent_with_equality(self):
        a = Resolution(1024, 1024)
        b = Resolution(1024, 1024)
        self.assertEqual(hash(a), hash(b))


class TestGetToleranceRange(unittest.TestCase):

    def test_xl_range_has_two_elements(self):
        tr = Resolution.get_tolerance_range(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        self.assertEqual(len(tr), 2)
        self.assertLess(tr[0], tr[1])

    def test_illustrious_range_is_larger_than_xl(self):
        xl_tr = Resolution.get_tolerance_range(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        il_tr = Resolution.get_tolerance_range(ArchitectureType.ILLUSTRIOUS, ResolutionGroup.FIFTEEN_THIRTY_SIX)
        self.assertGreater(il_tr[1], xl_tr[1])

    def test_cached_result_returned_on_second_call(self):
        # Two calls must return the same list instance (class-level cache)
        tr1 = Resolution.get_tolerance_range(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        tr2 = Resolution.get_tolerance_range(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR)
        self.assertIs(tr1, tr2)


class TestUpscaleRounded(unittest.TestCase):

    def test_upscale_produces_larger_dimensions(self):
        res = Resolution(512, 512)
        w, h = res.upscale_rounded(1.5)
        self.assertGreater(w, 512)
        self.assertGreater(h, 512)

    def test_upscale_result_divisible_by_4(self):
        res = Resolution(513, 769)
        w, h = res.upscale_rounded(1.5)
        self.assertEqual(w % 4, 0)
        self.assertEqual(h % 4, 0)


class TestRandomDimensionVariation(unittest.TestCase):

    def test_loose_dimensions_may_miss_multiple_of_four(self):
        """Grid snap is stochastic; repeated draws should occasionally hit integral-only sides."""
        random.seed(0)
        saw_non_four = False
        for _ in range(320):
            r = Resolution.SQUARE(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, scale=2)
            varied = r.with_random_variation(variation_ratio=0.05)
            if (varied.width % 4 != 0) or (varied.height % 4 != 0):
                saw_non_four = True
                break
        self.assertTrue(saw_non_four)

    def test_square_preset_sometimes_independent_axes(self):
        """Square jitter uses independent axes at RANDOM_SQUARE_INDEPENDENT_AXIS_PROBABILITY — widths may differ."""
        random.seed(42)
        saw_unequal = False
        for _ in range(800):
            r = Resolution.SQUARE(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, scale=2)
            varied = r.with_random_variation(variation_ratio=0.05)
            if varied.width != varied.height:
                saw_unequal = True
                break
        self.assertTrue(saw_unequal)

    def test_preserves_aspect_orientation(self):
        random.seed(7)
        res = Resolution.PORTRAIT(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, scale=2)
        varied = res.with_random_variation(variation_ratio=0.03, round_to=16)
        self.assertGreater(varied.height, varied.width)

    def test_stays_within_resolution_group_tolerance(self):
        random.seed(13)
        v_ratio = 0.1
        res = Resolution.LANDSCAPE(ArchitectureType.SDXL, ResolutionGroup.TEN_TWENTY_FOUR, scale=3)
        varied = res.with_random_variation(variation_ratio=v_ratio, round_to=16)
        tr = Resolution.get_tolerance_range(
            architecture_type=ArchitectureType.SDXL,
            resolution_group=ResolutionGroup.TEN_TWENTY_FOUR,
        )
        j_lo, j_hi = Resolution.jitter_tolerance_pixel_extent(tr[0], tr[1], v_ratio)
        pixels = varied.width * varied.height
        self.assertGreaterEqual(pixels, math.floor(j_lo))
        self.assertLessEqual(pixels, math.ceil(j_hi))

    def test_monte_carlo_pixel_band_all_orientations(self):
        """Every draw stays inside jitter_tolerance_pixel_extent (matches sampler script totals)."""
        v_ratio = 0.05
        arch = ArchitectureType.SDXL
        rg = ResolutionGroup.TEN_TWENTY_FOUR
        tr = Resolution.get_tolerance_range(architecture_type=arch, resolution_group=rg)
        j_lo, j_hi = Resolution.jitter_tolerance_pixel_extent(tr[0], tr[1], v_ratio)
        random.seed(123)
        for factory in (
            lambda: Resolution.LANDSCAPE(arch, rg, scale=2),
            lambda: Resolution.SQUARE(arch, rg, scale=2),
            lambda: Resolution.PORTRAIT(arch, rg, scale=2),
        ):
            for _ in range(300):
                base = factory()
                varied = base.with_random_variation(variation_ratio=v_ratio, round_to=16)
                pixels = varied.width * varied.height
                self.assertGreaterEqual(
                    pixels, math.floor(j_lo),
                    msg=f"{base.width}x{base.height} -> {varied.width}x{varied.height}",
                )
                self.assertLessEqual(
                    pixels, math.ceil(j_hi),
                    msg=f"{base.width}x{base.height} -> {varied.width}x{varied.height}",
                )

    def test_landscape_portrait_aspect_stays_near_base(self):
        """Shared axis factor keeps aspect ratio near the preset (quantization slack only)."""
        v_ratio = 0.05
        arch = ArchitectureType.SDXL
        rg = ResolutionGroup.TEN_TWENTY_FOUR
        random.seed(201)
        for factory in (
            lambda: Resolution.LANDSCAPE(arch, rg, scale=2),
            lambda: Resolution.PORTRAIT(arch, rg, scale=2),
        ):
            base = factory()
            ar0 = base.aspect_ratio()
            self.assertGreater(ar0, 0)
            for _ in range(200):
                varied = base.with_random_variation(variation_ratio=v_ratio, round_to=16)
                ar1 = varied.aspect_ratio()
                rel = abs(ar1 - ar0) / ar0
                self.assertLess(rel, 0.03, msg=f"{base.width}x{base.height} -> {varied.width}x{varied.height}")

    def test_square_aspect_deviation_bounded(self):
        """Square jitter may use independent axes; |W/H − 1| stays within a coarse bound."""
        v_ratio = 0.05
        arch = ArchitectureType.SDXL
        rg = ResolutionGroup.TEN_TWENTY_FOUR
        random.seed(37)
        base = Resolution.SQUARE(arch, rg, scale=2)
        for _ in range(600):
            varied = base.with_random_variation(variation_ratio=v_ratio, round_to=16)
            drift = abs(varied.aspect_ratio() - 1.0)
            self.assertLess(drift, 0.145, msg=f"{varied.width}x{varied.height}")

    def test_zero_variation_returns_copy(self):
        res = Resolution(1024, 768, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR)
        varied = res.with_random_variation(variation_ratio=0.0)
        self.assertEqual(varied, res)
        self.assertIsNot(varied, res)


if __name__ == "__main__":
    unittest.main()
