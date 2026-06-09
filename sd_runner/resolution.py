
import math
import random
from typing import Optional, TypeVar

from utils.globals import Globals, ArchitectureType, ResolutionGroup
from utils.utils import Utils


class Resolution:
    T = TypeVar('T', bound='Resolution')
    #: When jittering dimensions, snap both sides to multiples of *round_to* this often;
    #: otherwise sides are integers only (may not be multiples of 4 / 16).
    RANDOM_DIMENSION_GRID_SNAP_PROBABILITY = 0.5
    #: For square presets only: use independent width/height scale factors this often; otherwise
    #: one shared factor (output stays square aside from symmetric quantization).
    RANDOM_SQUARE_INDEPENDENT_AXIS_PROBABILITY = 0.5
    TOTAL_PIXELS_TOLERANCE_RANGE = []
    XL_TOTAL_PIXELS_TOLERANCE_RANGE = []
    ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE = []
    QWEN_TOTAL_PIXELS_TOLERANCE_RANGE = []

    def __init__(
        self,
        width: int = Globals.DEFAULT_RESOLUTION_WIDTH,
        height: int = Globals.DEFAULT_RESOLUTION_HEIGHT,
        scale: int = 2,
        random_skip: bool = False,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR,
    ):
        self.width = width
        self.height = height
        self.scale = scale
        self.random_skip = random_skip
        self.resolution_group = resolution_group

    @staticmethod
    def get_resolution(
        resolution_tag: str,
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR
    ) -> T:
        scale_str = Utils.extract_substring(resolution_tag, "[0-9]+")
        scale = int(scale_str) if scale_str and scale_str != "" else 2
        random_skip = "*" in resolution_tag
        resolution_tag = Utils.extract_substring(resolution_tag, "[a-z]+")
        if "square".startswith(resolution_tag):
            return Resolution.SQUARE(architecture_type=architecture_type, resolution_group=resolution_group, scale=scale, random_skip=random_skip)
        elif "portrait".startswith(resolution_tag):
            return Resolution.PORTRAIT(architecture_type=architecture_type, resolution_group=resolution_group, scale=scale, random_skip=random_skip)
        elif "landscape".startswith(resolution_tag):
            return Resolution.LANDSCAPE(architecture_type=architecture_type, resolution_group=resolution_group, scale=scale, random_skip=random_skip)

    @staticmethod
    def get_resolutions(
        resolution_tag_str: str,
        default_tag: str = Globals.DEFAULT_RESOLUTION_TAG,
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR
    ) -> list[T]:
        if resolution_tag_str is None or resolution_tag_str.strip() == "":
            resolution_tag_str = default_tag
        resolution_tags = resolution_tag_str.split(",")
        resolutions = []
        for resolution_tag in resolution_tags:
            resolutions.append(Resolution.get_resolution(resolution_tag.lower().strip(),
                                                         architecture_type=architecture_type,
                                                         resolution_group=resolution_group))
        return resolutions

    @classmethod
    def SQUARE(
        cls,
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR,
        scale: int = 2,
        random_skip: bool = False
    ) -> T:
        resolution = Resolution(scale=scale, random_skip=random_skip, resolution_group=resolution_group)
        resolution.square(architecture_type)
        return resolution

    @classmethod
    def PORTRAIT(
        cls,
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR,
        scale: int = 2,
        random_skip: bool = False
    ) -> T:
        resolution = Resolution(scale=scale, random_skip=random_skip, resolution_group=resolution_group)
        resolution.portrait(architecture_type)
        return resolution

    @classmethod
    def LANDSCAPE(
        cls,
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR,
        scale: int = 2,
        random_skip: bool = False
    ) -> T:
        resolution = Resolution(scale=scale, random_skip=random_skip, resolution_group=resolution_group)
        resolution.landscape(architecture_type)
        return resolution

    @staticmethod
    def get_long_scale(scale: int = 2) -> int:
        if scale < 2:
            return 512
        if scale == 2:
            return 768
        if scale > 2:
            return 960

    @staticmethod
    def get_short_scale(scale: int = 2) -> int:
        if scale == 1:
            return 704
        if scale == 2:
            return 640
        if scale > 2:
            return 512
        return 768

    @staticmethod
    def get_xl_long_scale(scale: int = 2) -> int:
        if scale == 1:
            return 1152
        if scale == 2:
            return 1216
        if scale == 3:
            return 1344
        if scale > 3:
            return 1536
        return 1024

    @staticmethod
    def get_xl_short_scale(scale: int = 2) -> int:
        if scale == 1:
            return 896
        if scale == 2:
            return 832
        if scale == 3:
            return 768
        if scale > 3:
            return 640
        return 1024

    @staticmethod
    def get_qwen_long_scale(scale: int = 2) -> int:
        """
        Qwen-specific long side scale.
        Uses discrete steps similar to XL/Illustrious so that:
          - All non-square scales are larger than the square size (1328),
          - Values increase as scale increases,
          - The final value (default case) converges to the square dimension (1328).
        """
        if scale <= 1:
            return 1472   # 1472x1200 ≈ 1.77M pixels
        if scale == 2:
            return 1664   # 1664x1072 ≈ 1.78M pixels
        if scale == 3:
            return 1792   # 1792x992 ≈ 1.78M pixels
        return 1328       # 1328x1328 = 1,763,584 pixels (square target)

    @staticmethod
    def get_qwen_short_scale(scale: int = 2) -> int:
        """
        Qwen-specific short side scale.
        Paired with get_qwen_long_scale() so that:
          - All non-square scales are smaller than the square size (1328),
          - Values decrease as scale increases,
          - The final value (default case) converges to the square dimension (1328),
          - long * short stays close to 1328x1328 and both sides are multiples of 16.
        """
        if scale <= 1:
            return 1200   # 1472x1200
        if scale == 2:
            return 1072   # 1664x1072
        if scale == 3:
            return 992    # 1792x992
        return 1328       # 1328x1328

    @staticmethod
    def get_illustrious_long_scale(scale: int = 2) -> int:
        if scale == 1:
            return 1664
        elif scale == 2:
            return 1792
        elif scale == 3:
            return 2048
        return 1536

    @staticmethod
    def get_illustrious_short_scale(scale: int = 2) -> int:
        if scale == 1:
            return 1344
        if scale == 2:
            return 1216
        if scale == 3:
            return 1152
        return 1536

    @staticmethod
    def round_int(value: int, multiplier: int = 4) -> int:
        """Prefer a multiple of *multiplier*, using alternating widen-away-from-*value*
        exploration (historical behaviour). Bounded work + fallback so this never spins.
        """
        m = int(multiplier)
        v = int(value)
        if m <= 1:
            return v
        modified_value = v
        try_above = True
        difference = 1
        # Original loop always terminates quickly for valid width/height; cap defensively.
        safeguard = min(m * 256 + 8192, 200_000)
        iterations = 0
        while modified_value % m != 0:
            modified_value = v + difference if try_above else v - difference
            try_above = not try_above
            difference += 1
            iterations += 1
            if iterations >= safeguard:
                if v <= 0:
                    return m
                return ((v + m // 2) // m) * m
        return modified_value

    def upscale_rounded(self, factor: float = 1.5) -> tuple[int, int]:
        width = Resolution.round_int(int(self.width * factor))
        height = Resolution.round_int(int(self.height * factor))
        return width, height

    def copy(self) -> T:
        return Resolution(
            width=self.width,
            height=self.height,
            scale=self.scale,
            random_skip=self.random_skip,
            resolution_group=self.resolution_group,
        )

    @staticmethod
    def _default_architecture_type_for_group(resolution_group: ResolutionGroup) -> ArchitectureType:
        if resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            return ArchitectureType.SDXL
        if resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            return ArchitectureType.ILLUSTRIOUS
        if resolution_group == ResolutionGroup.THIRTEEN_TWENTY_EIGHT:
            return ArchitectureType.QWEN
        return ArchitectureType.SD_15

    @staticmethod
    def jitter_tolerance_pixel_extent(
        min_pixels: int,
        max_pixels: int,
        variation_ratio: float,
    ) -> tuple[float, float]:
        """Pixel-count band that matches uniform geometric scale jitter.

        The discrete preset envelope [min_pixels, max_pixels] is intentionally tight—e.g. for SDXL
        squares the nominal max equals the preset square area, so any scale-up hits the clamp and
        quantizes straight back to the base side length. Stretch the band symmetrically in *area*
        using the same (1 ± variation_ratio)**2 extremes implied by scaling both sides.
        """
        v = max(0.0, min(float(variation_ratio), 0.2))
        loosen_sq = (1.0 + v) ** 2
        lo = float(min_pixels) / loosen_sq
        hi = float(max_pixels) * loosen_sq
        return lo, hi

    def with_random_variation(self, variation_ratio: float = 0.05, round_to: int = 16) -> T:
        """Scale jitter per side with optional grid snap and soft pixel clamp.

        Square presets (:pyattr:`width` == :pyattr:`height`) with probability
        :pyattr:`RANDOM_SQUARE_INDEPENDENT_AXIS_PROBABILITY` draw **independent** scale factors
        for width and height (mild non-square aspect); otherwise they use one shared factor.

        Non-square presets always use one shared scale factor so landscape/portrait orientation is kept.

        With probability :pyattr:`RANDOM_DIMENSION_GRID_SNAP_PROBABILITY`, snaps each side to a
        multiple of *round_to* (normally 16, hence multiples of 4); otherwise rounds to nearest
        integer pixels only (often not divisible by 4).

        Uses bounded arithmetic; pixel clamp may run a short guarded loop when grid
        snap rounds past the soft area band.
        """
        variation_ratio = max(0.0, min(float(variation_ratio), 0.2))
        if variation_ratio == 0:
            return self.copy()

        rt = max(2, min(int(round_to), 4096))
        snap_grid = random.random() < Resolution.RANDOM_DIMENSION_GRID_SNAP_PROBABILITY

        architecture_type = Resolution._default_architecture_type_for_group(self.resolution_group)
        min_pixels, max_pixels = Resolution.get_tolerance_range(
            architecture_type=architecture_type,
            resolution_group=self.resolution_group,
        )

        def _quantize_side(side: float) -> int:
            if snap_grid:
                qi = Resolution.round_int(int(side), multiplier=rt)
                return max(rt, qi)
            return max(rt, int(round(side)))

        lo_f = 1.0 - variation_ratio
        hi_f = 1.0 + variation_ratio
        if self.width == self.height and random.random() < Resolution.RANDOM_SQUARE_INDEPENDENT_AXIS_PROBABILITY:
            factor_w = random.uniform(lo_f, hi_f)
            factor_h = random.uniform(lo_f, hi_f)
        else:
            factor_w = factor_h = random.uniform(lo_f, hi_f)

        wf = float(self.width) * factor_w
        hf = float(self.height) * factor_h

        varied = Resolution(
            width=_quantize_side(wf),
            height=_quantize_side(hf),
            scale=self.scale,
            random_skip=self.random_skip,
            resolution_group=self.resolution_group,
        )

        pixels_area = wf * hf
        if pixels_area <= 0:
            return varied

        j_lo, j_hi = Resolution.jitter_tolerance_pixel_extent(
            min_pixels, max_pixels, variation_ratio
        )
        # Enforce band on quantized pixels: float wf*hf can sit inside the band while integer
        # W×H after snap/round overshoots (e.g. 1024 preset → 1088×1088).
        pix_int = varied.width * varied.height
        if j_lo <= pix_int <= j_hi:
            return varied

        clamped_pf = min(max(float(pix_int), j_lo), j_hi)
        ar_raw = wf / hf if hf != 0 else 1.0
        safeguard = 48
        for _ in range(safeguard):
            wf2 = math.sqrt(max(1.0, clamped_pf * ar_raw))
            hf2 = math.sqrt(max(1.0, clamped_pf / ar_raw))
            varied.width = _quantize_side(wf2)
            varied.height = _quantize_side(hf2)
            pix_int = varied.width * varied.height
            if j_lo <= pix_int <= j_hi:
                return varied
            if pix_int > j_hi:
                clamped_pf *= (float(j_hi) / float(pix_int)) * 0.99995
                continue
            if pix_int < j_lo:
                clamped_pf *= (float(j_lo) / float(pix_int)) * 1.00005
                continue
            break
        return varied

    def is_xl(self) -> bool:
        return self.width > 768 and self.height > 768

    def is_illustrious(self) -> bool:
        return self.width > 1024 and self.height > 1024 or \
            self.height == 1024 and self.width > 1024 or \
            self.width == 1024 and self.height > 1024

    def aspect_ratio(self) -> float:
        return float(self.width) / float(self.height)

    def invert(self) -> None:
        temp = self.width
        self.width = self.height
        self.height = temp

    def convert_for_model_type(self, architecture_type: ArchitectureType) -> T:
        if architecture_type == ArchitectureType.ILLUSTRIOUS:
            if not self.is_illustrious():
                return self.convert_to(architecture_type)
        elif architecture_type == ArchitectureType.SDXL:
            if not self.is_xl():
                return self.convert_to(architecture_type)
        else:
            if self.is_xl():
                return self.convert_to(architecture_type)
        return self

    def convert_to(self, architecture_type: ArchitectureType) -> T:
        return self.get_closest(self.width, self.height, architecture_type=architecture_type, resolution_group=self.resolution_group)

    def square(self, architecture_type: ArchitectureType) -> None:
        if architecture_type == ArchitectureType.SD_15 or self.resolution_group == ResolutionGroup.FIVE_ONE_TWO:
            self.height = Resolution.get_long_scale(self.scale-2)
            self.width = self.height
        elif self.resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            self.height = Resolution.get_illustrious_long_scale(self.scale-2)
            self.width = self.height
        elif self.resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            self.height = Resolution.get_xl_long_scale(self.scale-2)
            self.width = self.height
        elif self.resolution_group == ResolutionGroup.THIRTEEN_TWENTY_EIGHT:
            self.height = Resolution.get_qwen_long_scale(self.scale-2)
            self.width = self.height
        else:
            raise Exception(f"Unhandled architecture type: {architecture_type} and resolution group: {self.resolution_group}")

    def portrait(self, architecture_type: ArchitectureType) -> None:
        if architecture_type == ArchitectureType.SD_15 or self.resolution_group == ResolutionGroup.FIVE_ONE_TWO:
            self.height = Resolution.get_long_scale(self.scale)
            self.width = Resolution.get_short_scale(self.scale)
        elif self.resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            self.height = Resolution.get_illustrious_long_scale(self.scale)
            self.width = Resolution.get_illustrious_short_scale(self.scale)
        elif self.resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            self.height = Resolution.get_xl_long_scale(self.scale)
            self.width = Resolution.get_xl_short_scale(self.scale)
        elif self.resolution_group == ResolutionGroup.THIRTEEN_TWENTY_EIGHT:
            self.height = Resolution.get_qwen_long_scale(self.scale)
            self.width = Resolution.get_qwen_short_scale(self.scale)
        else:
            raise Exception(f"Unhandled architecture type: {architecture_type} and resolution group: {self.resolution_group}")

    def landscape(self, architecture_type: ArchitectureType) -> None:
        self.portrait(architecture_type)
        self.invert()

    def switch_mode(self, is_xl: bool) -> None:
        if self.width == self.height:
            return self.square(is_xl)
        elif self.width > self.height:
            return self.landscape(is_xl)
        else:
            return self.portrait(is_xl)

    def should_be_randomly_skipped(self, skip_chance: float = 0.5) -> bool:
        if self.random_skip:
            return random.random() < skip_chance
        return False

    @staticmethod
    def construct_tolerance_range(
        architecture_type: ArchitectureType,
        resolution_group: ResolutionGroup
    ) -> list[int]:
        all_resolutions = ["square", "landscape1", "portrait1", "landscape2", "portrait2", "landscape3", "portrait3", "landscape4", "portrait4"]
        tolerance_range = [99999999999, -1]
        for res_tag in all_resolutions:
            res = Resolution.get_resolution(res_tag, architecture_type=architecture_type, resolution_group=resolution_group)
            assert res is not None and res.width is not None and res.height is not None
            total_pixels = res.width * res.height
            if total_pixels < tolerance_range[0]:
                tolerance_range[0] = total_pixels
            if total_pixels > tolerance_range[1]:
                tolerance_range[1] = total_pixels
        return tolerance_range

    @staticmethod
    def get_tolerance_range(
        architecture_type: ArchitectureType = ArchitectureType.SDXL,
        resolution_group: ResolutionGroup = ResolutionGroup.TEN_TWENTY_FOUR
    ) -> list[int]:
        architecture_type = architecture_type if architecture_type is not None else ArchitectureType.SDXL
        if resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            tolerance_range = Resolution.XL_TOTAL_PIXELS_TOLERANCE_RANGE
        elif resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            tolerance_range = Resolution.ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE
        elif resolution_group == ResolutionGroup.THIRTEEN_TWENTY_EIGHT:
            tolerance_range = Resolution.QWEN_TOTAL_PIXELS_TOLERANCE_RANGE
        else:
            tolerance_range = Resolution.TOTAL_PIXELS_TOLERANCE_RANGE
        if len(tolerance_range) == 0:
            tolerance_range = Resolution.construct_tolerance_range(architecture_type=architecture_type, resolution_group=resolution_group)
            if resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
                Resolution.XL_TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
            elif resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
                Resolution.ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
            elif resolution_group == ResolutionGroup.THIRTEEN_TWENTY_EIGHT:
                Resolution.QWEN_TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
            else:
                Resolution.TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
        return tolerance_range

    @staticmethod
    def find_matching_aspect_ratio_resolution(
        is_xl: bool,
        resolution_group: ResolutionGroup,
        target_width: int,
        target_height: int
    ) -> Optional[T]:
        all_resolutions = ["square", "landscape1", "portrait1", "landscape2", "portrait2", "landscape3", "portrait3", "landscape4", "portrait4"]
        aspect_ratio = float(target_width)/float(target_height)
        for res_tag in all_resolutions:
            res = Resolution.get_resolution(res_tag, is_xl, resolution_group)
            assert res is not None
            if aspect_ratio == res.aspect_ratio():
                return res
        return None

    def get_closest_to_image(self, ref_image_path: str, round_to: int = 4) -> T:
        width, height = Globals.get_image_data_extractor().get_image_size(ref_image_path)
        return self.get_closest(width=width, height=height, round_to=round_to, resolution_group=self.resolution_group)

    def get_closest(
        self,
        width: int,
        height: int,
        round_to: int = 4,
        architecture_type: ArchitectureType = None,
        resolution_group: ResolutionGroup = ResolutionGroup.FIVE_ONE_TWO
    ) -> T:
        architecture_type = architecture_type if architecture_type is not None else (ArchitectureType.SDXL if self.is_xl() else ArchitectureType.SD_15)
        resolution_group = resolution_group if resolution_group is not None else (ResolutionGroup.TEN_TWENTY_FOUR if self.is_xl() else ResolutionGroup.FIVE_ONE_TWO)
        # First check if the aspect ratio matches one of the existing resolutions, and return that
        matching_resolution = Resolution.find_matching_aspect_ratio_resolution(architecture_type, resolution_group, width, height)
        if matching_resolution is not None:
            return matching_resolution
        # If not, find the closest resolution that is within the tolerance range
        tolerance_range = Resolution.get_tolerance_range(architecture_type=architecture_type, resolution_group=resolution_group)
        if width * height < tolerance_range[0]:
            while width * height < tolerance_range[0]:
                width *= 1.1
                height *= 1.1
        elif width * height > tolerance_range[1]:
            while width * height > tolerance_range[1]:
                width *= 0.9
                height *= 0.9
        width = int(width)
        height = int(height)
        while width % round_to != 0:
            width += 1
        while height % round_to != 0:
            height += 1
        return Resolution(width, height, resolution_group=resolution_group)

    def to_aspect_ratio_string(self, ratios: list[str]) -> str:
        """Return the entry from *ratios* whose aspect ratio is closest to this resolution.

        Each entry must be a colon-separated string such as ``"16:9"`` or ``"2:3"``.
        Comparison is by absolute difference of the floating-point ratios, so both
        portrait and landscape orientations are matched correctly.

        Example::

            # Stability AI supported ratios
            STABILITY_RATIOS = ["16:9", "1:1", "21:9", "2:3", "3:2", "4:5", "5:4", "9:16", "9:21"]
            res = Resolution(1216, 832)   # landscape SDXL
            res.to_aspect_ratio_string(STABILITY_RATIOS)  # -> "3:2"
        """
        if not ratios:
            raise ValueError("ratios list must not be empty")

        own_ratio = self.width / self.height

        def _parse(r: str) -> float:
            parts = r.split(":")
            if len(parts) != 2:
                raise ValueError(f"Invalid ratio string: {r!r}")
            return float(parts[0]) / float(parts[1])

        return min(ratios, key=lambda r: abs(_parse(r) - own_ratio))

    def __str__(self) -> str:
        return f"{self.width}x{self.height}"

    def __eq__(self, other: object) -> bool:
        if isinstance(other, Resolution):
            return self.width == other.width and self.height == other.height
        return False

    def hash(self) -> int:
        return hash((self.width, self.height))
