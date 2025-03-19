import json
from urllib import request, parse, error
import traceback

from sd_runner.gen_config import GenConfig
from utils.globals import Globals, WorkflowType, ComfyNodeName

from sd_runner.base_image_generator import BaseImageGenerator
from sd_runner.models import Model, LoraBundle
from sd_runner.workflow_prompt import WorkflowPrompt
from utils.config import config
from utils.utils import Utils


class ComfyGen(BaseImageGenerator):
    BASE_URL = config.comfyui_url
    PROMPT_URL = BASE_URL + "/prompt"
    HISTORY_URL = BASE_URL + "/history"

    def __init__(self, config=GenConfig()):
        super().__init__(config)

    def prompt_setup(self, workflow_type, action, prompt, model, vae=None, resolution=None, **kw):
        if prompt:
            prompt.set_from_workflow(workflow_type.value)
            model, vae = prompt.check_for_existing_image(model, vae, resolution)
        else:
            self.print_pre(action=action, model=model, vae=vae, resolution=resolution, **kw)
            if workflow_type == WorkflowType.SIMPLE_IMAGE_GEN_LORA:
                lora = kw["lora"]
                if isinstance(lora, LoraBundle):
                    prompt = WorkflowPrompt("simple_image_gen_lora2.json")
            if workflow_type == WorkflowType.INSTANT_LORA and model.is_xl():
                prompt = WorkflowPrompt("instant_lora_xl.json")
            if workflow_type == WorkflowType.CONTROLNET and model.is_xl():
                prompt = WorkflowPrompt("controlnet_sdxl.json")
            if not prompt:
                prompt = WorkflowPrompt(workflow_type.value)
        return prompt, model, vae

    def _get_workflows(self) -> dict:
        """Return a dictionary mapping workflow IDs to methods"""
        return {
            WorkflowType.ANIMATE_DIFF: self.animate_diff,
            WorkflowType.CONTROLNET: self.control_net,
            WorkflowType.ELLA: self.ella,
            WorkflowType.INPAINT_CLIPSEG: self.inpaint_clipseg,
            WorkflowType.INSTANT_LORA: self.instant_lora,
            WorkflowType.IP_ADAPTER: self.ip_adapter,
            WorkflowType.REDO_PROMPT: self.redo_with_different_parameter,
            WorkflowType.RENOISER: self.renoiser,
            WorkflowType.SIMPLE_IMAGE_GEN_LORA: self.simple_image_gen_lora,
            WorkflowType.SIMPLE_IMAGE_GEN_TILED_UPSCALE: self.simple_image_gen_tiled_upscale,            
            WorkflowType.SIMPLE_IMAGE_GEN: self.simple_image_gen,
            WorkflowType.TURBO: self.simple_image_gen_turbo,
            WorkflowType.UPSCALE_BETTER: self.upscale_better,
            WorkflowType.UPSCALE_SIMPLE: self.upscale_simple,
        }

    @staticmethod
    def queue_prompt(prompt):
        data = prompt.get_json()
        req = request.Request(ComfyGen.PROMPT_URL, data=data)
        try:
            request.urlopen(req)
        except error.URLError:
            raise Exception("Failed to connect to ComfyUI. Is ComfyUI running?")

    @staticmethod
    def clear_history():
        data = json.dumps({"clear": "true"}).encode('utf-8')
        req = request.Request(ComfyGen.HISTORY_URL, data=data)
        try:
            return request.urlopen(req)
        except error.URLError:
            raise Exception("Failed to connect to ComfyUI. Is ComfyUI running?")

    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling Simple Image Gen prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="3", negative_id="4", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA, "Assembling Simple Image Gen LoRA prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, lora=lora, n_latents=n_latents, positive=positive, negative=negative)
        model.validate_loras(lora)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="3", negative_id="4", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def simple_image_gen_tiled_upscale(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_TILED_UPSCALE, "Assembling Simple Image Gen Tiled Upscale prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="3", negative_id="4", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        width, height = resolution.upscale_rounded()
        prompt.set_for_class_type(ComfyNodeName.IMAGE_SCALE, "width", width)
        prompt.set_for_class_type(ComfyNodeName.IMAGE_SCALE, "height", height)
        ComfyGen.queue_prompt(prompt)

    def simple_image_gen_turbo(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.TURBO, "Assembling Simple Image Gen Turbo prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        # prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="6", negative_id="7", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def ella(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.ELLA, "Assembling Ella prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive)
        model = self.gen_config.redo_param("model", model)
        if not model.is_sd_15() or resolution.is_xl():
            raise Exception("ELLA only supports SD1.5 models and resolutions.")
        prompt.set_model(model)
#        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_for_class_type(ComfyNodeName.ELLA_T5_EMBEDS, "prompt", self.gen_config.redo_param("positive", positive))
        prompt.set_for_class_type(ComfyNodeName.ELLA_SAMPLER, "seed", self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_for_class_type(ComfyNodeName.ELLA_SAMPLER, "steps", self.gen_config.steps) if self.gen_config.steps and self.gen_config.steps > 0 else None
        resolution = self.gen_config.redo_param("resolution", resolution)
        if resolution:
            prompt.set_for_class_type(ComfyNodeName.ELLA_SAMPLER, "width", resolution.width)
            prompt.set_for_class_type(ComfyNodeName.ELLA_SAMPLER, "height", resolution.height)
        prompt.set_for_class_type(ComfyNodeName.ELLA_T5_EMBEDS, "batch_size", self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def renoiser(self, prompt="", model=None, vae=None, n_latents=None, positive=None, negative=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.RENOISER, "Assembling Renoiser prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="21", negative_id="24", model=model)
        prompt.set_seed(0) # changing seed is basically useless for this workflow
#        prompt.set_other_sampler_inputs(self.gen_config)
        control_net = self.gen_config.redo_param("control_net", control_net)
        if control_net:
            prompt.set_by_id("56", "image", control_net.id) # There are two control nets in this workflow, not easy to find right linked input node
            prompt.set_by_id("25", "strength", control_net.strength)
            prompt.set_by_id("30", "strength", control_net.strength)
        ComfyGen.queue_prompt(prompt)

    def inpaint_clipseg(self, prompt="", model=None, vae=None, n_latents=None, positive=None, negative=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.INPAINT_CLIPSEG, "Assembling clipseg-assisted inpaint prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, inpaint_image=control_net)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="2", negative_id="3", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_image_duplicator(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.UPSCALE_SIMPLE, "Assembling simple upscale image prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=1, positive="", negative="", upscale_image=control_net)
        # prompt.set_upscaler_model()
        prompt.set_image_scale_to_side(1024) # Max image side length
        control_net = self.gen_config.redo_param("control_net", control_net)
        if control_net:
            prompt.set_linked_input_node(control_net.id, starting_class_type="ImageUpscaleWithModel")
        ComfyGen.queue_prompt(prompt)

    def upscale_better(self, prompt="", model=None, positive=None, negative=None, control_net=None, **kw):
        """
        Will upscale the image by 2x using SDXL model. If the output size is lower than XL resolutions, may not be a good result
        """
        prompt, model, vae = self.prompt_setup(WorkflowType.UPSCALE_BETTER, "Assembling upscale image better prompt", prompt=prompt, model=model, vae=None, resolution=None, n_latents=1, positive="", negative="", upscale_image=control_net)
        if not model.is_xl():
            raise Exception("SDXL model should be used for the upscale better workflow.")
        positive = self.maybe_caption_image(control_net.id, positive)
#        prompt.set_upscaler_model()
        positive += ", photorealistic, 8kdslr, sharp focus"
        negative += ", anime, illustration"
        positive = self.gen_config.redo_param("positive", positive)
        negative = self.gen_config.redo_param("negative", negative)
        prompt.set_by_id("75", "text_g", positive)
        prompt.set_by_id("75", "text_l", positive)
        prompt.set_by_id("81", "text", negative)
        prompt.set_by_id("82", "text_g", negative)
        prompt.set_by_id("82", "text_l", negative)
        prompt.set_other_sampler_inputs(self.gen_config)
        control_net = self.gen_config.redo_param("control_net", control_net)
        if control_net:
            prompt.set_linked_input_node(control_net.id, starting_class_type="ImageUpscaleWithModel")
        ComfyGen.queue_prompt(prompt)

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.INSTANT_LORA, "Assembling Instant LoRA prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id=None, negative_id="18", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_for_class_type(ComfyNodeName.IMAGE_SCALE_TO_SIDE, "side_length", 1024 if self.gen_config.is_xl() else 768)
        prompt.set_control_net(self.gen_config.redo_param("control_net", control_net))
#        ip_adapter_model, clip_vision_model = self.gen_config.get_ip_adapter_models()
 #       prompt.set_ip_adapter_model(ip_adapter_model)
 #       prompt.set_clip_vision_model(clip_vision_model) TODO update these
        prompt.set_ip_adapter_strength(ip_adapter.strength)
        prompt.set_ip_adapter_image(self.gen_config.redo_param("ip_adapter", ip_adapter.get_id(control_net=control_net)))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(control_net.id)
        prompt, model, vae = self.prompt_setup(WorkflowType.CONTROLNET, "Assembling Control Net prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, lora=lora)
        model = self.gen_config.redo_param("model", model)
        model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id=None, negative_id="18", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if control_net.id is None:
            return
        prompt.set_control_net_image(self.gen_config.redo_param("control_net", control_net.id))
        prompt.set_control_net_strength(control_net.strength)
        prompt.set_latent_dimensions(resolution)
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling IP Adapter prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id=None, negative_id="18", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if ip_adapter.id is None:
            return
        ip_adapter_model, clip_vision_model = self.gen_config.get_ip_adapter_models()
        prompt.set_ip_adapter_model(ip_adapter_model)
        prompt.set_clip_vision_model(clip_vision_model)
        prompt.set_ip_adapter_strength(ip_adapter.strength)
        prompt.set_ip_adapter_image(self.gen_config.redo_param("ip_adapter", ip_adapter.id))
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        ComfyGen.queue_prompt(prompt)

    def animate_diff(self, prompt="", resolution=None, model=None, vae=None, lora=None, n_latents=None, positive=None, negative=None, control_net=None, ip_adapter=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.ANIMATE_DIFF, "Assembling Animate Diff prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, first_image=control_net, second_image=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_clip_text(self.gen_config.redo_param("positive", positive), model, positive=True)
        prompt.set_clip_text(self.gen_config.redo_param("negative", negative), model, positive=False)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_for_class_type(ComfyNodeName.IMAGE_SCALE_TO_SIDE, "side_length", 1024 if self.gen_config.is_xl() else 768)
#        ip_adapter_model, clip_vision_model = self.gen_config.get_ip_adapter_models()
        if control_net:
            prompt.set_by_id("73", "image", control_net.id) # There are two control nets in this workflow, not easy to find right linked input node
            prompt.set_by_id("75", "image", control_net.id if ip_adapter is None else ip_adapter.id) # There are two control nets in this workflow, not easy to find right linked input node
        prompt.set_ip_adapter_model("ip-adapter-plus_sdxl_vit-h.safetensors" if self.gen_config.is_xl() else "ip-adapter-plus_sd15.safetensors")
        prompt.set_clip_vision_model("XL\\clip_vision_g.safetensors" if self.gen_config.is_xl() else"IPAdapter_image_encoder_sd15.safetensors")
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        ComfyGen.queue_prompt(prompt)

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        self.print_pre("Assembling redo prompt", model=model, resolution=resolution, vae=vae, n_latents=n_latents, positive="", negative="", lora=lora, control_net=control_net, ip_adapter=ip_adapter)
        prompt = WorkflowPrompt(source_file)

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

        prompt.change_preview_images_to_save_images()

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
                    prompt.set_control_net(control_net)
                elif attr.startswith("ip_adapter"):
                    prompt.set_ip_adapter_image(ip_adapter.id)
                elif attr == "positive":
                    prompt.set_clip_text(positive, model, positive=True)
                elif attr == "negative":
                    prompt.set_clip_text(negative, model, positive=False)
                elif attr == "n_latents":
                    prompt.set_empty_latents(n_latents)
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
        
        ComfyGen.queue_prompt(prompt)



