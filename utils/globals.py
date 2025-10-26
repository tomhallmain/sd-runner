from enum import Enum
import os

from utils.config import config
from extensions.image_data_extractor import ImageDataExtractor
from utils.translations import I18N

_ = I18N._


class PromptMode(Enum):
    FIXED = "FIXED"
    SFW = "SFW"
    NSFW = "NSFW"
    NSFL = "NSFL"
    TAKE = "TAKE"
    RANDOM = "RANDOM"
    NONSENSE = "NONSENSE"
    ANY_ART = "ANY_ART"
    PAINTERLY = "PAINTERLY"
    ANIME = "ANIME"
    GLITCH = "GLITCH"
    LIST = "LIST"
    IMPROVE = "IMPROVE"

    def __str__(self):
        return self.value

    def display(self):
        return {
            PromptMode.FIXED: _("Fixed"),
            PromptMode.SFW: _("SFW"),
            PromptMode.NSFW: _("NSFW"),
            PromptMode.NSFL: _("NSFL"),
            PromptMode.TAKE: _("Take"),
            PromptMode.RANDOM: _("Random"),
            PromptMode.NONSENSE: _("Nonsense"),
            PromptMode.ANY_ART: _("Any Art"),
            PromptMode.PAINTERLY: _("Painterly"),
            PromptMode.ANIME: _("Anime"),
            PromptMode.GLITCH: _("Glitch"),
            PromptMode.LIST: _("List"),
            PromptMode.IMPROVE: _("Improve"),
        }[self]

    @classmethod
    def display_values(cls):
        return [mode.display() for mode in cls]

    @staticmethod
    def get(name):
        for key, value in PromptMode.__members__.items():
            if key == name or value.display() == name:
                return value
        
        raise Exception(f"Not a valid prompt mode: {name} (type: {type(name)})")

    def is_nsfw(self):
        return self in [PromptMode.NSFW, PromptMode.NSFL]


class BlacklistMode(Enum):
    REMOVE_WORD_OR_PHRASE = "REMOVE_WORD_OR_PHRASE"
    REMOVE_ENTIRE_TAG = "REMOVE_ENTIRE_TAG"
    FAIL_PROMPT = "FAIL_PROMPT"
    LOG_ONLY = "LOG_ONLY"

    def __str__(self):
        return self.value

    def display(self):
        # Use I18N._ for translation
        _ = I18N._
        display_map = {
            BlacklistMode.REMOVE_WORD_OR_PHRASE: _(u"Remove word/phrase (only the blacklisted part)"),
            BlacklistMode.REMOVE_ENTIRE_TAG: _(u"Remove entire tag (if any part matches)"),
            BlacklistMode.FAIL_PROMPT: _(u"Fail prompt (block generation)"),
            BlacklistMode.LOG_ONLY: _(u"Log only (do not remove, just log)"),
        }
        return display_map.get(self, str(self))

    @staticmethod
    def display_values():
        return [mode.display() for mode in BlacklistMode]

    @staticmethod
    def from_display(display_str):
        for mode in BlacklistMode:
            if mode.display() == display_str:
                return mode
        raise ValueError(f"No BlacklistMode with display value '{display_str}'")

class BlacklistPromptMode(Enum):
    DISALLOW = "DISALLOW"
    ALLOW_IN_NSFW = "ALLOW_IN_NSFW"

    def __str__(self):
        return self.value
    
    def display(self):
        return {
            BlacklistPromptMode.DISALLOW: _("Disallow"),
            BlacklistPromptMode.ALLOW_IN_NSFW: _("Allow in NSFW"),
        }[self]
    
    @classmethod
    def display_values(cls):
        return [mode.display() for mode in cls]
    
    @staticmethod
    def from_display(display_str):
        for mode in BlacklistPromptMode:
            if mode.display() == display_str:
                return mode
        raise ValueError(f"No BlacklistPromptMode with display value '{display_str}'")


class ModelBlacklistMode(Enum):
    DISALLOW = "DISALLOW"
    ALLOW_IN_NSFW = "ALLOW_IN_NSFW"

    def __str__(self):
        return self.value
    
    def display(self):
        return {
            ModelBlacklistMode.DISALLOW: _("Disallow"),
            ModelBlacklistMode.ALLOW_IN_NSFW: _("Allow in NSFW"),
        }[self]
    
    @classmethod
    def display_values(cls):
        return [mode.display() for mode in cls]
    
    @staticmethod
    def from_display(display_str):
        for mode in ModelBlacklistMode:
            if mode.display() == display_str:
                return mode
        raise ValueError(f"No ModelBlacklistMode with display value '{display_str}'")


class Globals:
    SERVICE_NAME = "MyPersonalApplicationsService"
    APP_IDENTIFIER = "sd_runner"
    HOME = os.path.expanduser("~")
    DEFAULT_PROMPT_MODE = PromptMode.get(config.dict["default_prompt_mode"])
    DEFAULT_WORKFLOW = config.dict["default_workflow"]
    DEFAULT_MODEL = config.dict["default_model"]
    DEFAULT_N_LATENTS = config.dict["default_n_latents"]
    DEFAULT_POSITIVE_PROMPT = config.dict["default_positive_prompt"]
    DEFAULT_NEGATIVE_PROMPT = config.dict["default_negative_prompt"]
    POSITIVE_PROMPT_MASSAGE_TAGS = None # Used for models trained with quality tags in positive prompt
    DEFAULT_B_W_COLORIZATION = config.dict["default_b_w_colorization"]
    DEFAULT_LORA_STRENGTH = config.dict["default_lora_strength"]
    DEFAULT_CONTROL_NET_STRENGTH = config.dict["default_controlnet_strength"]
    DEFAULT_IPADAPTER_STRENGTH = config.dict["default_ipadapter_strength"]
    DEFAULT_RESOLUTION_TAG = config.dict["default_resolution_tag"]
    DEFAULT_RESOLUTION_WIDTH = config.dict["default_resolution_width"]
    DEFAULT_RESOLUTION_HEIGHT = config.dict["default_resolution_height"]
    MODEL_PROMPT_TAGS_NEGATIVE = config.dict["model_prompt_tags_negative"]
    MODEL_PROMPT_TAGS_POSITIVE = config.dict["model_prompt_tags_positive"]
    OVERRIDE_BASE_NEGATIVE = config.dict["override_base_negative"]
    SKIP_CONFIRMATIONS = config.dict["skip_confirmations"]
    PRINT_NEGATIVES = config.dict["print_negatives"]
    PROMPTER_GET_SPECIFIC_LOCATIONS = config.dict["prompter_get_specific_locations"]
    GENERATION_DELAY_TIME_SECONDS = 10
    TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS = 7200  # 2 hours default threshold
    image_data_extractor = None

    @classmethod
    def set_prompt_massage_tags(cls, tags):
        cls.POSITIVE_PROMPT_MASSAGE_TAGS = tags

    @classmethod
    def get_image_data_extractor(cls):
        if cls.image_data_extractor is None:
            cls.image_data_extractor = ImageDataExtractor()
        return cls.image_data_extractor

    @classmethod
    def set_lora_strength(cls, strength):
        cls.DEFAULT_LORA_STRENGTH = strength

    @classmethod
    def set_ipadapter_strength(cls, strength):
        cls.DEFAULT_IPADAPTER_STRENGTH = strength

    @classmethod
    def set_controlnet_strength(cls, strength):
        cls.DEFAULT_CONTROL_NET_STRENGTH = strength

    @classmethod
    def set_override_base_negative(cls, override_negative):
        cls.OVERRIDE_BASE_NEGATIVE = override_negative

    @classmethod
    def set_delay(cls, delay):
        cls.GENERATION_DELAY_TIME_SECONDS = delay

    @classmethod
    def set_time_estimation_threshold(cls, threshold_seconds):
        cls.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS = threshold_seconds


class WorkflowType(Enum):
    SIMPLE_IMAGE_GEN = "simple_image_gen.json"
    SIMPLE_IMAGE_GEN_LORA = "simple_image_gen_lora.json"
    SIMPLE_IMAGE_GEN_TILED_UPSCALE = "simple_image_gen_tiled_upscale.json"
    ELLA = "ella.json"
    INSTANT_LORA = "instant_lora.json"
    IP_ADAPTER = "ip_adapter.json"
    IMG2IMG = "img2img.json"
    CONTROLNET = "controlnet.json"
    INPAINT_CLIPSEG = "inpaint_clipseg.json"
    ANIMATE_DIFF = "animate_diff.json"
    RENOISER = "renoiser.json"
    TURBO = "turbo2.json"
    UPSCALE_SIMPLE = "upscale_image.json"
    UPSCALE_BETTER = "upscale_better.json"
    REDO_PROMPT = "redo_prompt"

    def get_translation(self):
        return {
            WorkflowType.SIMPLE_IMAGE_GEN: _("Simple Image Gen"),
            WorkflowType.SIMPLE_IMAGE_GEN_LORA: _("Simple Image Gen Lora"),
            WorkflowType.SIMPLE_IMAGE_GEN_TILED_UPSCALE: _("Simple Image Gen Tiled Upscale"),
            WorkflowType.ELLA: _("Ella"),
            WorkflowType.INSTANT_LORA: _("Instant Lora"),
            WorkflowType.IP_ADAPTER: _("IP Adapter"),
            WorkflowType.IMG2IMG: _("Image to Image"),
            WorkflowType.CONTROLNET: _("ControlNet"),
            WorkflowType.INPAINT_CLIPSEG: _("Inpaint ClipSeg"),
            WorkflowType.ANIMATE_DIFF: _("Animate Diff"),
            WorkflowType.RENOISER: _("Renoiser"),
            WorkflowType.TURBO: _("Turbo"),
            WorkflowType.UPSCALE_SIMPLE: _("Upscale Simple"),
            WorkflowType.UPSCALE_BETTER: _("Upscale Better"),
            WorkflowType.REDO_PROMPT: _("Redo Prompt"),
        }[self]

    @staticmethod
    def get(name):
        for key, value in WorkflowType.__members__.items():
            if key.upper() == name.upper() or value.get_translation() == name:
                return value
        
        # Fallback: try to match by partial value (e.g., "instant_lora" matches "instant_lora.json")
        for workflow_type in WorkflowType.__members__.values():
            if name.lower() in workflow_type.value.lower():
                return workflow_type
                
        raise Exception(f"Not a valid workflow type: {name}")


class PromptTypeSDWebUI(Enum):
    TXT2IMG = "txt2img.json"
    TXT2IMG_LORA  = "txt2img.json"
    TXT2IMG_REFINER = "txt2img_refiner.json"
    UPSCALE_SIMPLE = "upscale_image.json"
    CONTROLNET = "controlnet.json"
    IMG2IMG = "img2img.json"
    IMG2IMG_CONTROLNET = "img2img_controlnet.json"

    @staticmethod
    def convert_to_sd_webui_filename(filename):
        this_workflow_type = None
        for key, workflow_type in WorkflowType.__members__.items():
            if workflow_type.value == filename:
                this_workflow_type = workflow_type
        if this_workflow_type == WorkflowType.IP_ADAPTER:
            return PromptTypeSDWebUI.IMG2IMG.value
        elif this_workflow_type == WorkflowType.CONTROLNET:
            return PromptTypeSDWebUI.CONTROLNET.value
        elif this_workflow_type == WorkflowType.INSTANT_LORA:
            return PromptTypeSDWebUI.IMG2IMG_CONTROLNET.value
        else:
            return PromptTypeSDWebUI.TXT2IMG.value

class Sampler(Enum):
    ACCEPT_ANY = "Any"
    EULER = "euler"
    EULER_ANCESTRAL = "euler_ancestral"
    DPM_2 = "dpm_2"
    DPM_2_ANCESTRAL = "dpm_2_ancestral"
    DPMPP_SDE = "dpmpp_sde"
    DPMPP_SDE_GPU = "dpmpp_sde_gpu"
    DPMPP_2M = "dpmpp_2m"
    DPMPP_2M_SDE = "dpmpp_2m_sde"
    DPMPP_2M_SDE_GPU = "dpmpp_2m_sde_gpu"
    DPMPP_3M_SDE = "dpmpp_3m_sde"
    DPMPP_3M_SDE_GPU = "dpmpp_3m_sde_gpu"
    DDIM = "ddim"
    DDPM = "ddpm"
    LCM = "lcm"

    def __str__(self):
        return self.name
    
    @classmethod
    def get(cls, name):
        if isinstance(name, cls):
            return name
        elif isinstance(name, str):
            return cls[name]
        raise ValueError(f"Invalid enum value for class {cls.__name__}: {name} (type: {type(name)})")


class Scheduler(Enum):
    ACCEPT_ANY = "Any"
    NORMAL = "normal"
    KARRAS = "karras"
    SIMPLE = "simple"
    EXPONENTIAL = "exponential"
    SGM_UNIFORM = "sgm_uniform"
    DDIM_UNIFORM = "ddim_uniform"

    def __str__(self):
        return self.name
    
    @classmethod
    def get(cls, name):
        if isinstance(name, cls):
            return name
        elif isinstance(name, str):
            return cls[name]
        raise ValueError(f"Invalid enum value for class {cls.__name__}: {name} (type: {type(name)})")


class ComfyNodeName:
    LOAD_CHECKPOINT = "CheckpointLoaderSimple"
    UNET_LOADER = "UNETLoader"
    LOAD_IMAGE = "LoadImage"
    LOAD_IMAGE_MASK = "LoadImageMask"
    LOAD_LORA = "LoraLoader"
    LOAD_VAE = "VAELoader"
    SAVE_IMAGE = "SaveImage"
    PREVIEW_IMAGE = "PreviewImage"
    EMPTY_LATENT = "EmptyLatentImage"
    EMPTY_LATENT_SD3 = "EmptySD3LatentImage"
    KSAMPLER = "KSampler"
    KSAMPLER_ADVANCED = "KSamplerAdvanced"
    SAMPLER_CUSTOM = "SamplerCustom"
    IP_ADAPTER = "IPAdapter"
    IP_ADAPTER_ADVANCED = "IPAdapterAdvanced"
    IP_ADAPTER_MODEL_LOADER = "IPAdapterModelLoader"
    IMAGE_DUPLICATOR = "ImageDuplicator"
    IMPACT_WILDCARD_PROCESSOR = "ImpactWildcardProcessor"
    CLIP_SEG = "CLIPSeg"
    CONTROL_NET = "ControlNetApply"
    CLIP_TEXT_ENCODE = "CLIPTextEncode"
    CLIP_VISION = "CLIPVisionLoader"
    IMAGE_SCALE_TO_SIDE = "Image scale to side"
    IMAGE_SCALE = "ImageScale"
    ELLA_T5_EMBEDS = "ella_t5_embeds"
    ELLA_SAMPLER = "ella_sampler"
    BASIC_SCHEDULER = "BasicScheduler"


class SoftwareType(Enum):
    ComfyUI = "ComfyUI"
    SDWebUI = "SDWebUI"

class ArchitectureType(Enum):
    SD_15 = "SD_15"
    SDXL = "SDXL"
    ILLUSTRIOUS = "ILLUSTRIOUS"
    TURBO = "TURBO"
    FLUX = "FLUX"

    def is_xl(self):
        return self == ArchitectureType.SDXL or self == ArchitectureType.ILLUSTRIOUS

    def display(self):
        """Get the display value for this architecture type."""
        return {
            ArchitectureType.SD_15: _("SD 1.5"),
            ArchitectureType.SDXL: _("SDXL"),
            ArchitectureType.ILLUSTRIOUS: _("Illustrious"),
            ArchitectureType.TURBO: _("Turbo"),
            ArchitectureType.FLUX: _("Flux"),
        }[self]

    @classmethod
    def display_values(cls):
        """Get all display values for architecture types."""
        return [arch_type.display() for arch_type in cls]

    @staticmethod
    def from_display(display_str):
        """Get ArchitectureType from display string."""
        for arch_type in ArchitectureType:
            if arch_type.display() == display_str:
                return arch_type
        raise ValueError(f"No ArchitectureType with display value '{display_str}'")


class ResolutionGroup(Enum):
    FIFTEEN_THIRTY_SIX = "1536"
    TEN_TWENTY_FOUR = "1024"
    SEVEN_SIXTY_EIGHT = "768"
    FIVE_ONE_TWO = "512"

    def get_description(self):
        return {
            ResolutionGroup.FIFTEEN_THIRTY_SIX: _("1536"),
            ResolutionGroup.TEN_TWENTY_FOUR: _("1024"),
            ResolutionGroup.SEVEN_SIXTY_EIGHT: _("768"),
            ResolutionGroup.FIVE_ONE_TWO: _("512"),
        }[self]

    @classmethod
    def display_values(cls):
        return [rg.get_description() for rg in cls]

    @staticmethod
    def get(name):
        for key, value in ResolutionGroup.__members__.items():
            if key.upper() == name.upper() or value.get_description() == name:
                return value
        raise Exception(f"Not a valid resolution group: {name}")


class ProtectedActions(Enum):
    """Enumeration of actions that can be password protected."""
    OPEN_APPLICATION = "open_application"
    NSFW_PROMPTS = "nsfw_prompts"
    EDIT_BLACKLIST = "edit_blacklist"
    REVEAL_BLACKLIST_CONCEPTS = "reveal_blacklist_concepts"
    EDIT_SCHEDULES = "edit_schedules"
    EDIT_TIMED_SCHEDULES = "edit_timed_schedules"
    EDIT_EXPANSIONS = "edit_expansions"
    EDIT_PRESETS = "edit_presets"
    EDIT_CONCEPTS = "edit_concepts"
    ACCESS_ADMIN = "access_admin"
    
    @staticmethod
    def get_action(action_name: str):
        """Get the ProtectedActions enum value for a given action name."""
        try:
            return ProtectedActions(action_name.lower().replace(" ", "_"))
        except ValueError:
            return None

    def get_description(self):
        """Get the user-friendly description for this action."""
        descriptions = {
            ProtectedActions.OPEN_APPLICATION: _("Open Application"),
            ProtectedActions.NSFW_PROMPTS: _("NSFW/NSFL Prompt Modes"),
            ProtectedActions.EDIT_BLACKLIST: _("Edit Blacklist"),
            ProtectedActions.REVEAL_BLACKLIST_CONCEPTS: _("Reveal Blacklist Concepts"),
            ProtectedActions.EDIT_SCHEDULES: _("Edit Schedules"),
            ProtectedActions.EDIT_TIMED_SCHEDULES: _("Edit Timed Schedules"),
            ProtectedActions.EDIT_EXPANSIONS: _("Edit Expansions"),
            ProtectedActions.EDIT_PRESETS: _("Edit Presets"),
            ProtectedActions.EDIT_CONCEPTS: _("Edit Concepts"),
            ProtectedActions.ACCESS_ADMIN: _("Access Password Administration"),
        }
        return descriptions.get(self, self.value)

