import glob
import os
import random
import re
from typing import TypeVar

from sd_runner.blacklist import Blacklist, BlacklistException
from sd_runner.model_adapters import LoraBundle
from utils.config import config
from utils.globals import Globals, PromptMode, ModelBlacklistMode, WorkflowType, ArchitectureType, ResolutionGroup
from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._

logger = get_logger("models")


class Model:
    T = TypeVar('T', bound='Model')
    DEFAULT_SD15_MODEL = "analogMadness"
    DEFAULT_XL_MODEL = "realvisXLV20"
    DEFAULT_TURBO_MODEL = "realvisxlV30Turbo"
    DEFAULT_ILLUSTRIOUS_MODEL = "Illustrious-XL-v1.0"
    DEFAULT_SDXL_VAE = "sdxl_vae.safetensors"
    DEFAULT_SD15_VAE = "vae-ft-mse-840000-ema-pruned.ckpt"
    DEFAULT_CHROMA_VAE = "ae.safetensors"
    MODELS_DIR = config.models_dir
    CHECKPOINTS = {}
    LORAS = {}

    @staticmethod
    def determine_architecture_type(model_id, path, is_xl, is_turbo, is_flux, is_chroma, is_z_image_turbo, is_qwen):
        # NOTE this can be overridden by the presets
        if "Illustrious" in model_id:
            # print(f"Assuming model is based on IllustriousXL architecture: {model_id}")
            architecture_type = ArchitectureType.ILLUSTRIOUS
        elif path is not None and (path.lower().startswith("chroma") or "chroma" in path.lower()) or is_chroma:
            architecture_type = ArchitectureType.CHROMA
        elif path is not None and (path.lower().startswith("zimage") or "z_image" in path.lower() or "zimage" in path.lower()) or is_z_image_turbo:
            architecture_type = ArchitectureType.Z_IMAGE_TURBO
        elif path is not None and ("qwen" in path.lower()) or is_qwen:
            architecture_type = ArchitectureType.QWEN
        elif path is not None and path.startswith("XL") or is_xl:
            architecture_type = ArchitectureType.SDXL
        elif path is not None and path.startswith("Turbo") or is_turbo:
            architecture_type = ArchitectureType.TURBO
        elif path is not None and (path.lower().startswith("flux")) or is_flux:
            architecture_type = ArchitectureType.FLUX
        else:
            architecture_type = ArchitectureType.SD_15
        return architecture_type

    def __init__(
        self,
        id: str,
        path: str = None,
        is_lora: bool = False,
        is_xl: bool = False,
        is_turbo: bool = False,
        is_flux: bool = False,
        is_chroma: bool = False,
        is_z_image_turbo: bool = False,
        is_qwen: bool = False,
        clip_req: float = None,
        lora_strength: float = Globals.DEFAULT_LORA_STRENGTH
    ):
        self.id = id
        self.path = path if path else os.path.join(Model.MODELS_DIR, id)
        self.architecture_type = Model.determine_architecture_type(
            id, path, is_xl, is_turbo, is_flux, is_chroma, is_z_image_turbo, is_qwen
        )
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

    def is_chroma(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.CHROMA

    def is_z_image_turbo(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.Z_IMAGE_TURBO

    def is_qwen(self):
        return not self.is_lora and self.architecture_type == ArchitectureType.QWEN

    def get_default_lora(self):
        if self.is_chroma():
            return "lenovo_chroma"
        return "add_detail" if self.is_sd_15() else "add-detail-xl"

    def get_other_default_lora(self):
        return "add-detail" if not self.is_sd_15() else "add-detail-xl"

    def get_standard_resolution_group(self) -> ResolutionGroup:
        if self.is_sd_15():
            return ResolutionGroup.SEVEN_SIXTY_EIGHT
        elif self.is_illustrious():
            return ResolutionGroup.FIFTEEN_THIRTY_SIX
        elif self.is_xl():
            return ResolutionGroup.TEN_TWENTY_FOUR
        elif self.is_turbo():
            return ResolutionGroup.TEN_TWENTY_FOUR
        elif self.is_flux():
            return ResolutionGroup.TEN_TWENTY_FOUR
        elif self.is_chroma():
            return ResolutionGroup.TEN_TWENTY_FOUR
        elif self.is_z_image_turbo():
            return ResolutionGroup.TEN_TWENTY_FOUR
        elif self.is_qwen():
            return ResolutionGroup.THIRTEEN_TWENTY_EIGHT
        else:
            return ResolutionGroup.FIVE_ONE_TWO

    def get_architecture_type(self) -> ArchitectureType:
        """Get the architecture type as a string."""
        return self.architecture_type

    def get_file_creation_date(self) -> str:
        """Get the creation date of a model file."""
        try:
            from datetime import datetime
            
            # Construct full file path
            if self.path:
                if os.path.isabs(self.path):
                    file_path = self.path
                else:
                    # Relative path from models directory
                    lora_or_sd = "Lora" if self.is_lora else "Stable-diffusion"
                    root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
                    file_path = os.path.join(root_dir, self.path)
            else:
                # Fallback to model name
                lora_or_sd = "Lora" if self.is_lora else "Stable-diffusion"
                root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
                file_path = os.path.join(root_dir, self.id)
            
            if os.path.exists(file_path):
                # Get file creation time
                stat = os.stat(file_path)
                # Use st_ctime (creation time on Windows, change time on Unix)
                creation_time = stat.st_ctime
                dt = datetime.fromtimestamp(creation_time)
                return dt.strftime("%Y-%m-%d %H:%M")
            else:
                return "Unknown"
        except Exception:
            return "Unknown"

    def is_blacklisted(self, prompt_mode: PromptMode = PromptMode.SFW) -> bool:
        """Check if this model is blacklisted.
        
        Args:
            prompt_mode: The current prompt mode to check against blacklist settings
            
        Returns:
            bool: True if the model is blacklisted, False otherwise
        """
        if Blacklist.is_model_empty():
            return False
        
        # Check if blacklist allows this prompt mode
        if Blacklist.get_model_blacklist_mode() == ModelBlacklistMode.ALLOW_IN_NSFW and prompt_mode.is_nsfw():
            return False
        
        # Check if model violates blacklist
        return Blacklist.get_model_blacklist_violations(self.id)

    def get_lora_text(self):
        if not self.is_lora:
            raise Exception("Model is not of type LoRA")
        name = self.id if "." not in self.id else self.id[:self.id.index(".")]
        if self.lora_strength_clip is not None and self.lora_strength_clip != self.lora_strength:
            return f" <lora:{name}:{self.lora_strength}:{self.lora_strength_clip}>"
        else:
            return f" <lora:{name}:{self.lora_strength}>"

    def get_default_vae(self):
        if self.is_chroma() or self.is_z_image_turbo():
            return Model.DEFAULT_CHROMA_VAE
        if self.is_qwen():
            # Qwen uses its own VAE in ComfyUI; we don't enforce a specific SD VAE
            return None
        return Model.DEFAULT_SD15_VAE if self.is_sd_15() else Model.DEFAULT_SDXL_VAE

    def validate_vae(self, vae):
        if self.is_flux():
            return # Flux models use their own VAE
        if self.is_chroma():
            if vae != Model.DEFAULT_CHROMA_VAE:
                raise Exception(f"Invalid VAE {vae} for Chroma model {self.id}. Expected {Model.DEFAULT_CHROMA_VAE}")
            return
        if self.is_z_image_turbo():
            if vae != Model.DEFAULT_CHROMA_VAE:
                raise Exception(f"Invalid VAE {vae} for ZImageTurbo model {self.id}. Expected {Model.DEFAULT_CHROMA_VAE}")
            return
        if self.is_qwen():
            # Don't enforce a specific VAE for Qwen models
            return
        if self.is_xl() or self.is_turbo():
            if vae != Model.DEFAULT_SDXL_VAE: # TODO update if more
                raise Exception(f"Invalid VAE {vae} for SDXL model {self.id}")
        else:
            if vae == Model.DEFAULT_SDXL_VAE:
                raise Exception(f"Invalid SDXL VAE {vae} for model {self.id}")

    def validate_loras(self, lora_bundle):
        if self.is_xl() or self.is_turbo():
            if not lora_bundle.is_xl(): # TODO update if more
                if isinstance(lora_bundle, Model) and self.get_other_default_lora() in lora_bundle.id:
                    return Model.get_model(self.get_default_lora(), is_lora=True, architecture_type=self.architecture_type)
                else:
                    raise Exception(f"Invalid non-SDXL Lora {lora_bundle} for SDXL model {self.id}")
        else:
            if lora_bundle.is_xl():
                if isinstance(lora_bundle, Model) and self.get_other_default_lora() in lora_bundle.id:
                    return Model.get_model(self.get_default_lora(), is_lora=True, architecture_type=self.architecture_type)
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
    def get_model(
        model_tag: str,
        is_lora=False,
        inpainting=False,
        architecture_type=None
    ) -> T:
        if model_tag is None or model_tag.strip() == "":
            return None

        models = Model.LORAS if is_lora else Model.CHECKPOINTS

        if model_tag == "*":
            if is_lora:
                # For loras, architecture_type is required since a model has already been established
                if architecture_type is None:
                    raise Exception("architecture_type is required for wildcard '*' when is_lora=True")
                filtered_list = [model_name for model_name, model in models.items() 
                                if model.get_architecture_type() == architecture_type]
            else:
                # For checkpoints, architecture_type is optional (caller can provide if needed)
                if architecture_type is not None:
                    filtered_list = [model_name for model_name, model in models.items() 
                                    if model.get_architecture_type() == architecture_type]
                else:
                    # No filtering - return any random model
                    filtered_list = list(models.keys())
            # print(filtered_list)
            if not filtered_list:
                raise Exception(f"No models found matching architecture type {architecture_type} for wildcard '*'")
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
        # Strip common file extensions to support lookup with or without extension
        if '.' in model_tag:
            ext = model_tag.lower().split('.')[-1]
            if ext in ('safetensors', 'ckpt', 'pth', 'pt'):
                model_tag = model_tag.rsplit('.', 1)[0]
        model_tag = model_tag.lower()
        model = None
        for _model_name in models:
            model_name = _model_name.lower()
            if model_name.startswith(model_tag):
                if not is_lora and inpainting:
                    if "inpaint" in model_name:
                        model = models[_model_name]
                elif is_lora or "inpaint" not in model_name:
                    model = models[_model_name]

        if model is None:
            for _model_name in models:
                model_name = _model_name.lower()
                if model_tag in model_name:
                    if inpainting:
                        if "inpainting" in model_name:
                            model = models[_model_name]
                    elif "inpainting" not in model_name:
                        model = models[_model_name]

        if model is None:
            raise Exception(f"Failed to find model for tag {model_tag}, inpainting={inpainting}")        
        if lora_strength is not None:
            model.lora_strength = lora_strength
        if lora_strength_clip is not None:
            model.lora_strength_clip = lora_strength_clip
        return model

    @staticmethod
    def get_models(
        model_tags_str: str,
        is_lora=False,
        default_tag="analogMadness",
        inpainting=False,
        architecture_type=None
    ) -> list[T]:
        if model_tags_str is None or model_tags_str.strip() == "":
            model_tags_str = default_tag
        model_tags = model_tags_str.split(",")
        models = []
        for model_tag in model_tags:
            tag = model_tag.strip()
            if tag == "":
                continue
            try:
                if "+" in tag:
                    if not is_lora:
                        raise Exception("Expected lora for use of Lora bundle token '+'")
                    bundle_model_tags = tag.replace("+", ",")
                    try:
                        bundle = Model.get_models(bundle_model_tags, is_lora=is_lora, default_tag=default_tag, inpainting=inpainting, architecture_type=architecture_type)
                        if len(bundle) > 0:
                            models.append(LoraBundle(bundle))
                        else:
                            if config.debug:
                                print(f"No models found for bundle tag: {tag}")
                    except Exception as e:
                        if config.debug:
                            print(f"Failed to resolve bundle tag '{tag}': {e}")
                else:
                    try:
                        models.append(Model.get_model(tag, is_lora, inpainting=inpainting, architecture_type=architecture_type))
                    except Exception:
                        alt_tag = tag.replace("-", "_") if "-" in tag else tag.replace("_", "-")
                        models.append(Model.get_model(alt_tag, is_lora, inpainting=inpainting, architecture_type=architecture_type))
            except Exception as e:
                if config.debug:
                    print(f"Failed to find model for tag '{tag}' - skipping")
        return models

    @staticmethod
    def load_models(is_lora):
        models = {}
        lora_or_sd = "Lora" if is_lora else "Stable-diffusion"
        root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
        if config.debug:
            print(f"Loading models from {root_dir}")
        for file in glob.glob(pathname="**/*", root_dir=root_dir, recursive=True):
            if not file.endswith("ckpt") and not file.endswith("safetensors") and not file.endswith("pth") and not file.endswith("pt"):
                continue
            model_name = re.sub("^.+\\\\", "", file)
            is_xl = file.startswith("XL")
            is_turbo = file.startswith("Turbo")
            is_flux = file.startswith("Flux")
            is_chroma = file.lower().startswith("chroma") or "chroma" in file.lower()
            is_z_image_turbo = file.lower().startswith("zimage") or "z_image" in file.lower() or "zimage" in file.lower()
            is_qwen = "qwen" in file.lower()
            model = Model(
                model_name,
                file,
                is_xl=is_xl,
                is_lora=is_lora,
                is_turbo=is_turbo,
                is_flux=is_flux,
                is_chroma=is_chroma,
                is_z_image_turbo=is_z_image_turbo,
                is_qwen=is_qwen,
            )
            models[model_name] = model
            # print(model)
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
                logger.warning(f"Failed to get model to set presets with exception: {e}")
            for model in models:
                if "architecture_type" in preset_config:
                    architecture_type_str = preset_config.get("architecture_type", None)
                    try:
                        model.architecture_type = ArchitectureType[architecture_type_str]
                    except Exception as e:
                        print(f"Failed to set architecture_type {architecture_type_str} for model {model}: {e}")
                if "clip_req" in preset_config:
                    model.clip_req = preset_config.get("clip_req", None)
                if "prompt_tags" in preset_config:
                    for prompt_mode_name, prompt_config in preset_config["prompt_tags"].items():
                        if prompt_mode_name in PromptMode.__members__.keys():
                            prompt_mode_config = PromptMode[prompt_mode_name]
                            if prompt_mode_config == prompt_mode:
                                model.positive_tags = prompt_config.get("positive", None)
                                model.negative_tags = prompt_config.get("negative", None)
                        else:
                            model.positive_tags = prompt_config.get("positive", None)
                            model.negative_tags = prompt_config.get("negative", None)

    @staticmethod
    def get_first_model_lora_tags(model_tags, lora_tags):
        # TODO in case there was a model switch, need to be sure the default lora for the model type is set.
        pass

    @staticmethod
    def get_first_model_prompt_massage_tags(
        model_tags_str,
        prompt_mode=PromptMode.SFW,
        inpainting=False,
        default_tag=""
    ) -> tuple[str, list[T]]:
        Model.load_all_if_unloaded()
        Model.set_model_presets(prompt_mode)
        models = []
        try:
            models = Model.get_models(model_tags_str, default_tag=default_tag, inpainting=inpainting)
        except Exception as e:
            print(e)
        prompt_massage_tags = ""
        if len(models) == 1:
            # print(models[0])
            # print(models[0].positive_tags)
            tags_from_model = models[0].positive_tags
            if tags_from_model:
                prompt_massage_tags = tags_from_model
        return prompt_massage_tags, models

    @staticmethod
    def validate_model_blacklist(
        tags_str,
        prompt_mode=PromptMode.SFW,
        default_tag="analogMadness",
        is_lora=False,
        inpainting=False,
        architecture_type=None
    ) -> dict[str, list[str]]:
        if Blacklist.is_model_empty():
            return {}
        if Blacklist.get_model_blacklist_mode() == ModelBlacklistMode.ALLOW_IN_NSFW and prompt_mode.is_nsfw():
            return {}
        models = Model.get_models(tags_str, is_lora=is_lora, default_tag=default_tag, inpainting=inpainting, architecture_type=architecture_type)
        whitelist = []
        violations = []
        for model in models:
            model_violates_blacklist = Blacklist.get_model_blacklist_violations(model.id)
            if model_violates_blacklist:
                violations.append(model.id)
            else:
                whitelist.append(model.id)

        if violations:
            if is_lora:
                if Blacklist.get_blacklist_silent_removal():
                    raise BlacklistException(_("One or more loras are blacklisted. Please try again with a different lora."),
                                             whitelist=whitelist,
                                             filtered=violations)
                else:
                    raise BlacklistException(_("The following loras are blacklisted: {0}\n\nPlease try again with a different lora.").format(list(violations.keys())),
                                             whitelist=whitelist,
                                             filtered=violations)
            else:
                if Blacklist.get_blacklist_silent_removal():
                    raise BlacklistException(_("One or more models are blacklisted. Please try again with a different model."),
                                             whitelist=whitelist,
                                             filtered=violations)
                else:
                    raise BlacklistException(_("The following models are blacklisted: {0}\n\nPlease try again with a different model.").format(violations),
                                             whitelist=whitelist,
                                             filtered=violations)




