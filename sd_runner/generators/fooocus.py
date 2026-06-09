"""Fooocus backend (lllyasviel/Fooocus). Requires --listen --api flag."""

import base64
import json
import os
import time
from typing import Optional
from urllib import request as urllib_request, error as urllib_error

from sd_runner.gen_config import GenConfig
from sd_runner.generators.base import BaseImageGenerator
from sd_runner.model_adapters import LoraBundle
from sd_runner.models import Model
from utils.config import config
from utils.globals import WorkflowType


def _timestamp_str() -> str:
    time_str = str(time.time()).replace(".", "")
    while len(time_str) < 17:
        time_str += "0"
    return time_str


class FooocusGen(BaseImageGenerator):
    """Generator for Fooocus (lllyasviel/Fooocus).

    Fooocus is SDXL-only and exposes a simple synchronous JSON API.  Calls
    block until generation is complete — no polling required.  Sampler and
    scheduler knobs are replaced by Fooocus's high-level ``performance_selection``
    preset ("Speed", "Quality", "Extreme Speed", "Lightning", "Hyper-SD").
    If the configured sampler value matches one of those strings exactly it is
    forwarded; otherwise "Speed" is used.

    Start Fooocus with ``--listen --api`` and set ``fooocus_url`` (and
    optionally ``fooocus_save_path``) in ``config.json``.
    """

    BASE_URL = config.fooocus_url
    SAVE_PATH = config.fooocus_save_path
    FILE_PREFIX = "Fooocus"

    TXT2IMG_ENDPOINT = "v1/generation/text-to-image"
    IMG_PROMPT_ENDPOINT = "v1/generation/image-prompt"
    UPSCALE_ENDPOINT = "v1/generation/image-upscale-vary"

    _PERFORMANCE_OPTIONS = frozenset({"Speed", "Quality", "Extreme Speed", "Lightning", "Hyper-SD"})

    def __init__(self, gen_config=GenConfig(), ui_callbacks=None):
        super().__init__(gen_config, ui_callbacks)

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def _performance(self) -> str:
        val = self.gen_config.sampler
        if hasattr(val, "value"):
            val = val.value
        return val if val in self._PERFORMANCE_OPTIONS else "Speed"

    @staticmethod
    def _read_image_b64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def _loras_payload(self, lora) -> list:
        if lora is None:
            return []
        lora_list = lora.loras if isinstance(lora, LoraBundle) else [lora]
        return [
            {"model_name": os.path.basename(l.id), "weight": l.lora_strength}
            for l in lora_list if l and l.id
        ]

    def _base_payload(self, model, resolution, n_latents: int,
                      positive: str, negative: str) -> dict:
        width = resolution.width if resolution else 1024
        height = resolution.height if resolution else 1024
        payload = {
            "prompt": positive,
            "negative_prompt": negative,
            "style_selections": ["Fooocus V2"],
            "performance_selection": self._performance(),
            "aspect_ratios_selection": f"{width}*{height}",
            "image_number": max(n_latents, 1),
            "image_seed": self.gen_config.get_seed(),
            "require_base64": True,
            "async_process": False,
        }
        if model and model.id:
            payload["base_model_name"] = os.path.basename(model.id)
        return payload

    # -------------------------------------------------------------------------
    # Core generation
    # -------------------------------------------------------------------------

    def _post(self, endpoint: str, payload: dict) -> list:
        cls = type(self)
        url = f"{cls.BASE_URL}/{endpoint}"
        req = urllib_request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib_request.urlopen(req, timeout=600) as resp:
            return json.loads(resp.read())

    def _save_results(self, results: list) -> None:
        cls = type(self)
        for i, item in enumerate(results):
            img_bytes = None
            if "base64" in item and item["base64"]:
                img_data = item["base64"]
                if "," in img_data:
                    img_data = img_data.split(",", 1)[1]
                img_bytes = base64.b64decode(img_data)
            elif "url" in item:
                img_url = item["url"]
                if img_url.startswith("/"):
                    img_url = f"{cls.BASE_URL}{img_url}"
                with urllib_request.urlopen(urllib_request.Request(img_url), timeout=30) as resp:
                    img_bytes = resp.read()
            if img_bytes:
                save_path = os.path.join(cls.SAVE_PATH, f"{cls.FILE_PREFIX}_{_timestamp_str()}_{i}.png")
                with open(save_path, "wb") as fh:
                    fh.write(img_bytes)

    def queue_prompt(self, endpoint: str, payload: dict) -> None:
        try:
            results = self._post(endpoint, payload)
            self._save_results(results)
        except urllib_error.URLError as exc:
            raise Exception(f"Failed to connect to Fooocus. Is it running with --api? ({exc})") from exc
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    # -------------------------------------------------------------------------
    # BaseImageGenerator interface
    # -------------------------------------------------------------------------

    def _get_workflows(self) -> dict:
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

    def prompt_setup(self, workflow_type: WorkflowType, action: str, prompt,
                     model: Model, vae=None, resolution=None, **kw):
        self.print_pre(action=action, model=model, resolution=resolution, **kw)

    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None,
                         n_latents=None, positive=None, negative=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling Fooocus simple image gen",
                          None, model, resolution=resolution, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        self.queue_prompt(self.TXT2IMG_ENDPOINT, payload)

    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None,
                              n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA, "Assembling Fooocus LoRA image gen",
                          None, model, resolution=resolution, lora=lora, positive=positive, negative=negative)
        model = self.gen_config.redo_param("model", model)
        lora = self.gen_config.redo_param("lora", lora)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        payload["loras"] = self._loras_payload(lora)
        self.queue_prompt(self.TXT2IMG_ENDPOINT, payload)

    def control_net(self, prompt="", resolution=None, model=None, vae=None,
                    n_latents=None, positive=None, negative=None, lora=None,
                    control_net=None, **kw):
        if not self.gen_config.override_resolution and control_net:
            resolution = resolution.get_closest_to_image(control_net.generation_path, round_to=16)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.CONTROLNET, "Assembling Fooocus ControlNet prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          control_net=control_net)
        model = self.gen_config.redo_param("model", model)
        lora = self.gen_config.redo_param("lora", lora)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        image_path = self.gen_config.redo_param("control_net", control_net.generation_path) if control_net else None
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        payload["loras"] = self._loras_payload(lora)
        if image_path:
            payload["image_prompts"] = [{
                "cn_img": self._read_image_b64(image_path),
                "cn_stop": 1.0,
                "cn_weight": control_net.strength,
                "cn_type": "PyraCanny",
            }]
        self.queue_prompt(self.IMG_PROMPT_ENDPOINT if image_path else self.TXT2IMG_ENDPOINT, payload)

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None,
                   n_latents=None, positive=None, negative=None, lora=None,
                   control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling Fooocus IP-Adapter prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        lora = self.gen_config.redo_param("lora", lora)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path) if ip_adapter and ip_adapter.id else None
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        payload["loras"] = self._loras_payload(lora)
        if image_path:
            payload["image_prompts"] = [{
                "cn_img": self._read_image_b64(image_path),
                "cn_stop": 0.6,
                "cn_weight": ip_adapter.strength,
                "cn_type": "ImagePrompt",
            }]
        self.queue_prompt(self.IMG_PROMPT_ENDPOINT if image_path else self.TXT2IMG_ENDPOINT, payload)

    def img2img(self, prompt="", resolution=None, model=None, vae=None,
                n_latents=None, positive=None, negative=None, lora=None,
                control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IMG2IMG, "Assembling Fooocus img2img prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        lora = self.gen_config.redo_param("lora", lora)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path) if ip_adapter and ip_adapter.id else None
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        payload["loras"] = self._loras_payload(lora)
        if image_path:
            # img2img in Fooocus uses ImagePrompt type with high weight
            payload["image_prompts"] = [{
                "cn_img": self._read_image_b64(image_path),
                "cn_stop": 0.85,
                "cn_weight": 1.0 - (self.gen_config.denoise or 0.5),
                "cn_type": "ImagePrompt",
            }]
        self.queue_prompt(self.IMG_PROMPT_ENDPOINT if image_path else self.TXT2IMG_ENDPOINT, payload)

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None,
                     n_latents=None, positive=None, negative=None, lora=None,
                     control_net=None, ip_adapter=None, **kw):
        # Fooocus supports both LoRA and image-prompt simultaneously
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.INSTANT_LORA, "Assembling Fooocus InstantLoRA prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          control_net=control_net, ip_adapter=ip_adapter)
        model = self.gen_config.redo_param("model", model)
        lora = self.gen_config.redo_param("lora", lora)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""
        payload = self._base_payload(model, resolution, n_latents, positive, negative)
        payload["loras"] = self._loras_payload(lora)
        image_prompts = []
        cn_path = self.gen_config.redo_param("control_net", control_net.id) if control_net and control_net.id else None
        if cn_path:
            image_prompts.append({
                "cn_img": self._read_image_b64(cn_path),
                "cn_stop": 1.0,
                "cn_weight": control_net.strength,
                "cn_type": "PyraCanny",
            })
        ipa_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path) if ip_adapter and ip_adapter.id else None
        if ipa_path:
            image_prompts.append({
                "cn_img": self._read_image_b64(ipa_path),
                "cn_stop": 0.6,
                "cn_weight": ip_adapter.strength,
                "cn_type": "ImagePrompt",
            })
        if image_prompts:
            payload["image_prompts"] = image_prompts
        self.queue_prompt(self.IMG_PROMPT_ENDPOINT if image_prompts else self.TXT2IMG_ENDPOINT, payload)

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        self.prompt_setup(WorkflowType.UPSCALE_SIMPLE, "Assembling Fooocus upscale prompt",
                          None, model, control_net=control_net)
        image_path = control_net.generation_path if control_net and control_net.id else None
        if not image_path:
            raise ValueError("upscale_simple requires a control_net image")
        payload = {
            "input_image": self._read_image_b64(image_path),
            "uov_method": "Upscale (2x)",
            "image_number": 1,
            "image_seed": self.gen_config.get_seed(),
            "require_base64": True,
            "async_process": False,
        }
        self.queue_prompt(self.UPSCALE_ENDPOINT, payload)

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None,
                                      vae=None, lora=None, positive=None, negative=None,
                                      n_latents=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not yet implemented for Fooocus")
