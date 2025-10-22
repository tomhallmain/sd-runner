import base64
import json
import os
from urllib import request, response, parse, error
import time
import traceback
import threading
from typing import Optional

from sd_runner.gen_config import GenConfig
from utils.globals import Globals, WorkflowType, PromptTypeSDWebUI

from sd_runner.base_image_generator import BaseImageGenerator
from sd_runner.models import Model, LoraBundle
from sd_runner.prompter import PrompterConfiguration
from sd_runner.workflow_prompt import WorkflowPromptSDWebUI
from utils.config import config
from utils.utils import Utils


def timestamp_str():
    time_str = str(time.time()).replace(".", "")
    while len(time_str) < 17:
        time_str += "0"
    return time_str

def encode_file_to_base64(path):
    try:
        if not os.path.exists(path):
            raise FileNotFoundError(f"File does not exist: {path}")
        
        file_size = os.path.getsize(path)
        
        if file_size == 0:
            raise ValueError(f"File is empty: {path}")
        
        with open(path, 'rb') as file:
            data = file.read()
            encoded = base64.b64encode(data).decode('utf-8')
            return encoded
    except Exception as e:
        print(f"[CLIENT ERROR] Failed to encode file {path}: {type(e).__name__}: {e}")
        raise


def decode_and_save_base64(base64_str, save_path):
    with open(save_path, "wb") as file:
        file.write(base64.b64decode(base64_str))



class SDWebuiGen(BaseImageGenerator):
    BASE_URL = config.sd_webui_url
    TXT_2_IMG = "sdapi/v1/txt2img"
    IMG_2_IMG = "sdapi/v1/img2img"
    _has_run_txt2img = False  # Class-level flag to track if txt2img has been run
    _txt2img_lock = threading.Lock()  # Thread-safe lock for the flag

    def __init__(self, config=GenConfig(), ui_callbacks=None):
        super().__init__(config, ui_callbacks)

    def prompt_setup(self, workflow_type: WorkflowType, action: str, prompt: Optional[WorkflowPromptSDWebUI], model: Model, vae=None, resolution=None, **kw):
        if prompt:
            raise Exception("Redo prompt not supported for SDWebui at this time")
            # prompt.set_from_workflow(workflow_type.value)
            # model, vae = prompt.check_for_existing_image(model, vae, resolution)
        else:
            self.print_pre(action=action, model=model, vae=vae, resolution=resolution, **kw)
            if not prompt:
                prompt = WorkflowPromptSDWebUI(workflow_type.value)
        return prompt, model, vae

    def _get_workflows(self) -> dict:
        """Return a dictionary mapping workflow IDs to methods"""
        return {
            WorkflowType.ANIMATE_DIFF: None,
            WorkflowType.CONTROLNET: self.control_net,
            WorkflowType.ELLA: None,
            WorkflowType.INPAINT_CLIPSEG: None,
            WorkflowType.INSTANT_LORA: self.instant_lora,
            WorkflowType.IP_ADAPTER: self.ip_adapter,
            WorkflowType.IMG2IMG: self.img2img,
            WorkflowType.REDO_PROMPT: self.redo_with_different_parameter,
            WorkflowType.RENOISER: None,
            WorkflowType.SIMPLE_IMAGE_GEN_LORA: self.simple_image_gen_lora,
            WorkflowType.SIMPLE_IMAGE_GEN_TILED_UPSCALE: None,            
            WorkflowType.SIMPLE_IMAGE_GEN: self.simple_image_gen,
            WorkflowType.TURBO: None,
            WorkflowType.UPSCALE_BETTER: None,
            WorkflowType.UPSCALE_SIMPLE: self.upscale_simple,
        }

    # @staticmethod
    # def schedule_prompt(prompt, img2img=False, related_image_path=None, workflow=None):
    #     Utils.start_thread(self.queue_prompt, use_asyncio=False, args=[prompt, img2img, related_image_path, workflow])

    def queue_prompt(self, prompt: WorkflowPromptSDWebUI, img2img: bool=False, related_image_path: Optional[str]=None, workflow: Optional[WorkflowType]=None):
        api_endpoint = SDWebuiGen.IMG_2_IMG if img2img else SDWebuiGen.TXT_2_IMG
        data = prompt.get_json()
        req = request.Request(
            f'{SDWebuiGen.BASE_URL}/{api_endpoint}',
            headers={'Content-Type': 'application/json'},
            data=data,
        )
        try:
            resp = request.urlopen(req)
            result = self.save_image_data(resp, related_image_path, workflow, self.gen_config.get_prompter_config())
        except error.URLError as e:
            print(f"[CLIENT ERROR] URLError: {e}")
            if related_image_path:
                print(f"[CLIENT ERROR] Related image path: {related_image_path}")
            raise Exception("Failed to connect to SD Web UI. Is SD Web UI running?")
        except Exception as e:
            print(f"[CLIENT ERROR] Unexpected error: {type(e).__name__}: {e}")
            raise
        return result

    def save_image_data(self, response: response, related_image_path: Optional[str]=None, workflow: Optional[WorkflowType]=None, prompter_config: Optional[PrompterConfiguration]=None):
        resp_json = json.loads(response.read().decode('utf-8'))
        for index, image in enumerate(resp_json.get('images')):
            if workflow == PromptTypeSDWebUI.CONTROLNET and index % 2 == 1:
                continue # Extra control net mask is not an image we want to save.
            save_path = os.path.join(config.sd_webui_save_path, f'SDWebUI_{timestamp_str()}_{index}.png')
            decode_and_save_base64(image, save_path)
            if related_image_path is not None:
                Globals.get_image_data_extractor().add_related_image_path(save_path, related_image_path)
            # Add original prompt decomposition to EXIF data
            if prompter_config is not None:
                Globals.get_image_data_extractor().add_prompt_decomposition_to_exif(save_path, prompter_config.original_positive_tags, original_negative_tags=None)
        with self._lock:
            self.pending_counter -= 1
            self.update_ui_pending()
        return save_path

    @staticmethod
    def clear_history():
        pass # TODO figure out if there is a history api

    def _run_fake_txt2img(self, model, vae=None):
        """Run a minimal txt2img generation to fix a known SD WebUI bug.
        
        There is a bug in stable-diffusion-webui where img2img processes will fail if they are the first
        generation run during the application's runtime. This bug persists until at least one txt2img
        process has been run. This method provides a workaround by running a minimal txt2img generation
        with empty prompts before the first img2img request.
        
        The fake generation uses the same model and VAE as the requested img2img to ensure compatibility
        and minimal resource usage. The generated image is temporarily saved but immediately deleted.
        
        Args:
            model: The model to use for the fake generation, should match the model being used for img2img
            vae: The VAE to use for the fake generation, should match the VAE being used for img2img
        """
        with SDWebuiGen._txt2img_lock:
            if not SDWebuiGen._has_run_txt2img:
                print("Running initial txt2img to fix SD WebUI img2img bug...")
                prompt = WorkflowPromptSDWebUI(WorkflowType.SIMPLE_IMAGE_GEN.value)
                prompt.set_model(model)
                prompt.set_vae(vae)
                prompt.set_clip_texts("", "", model=model)
                prompt.set_seed(self.get_seed())
                prompt.set_other_sampler_inputs(self.gen_config)
                prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", None))
                prompt.set_empty_latents(1)
                try:
                    fake_image_path = self.queue_prompt(prompt)
                except Exception as e:
                    # Maybe SDWebUI is not running?
                    raise Exception(f"Warning: Failed to run fake txt2img: {e}")
                try:
                    if fake_image_path and os.path.exists(fake_image_path):
                        os.unlink(fake_image_path)
                except Exception as e:
                    print(f"Warning: Failed to clean up fake txt2img image: {e}")
                SDWebuiGen._has_run_txt2img = True

    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling Simple Image Gen prompt", prompt=prompt, model=model, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        seed = self.gen_config.redo_param("seed", self.get_seed())
        prompt.set_seed(seed)
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt)
        self._has_run_txt2img = True

    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA, "Assembling Simple Image Gen LoRA prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, lora=lora, n_latents=n_latents, positive=positive, negative=negative)
        lora = model.validate_loras(lora)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        prompt.set_lora(self.gen_config.redo_param("lora", lora)) # must set after set_clip_texts
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt)
        self._has_run_txt2img = True

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.UPSCALE_SIMPLE, "Assembling simple upscale image prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=1, positive="", negative="", upscale_image=control_net)
        # prompt.set_upscaler_model()
        prompt.set_image_scale_to_side(1024) # Max image side length
        control_net = self.gen_config.redo_param("control_net", control_net)
        self.queue_prompt(prompt)

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, **kw):
        # control_v11p_sd15_canny [d14c016b]
        # diffusers_xl_depth_full [2f51180b]
        # sai_xl_depth_256lora [73ad23d1]
        # t2i-adapter_diffusers_xl_depth_midas [9c183166]
        # t2i-adapter_diffusers_xl_depth_zoe [cc102381]
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(control_net.generation_path, round_to=16)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.CONTROLNET, "Assembling Control Net prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, lora=lora)
        model = self.gen_config.redo_param("model", model)
        lora = model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        if lora is not None and lora != "":
            prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        image_path = self.gen_config.redo_param("control_net", control_net.generation_path)
        if image_path is None:
            return
        prompt.set_control_net_image(encode_file_to_base64(image_path))
        prompt.set_control_net_strength(control_net.strength)
        prompt.set_latent_dimensions(resolution)
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt, related_image_path=control_net.id, workflow=PromptTypeSDWebUI.CONTROLNET)

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        prompt, model, vae = self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling Img2Img prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, lora=lora, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        vae = self.gen_config.redo_param("vae", vae)
        lora = model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(vae)
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        if lora is not None and lora!= "":
            prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if ip_adapter.id is None:
            return
        ip_adapter_model, clip_vision_model = self.gen_config.get_ip_adapter_models()
        # prompt.set_ip_adapter_model(ip_adapter_model)
        # prompt.set_clip_vision_model(clip_vision_model)
        prompt.set_denoise(1 - ip_adapter.strength)
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
        prompt.set_img2img_image(encode_file_to_base64(image_path))
        prompt.set_latent_dimensions(resolution)
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))

        # Run fake txt2img if needed to fix the SD WebUI bug
        self._run_fake_txt2img(model, vae)

        self.queue_prompt(prompt, img2img=True, related_image_path=ip_adapter.id)

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        prompt, model, vae = self.prompt_setup(WorkflowType.IMG2IMG, "Assembling Img2Img prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, lora=lora, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        vae = self.gen_config.redo_param("vae", vae)
        lora = model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(vae)
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        if lora is not None and lora!= "":
            prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if ip_adapter.id is None:
            return
        prompt.set_denoise(1 - ip_adapter.strength)  # Inverse of ip_adapter strength
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
        prompt.set_img2img_image(encode_file_to_base64(image_path))
        prompt.set_latent_dimensions(resolution)
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))

        # Run fake txt2img if needed to fix the SD WebUI bug
        self._run_fake_txt2img(model, vae)

        self.queue_prompt(prompt, img2img=True, related_image_path=ip_adapter.id)

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.INSTANT_LORA, "Assembling Img2Img ControlNet prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        lora = model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        if lora is not None and lora!= "":
            prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if ip_adapter.id is None or control_net.id is None:
            return
        image_path = self.gen_config.redo_param("control_net", control_net.id)
        prompt.set_control_net_image(encode_file_to_base64(image_path))
        prompt.set_control_net_strength(control_net.strength)
#        ip_adapter_model, clip_vision_model = self.gen_config.get_ip_adapter_models()
 #       prompt.set_ip_adapter_model(ip_adapter_model)
 #       prompt.set_clip_vision_model(clip_vision_model) TODO update these
        prompt.set_denoise(1 - ip_adapter.strength)
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
        prompt.set_img2img_image(encode_file_to_base64(image_path))
        prompt.set_latent_dimensions(resolution)
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt, img2img=True, related_image_path=ip_adapter.id)

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        self.print_pre("Assembling redo prompt", model=model, resolution=resolution, vae=vae, n_latents=n_latents, positive="", negative="", lora=lora, control_net=control_net, ip_adapter=ip_adapter)
        prompt = WorkflowPromptSDWebUI(source_file)

        # If this is not an API prompt, handle in an annoying way
        if not prompt.validate_api_prompt():
            print("Not an API prompt image: " + source_file)
            try:
                if prompt.try_set_workflow_non_api_prompt():
                    resolution = prompt.temp_redo_inputs.resolution
                    model = prompt.temp_redo_inputs.model
                    vae = prompt.temp_redo_inputs.vae
                    lora = prompt.temp_redo_inputs.lora
                    positive = prompt.temp_redo_inputs.positive
                    negative = prompt.temp_redo_inputs.negative
                    control_net = prompt.temp_redo_inputs.control_net
                    ip_adapter = prompt.temp_redo_inputs.ip_adapter
                    self.run_workflow(prompt.workflow_filename, prompt=prompt, resolution=resolution, model=model, vae=vae, n_latents=n_latents, positive=positive,
                                      negative=negative, lora=lora, control_net=control_net, ip_adapter=ip_adapter)
                else:
                    print(Utils.format_red("Invalid prompt for file: " + source_file))
                    return
            except Exception:
                traceback.print_exc()
                return

        try:
            prompt.set_empty_latents(n_latents)
        except Exception:
            print("Failed to set number of empty latents")

        has_made_one_change = False
        if "model" not in GenConfig.REDO_PARAMETERS and "models" not in GenConfig.REDO_PARAMETERS:
            model = Model.get_model(prompt.get_model())

        for attr in GenConfig.REDO_PARAMETERS:
            try:
                if attr.startswith("model"):
                    prompt.set_model(model)
                elif attr.startswith("vae"):
                    prompt.set_vae(vae)
                elif attr.startswith("resolution"):
                    prompt.set_latent_dimensions(resolution)
                elif attr.startswith("lora"):
                    prompt.set_lora(lora)
                elif attr.startswith("control_net"):
                    prompt.set_control_net_image(encode_file_to_base64(control_net.id))
                    prompt.set_control_net_strength(control_net.strength)
                elif attr.startswith("ip_adapter"):
                    prompt.set_img2img_image(encode_file_to_base64(ip_adapter.id))
                    prompt.set_denoise(1 - ip_adapter.strength)
                elif attr == "positive":
                    prompt.set_clip_text(positive, model, positive=True)
                elif attr == "negative":
                    prompt.set_clip_text(negative, model, positive=False)
                elif attr == "n_latents":
                    prompt.set_empty_latents(n_latents) # TODO maybe remove as this is set above
                elif attr == "seed":
                    prompt.set_seed(self.get_seed())
                else:
                    raise Exception("Unhandled redo parameter: " + attr)
                print("Redoing parameter with different value: " + attr)
                has_made_one_change = True
            except Exception as e:
                print(e)

        if not has_made_one_change:
            print("Did not make any changes to prompt for image: " + source_file)
        
        # if prompt.requires_img2img():
        #     self.queue_prompt()
        # else:
        #     self.queue_prompt(prompt, img2img=False, workflow=)





