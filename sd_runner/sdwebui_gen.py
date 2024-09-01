import base64
from datetime import datetime
import json
import os
import random
from urllib import request, parse, error
from time import sleep
import time
import traceback

from sd_runner.captioner import Captioner
from sd_runner.gen_config import GenConfig, format_white, format_red
from utils.globals import Globals, WorkflowType, PromptTypeSDWebUI
from sd_runner.models import Model, LoraBundle
from sd_runner.workflow_prompt import WorkflowPromptSDWebUI
from utils.config import config
from utils.utils import start_thread


def timestamp():
    time_str = str(time.time()).replace(".", "")
    while len(time_str) < 17:
        time_str += "0"
    return time_str

def encode_file_to_base64(path):
    with open(path, 'rb') as file:
        return base64.b64encode(file.read()).decode('utf-8')


def decode_and_save_base64(base64_str, save_path):
    with open(save_path, "wb") as file:
        file.write(base64.b64decode(base64_str))



class SDWebuiGen:
    BASE_URL = config.sd_webui_url
    TXT_2_IMG = "sdapi/v1/txt2img"
    IMG_2_IMG = "sdapi/v1/img2img"
    ORDER = config.gen_order
    RANDOM_SKIP_CHANCE = config.dict["random_skip_chance"]

    def __init__(self, config=GenConfig()):
        self.gen_config = config
        self.counter = 0
        self.latent_counter = 0
        self.captioner = None

    def reset_counters(self):
        self.counter = 0
        self.latent_counter = 0

    def get_captioner(self):
        if self.captioner is None:
            self.captioner = Captioner()
        return self.captioner

    def random_skip(self):
        do_skip = SDWebuiGen.RANDOM_SKIP_CHANCE > 0 and random.random() < SDWebuiGen.RANDOM_SKIP_CHANCE
        if do_skip:
            print("Skipping by random chance. Current skip chance set at: " + str(SDWebuiGen.RANDOM_SKIP_CHANCE))
        return do_skip

    def run(self):
        self.gen_config.prepare()
        workflow_id = self.gen_config.workflow_id
        n_latents = self.gen_config.n_latents
        positive = self.gen_config.positive
        negative = self.gen_config.negative
        if workflow_id is None or workflow_id == "":
            raise Exception("Invalid workflow ID.")
        for _1 in getattr(self.gen_config, SDWebuiGen.ORDER[0]):
            for _2 in getattr(self.gen_config, SDWebuiGen.ORDER[1]):
                for _3 in getattr(self.gen_config, SDWebuiGen.ORDER[2]):
                    for _4 in getattr(self.gen_config, SDWebuiGen.ORDER[3]):
                        for _5 in getattr(self.gen_config, SDWebuiGen.ORDER[4]):
                            for _6 in getattr(self.gen_config, SDWebuiGen.ORDER[5]):
                                if self.random_skip():
                                    continue

                                args = [_1, _2, _3, _4, _5, _6]
                                # print_list_str(args)
                                resolution = args[SDWebuiGen.ORDER.index("resolutions")]
                                model = args[SDWebuiGen.ORDER.index("models")]
                                vae = args[SDWebuiGen.ORDER.index("vaes")]
                                if vae is None:
                                    vae = model.get_default_vae()
                                model.validate_vae(vae)
                                lora = args[SDWebuiGen.ORDER.index("loras")]
                                control_net = args[SDWebuiGen.ORDER.index("control_nets")]
                                ip_adapter = args[SDWebuiGen.ORDER.index("ip_adapters")]
                                positive_copy = str(positive)
                                if ip_adapter:
                                    positive_copy += ip_adapter.modifiers
                                    positive_copy = ip_adapter.b_w_coloration_modifier(positive_copy)
                                
                                if self.gen_config.is_redo_prompt():
                                    raise Exception("Redo prompt is not supported for SD Web UI.")
                                else:
                                    self.run_workflow(None, workflow_id, resolution, model, vae, n_latents, positive_copy,
                                                      negative, lora, control_net=control_net, ip_adapter=ip_adapter)
        self.print_stats()

    def run_workflow(self, prompt, workflow_id, resolution, model, vae, n_latents, positive, negative, lora, control_net=None, ip_adapter=None):
        if workflow_id == WorkflowType.SIMPLE_IMAGE_GEN_LORA:
            if lora is None:
                raise Exception("Image gen with lora - lora not set!")
            self.simple_image_gen_lora(prompt, resolution, model, vae, n_latents, positive, negative, lora)
        elif workflow_id == WorkflowType.SIMPLE_IMAGE_GEN:
            self.simple_image_gen(prompt, resolution, model, vae, n_latents, positive, negative)
        elif workflow_id == WorkflowType.CONTROLNET:
            self.control_net(prompt, resolution, model, vae, n_latents, positive, negative, lora, control_net)
        elif workflow_id == WorkflowType.IP_ADAPTER:
            self.ip_adapter(prompt, resolution, model, vae, n_latents, positive, negative, lora, ip_adapter=ip_adapter)
        elif workflow_id == WorkflowType.UPSCALE_SIMPLE:
            self.upscale_simple(prompt, model, control_net)
        else:
            raise Exception(f"Workflow not set up for SD Web UI: {workflow_id}")
        sleep(0.2)

    def print_stats(self):
        print(f"Started {self.counter} prompts, {self.latent_counter} images to be saved if all complete")
        self.reset_counters()

    def print_pre(self, action, **kw):
        if not "n_latents" in kw:
            raise Exception("Missing n_latents setting!")
        self.latent_counter += kw["n_latents"]
        out = f"{format_white(action)} with config: "
        for item in kw.items():
            if not item[1]:
                continue
            if item[0] != "negative" or Globals.PRINT_NEGATIVES:
                out += f"\n{format_white(item[0])}: {item[1]}"
        print(out)

    def prompt_setup(self, workflow_type, action, prompt, model, vae=None, resolution=None, **kw):
        if prompt:
            raise Exception("Redo prompt not supported for SDWebui at this time")
            # prompt.set_from_workflow(workflow_type.value)
            # model, vae = prompt.check_for_existing_image(model, vae, resolution)
        else:
            self.print_pre(action=action, model=model, vae=vae, resolution=resolution, **kw)
            if not prompt:
                prompt = WorkflowPromptSDWebUI(workflow_type.value)
        self.counter += 1
        return prompt, model, vae

    @staticmethod
    def schedule_prompt(prompt, img2img=False):
        start_thread(SDWebuiGen.queue_prompt, use_asyncio=False, args=[prompt, img2img])

    @staticmethod
    def queue_prompt(prompt, img2img=False):
        api_endpoint = SDWebuiGen.IMG_2_IMG if img2img else SDWebuiGen.TXT_2_IMG
        data = prompt.get_json()
        req = request.Request(
            f'{SDWebuiGen.BASE_URL}/{api_endpoint}',
            headers={'Content-Type': 'application/json'},
            data=data,
        )
        try:
            response = request.urlopen(req)
            SDWebuiGen.save_image_data(response)
        except error.URLError:
            raise Exception("Failed to connect to SD Web UI. Is SD Web UI running?")

    @staticmethod
    def save_image_data(response):
        resp_json = json.loads(response.read().decode('utf-8'))
        for index, image in enumerate(resp_json.get('images')):
            save_path = os.path.join(config.sd_webui_save_path, f'SDWebUI_{timestamp()}_{index}.png')
            decode_and_save_base64(image, save_path)

    @staticmethod
    def clear_history():
        pass # TODO figure out if there is a history api

    def get_seed(self):
        return self.gen_config.get_seed()

    def simple_image_gen(self, prompt, resolution, model, vae, n_latents, positive, negative):
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling Simple Image Gen prompt", prompt=prompt, model=model, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        SDWebuiGen.schedule_prompt(prompt)

    def simple_image_gen_lora(self, prompt, resolution, model, vae, n_latents, positive, negative, lora):
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA, "Assembling Simple Image Gen LoRA prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, lora=lora, n_latents=n_latents, positive=positive, negative=negative)
        model.validate_loras(lora)
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
        SDWebuiGen.schedule_prompt(prompt)

    def upscale_simple(self, prompt, model, control_net):
        prompt, model, vae = self.prompt_setup(WorkflowType.UPSCALE_SIMPLE, "Assembling simple upscale image prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=1, positive="", negative="", upscale_image=control_net)
        # prompt.set_upscaler_model()
        prompt.set_image_scale_to_side(1024) # Max image side length
        control_net = self.gen_config.redo_param("control_net", control_net)
        SDWebuiGen.schedule_prompt(prompt)

    def control_net(self, prompt, resolution, model, vae, n_latents, positive, negative, lora, control_net):
        prompt, model, vae = self.prompt_setup(WorkflowType.CONTROLNET, "Assembling Control Net prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, lora=lora)
        model = self.gen_config.redo_param("model", model)
        model.validate_loras(lora)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_texts(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative), model=model)
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if control_net.id is None:
            return
        prompt.set_control_net_image(self.gen_config.redo_param("control_net", control_net.id))
        prompt.set_control_net_strength(control_net.strength)
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        SDWebuiGen.schedule_prompt(prompt)

    def ip_adapter(self, prompt, resolution, model, vae, n_latents, positive, negative, lora, ip_adapter):
        prompt, model, vae = self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling Img2Img prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative, lora=lora, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
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
        print(1 - ip_adapter.strength)
        print(prompt.json["denoising_strength"])
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.id)
        prompt.set_img2img_image(encode_file_to_base64(image_path))
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        SDWebuiGen.schedule_prompt(prompt, img2img=True)

    def maybe_caption_image(self, image_path, positive):
        if positive is None or positive == "":
            return self.get_captioner().caption(image_path)
        return positive

    def redo_with_different_parameter(self, source_file, resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None):
        raise Exception("Redo prompt is not supported for SDWebUI")



