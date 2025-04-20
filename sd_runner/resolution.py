
import random

from utils.globals import Globals, ArchitectureType, ResolutionGroup
from utils.utils import Utils


class Resolution:
    TOTAL_PIXELS_TOLERANCE_RANGE = []
    XL_TOTAL_PIXELS_TOLERANCE_RANGE = []
    ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE = []

    def __init__(self, width=Globals.DEFAULT_RESOLUTION_WIDTH, height=Globals.DEFAULT_RESOLUTION_HEIGHT, scale=2, random_skip=False):
        self.width = width
        self.height = height
        self.scale = scale
        self.random_skip = random_skip

    @classmethod
    def SQUARE(cls, architecture_type=ArchitectureType.SDXL, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR, scale=2, random_skip=False):
        resolution = Resolution(scale=scale, random_skip=random_skip)
        resolution.square(architecture_type, resolution_group)
        return resolution

    @classmethod
    def PORTRAIT(cls, architecture_type=ArchitectureType.SDXL, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR, scale=2, random_skip=False):
        resolution = Resolution(scale=scale, random_skip=random_skip)
        resolution.portrait(architecture_type, resolution_group)
        return resolution

    @classmethod
    def LANDSCAPE(cls, architecture_type=ArchitectureType.SDXL, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR, scale=2, random_skip=False):
        resolution = Resolution(scale=scale, random_skip=random_skip)
        resolution.landscape(architecture_type, resolution_group)
        return resolution

    @staticmethod
    def get_long_scale(scale=2):
        if scale < 2:
            return 768
        if scale == 2:
            return 768
        if scale > 2:
            return 960

    @staticmethod
    def get_short_scale(scale=2):
        if scale == 1:
            return 704
        if scale == 2:
            return 640
        if scale > 2:
            return 512
        return 768

    @staticmethod
    def get_xl_long_scale(scale=2):
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
    def get_xl_short_scale(scale=2):
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
    def get_illustrious_long_scale(scale=2):
        if scale == 1:
            return 1664
        elif scale == 2:
            return 1792
        elif scale == 3:
            return 2048
        return 1536

    @staticmethod
    def get_illustrious_short_scale(scale=2):
        if scale == 1:
            return 1344
        if scale == 2:
            return 1216
        if scale == 3:
            return 1152
        return 1536

    @staticmethod
    def round_int(value, multiplier=4):
        modified_value = int(value)
        try_above = True
        difference = 1
        while modified_value % multiplier != 0:
            modified_value = value + difference if try_above else value - difference
            try_above = not try_above
        return modified_value

    def upscale_rounded(self, factor=1.5):
        width = Resolution.round_int(int(self.width * 1.5))
        height = Resolution.round_int(int(self.height * 1.5))
        return width, height

    def is_xl(self):
        return self.width > 768 and self.height > 768

    def is_illustrious(self):
        return self.width > 1024 and self.height > 1024 or \
            self.height == 1024 and self.width > 1024 or \
            self.width == 1024 and self.height > 1024

    def aspect_ratio(self):
        return float(self.width) / float(self.height)

    def invert(self):
        temp = self.width
        self.width = self.height
        self.height = temp

    def convert_for_model_type(self, architecture_type):
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

    def convert_to(self, architecture_type):
        return self.get_closest(self.width, self.height, architecture_type=architecture_type)

    def square(self, architecture_type, resolution_group):
        if architecture_type == ArchitectureType.SD_15 or resolution_group == ResolutionGroup.FIVE_ONE_TWO:
            self.height = Resolution.get_long_scale(self.scale-2)
            self.width = self.height
        elif resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            self.height = Resolution.get_illustrious_long_scale(self.scale-2)
            self.width = self.height
        elif resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            self.height = Resolution.get_xl_long_scale(self.scale-2)
            self.width = self.height
        else:
            raise Exception(f"Unhandled architecture type: {architecture_type} and resolution group: {resolution_group}")

    def portrait(self, architecture_type, resolution_group):
        if architecture_type == ArchitectureType.SD_15 or resolution_group == ResolutionGroup.FIVE_ONE_TWO:
            self.height = Resolution.get_short_scale(self.scale)
            self.width = Resolution.get_long_scale(self.scale)
        elif resolution_group == ResolutionGroup.FIFTEEN_THIRTY_SIX:
            self.height = Resolution.get_illustrious_short_scale(self.scale)
            self.width = Resolution.get_illustrious_long_scale(self.scale)
        elif resolution_group == ResolutionGroup.TEN_TWENTY_FOUR:
            self.height = Resolution.get_xl_short_scale(self.scale)
            self.width = Resolution.get_xl_long_scale(self.scale)
        else:
            raise Exception(f"Unhandled architecture type: {architecture_type} and resolution group: {resolution_group}")

    def landscape(self, architecture_type, resolution_group):
        self.portrait(architecture_type, resolution_group)
        self.invert()

    def switch_mode(self, is_xl):
        if self.width == self.height:
            return self.square(is_xl)
        elif self.width > self.height:
            return self.landscape(is_xl)
        else:
            return self.portrait(is_xl)

    def should_be_randomly_skipped(self, skip_chance=0.5):
        if self.random_skip:
            return random.random() < skip_chance
        return False

    @staticmethod
    def construct_tolerance_range(architecture_type):
        all_resolutions = ["square", "landscape1", "portrait1", "landscape2", "portrait2", "landscape3", "portrait3", "landscape4", "portrait4"]
        tolerance_range = [99999999999, -1]
        for res_tag in all_resolutions:
            res = Resolution.get_resolution(res_tag, architecture_type=architecture_type)
            assert res is not None and res.width is not None and res.height is not None
            total_pixels = res.width * res.height
            if total_pixels < tolerance_range[0]:
                tolerance_range[0] = total_pixels
            if total_pixels > tolerance_range[1]:
                tolerance_range[1] = total_pixels
        return tolerance_range

    @staticmethod
    def get_tolerance_range(architecture_type=None, resolution_group=ResolutionGroup.FIVE_ONE_TWO):
        architecture_type = architecture_type if architecture_type is not None else ArchitectureType.SDXL
        if architecture_type == ArchitectureType.SDXL:
            tolerance_range = Resolution.XL_TOTAL_PIXELS_TOLERANCE_RANGE
        elif architecture_type == ArchitectureType.ILLUSTRIOUS:
            tolerance_range = Resolution.ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE
        else:
            tolerance_range = Resolution.TOTAL_PIXELS_TOLERANCE_RANGE
        if len(tolerance_range) == 0:
            tolerance_range = Resolution.construct_tolerance_range(architecture_type=architecture_type)
            if architecture_type == ArchitectureType.SDXL:
                Resolution.XL_TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
            if architecture_type == ArchitectureType.ILLUSTRIOUS:
                Resolution.ILLUSTRIOUS_TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
            else:
                Resolution.TOTAL_PIXELS_TOLERANCE_RANGE = tolerance_range
        return tolerance_range

    @staticmethod
    def find_matching_aspect_ratio_resolution(is_xl, resolution_group, target_width, target_height):
        all_resolutions = ["square", "landscape1", "portrait1", "landscape2", "portrait2", "landscape3", "portrait3", "landscape4", "portrait4"]
        aspect_ratio = float(target_width)/float(target_height)
        for res_tag in all_resolutions:
            res = Resolution.get_resolution(res_tag, is_xl, resolution_group)
            assert res is not None
            if aspect_ratio == res.aspect_ratio():
                return res
        return None

    def get_closest_to_image(self, ref_image_path, round_to=4):
        width, height = Globals.get_image_data_extractor().get_image_size(ref_image_path)
        return self.get_closest(width=width, height=height, round_to=round_to)

    def get_closest(self, width, height, round_to=4, architecture_type=None, resolution_group=ResolutionGroup.FIVE_ONE_TWO):
        architecture_type = architecture_type if architecture_type is not None else (ArchitectureType.SDXL if self.is_xl() else ArchitectureType.SD_15)
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
        return Resolution(width, height)

    def __str__(self):
        return f"{self.width}x{self.height}"

    def __eq__(self, other):
        if isinstance(other, Resolution):
            return self.width == other.width and self.height == other.height
        return False

    def hash(self):
        return hash((self.width, self.height))

    @staticmethod
    def get_resolution(resolution_tag, architecture_type=ArchitectureType.SDXL, resolution_group=ResolutionGroup.TEN_TWENTY_FOUR):
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
    def get_resolutions(resolution_tag_str,
                        default_tag=Globals.DEFAULT_RESOLUTION_TAG,
                        architecture_type=ArchitectureType.SDXL,
                        resolution_group=ResolutionGroup.FIVE_ONE_TWO):
        if resolution_tag_str is None or resolution_tag_str.strip() == "":
            resolution_tag_str = default_tag
        resolution_tags = resolution_tag_str.split(",")
        resolutions = []
        for resolution_tag in resolution_tags:
            resolutions.append(Resolution.get_resolution(resolution_tag.lower().strip(),
                                                         architecture_type=architecture_type,
                                                         resolution_group=resolution_group))
        return resolutions
