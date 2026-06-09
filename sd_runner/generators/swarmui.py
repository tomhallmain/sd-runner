"""SwarmUI (mcmonkeyproductions/SwarmUI) backend."""

import base64
import json
import os
import threading
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


class SwarmUIGen(BaseImageGenerator):
    """Generator for SwarmUI (mcmonkeyproductions/SwarmUI).

    SwarmUI exposes a REST API at ``/API/...`` with session-based auth.
    A session ID is obtained once per process and refreshed automatically on
    HTTP 401/403.  LoRAs are injected into the prompt text as
    ``<lora:name:strength>``.  Model names map directly from ``Model.id``
    (relative path from the models root).

    Set ``swarmui_url`` and optionally ``swarmui_save_path`` in
    ``config.json``.
    """

    BASE_URL = config.swarmui_url
    SAVE_PATH = config.swarmui_save_path
    FILE_PREFIX = "SwarmUI"
    GENERATE_ENDPOINT = "API/GenerateText2Image"
    SESSION_ENDPOINT = "API/GetNewSession"

    _session_id: Optional[str] = None
    _session_lock = threading.Lock()

    def __init__(self, gen_config=GenConfig(), ui_callbacks=None):
        super().__init__(gen_config, ui_callbacks)

    # -------------------------------------------------------------------------
    # Session management
    # -------------------------------------------------------------------------

    def _fetch_session_id(self) -> str:
        cls = type(self)
        url = f"{cls.BASE_URL}/{cls.SESSION_ENDPOINT}"
        body = json.dumps({}).encode()
        headers = {"Content-Type": "application/json"}
        req = urllib_request.Request(url, data=body, headers=headers, method="POST")
        with urllib_request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        return data["session_id"]

    def _get_session(self) -> str:
        cls = type(self)
        with cls._session_lock:
            if cls._session_id is None:
                cls._session_id = self._fetch_session_id()
            return cls._session_id

    # -------------------------------------------------------------------------
    # HTTP helpers
    # -------------------------------------------------------------------------

    def _api_post(self, endpoint: str, payload: dict) -> dict:
        cls = type(self)
        url = f"{cls.BASE_URL}/{endpoint}"
        for attempt in range(2):
            payload["session_id"] = self._get_session()
            body = json.dumps(payload).encode()
            headers = {"Content-Type": "application/json"}
            req = urllib_request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib_request.urlopen(req, timeout=300) as resp:
                    return json.loads(resp.read())
            except urllib_error.HTTPError as exc:
                if exc.code in (401, 403) and attempt == 0:
                    with cls._session_lock:
                        cls._session_id = None
                else:
                    raise
        raise RuntimeError("SwarmUI: failed after session refresh")

    @staticmethod
    def _read_image_b64(path: str) -> str:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    # -------------------------------------------------------------------------
    # Core generation
    # -------------------------------------------------------------------------

    def queue_prompt(self, payload: dict) -> None:
        cls = type(self)
        try:
            result = self._api_post(cls.GENERATE_ENDPOINT, payload)
            for i, img_data in enumerate(result.get("images", [])):
                if "," in img_data:
                    img_data = img_data.split(",", 1)[1]
                save_path = os.path.join(
                    cls.SAVE_PATH,
                    f"{cls.FILE_PREFIX}_{_timestamp_str()}_{i}.png",
                )
                with open(save_path, "wb") as fh:
                    fh.write(base64.b64decode(img_data))
        except urllib_error.URLError as exc:
            raise Exception(f"Failed to connect to SwarmUI. Is it running? ({exc})") from exc
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    def _base_payload(
        self,
        model: Optional[Model] = None,
        resolution=None,
        n_latents: int = 1,
        positive: str = "",
        negative: str = "",
    ) -> dict:
        width, height = 1024, 1024
        if resolution is not None:
            width = resolution.width
            height = resolution.height
        payload: dict = {
            "images": max(n_latents or 1, 1),
            "prompt": positive or "",
            "negativeprompt": negative or "",
            "width": width,
            "height": height,
            "seed": self.gen_config.get_seed(),
        }
        if model:
            payload["model"] = model.id
        if self.gen_config.steps and self.gen_config.steps > 0:
            payload["steps"] = self.gen_config.steps
        if self.gen_config.cfg and self.gen_config.cfg > 0:
            payload["cfgscale"] = self.gen_config.cfg
        if self.gen_config.sampler:
            payload["sampler"] = str(self.gen_config.sampler)
        if self.gen_config.scheduler:
            payload["scheduler"] = str(self.gen_config.scheduler)
        return payload

    @staticmethod
    def _lora_text(lora) -> str:
        if isinstance(lora, LoraBundle):
            return "".join(l.get_lora_text() for l in lora.loras)
        if lora and lora.id:
            return lora.get_lora_text()
        return ""

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
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling SwarmUI simple image gen",
                          None, model, resolution=resolution, positive=positive, negative=negative)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=self.gen_config.redo_param("positive", positive) or "",
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        self.queue_prompt(payload)

    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None,
                              n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA,
                          "Assembling SwarmUI LoRA image gen", None, model,
                          resolution=resolution, lora=lora, positive=positive, negative=negative)
        effective_positive = (self.gen_config.redo_param("positive", positive) or "") + self._lora_text(lora)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=effective_positive,
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        self.queue_prompt(payload)

    def control_net(self, prompt="", resolution=None, model=None, vae=None,
                    n_latents=None, positive=None, negative=None, lora=None,
                    control_net=None, **kw):
        if not self.gen_config.override_resolution and control_net:
            resolution = resolution.get_closest_to_image(control_net.generation_path, round_to=16)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.CONTROLNET, "Assembling SwarmUI ControlNet prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          control_net=control_net)
        effective_positive = (self.gen_config.redo_param("positive", positive) or "") + self._lora_text(lora)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=effective_positive,
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        image_path = self.gen_config.redo_param("control_net", control_net.generation_path) if control_net else None
        if image_path:
            payload["controlnetimage"] = self._read_image_b64(image_path)
            payload["controlnetstrength"] = control_net.strength
        self.queue_prompt(payload)

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None,
                   n_latents=None, positive=None, negative=None, lora=None,
                   control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling SwarmUI IP-Adapter prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        effective_positive = (self.gen_config.redo_param("positive", positive) or "") + self._lora_text(lora)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=effective_positive,
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        if ip_adapter and ip_adapter.id:
            image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
            if image_path:
                payload["ipadapterimage"] = self._read_image_b64(image_path)
                payload["ipadapterstrength"] = ip_adapter.strength
        self.queue_prompt(payload)

    def img2img(self, prompt="", resolution=None, model=None, vae=None,
                n_latents=None, positive=None, negative=None, lora=None,
                control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IMG2IMG, "Assembling SwarmUI img2img prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        effective_positive = (self.gen_config.redo_param("positive", positive) or "") + self._lora_text(lora)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=effective_positive,
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        if ip_adapter and ip_adapter.id:
            image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
            if image_path:
                payload["initimage"] = self._read_image_b64(image_path)
                if self.gen_config.denoise:
                    payload["init_image_creativity"] = self.gen_config.denoise
        self.queue_prompt(payload)

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None,
                     n_latents=None, positive=None, negative=None, lora=None,
                     control_net=None, ip_adapter=None, **kw):
        if ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.INSTANT_LORA, "Assembling SwarmUI InstantLoRA prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          control_net=control_net, ip_adapter=ip_adapter)
        effective_positive = (self.gen_config.redo_param("positive", positive) or "") + self._lora_text(lora)
        payload = self._base_payload(
            model=self.gen_config.redo_param("model", model),
            resolution=self.gen_config.redo_param("resolution", resolution),
            n_latents=self.gen_config.redo_param("n_latents", n_latents),
            positive=effective_positive,
            negative=self.gen_config.redo_param("negative", negative) or "",
        )
        if control_net and control_net.id:
            image_path = self.gen_config.redo_param("control_net", control_net.id)
            if image_path:
                payload["controlnetimage"] = self._read_image_b64(image_path)
                payload["controlnetstrength"] = control_net.strength
        if ip_adapter and ip_adapter.id:
            image_path = self.gen_config.redo_param("ip_adapter", ip_adapter.generation_path)
            if image_path:
                payload["initimage"] = self._read_image_b64(image_path)
                if self.gen_config.denoise:
                    payload["init_image_creativity"] = self.gen_config.denoise
        self.queue_prompt(payload)

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not yet implemented for SwarmUI")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None,
                                      vae=None, lora=None, positive=None, negative=None,
                                      n_latents=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not yet implemented for SwarmUI")
