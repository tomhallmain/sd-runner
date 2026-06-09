import os
import json
from utils.globals import Globals
from utils.globals import PromptTypeSDWebUI
from utils.globals import Sampler
from utils.globals import Scheduler
from sd_runner.model_adapters import LoraBundle
from .base import WorkflowPrompt


class WorkflowPromptSDWebUI(WorkflowPrompt):
    """
    Used for creating new prompts to serve to the SD Web UI API
    Can also be used for gathering information about prompts stored in images already created by Comfy
    """
    PROMPTS_LOC = os.path.join(WorkflowPrompt.PROMPTS_LOC, "sdwebui")
    ALWAYSON_SCRIPTS_KEY = "alwayson_scripts"
    CONTROLNET_KEY = "ControlNet"

    def __init__(self, workflow_filename):
        if workflow_filename.endswith(".png"):
            raise Exception("Redo not yet supported for SDWebUI")
            # self.full_path = workflow_filename
            # self.json = Globals.get_image_data_extractor().extract_prompt(self.full_path)
        else:
            self.workflow_filename = PromptTypeSDWebUI.convert_to_sd_webui_filename(workflow_filename)
            self.full_path = os.path.join(WorkflowPromptSDWebUI.PROMPTS_LOC, self.workflow_filename)
            self.json = json.load(open(self.full_path, "r"))
        assert self.json is not None
        self.temp_redo_inputs = None
        self.is_xl = None

    def set_from_workflow(self, workflow_filename):
        # TODO this will need to be changed if Redo is implemented for SDWebUI
        self.workflow_filename = workflow_filename
        self.full_path = os.path.join(WorkflowPrompt.PROMPTS_LOC, workflow_filename)
        if self.workflow_filename.endswith(".png"):
            raise Exception("No preset workflow: " + self.workflow_filename)
        self.json = json.load(open(self.full_path, "r"))

    def get_json(self):
        if self.save_prompt:
            with open(WorkflowPrompt.LAST_PROMPT_FILE, "w") as store:
                json.dump(self.json, store, indent=2)
        return json.dumps(self.json).encode('utf-8')

    def set_by_id(self, id_key, value):
        self.json[id_key] = value

    def set_model(self, model):
        if not model:
            return
        override_settings = self.json["override_settings"] if "override_settings" in self.json else {}
        override_settings["sd_model_checkpoint"] = model.path
        self.json["override_settings"] = override_settings

    def get_model(self):
        return self.json["override_settings"]["sd_model_checkpoint"]

    def set_vae(self, vae):
        pass # Nothing to do here

    def get_vae(self):
        return None

    def get_scripts(self):
        return self.json[WorkflowPromptSDWebUI.ALWAYSON_SCRIPTS_KEY]

    def set_empty_latents(self, n_latents):
        if not n_latents:
            return
        self.set_by_id("batch_size", n_latents)
    
    def set_image_duplicator(self, n_latents):
        self.set_empty_latents(n_latents)

    def set_latent_dimensions(self, resolution):
        if not resolution:
            return
        self.set_by_id("width", resolution.width)
        self.set_by_id("height", resolution.height)

    def set_clip_text(self, text, model, positive=True):
        if not text:
            return
        if model:
            if positive:
                text, negative = model.get_model_text(text, "")
            else:
                _positive, text = model.get_model_text("", text)
            if model.clip_req:
                pass # Nothing to do here
        if positive:
            self.set_by_id("prompt", text)
        else:
            self.set_by_id("negative_prompt", text)

    # Have to use IDs because these nodes use the same class type CLIPTextEncode
    def set_clip_texts(self, positive, negative, model=None):
        if not (positive or negative):
            return
        if model:
            positive, negative = model.get_model_text(positive, negative)
            if model.clip_req:
                self.set_clip_last_layer(model.clip_req)
        if positive:
            self.set_by_id("prompt", positive)
        if negative:
            self.set_by_id("negative_prompt", negative)

    def set_clip_last_layer(self, clip_last_layer):
        if not clip_last_layer:
            return
        pass

    def set_clip_seg(self, text):
        if not text:
            return
        pass

    def set_load_image(self, image_path):
        if not image_path:
            return
        pass

    def set_load_image_mask(self, image_path):
        if not image_path:
            return
        pass

    def set_seed(self, seed_val):
        if not seed_val:
            return
        self.set_by_id("seed", seed_val)

    def set_other_sampler_inputs(self, gen_config):
        if gen_config.steps and gen_config.steps > 0:
            self.set_sampler_steps(gen_config.steps)
        if gen_config.cfg and gen_config.cfg > 0:
            self.set_sampler_cfg(gen_config.cfg)
        if gen_config.sampler and gen_config.sampler != Sampler.ACCEPT_ANY:
            self.set_sampler(gen_config.sampler)
        if gen_config.scheduler and gen_config.scheduler != Scheduler.ACCEPT_ANY:
            self.set_scheduler(gen_config.scheduler)
        if gen_config.denoise and gen_config.denoise > 0:
            self.set_denoise(gen_config.denoise)

    def set_sampler_steps(self, steps):
        if not steps:
            return
        self.set_by_id("steps", steps)

    def set_sampler_cfg(self, cfg):
        if not cfg:
            return
        self.set_by_id("cfg", cfg)

    def set_sampler(self, sampler):
        if not sampler:
            return
        self.set_by_id("sampler_name", sampler)

    def set_scheduler(self, scheduler):
        if not scheduler:
            return
        pass
#        self.set_by_id("scheduler", scheduler)

    def set_denoise(self, denoise):
        if not denoise:
            return
        self.set_by_id("denoising_strength", denoise)

    def set_lora(self, lora):
        if not lora:
            return
        assert self.json is not None
        if not "prompt" in self.json or not isinstance(self.json["prompt"], str):
            raise Exception("prompt not found on JSON.")
        positive = self.json["prompt"]

        if isinstance(lora, LoraBundle):
            if len(lora.loras) > 2:
                raise Exception("Only two bundled loras are supported for this workflow at the moment.")
            positive += lora.loras[0].get_lora_text()
            positive += lora.loras[1].get_lora_text()
        else:
            positive += lora.get_lora_text()
        self.json["prompt"] = positive

    def set_upscaler_model(self, model):
        if not model:
            return
        pass
#        self.set_for_class_type("UpscaleModelLoader", "model_name", model)

    def get_controlnet_script_args(self):
        return self.get_scripts()[WorkflowPromptSDWebUI.CONTROLNET_KEY]["args"][0]

    def set_control_net_image(self, image):
        if not image:
            return
        controlnet_script = self.get_controlnet_script_args()
        controlnet_script["image"]["image"] = image

    def set_control_net_strength(self, strength):
        if not strength:
            return
        controlnet_script = self.get_controlnet_script_args()
        controlnet_script["weight"] = strength * 2

    def set_control_net(self, control_net):
        if not control_net:
            return
        self.set_control_net_image(control_net.id)
        self.set_control_net_strength(control_net.strength)

    def set_clip_vision_model(self, model):
        if not model:
            return
        pass
#        self.set_for_class_type(ComfyNodeName.CLIP_VISION, "clip_name", model)

    def set_img2img_image(self, image_path):
        if not image_path:
            return
        self.set_by_id("init_images", [image_path])

    def set_ip_adapter_model(self, model):
        if not model:
            return
        pass

    def set_ip_adapter_strength(self, strength):
        if not strength:
            print("NO STRENGTH FOUND")
            return
        pass

    def set_image_scale_to_side(self, longest):
        if not longest:
            return
        pass

    def validate_api_prompt(self):
        return True

    def is_existing_image_xl(self):
        if self.is_xl is not None:
            return self.is_xl
        self.is_xl = Globals.get_image_data_extractor().is_xl(self.workflow_filename)
        return self.is_xl

    def check_model(self, model):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and not model.is_xl:
            return Model.get_xl_model(model)
        elif not is_xl and model.is_xl:
            return Model.get_sd15_model(model)
        return model

    def check_vae(self, vae):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and vae != Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SDXL_VAE
        elif not is_xl and vae == Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SD15_VAE
        return vae

    def check_resolution(self, resolution):
        is_xl = self.is_existing_image_xl() or self.get_model().is_xl
        if (is_xl and not resolution.is_xl()) or (not is_xl and resolution.is_xl()):
            resolution.switch_mode(is_xl)


