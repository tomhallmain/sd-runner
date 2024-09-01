import glob
import os
import random
import re

from sd_runner.concepts import PromptMode
from utils.config import config
from utils.globals import Globals, WorkflowType
from utils.utils import extract_substring


class Resolution:
    def __init__(self, width=Globals.DEFAULT_RESOLUTION_WIDTH, height=Globals.DEFAULT_RESOLUTION_HEIGHT, scale=2):
        self.width = width
        self.height = height
        self.scale = scale

    @classmethod
    def SQUARE(cls, is_xl, scale=2):
        resolution = Resolution(scale=scale)
        resolution.square(is_xl)
        return resolution

    @classmethod
    def PORTRAIT(cls, is_xl, scale=2):
        resolution = Resolution(scale=scale)
        resolution.portrait(is_xl)
        return resolution

    @classmethod
    def LANDSCAPE(cls, is_xl, scale=2):
        resolution = Resolution(scale=scale)
        resolution.landscape(is_xl)
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

    def invert(self):
        temp = self.width
        self.width = self.height
        self.height = temp

    def square(self, is_xl):
        if is_xl:
            self.height = Resolution.get_xl_long_scale(self.scale-2)
            self.width = self.height
        else:
            self.height = Resolution.get_long_scale(self.scale-2)
            self.width = self.height

    def portrait(self, is_xl):
        if is_xl:
            self.height = Resolution.get_xl_long_scale(self.scale)
            self.width = Resolution.get_xl_short_scale(self.scale)
        else:
            self.height = Resolution.get_long_scale(self.scale)
            self.width = Resolution.get_short_scale(self.scale)

    def landscape(self, is_xl):
        self.portrait(is_xl)
        self.invert()

    def switch_mode(self, is_xl):
        if self.width == self.height:
            return self.square(is_xl)
        elif self.width > self.height:
            return self.landscape(is_xl)
        else:
            return self.portrait(is_xl)

    def __str__(self):
        return f"{self.width}x{self.height}"

    def __eq__(self, other):
        if isinstance(other, Resolution):
            return self.width == other.width and self.height == other.height
        return False

    def hash(self):
        return hash((self.width, self.height))

    @staticmethod
    def get_resolution(resolution_tag, is_xl=False):
        scale_str = extract_substring(resolution_tag, "[0-9]+")
        scale = int(scale_str) if scale_str and scale_str != "" else 2
        resolution_tag = extract_substring(resolution_tag, "[a-z]+")
        if "square".startswith(resolution_tag):
            return Resolution.SQUARE(is_xl=is_xl, scale=scale)
        elif "portrait".startswith(resolution_tag):
            return Resolution.PORTRAIT(is_xl=is_xl, scale=scale)
        elif "landscape".startswith(resolution_tag):
            return Resolution.LANDSCAPE(is_xl=is_xl, scale=scale)

    @staticmethod
    def get_resolutions(resolution_tag_str, default_tag=Globals.DEFAULT_RESOLUTION_TAG, is_xl=False):
        if resolution_tag_str is None or resolution_tag_str.strip() == "":
            resolution_tag_str = default_tag
        resolution_tags = resolution_tag_str.split(",")
        resolutions = []
        for resolution_tag in resolution_tags:
            resolutions.append(Resolution.get_resolution(resolution_tag.lower().strip(), is_xl=is_xl))
        return resolutions

class Model:
    DEFAULT_SD15_MODEL = "analogMadness"
    DEFAULT_XL_MODEL = "realvisXLV20"
    DEFAULT_TURBO_MODEL = "realvisxlV30Turbo"
    DEFAULT_SDXL_VAE = "sdxl_vae.safetensors"
    DEFAULT_SD15_VAE = "vae-ft-mse-840000-ema-pruned.ckpt"
    MODELS_DIR = config.models_dir
    CHECKPOINTS = {}
    LORAS = {}

    def __init__(self, id, path=None, is_lora=False, is_xl=False, is_turbo=False, clip_req=None, lora_strength=Globals.DEFAULT_LORA_STRENGTH):
        self.id = id
        self.path = path if path else os.path.join(Model.MODELS_DIR, id)
        self.is_lora = is_lora
        self.is_xl = is_xl or (path is not None and path.startswith("XL"))
        self.is_turbo = is_turbo or (path is not None and path.startswith("Turbo"))
        self.positive_tags = None
        self.negative_tags = None
        self.clip_req = clip_req
        self.lora_strength = lora_strength
        self.lora_strength_clip = lora_strength

    def is_sd_15(self):
        return not self.is_lora and not self.is_xl and not self.is_turbo

    def get_default_lora(self):
        return "add-detail" if self.is_sd_15() else "add-detail-xl"
    
    def get_lora_text(self):
        if not self.is_lora:
            raise Exception("Model is not of type LoRA")
        name = self.id if "." not in self.id else self.id[:self.id.index(".")]
        if self.lora_strength_clip is not None and self.lora_strength_clip != self.lora_strength:
            return f" <lora:{name}:{self.lora_strength}:{self.lora_strength_clip}>"
        else:
            return f" <lora:{name}:{self.lora_strength}>"

    def get_default_vae(self):
        return Model.DEFAULT_SDXL_VAE if self.is_xl or self.is_turbo else Model.DEFAULT_SD15_VAE

    def validate_vae(self, vae):
        if self.is_xl or self.is_turbo:
            if vae != Model.DEFAULT_SDXL_VAE: # TODO update if more
                raise Exception(f"Invalid VAE {vae} for SDXL model {self.id}")
        else:
            if vae == Model.DEFAULT_SDXL_VAE:
                raise Exception(f"Invalid SDXL VAE {vae} for model {self.id}")
    
    def validate_loras(self, lora_bundle):
        if self.is_xl or self.is_turbo:
            if not lora_bundle.is_xl: # TODO update if more
                raise Exception(f"Invalid Lora {lora_bundle} for SDXL model {self.id}")
        else:
            if lora_bundle.is_xl:
                raise Exception(f"Invalid SDXL lora {lora_bundle} for model {self.id}")

    def __str__(self):
        if self.is_lora:
            return "Model " + self.id + " - LoRA: " + str(self.is_lora) + " - Strength: " + str(self.lora_strength)
        else:
            return "Model " + self.id + " - LoRA: " + str(self.is_lora) + " - XL: " + str(self.is_xl) + " - Turbo: " + str(self.is_turbo)

    def __eq__(self, other):
        if isinstance(other, Model):
            return self.id == other.id
        return False

    def hash(self):
        return hash(self.id)

    def get_xl_model(self):
        if self.is_xl:
            return self
        if "hentai" in self.id or "orange" in self.id:
            return Model.get_model("pony")
        return Model.get_model(Model.DEFAULT_XL_MODEL)
    
    def get_sd15_model(self):
        if self.is_sd_15():
            return self
        if "pony" in self.id:
            return Model.get_model("hentai")
        return Model.get_model(Model.DEFAULT_SD15_MODEL)

    def get_model_text(self, positive, negative):
        if positive:
            if Globals.MODEL_PROMPT_TAGS_POSITIVE:
                if Globals.POSITIVE_PROMPT_MASSAGE_TAGS and Globals.POSITIVE_PROMPT_MASSAGE_TAGS != "":
                    positive = Globals.POSITIVE_PROMPT_MASSAGE_TAGS + positive
                elif self.positive_tags:
                    positive = self.positive_tags + positive
        if negative:
            if not Globals.OVERRIDE_BASE_NEGATIVE and Globals.MODEL_PROMPT_TAGS_NEGATIVE and self.negative_tags:
                negative = self.negative_tags + negative
        return positive, negative

    @staticmethod
    def get_default_model_tag(workflow):
        if workflow == WorkflowType.TURBO:
            return Model.DEFAULT_TURBO_MODEL
        elif workflow in [WorkflowType.UPSCALE_BETTER, WorkflowType.UPSCALE_SIMPLE]:
            return Model.DEFAULT_XL_MODEL
        else:
            return Model.DEFAULT_SD15_MODEL

    @staticmethod
    def get_model(model_tag, is_lora=False, inpainting=False, is_xl=0):
        if model_tag is None or model_tag.strip() == "":
            return None

        models = Model.LORAS if is_lora else Model.CHECKPOINTS

        if model_tag == "*":
            filtered_list = [model_name for model_name, model in models.items() if (model.is_xl == (is_xl == 1))]
#            print(filtered_list)
            random_model_name = random.sample(filtered_list, 1)
            return models[random_model_name[0]]

        lora_strength = None
        lora_strength_clip = None
        if "\\" in model_tag:
            model_tag = model_tag[model_tag.index("\\")+1]
        if ":" in model_tag:
            parts = model_tag.split(":")
            model_tag = parts[0]
            lora_strength = float(parts[1])
            if len(parts) > 2:
                lora_strength_clip = float(parts[2])
        model_tag = model_tag.lower()
        model = None
        for _model_name in models:
            model_name = _model_name.lower()
            if model_name.startswith(model_tag):
                if not is_lora and inpainting:
                    if "inpaint" in model_name:
                        if is_xl == 0 or is_xl == 1 or "xl" not in model_name:
                            model = models[_model_name]
                elif is_lora or "inpaint" not in model_name:
                    if is_xl == 0 or is_xl == 1 or "xl" not in model_name:
                        model = models[_model_name]

        if model is None:
            for _model_name in models:
                model_name = _model_name.lower()
                if model_tag in model_name:
                    if inpainting:
                        if "inpainting" in model_name:
                            if is_xl == 0 or is_xl == 1 or "xl" not in model_name:
                                model = models[_model_name]
                    elif "inpainting" not in model_name:
                        if is_xl == 0 or is_xl == 1 or "xl" not in model_name:
                            model = models[_model_name]

        if model is None:
            raise Exception(f"Failed to find model for tag {model_tag}, inpainting={inpainting}")        
        if lora_strength is not None:
            model.lora_strength = lora_strength
        if lora_strength_clip is not None:
            model.lora_strength_clip = lora_strength_clip
        return model

    @staticmethod
    def get_models(model_tags_str, is_lora=False, default_tag="analogMadness", inpainting=False, is_xl=0):
        if model_tags_str is None or model_tags_str.strip() == "":
            model_tags_str = default_tag
        model_tags = model_tags_str.split(",")
        models = []
        for model_tag in model_tags:
            try:
                if "+" in model_tag:
                    if not is_lora:
                        raise Exception("Expected lora for use of Lora bundle token \":\"")
                    bundle_model_tags = model_tag.replace("+", ",")
                    models.append(LoraBundle(Model.get_models(bundle_model_tags, is_lora=is_lora, default_tag=default_tag, inpainting=inpainting, is_xl=is_xl)))
                else:
                    models.append(Model.get_model(model_tag, is_lora, inpainting=inpainting, is_xl=is_xl))
            except Exception:
                model_tag = model_tag.replace("-", "_") if "-" in model_tag else model_tag.replace("_", "-")
                models.append(Model.get_model(model_tag, is_lora, inpainting=inpainting, is_xl=is_xl))
        return models

    @staticmethod
    def load_models(is_lora):
        models = {}
        lora_or_sd = "Lora" if is_lora else "Stable-diffusion"
        root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
        for file in glob.glob(pathname="**/*", root_dir=root_dir, recursive=True):
            if not file.endswith("ckpt") and not file.endswith("safetensors") and not file.endswith("pth"):
                continue
            model_name = re.sub("^.+\\\\", "", file)
            is_xl = file.startswith("XL")
            is_turbo = file.startswith("Turbo")
            model = Model(model_name, file, is_xl=is_xl, is_lora=is_lora, is_turbo=is_turbo)
            models[model_name] = model
#            print(model)
        if is_lora:
            Model.LORAS = models
        else:
            Model.CHECKPOINTS = models

    @staticmethod
    def load_all_if_unloaded():
        if len(Model.CHECKPOINTS) == 0:
            Model.load_all()

    @staticmethod
    def load_all():
        Model.load_models(is_lora=False)
        Model.load_models(is_lora=True)

    @staticmethod
    def apply_positive_tags_to_models(positive_tag, models_tags):
        for model_tag in models_tags:
            model = Model.get_model(model_tag)
            model.positive_tags = positive_tag

    @staticmethod
    def apply_negative_tags_to_models(negative_tag, models_tags):
        for model_tag in models_tags:
            model = Model.get_model(model_tag)
            model.negative_tags = negative_tag

    @staticmethod
    def set_lora_strength(strength=0.8):
        for lora in Model.LORAS.values():
            lora.lora_strength = strength

    @staticmethod
    def set_model_presets(prompt_mode):
        for preset_config in config.model_presets:
            model_tags = preset_config["model_tags"]
            models = []
            try:
                models = Model.get_models(model_tags)
            except Exception as e:
                print(f"Failed to get model to set presets with exception: {e}")
            for model in models:
                if "clip_req" in preset_config:
                    model.clip_req = preset_config["clip_req"]
                if "prompt_tags" in preset_config:
                    for prompt_mode_name, prompt_config in preset_config["prompt_tags"].items():
                        if prompt_mode_name in PromptMode.__members__.keys():
                            prompt_mode_config = PromptMode[prompt_mode_name]
                            if prompt_mode_config == prompt_mode:
                                model.positive_tags = prompt_config["positive"]
                                model.negative_tags = prompt_config["negative"]
                        else:
                            model.positive_tags = prompt_config["positive"]
                            model.negative_tags = prompt_config["negative"]

    @staticmethod
    def get_first_model_lora_tags(model_tags, lora_tags):
        # TODO in case there was a model switch, need to be sure the default lora for the model type is set.
        pass

    @staticmethod
    def get_first_model_prompt_massage_tags(model_tags_str, prompt_mode=PromptMode.SFW, inpainting=False, default_tag=""):
        Model.load_all_if_unloaded()
        Model.set_model_presets(prompt_mode)
        models = []
        try:
            models = Model.get_models(model_tags_str, default_tag=default_tag, inpainting=inpainting)
        except Exception as e:
            print(e)
        prompt_massage_tags = ""
        if len(models) == 1:
            print(models[0])
            print(models[0].positive_tags)
            tags_from_model = models[0].positive_tags
            if tags_from_model:
                prompt_massage_tags = tags_from_model
        return prompt_massage_tags

class LoraBundle:
    def __init__(self, loras=[]):
        self.loras = loras
        if len(self.loras) == 0:
            raise Exception("No loras provided to Lora bundle!")
        self.is_xl = self.loras[0].is_xl
        for lora in self.loras:
            if self.is_xl != lora.is_xl:
                raise Exception(f"Inconsistent SDXL specification for loras in lora bundle: {lora.id} expected is_xl: {self.is_xl}")

    def __str__(self):
        out = "LoraBundle: [ "
        for lora in self.loras:
            out += str(lora) + " "
        out += "]"
        return out

class IPAdapter:
    BASE_DIR = config.ipadapter_dir
    DEFAULT_SD15_MODEL = "ip-adapter_sd15_plus.pth"
    DEFAULT_SDXL_MODEL = "ip-adapter_xl.pth"
    DEFAULT_SD15_CLIP_VISION_MODEL = "SD1.5\\pytorch_model.bin"
    DEFAULT_SDXL_CLIP_VISION_MODEL = "XL\\clip_vision_g.safetensors"
    # Set to prompt extra coloration if the IP adapter image is black and white
    B_W_COLORATION = Globals.DEFAULT_B_W_COLORIZATION

    @classmethod
    def set_bw_coloration(cls, coloration):
        cls.B_W_COLORATION = coloration

    def __init__(self, id, desc="", modifiers="", strength=None):
        if strength is None:
            strength = Globals.DEFAULT_IPADAPTER_STRENGTH
        if not id or id.startswith("C:\\") or id.startswith("D:\\") or id.startswith("/"):
            self.id = id
        else:
            self.id = os.path.join(IPAdapter.BASE_DIR, id)
        if id and not os.path.isfile(self.id):
            raise Exception("Invalid file for IPAdapter: " + self.id)
        self.desc = desc
        self.modifiers = modifiers
        self.strength = strength

    def get_id(self, control_net=None):
        if self.id:
            return self.id    
        if control_net:
            return control_net.id
        raise Exception("Expected control net on IPAdapter with no id")

    def b_w_coloration_modifier(self, positive):
        if "b & w" in self.desc:
            if IPAdapter.B_W_COLORATION and IPAdapter.B_W_COLORATION != "":
                return positive  + ", " + IPAdapter.B_W_COLORATION
            return positive + ", " + Globals.PROMPTER.mix_colors()
        return positive

    def __str__(self):
        if self.desc and self.desc != "":
            if self.modifiers and self.modifiers != "":
                return f"IPAdapter image: {self.id}, desc: \"{self.desc}\", modifiers \"{self.modifiers}\", strength: {self.strength}"
            else:
                return f"IPAdapter image: {self.id}, desc: \"{self.desc}\", strength: {self.strength}"
        elif self.modifiers and self.modifiers != "":
            return f"IPAdapter image: {self.id}, modifiers \"{self.modifiers}\", strength: {self.strength}"
        else:
            return f"IPAdapter image: {self.id}, strength: {self.strength}"

    def __eq__(self, other):
        if isinstance(other, IPAdapter):
            return self.id == other.id
        return False

    def hash(self):
        return hash(self.id)

class ControlNet:
    def __init__(self, id, desc="", strength=Globals.DEFAULT_CONTROL_NET_STRENGTH):
        self.id = id
        self.desc = desc
        self.strength = strength

    def __str__(self):
        if self.desc and self.desc != "":
            return f"ControlNet image: {self.id}, desc: \"{self.desc}\", strenth: {self.strength}"
        else:
            return f"ControlNet image: {self.id}, strength: {self.strength}"

    def __eq__(self, other):
        if isinstance(other, ControlNet):
            return self.id == other.id
        return False

    def __ne__(self, other):
        return not self.__eq__(other)

    def hash(self):
        return hash(self.id)

