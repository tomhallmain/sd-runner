import json
import os
import traceback
from typing import Optional
from urllib import request, response, parse, error
import uuid
import websocket
import time

from sd_runner.gen_config import GenConfig
from utils.globals import Globals, WorkflowType, ComfyNodeName

from sd_runner.base_image_generator import BaseImageGenerator
from sd_runner.models import Model, LoraBundle
from sd_runner.prompter import PrompterConfiguration
from sd_runner.workflow_prompt import WorkflowPrompt, WorkflowPromptComfy
from utils.config import config
from utils.logging_setup import get_logger
from utils.utils import Utils

logger = get_logger("comfy_gen")

class ComfyGen(BaseImageGenerator):
    BASE_URL = config.comfyui_url.replace("http://", "").replace("https://", "")
    PROMPT_URL = BASE_URL + "/prompt"
    CLIENT_ID = str(uuid.uuid4())
    _active_connections = []  # Track all active websocket connections

    def __init__(self, config=GenConfig(), ui_callbacks=None):
        super().__init__(config, ui_callbacks)
        logger.debug(f"ComfyGen initialized with config: {config}")

    @classmethod
    def add_connection(cls, ws):
        """Add a websocket connection to the tracking list"""
        cls._active_connections.append(ws)
        logger.debug(f"Added websocket connection. Total active connections: {len(cls._active_connections)}")

    @classmethod
    def remove_connection(cls, ws):
        """Remove a websocket connection from the tracking list"""
        if ws in cls._active_connections:
            cls._active_connections.remove(ws)
            logger.debug(f"Removed websocket connection. Total active connections: {len(cls._active_connections)}")

    @classmethod
    def close_all_connections(cls):
        """Close all active websocket connections"""
        logger.info(f"Closing all {len(cls._active_connections)} websocket connections...")
        for ws in cls._active_connections[:]:  # Use a copy of the list to avoid modification during iteration
            try:
                ws.close()
                cls.remove_connection(ws)
            except Exception as e:
                logger.warning(f"Error closing websocket connection: {e}")
        logger.info("All websocket connections closed")

    def prompt_setup(self, workflow_type: WorkflowType, action: str, prompt: Optional[WorkflowPrompt], model: Model, vae=None, resolution=None, **kw):
        if prompt:
            # NOTE this is only needed for redo_with_different_parameter case `if not prompt.validate_api_prompt()`
            prompt.set_from_workflow(workflow_type.value)
            model, vae = prompt.check_for_existing_image(model, vae, resolution)
        else:
            self.print_pre(action=action, model=model, vae=vae, resolution=resolution, **kw)
            if workflow_type == WorkflowType.SIMPLE_IMAGE_GEN_LORA:
                lora = kw["lora"]
                if isinstance(lora, LoraBundle):
                    prompt = WorkflowPromptComfy("simple_image_gen_lora2.json")
            if workflow_type == WorkflowType.INSTANT_LORA and model.is_xl():
                prompt = WorkflowPromptComfy("instant_lora_xl.json")
            if workflow_type == WorkflowType.RENOISER and model.is_xl():
                prompt = WorkflowPromptComfy("renoiser_xl.json")
            if model.is_flux():
                if workflow_type == WorkflowType.SIMPLE_IMAGE_GEN:
                    prompt = WorkflowPromptComfy("simple_image_gen_flux.json")
                else:
                    raise Exception("Flux workflows other than simple image gen are not supported in SDRunner's ComfyUI implementation at this time")
            if model.is_chroma():
                if workflow_type == WorkflowType.SIMPLE_IMAGE_GEN:
                    prompt = WorkflowPromptComfy("image_chroma_text_to_image.json")
                else:
                    raise Exception("Chroma workflows other than simple image gen are not supported in SDRunner's ComfyUI implementation at this time")
            if not prompt:
                prompt = WorkflowPromptComfy(workflow_type.value)
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
            WorkflowType.IMG2IMG: self.img2img,
            WorkflowType.REDO_PROMPT: self.redo_with_different_parameter,
            WorkflowType.RENOISER: self.renoiser,
            WorkflowType.SIMPLE_IMAGE_GEN_LORA: self.simple_image_gen_lora,
            WorkflowType.SIMPLE_IMAGE_GEN_TILED_UPSCALE: self.simple_image_gen_tiled_upscale,            
            WorkflowType.SIMPLE_IMAGE_GEN: self.simple_image_gen,
            WorkflowType.TURBO: self.simple_image_gen_turbo,
            WorkflowType.UPSCALE_BETTER: self.upscale_better,
            WorkflowType.UPSCALE_SIMPLE: self.upscale_simple,
        }

    def queue_prompt(self, prompt: WorkflowPromptComfy):
        data = prompt.get_json()
        if config.debug:
            print(data.decode("utf-8"))
        images = None
        try:
            ws = websocket.WebSocket()
            ws.connect("ws://{}/ws?clientId={}".format(ComfyGen.BASE_URL, ComfyGen.CLIENT_ID))
            ComfyGen.add_connection(ws)  # Track the new connection
            images = ComfyGen.get_images(ws, json.loads(data.decode('utf-8')), self.gen_config.get_prompter_config())
            try:
                ws.close() # Need this to avoid random timeouts, memory leaks, etc.
            except Exception:
                pass
        except error.URLError:
            raise Exception("Failed to connect to ComfyUI. Is ComfyUI running?")
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()
            return images

    @staticmethod
    def _queue_prompt(prompt):
        # p = {"prompt": prompt, "client_id": ComfyGen.CLIENT_ID}
        data = json.dumps(prompt).encode('utf-8')
        req = request.Request(
            "http://{}/prompt".format(ComfyGen.BASE_URL),
            data=data,
            method='POST',
            headers={'Content-Type': 'application/json'}
        )
        return json.loads(request.urlopen(req).read())

    @staticmethod
    def get_history(prompt_id):
        max_retries = 5
        retry_delay = 1  # seconds
        
        for attempt in range(max_retries):
            try:
                logger.debug(f"Getting history for prompt (attempt {attempt + 1}/{max_retries})...")
                with request.urlopen("http://{}/history/{}".format(ComfyGen.BASE_URL, prompt_id)) as response:
                    history = json.loads(response.read())
                    if prompt_id in history:
                        return history
                    logger.debug(f"Prompt ID not found in history, waiting {retry_delay} seconds...")
                    time.sleep(retry_delay)
            except Exception as e:
                logger.error(f"Error getting history (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
                else:
                    raise Exception(f"Failed to get history for prompt {prompt_id} after {max_retries} attempts")
        
        raise Exception(f"Failed to get history for prompt {prompt_id} after {max_retries} attempts")

    @staticmethod
    def clear_history(prompt_id):
        # TODO: Figure out how to clear a specific prompt from history
        return
        # data = json.dumps({"clear": "true"}).encode('utf-8')
        # req = request.Request("http://{}/history/{}".format(ComfyGen.BASE_URL, prompt_id), data=data)
        # try:
        #     return request.urlopen(req)
        # except error.URLError:
        #     raise Exception("Failed to connect to ComfyUI. Is ComfyUI running?")
    @staticmethod
    def get_images(ws, prompt, prompter_config: Optional[PrompterConfiguration]=None):
        logger.debug("Queueing prompt to ComfyUI...")
        prompt_id = ComfyGen._queue_prompt(prompt)['prompt_id']
        logger.debug(f"Got prompt ID: {prompt_id}")
        output_images = {}
        current_node = None
        websocket_error = None
        
        try:
            while True:
                try:
                    # Check if websocket is still connected before trying to receive
                    if not ws.connected:
                        logger.debug("WebSocket connection closed")
                        break
                        
                    out = ws.recv()
                    if isinstance(out, str):
                        message = json.loads(out)
                        logger.debug(f"Received message: {message}")
                        if message['type'] == 'executing':
                            data = message['data']
                            if data['node'] is None and data['prompt_id'] == prompt_id:
                                logger.debug("Execution completed")
                                break #Execution is done
                            else:
                                current_node = data['node']
                                logger.debug(f"Executing node: {current_node}")
                        elif message['type'] == 'execution_error':
                            data = message['data']
                            if data['prompt_id'] == prompt_id:
                                error_msg = data.get('message', 'Unknown execution error')
                                websocket_error = Exception(f"ComfyUI execution error: {error_msg}")
                                break
                        elif message['type'] == 'progress':
                            data = message['data']
                            if data['prompt_id'] == prompt_id and data['value'] == data['max']:
                                logger.debug("Progress reached 100%")
                                # Wait a bit to ensure all messages are processed
                                time.sleep(1)
                                break
                    else:
                        logger.debug(f"Received binary data from node: {current_node}")
                        # If you want to be able to decode the binary stream for latent previews, here is how you can do it:
                        # bytesIO = BytesIO(out[8:])
                        # preview_image = Image.open(bytesIO) # This is your preview in PIL image format, store it in a global
                        continue #previews are binary data
                except websocket.WebSocketConnectionClosedException as e:
                    logger.debug("WebSocket connection closed unexpectedly")
                    websocket_error = e
                    break
                except Exception as e:
                    logger.error(f"Error processing websocket message: {e}")
                    websocket_error = e
                    break

            # If we had a websocket error, don't try to get history
            if websocket_error:
                raise websocket_error

            logger.debug("Getting history for prompt...")
            history = ComfyGen.get_history(prompt_id)[prompt_id]
            
            # Process images and add EXIF data with original prompt decomposition
            for node_id in history['outputs']:
                node_output = history['outputs'][node_id]
                images_output = []
                if 'images' in node_output:
                    for image in node_output['images']:
                        logger.debug(f"Getting image: {image['filename']}")
                        image_data = ComfyGen.get_image(image['filename'], image['subfolder'], image['type'])
                        images_output.append(image_data)
                        
                        # Save image with EXIF data containing original prompt decomposition
                        if prompter_config is not None:
                            # Construct the expected file path where ComfyUI saves the image
                            save_path = os.path.join(config.get_comfyui_save_path(), f'ComfyUI_{image["filename"]}')
                            Globals.get_image_data_extractor().add_prompt_decomposition_to_exif(save_path, prompter_config.original_positive_tags, original_negative_tags=None)
                output_images[node_id] = images_output

            ComfyGen.clear_history(prompt_id)
            return output_images
        except Exception as e:
            logger.error(f"Error in get_images: {e}")
            raise
        finally:
            logger.debug("Closing websocket connection...")
            try:
                if ws.connected:
                    ws.close()
                ComfyGen.remove_connection(ws)  # Remove the connection from tracking
            except:
                pass

    @staticmethod
    def get_image(filename, subfolder, folder_type):
        data = {"filename": filename, "subfolder": subfolder, "type": folder_type}
        url_values = parse.urlencode(data)
        with request.urlopen("http://{}/view?{}".format(ComfyGen.PROMPT_URL, url_values)) as response:
            return response.read()

    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        prompt, model, vae = self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling Simple Image Gen prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        if model.is_flux():
            # NOTE Flux models don't have a negative prompt
            prompt.set_clip_text_by_id(
                self.gen_config.redo_param("positive", positive),
                None, positive_id="6", model=model)
        elif model.is_chroma():
            # NOTE Chroma uses different node IDs: positive="748", negative="749"
            prompt.set_vae(self.gen_config.redo_param("vae", vae))
            prompt.set_clip_text_by_id(
                self.gen_config.redo_param("positive", positive),
                self.gen_config.redo_param("negative", negative),
                positive_id="748", negative_id="749", model=model)
        else:
            prompt.set_vae(self.gen_config.redo_param("vae", vae))
            prompt.set_clip_text_by_id(
                self.gen_config.redo_param("positive", positive),
                self.gen_config.redo_param("negative", negative),
                positive_id="3", negative_id="4", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

    def renoiser(self, prompt="", model=None, vae=None, n_latents=None, positive=None, negative=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.RENOISER, "Assembling Renoiser prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=n_latents, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="21", negative_id="24", model=model)
        
        control_net = self.gen_config.redo_param("control_net", control_net)
        if control_net:
            # Use generation_path instead of id to match control_net workflow behavior
            image_path = control_net.generation_path if hasattr(control_net, 'generation_path') else control_net.id
            prompt.set_by_id("56", "image", image_path) # There are two control nets in this workflow, not easy to find right linked input node
            prompt.set_by_id("25", "strength", control_net.strength)
            prompt.set_by_id("30", "strength", control_net.strength)
        
        # Use existing seed logic to ensure uniqueness and prevent ComfyUI caching
        # Note: While seed may not significantly affect output quality for this workflow,
        # varying it prevents ComfyUI from treating prompts as identical and caching/skipping them
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        
        # Set ControlNet models based on model type
        if model.is_xl():
            # SDXL ControlNet models
            prompt.set_by_id("19", "control_net_name", "t2i-adapter_diffusers_xl_depth_zoe.safetensors")
            prompt.set_by_id("29", "control_net_name", "t2i-adapter_diffusers_xl_lineart.safetensors")
        else:
            # SD15 ControlNet models
            prompt.set_by_id("19", "control_net_name", "control_v11f1p_sd15_depth.pth")
            prompt.set_by_id("29", "control_net_name", "control_v11p_sd15_lineart.pth")
        
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        prompt, model, vae = self.prompt_setup(WorkflowType.UPSCALE_SIMPLE, "Assembling simple upscale image prompt", prompt=prompt, model=model, vae=vae, resolution=None, n_latents=1, positive="", negative="", upscale_image=control_net)
        # prompt.set_upscaler_model()
        prompt.set_image_scale_to_side(1024) # Max image side length
        control_net = self.gen_config.redo_param("control_net", control_net)
        if control_net:
            prompt.set_linked_input_node(control_net.id, starting_class_type="ImageUpscaleWithModel")
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

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
        self.queue_prompt(prompt)

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(control_net.generation_path)
        prompt, model, vae = self.prompt_setup(WorkflowType.CONTROLNET, "Assembling Control Net prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, control_net=control_net, lora=lora)
        model = self.gen_config.redo_param("model", model)
        model.validate_loras(lora)
        prompt.set_model(model)
        
        # vae = self.gen_config.redo_param("vae", vae)
        # if vae:
        #     if model.is_xl():
        #         prompt.set_by_id("8", "vae_name", vae)
        #     else:
        #         prompt.set_by_id("16", "vae_name", vae)
        #         prompt.set_by_id("31", "vae", ["16", 0])
                
        prompt.set_lora(self.gen_config.redo_param("lora", lora))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="30", negative_id="18", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if control_net.id is None:
            return
        prompt.set_control_net_image2(self.gen_config.redo_param("control_net", control_net.generation_path))
        prompt.set_control_net_strength(control_net.strength)
        
        # Set ControlNet model - this should be set dynamically based on model type and control net type
        # For now, using default - can be enhanced to detect based on control_net parameter
        
        prompt.set_latent_dimensions(resolution)
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt)

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
        prompt.set_ip_adapter_image(self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path))
        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        prompt.set_empty_latents(self.gen_config.redo_param("n_latents", n_latents))
        self.queue_prompt(prompt)

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        if not self.gen_config.override_resolution:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path, round_to=16)
        prompt, model, vae = self.prompt_setup(WorkflowType.IMG2IMG, "Assembling Img2Img prompt", prompt=prompt, model=model, vae=vae, resolution=resolution, n_latents=n_latents, positive=positive, negative=negative, lora=lora, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        prompt.set_model(model)
        prompt.set_vae(self.gen_config.redo_param("vae", vae))
        prompt.set_clip_text_by_id(
            self.gen_config.redo_param("positive", positive),
            self.gen_config.redo_param("negative", negative),
            positive_id="6", negative_id="7", model=model)
        prompt.set_seed(self.gen_config.redo_param("seed", self.get_seed()))
        prompt.set_other_sampler_inputs(self.gen_config)
        if ip_adapter.id is None:
            return
        prompt.set_by_id("10", "image", ip_adapter.generation_path)  # LoadImage node
        prompt.set_by_id("3", "denoise", 1 - ip_adapter.strength)  # Inverse of ip_adapter strength like SDWebUI
        # Set the target resolution for the ImageScale node
        resolution = self.gen_config.redo_param("resolution", resolution)
        if resolution:
            prompt.set_by_id("12", "width", resolution.width)  # ImageScale node
            prompt.set_by_id("12", "height", resolution.height)  # ImageScale node
        # prompt.set_image_duplicator(self.gen_config.redo_param("n_latents", n_latents))
        # TODO: Figure out how to handle the image duplicator
        self.queue_prompt(prompt)

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
            prompt.set_by_id("73", "image", control_net.generation_path) # There are two control nets in this workflow, not easy to find right linked input node
            prompt.set_by_id("75", "image", control_net.generation_path if ip_adapter is None else ip_adapter.generation_path) # There are two control nets in this workflow, not easy to find right linked input node
        prompt.set_ip_adapter_model("ip-adapter-plus_sdxl_vit-h.safetensors" if self.gen_config.is_xl() else "ip-adapter-plus_sd15.safetensors")
        prompt.set_clip_vision_model("XL\\clip_vision_g.safetensors" if self.gen_config.is_xl() else"IPAdapter_image_encoder_sd15.safetensors")
#        prompt.set_latent_dimensions(self.gen_config.redo_param("resolution", resolution))
        self.queue_prompt(prompt)

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        self.print_pre("Assembling redo prompt", model=model, resolution=resolution, vae=vae, n_latents=n_latents, positive="", negative="", lora=lora, control_net=control_net, ip_adapter=ip_adapter)
        prompt = WorkflowPrompt(source_file)

        # If this is not an API prompt, handle in an annoying way
        if not prompt.validate_api_prompt():
            if config.debug:
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
            logger.error("Failed to set number of empty latents")

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
                    prompt.set_ip_adapter_image(ip_adapter.generation_path)
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
                if config.debug:
                    print("Redoing parameter with different value: " + attr)
                has_made_one_change = True
            except Exception as e:
                logger.error(e)

        if not has_made_one_change and config.debug:
            print("Did not make any changes to prompt for image: " + source_file)
        
        self.queue_prompt(prompt)



