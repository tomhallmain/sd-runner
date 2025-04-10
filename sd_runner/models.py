import glob
import os
import random
import re

from sd_runner.concepts import PromptMode
from sd_runner.model_adapters import LoraBundle
from utils.config import config
from utils.globals import Globals, WorkflowType, ArchitectureType



class Model:
    DEFAULT_SD15_MODEL = "analogMadness"
    DEFAULT_XL_MODEL = "realvisXLV20"
    DEFAULT_TURBO_MODEL = "realvisxlV30Turbo"
    DEFAULT_ILLUSTRIOUS_MODEL = "Illustrious-XL-v1.0"
    DEFAULT_SDXL_VAE = "sdxl_vae.safetensors"
    DEFAULT_SD15_VAE = "vae-ft-mse-840000-ema-pruned.ckpt"
    MODELS_DIR = config.models_dir
    CHECKPOINTS = {}
    LORAS = {}

    @staticmethod
    def get_architecture_type(model_id, path, is_xl, is_turbo, is_flux):
        # NOTE this can be overridden by the presets
        if "Illustrious" in model_id:
            print(f"Assuming model is based on IllustriousXL architecture: {id}")
            architecture_type = ArchitectureType.ILLUSTRIOUS
        elif path is not None and path.startswith("XL") or is_xl:
            architecture_type = ArchitectureType.SDXL
        elif path is not None and path.startswith("Turbo") or is_turbo:
            architecture_type = ArchitectureType.TURBO
        elif path is not None and (path.lower().startswith("flux")) or is_flux:
            architecture_type = ArchitectureType.FLUX
        else:
            architecture_type = ArchitectureType.SD_15
        return architecture_type

    def __init__(self, id, path=None, is_lora=False, is_xl=False, is_turbo=False, is_flux=False, clip_req=None, lora_strength=Globals.DEFAULT_LORA_STRENGTH):
        self.id = id
        self.path = path if path else os.path.join(Model.MODELS_DIR, id)
        self.architecture_type = Model.get_architecture_type(id, path, is_xl, is_turbo, is_flux)
        self.is_lora = is_lora
        self.positive_tags = None
        self.negative_tags = None
        self.clip_req = clip_req
        self.lora_strength = lora_strength
        self.lora_strength_clip = lora_strength

    def is_sd_15(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.SD_15

    def is_xl(self):
        # NOTE Illustrious uses SDXL architecture but produces larger images, so it is not technically XL
        return self.architecture_type == ArchitectureType.SDXL or self.architecture_type == ArchitectureType.ILLUSTRIOUS

    def is_illustrious(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.ILLUSTRIOUS

    def is_turbo(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.TURBO

    def is_flux(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.FLUX

    def get_default_lora(self):
        return "add_detail" if self.is_sd_15() else "add-detail-xl"

    def get_other_default_lora(self):
        return "add-detail" if not self.is_sd_15() else "add-detail-xl"

    def get_lora_text(self):
        if not self.is_lora:
            raise Exception("Model is not of type LoRA")
        name = self.id if "." not in self.id else self.id[:self.id.index(".")]
        if self.lora_strength_clip is not None and self.lora_strength_clip != self.lora_strength:
            return f" <lora:{name}:{self.lora_strength}:{self.lora_strength_clip}>"
        else:
            return f" <lora:{name}:{self.lora_strength}>"

    def get_default_vae(self):
        return Model.DEFAULT_SDXL_VAE if self.is_xl() or self.is_turbo else Model.DEFAULT_SD15_VAE

    def validate_vae(self, vae):
        if self.is_flux():
            return # Flux models use their own VAE
        if self.is_xl() or self.is_turbo():
            if vae != Model.DEFAULT_SDXL_VAE: # TODO update if more
                raise Exception(f"Invalid VAE {vae} for SDXL model {self.id}")
        else:
            if vae == Model.DEFAULT_SDXL_VAE:
                raise Exception(f"Invalid SDXL VAE {vae} for model {self.id}")

    def validate_loras(self, lora_bundle):
        if self.is_xl() or self.is_turbo():
            if not lora_bundle.is_xl: # TODO update if more
                if isinstance(lora_bundle, Model) and self.get_other_default_lora() in lora_bundle.id:
                    return Model.get_model(self.get_default_lora(), is_lora=True, is_xl=self.is_xl())
                else:
                    raise Exception(f"Invalid non-SDXL Lora {lora_bundle} for SDXL model {self.id}")
        else:
            if lora_bundle.is_xl:
                if isinstance(lora_bundle, Model) and self.get_other_default_lora() in lora_bundle.id:
                    return Model.get_model(self.get_default_lora(), is_lora=True, is_xl=self.is_xl())
                else:
                    raise Exception(f"Invalid SDXL lora {lora_bundle} for non-SDXL model {self.id}")
        return lora_bundle

    def __str__(self):
        if self.is_lora:
            return "Model " + self.id + " - LoRA: " + str(self.is_lora) + " - Strength: " + str(self.lora_strength) + " - XL: " + str(self.is_xl())
        else:
            return "Model " + self.id + " - Architecture: " + str(self.architecture_type)

    def __eq__(self, other):
        if isinstance(other, Model):
            return self.id == other.id
        return False

    def hash(self):
        return hash(self.id)

    def get_illustrious_model(self):
        if self.is_illustrious():
            return self
        return Model.get_model(Model.DEFAULT_ILLUSTRIOUS_MODEL)

    def get_xl_model(self):
        if self.is_xl():
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
            filtered_list = [model_name for model_name, model in models.items() if (model.is_xl() == (is_xl == 1))]
            # print(filtered_list)
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
                        if is_xl == 0 or is_xl == 1 or "xl" not in model_name.lower():
                            model = models[_model_name]
                elif is_lora or "inpaint" not in model_name:
                    if is_xl == 0 or is_xl == 1 or "xl" not in model_name.lower():
                        model = models[_model_name]

        if model is None:
            for _model_name in models:
                model_name = _model_name.lower()
                if model_tag in model_name:
                    if inpainting:
                        if "inpainting" in model_name:
                            if is_xl == 0 or is_xl == 1 or "xl" not in model_name.lower():
                                model = models[_model_name]
                    elif "inpainting" not in model_name:
                        if is_xl == 0 or is_xl == 1 or "xl" not in model_name.lower():
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
                        raise Exception("Expected lora for use of Lora bundle token \"+\"")
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
            if not file.endswith("ckpt") and not file.endswith("safetensors") and not file.endswith("pth") and not file.endswith("pt"):
                continue
            model_name = re.sub("^.+\\\\", "", file)
            is_xl = file.startswith("XL")
            is_turbo = file.startswith("Turbo")
            is_flux = file.startswith("Flux")
            model = Model(model_name, file, is_xl=is_xl, is_lora=is_lora, is_turbo=is_turbo, is_flux=is_flux)
            models[model_name] = model
            print(model)
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
                if "architecture_type" in preset_config:
                    architecture_type_str = preset_config["architecture_type"]
                    try:
                        model.architecture_type = ArchitectureType[architecture_type_str]
                    except Exception as e:
                        print(f"Failed to set architecture_type {architecture_type_str} for model {model}: {e}")
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




