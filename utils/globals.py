from enum import Enum
import os

from sd_runner.concepts import PromptMode
from utils.config import config
from extensions.image_data_extractor import ImageDataExtractor
from sd_runner.prompter import Prompter


class Globals:
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
    PROMPTER = Prompter()
    PROMPTER_GET_SPECIFIC_LOCATIONS = config.dict["prompter_get_specific_locations"]
    GENERATION_DELAY_TIME_SECONDS = 10
    image_data_extractor = None

    @classmethod
    def set_prompter(cls, prompter=Prompter()):
        cls.PROMPTER = prompter

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

class WorkflowType(Enum):
    SIMPLE_IMAGE_GEN = "simple_image_gen.json"
    SIMPLE_IMAGE_GEN_LORA = "simple_image_gen_lora.json"
    SIMPLE_IMAGE_GEN_TILED_UPSCALE = "simple_image_gen_tiled_upscale.json"
    ELLA = "ella.json"
    INSTANT_LORA = "instant_lora.json"
    IP_ADAPTER = "ip_adapter.json"
    CONTROLNET = "controlnet_sd15.json"
    INPAINT_CLIPSEG = "inpaint_clipseg.json"
    ANIMATE_DIFF = "animate_diff.json"
    RENOISER = "renoiser.json"
    TURBO = "turbo2.json"
    UPSCALE_SIMPLE = "upscale_image.json"
    UPSCALE_BETTER = "upscale_better.json"
    REDO_PROMPT = "redo_prompt"


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


class ResolutionGroup(Enum):
    FIFTEEN_THIRTY_SIX = "1536"
    TEN_TWENTY_FOUR = "1024"
    SEVEN_SIXTY_EIGHT = "768"
    FIVE_ONE_TWO = "512"

