"""InvokeAI backend."""

import json
import os
import threading
import time
from typing import Optional
from urllib import request as urllib_request, error as urllib_error, parse as urllib_parse

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


def _edge(src_node: str, src_field: str, dst_node: str, dst_field: str) -> dict:
    return {
        "source": {"node_id": src_node, "field": src_field},
        "destination": {"node_id": dst_node, "field": dst_field},
    }


class InvokeAIGen(BaseImageGenerator):
    """Generator for InvokeAI (invoke-ai/InvokeAI), targeting the v3.x queue API.

    InvokeAI identifies models by UUID keys rather than filenames.  This
    generator fetches the model list from InvokeAI once (cached per process)
    and resolves ``model.id`` to a key by case-insensitive name match.  If no
    match is found the raw ``model.id`` is passed as-is, which lets users
    configure model keys directly in ``model_tags``.

    Image retrieval after generation relies on listing the most recent
    non-intermediate images from the InvokeAI gallery.  For best reliability
    avoid running other generations concurrently while this generator is active.

    Set ``invokeai_url`` and optionally ``invokeai_save_path`` in
    ``config.json``.
    """

    BASE_URL = config.invokeai_url
    SAVE_PATH = config.invokeai_save_path
    FILE_PREFIX = "InvokeAI"
    QUEUE_ID = "default"

    _model_cache: Optional[dict] = None
    _model_cache_lock = threading.Lock()

    def __init__(self, gen_config=GenConfig(), ui_callbacks=None):
        super().__init__(gen_config, ui_callbacks)

    # -------------------------------------------------------------------------
    # Model key lookup
    # -------------------------------------------------------------------------

    def _fetch_model_cache(self) -> dict:
        url = f"{type(self).BASE_URL}/api/v1/models/"
        try:
            with urllib_request.urlopen(urllib_request.Request(url), timeout=10) as resp:
                data = json.loads(resp.read())
            return {
                m.get("model_name") or m.get("name", ""): (m.get("key", ""), m.get("type", "main"))
                for m in data.get("models", [])
                if m.get("key")
            }
        except Exception as exc:
            print(f"[InvokeAI] Could not fetch model list: {exc}")
            return {}

    def _get_model_key(self, model_id: str, model_type: Optional[str] = None) -> str:
        cls = type(self)
        with cls._model_cache_lock:
            if cls._model_cache is None:
                cls._model_cache = self._fetch_model_cache()
            cache = cls._model_cache

        base_name = os.path.splitext(os.path.basename(model_id))[0].lower()
        for name, (key, mtype) in cache.items():
            if model_type and mtype != model_type:
                continue
            if base_name in name.lower() or name.lower() in base_name:
                return key

        return model_id  # fallback: treat as a raw key

    # -------------------------------------------------------------------------
    # Image upload (for img2img / control_net / ip_adapter inputs)
    # -------------------------------------------------------------------------

    def _upload_image(self, path: str) -> str:
        """Upload an image to InvokeAI and return its image_name."""
        url = f"{type(self).BASE_URL}/api/v1/images/upload?is_intermediate=true"
        with open(path, "rb") as f:
            data = f.read()
        boundary = "InvokeAIBoundary"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{os.path.basename(path)}"\r\n'
            f"Content-Type: image/png\r\n\r\n"
        ).encode() + data + f"\r\n--{boundary}--\r\n".encode()
        req = urllib_request.Request(
            url, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
            method="POST",
        )
        with urllib_request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["image_name"]

    # -------------------------------------------------------------------------
    # Node graph builders
    # -------------------------------------------------------------------------

    @staticmethod
    def _scheduler_str(scheduler) -> str:
        if scheduler is None:
            return "euler"
        val = scheduler.value if hasattr(scheduler, "value") else str(scheduler)
        return val if val and val.lower() not in ("", "any") else "euler"

    def _base_nodes(self, model_key: str, positive: str, negative: str,
                    width: int, height: int, seed: int) -> tuple:
        steps = self.gen_config.steps or 20
        cfg_scale = self.gen_config.cfg or 7.5
        scheduler = self._scheduler_str(self.gen_config.scheduler)

        nodes = {
            "noise": {
                "id": "noise", "type": "noise",
                "seed": seed, "width": width, "height": height, "use_cpu": False,
            },
            "model_loader": {
                "id": "model_loader", "type": "main_model_loader",
                "model": {"key": model_key},
            },
            "clip_skip": {"id": "clip_skip", "type": "clip_skip", "skipped_layers": 0},
            "positive_conditioning": {
                "id": "positive_conditioning", "type": "compel", "prompt": positive,
            },
            "negative_conditioning": {
                "id": "negative_conditioning", "type": "compel", "prompt": negative,
            },
            "denoise_latents": {
                "id": "denoise_latents", "type": "denoise_latents",
                "steps": steps, "cfg_scale": cfg_scale,
                "denoising_start": 0.0, "denoising_end": 1.0,
                "scheduler": scheduler,
            },
            "l2i": {"id": "l2i", "type": "l2i", "fp32": False},
            "save_image": {
                "id": "save_image", "type": "save_image",
                "is_intermediate": False, "use_cache": False,
            },
        }
        edges = [
            _edge("model_loader", "unet", "denoise_latents", "unet"),
            _edge("model_loader", "clip", "clip_skip", "clip"),
            _edge("clip_skip", "clip", "positive_conditioning", "clip"),
            _edge("clip_skip", "clip", "negative_conditioning", "clip"),
            _edge("noise", "noise", "denoise_latents", "noise"),
            _edge("positive_conditioning", "conditioning", "denoise_latents", "positive_conditioning"),
            _edge("negative_conditioning", "conditioning", "denoise_latents", "negative_conditioning"),
            _edge("denoise_latents", "latents", "l2i", "latents"),
            _edge("model_loader", "vae", "l2i", "vae"),
            _edge("l2i", "image", "save_image", "image"),
        ]
        return nodes, edges

    def _inject_loras(self, nodes: dict, edges: list, lora) -> None:
        lora_list = [l for l in (lora.loras if isinstance(lora, LoraBundle) else [lora]) if l and l.id]
        if not lora_list:
            return
        edges[:] = [e for e in edges if not (
            e["source"]["node_id"] == "model_loader"
            and e["destination"]["node_id"] in ("denoise_latents", "clip_skip")
        )]
        prev = "model_loader"
        for i, l in enumerate(lora_list):
            node_id = f"lora_{i}"
            nodes[node_id] = {
                "id": node_id, "type": "lora_loader",
                "lora": {"key": self._get_model_key(l.id, "lora")},
                "weight": l.lora_strength,
            }
            edges += [_edge(prev, "unet", node_id, "unet"), _edge(prev, "clip", node_id, "clip")]
            prev = node_id
        edges += [_edge(prev, "unet", "denoise_latents", "unet"), _edge(prev, "clip", "clip_skip", "clip")]

    def _inject_controlnet(self, nodes: dict, edges: list,
                            image_name: str, strength: float, cn_key: Optional[str]) -> None:
        node = {
            "id": "controlnet", "type": "controlnet",
            "image": {"image_name": image_name},
            "control_weight": strength,
            "begin_step_percent": 0.0, "end_step_percent": 1.0,
            "control_mode": "balanced", "resize_mode": "just_resize",
        }
        if cn_key:
            node["controlnet_model"] = {"key": cn_key}
        nodes["controlnet"] = node
        edges.append(_edge("controlnet", "control", "denoise_latents", "control"))

    def _inject_img2img(self, nodes: dict, edges: list,
                         image_name: str, denoising_start: float) -> None:
        nodes["i2l"] = {"id": "i2l", "type": "i2l", "image": {"image_name": image_name}, "fp32": False}
        edges.append(_edge("model_loader", "vae", "i2l", "vae"))
        edges.append(_edge("i2l", "latents", "denoise_latents", "latents"))
        nodes["denoise_latents"]["denoising_start"] = max(0.0, min(1.0, denoising_start))

    def _inject_ip_adapter(self, nodes: dict, edges: list,
                            image_name: str, strength: float, ipa_key: Optional[str]) -> None:
        node = {
            "id": "ip_adapter", "type": "ip_adapter",
            "image": {"image_name": image_name},
            "weight": strength,
            "begin_step_percent": 0.0, "end_step_percent": 1.0,
        }
        if ipa_key:
            node["ip_adapter_model"] = {"key": ipa_key}
        nodes["ip_adapter"] = node
        edges.append(_edge("ip_adapter", "ip_adapter", "denoise_latents", "ip_adapter"))

    # -------------------------------------------------------------------------
    # Queue management
    # -------------------------------------------------------------------------

    def _enqueue(self, graph: dict, n_runs: int = 1) -> str:
        cls = type(self)
        url = f"{cls.BASE_URL}/api/v2/queue/{cls.QUEUE_ID}/enqueue_batch"
        payload = {"batch": {"graph": graph, "runs": n_runs}, "prepend": False}
        req = urllib_request.Request(
            url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urllib_request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["batch"]["batch_id"]

    def _poll_batch(self, batch_id: str, n_runs: int, timeout: float = 300.0) -> None:
        cls = type(self)
        url = f"{cls.BASE_URL}/api/v2/queue/{cls.QUEUE_ID}/b/{batch_id}/status"
        req = urllib_request.Request(url, method="GET")
        deadline = time.time() + timeout
        while time.time() < deadline:
            with urllib_request.urlopen(req, timeout=10) as resp:
                st = json.loads(resp.read())
            done = st.get("completed", 0) + st.get("failed", 0) + st.get("canceled", 0)
            if done >= n_runs:
                return
            time.sleep(2)
        raise TimeoutError(f"InvokeAI batch {batch_id} did not complete within {timeout}s")

    def _download_recent_images(self, n: int) -> list:
        cls = type(self)
        params = urllib_parse.urlencode({"limit": n, "order_dir": "DESC", "is_intermediate": "false"})
        listing_url = f"{cls.BASE_URL}/api/v1/images/?{params}"
        with urllib_request.urlopen(urllib_request.Request(listing_url), timeout=10) as resp:
            items = json.loads(resp.read()).get("items", [])[:n]
        result = []
        for item in items:
            name = item.get("image_name", "")
            if not name:
                continue
            img_url = f"{cls.BASE_URL}/api/v1/images/{name}/full"
            with urllib_request.urlopen(urllib_request.Request(img_url), timeout=30) as resp:
                result.append(resp.read())
        return result

    def queue_prompt(self, graph: dict, n_runs: int = 1) -> None:
        cls = type(self)
        try:
            batch_id = self._enqueue(graph, n_runs)
            self._poll_batch(batch_id, n_runs)
            images = self._download_recent_images(n_runs)
            for i, img_bytes in enumerate(images):
                save_path = os.path.join(cls.SAVE_PATH, f"{cls.FILE_PREFIX}_{_timestamp_str()}_{i}.png")
                with open(save_path, "wb") as fh:
                    fh.write(img_bytes)
        except urllib_error.URLError as exc:
            raise Exception(f"Failed to connect to InvokeAI. Is it running? ({exc})") from exc
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    # -------------------------------------------------------------------------
    # Shared helpers
    # -------------------------------------------------------------------------

    def _make_graph(self, model, resolution, n_latents, positive, negative,
                    lora=None, control_net=None, ip_adapter=None,
                    init_image_path=None) -> tuple:
        model = self.gen_config.redo_param("model", model)
        resolution = self.gen_config.redo_param("resolution", resolution)
        n_latents = self.gen_config.redo_param("n_latents", n_latents) or 1
        positive = self.gen_config.redo_param("positive", positive) or ""
        negative = self.gen_config.redo_param("negative", negative) or ""

        model_key = self._get_model_key(model.id)
        width = resolution.width if resolution else 512
        height = resolution.height if resolution else 512
        seed = self.gen_config.get_seed()

        nodes, edges = self._base_nodes(model_key, positive, negative, width, height, seed)

        lora = self.gen_config.redo_param("lora", lora)
        if lora:
            self._inject_loras(nodes, edges, lora)

        cn = self.gen_config.redo_param("control_net", control_net)
        if cn and cn.id:
            cn_image_path = cn.generation_path if hasattr(cn, "generation_path") else cn.id
            cn_image_name = self._upload_image(cn_image_path)
            self._inject_controlnet(nodes, edges, cn_image_name, cn.strength, None)

        ipa = self.gen_config.redo_param("ip_adapter", ip_adapter)
        if ipa and ipa.id and init_image_path is None:
            ipa_path = ipa.generation_path if hasattr(ipa, "generation_path") else ipa.id
            ipa_image_name = self._upload_image(ipa_path)
            ipa_key = self._get_model_key(ipa.id, "ip_adapter")
            self._inject_ip_adapter(nodes, edges, ipa_image_name, ipa.strength, ipa_key)

        if init_image_path:
            init_name = self._upload_image(init_image_path)
            denoise = self.gen_config.denoise or 0.75
            self._inject_img2img(nodes, edges, init_name, 1.0 - denoise)

        return {"nodes": nodes, "edges": edges}, n_latents

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
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN, "Assembling InvokeAI simple image gen",
                          None, model, resolution=resolution, positive=positive, negative=negative)
        graph, n_runs = self._make_graph(model, resolution, n_latents, positive, negative)
        self.queue_prompt(graph, n_runs)

    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None,
                              n_latents=None, positive=None, negative=None, lora=None, **kw):
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.SIMPLE_IMAGE_GEN_LORA, "Assembling InvokeAI LoRA image gen",
                          None, model, resolution=resolution, lora=lora, positive=positive, negative=negative)
        graph, n_runs = self._make_graph(model, resolution, n_latents, positive, negative, lora=lora)
        self.queue_prompt(graph, n_runs)

    def control_net(self, prompt="", resolution=None, model=None, vae=None,
                    n_latents=None, positive=None, negative=None, lora=None,
                    control_net=None, **kw):
        if not self.gen_config.override_resolution and control_net:
            resolution = resolution.get_closest_to_image(control_net.generation_path, round_to=16)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.CONTROLNET, "Assembling InvokeAI ControlNet prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          control_net=control_net)
        graph, n_runs = self._make_graph(model, resolution, n_latents, positive, negative,
                                         lora=lora, control_net=control_net)
        self.queue_prompt(graph, n_runs)

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None,
                   n_latents=None, positive=None, negative=None, lora=None,
                   control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IP_ADAPTER, "Assembling InvokeAI IP-Adapter prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        graph, n_runs = self._make_graph(model, resolution, n_latents, positive, negative,
                                         lora=lora, ip_adapter=ip_adapter)
        self.queue_prompt(graph, n_runs)

    def img2img(self, prompt="", resolution=None, model=None, vae=None,
                n_latents=None, positive=None, negative=None, lora=None,
                control_net=None, ip_adapter=None, **kw):
        if not self.gen_config.override_resolution and ip_adapter:
            resolution = resolution.get_closest_to_image(ip_adapter.generation_path)
        resolution = resolution.convert_for_model_type(model.architecture_type)
        lora = model.validate_loras(lora)
        self.prompt_setup(WorkflowType.IMG2IMG, "Assembling InvokeAI img2img prompt",
                          None, model, resolution=resolution, positive=positive, negative=negative,
                          ip_adapter=ip_adapter)
        init_path = None
        if ip_adapter and ip_adapter.id:
            init_path = ip_adapter.generation_path if hasattr(ip_adapter, "generation_path") else ip_adapter.id
        graph, n_runs = self._make_graph(model, resolution, n_latents, positive, negative,
                                         lora=lora, init_image_path=init_path)
        self.queue_prompt(graph, n_runs)

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None,
                     n_latents=None, positive=None, negative=None, lora=None,
                     control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("instant_lora is not yet implemented for InvokeAI")

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not yet implemented for InvokeAI")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None,
                                      vae=None, lora=None, positive=None, negative=None,
                                      n_latents=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not yet implemented for InvokeAI")
