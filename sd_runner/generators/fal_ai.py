"""Fal.ai image generation backend (synchronous REST API)."""

import json
from typing import Optional

from sd_runner.gen_config import GenConfig
from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("fal_ai_gen")

_BASE_URL = "https://fal.run"


class FalAIGen(CloudGenBase):
    """Generator for the Fal.ai REST API (synchronous).

    ``model.id`` should be the full Fal.ai application ID, e.g.
    ``"fal-ai/flux/dev"``, ``"fal-ai/flux/schnell"``, or
    ``"fal-ai/stable-diffusion-v3-medium"``.  The URL is constructed as
    ``https://fal.run/{model.id}``.
    """

    BACKEND_NAME = "fal"

    def __init__(self, config: GenConfig = None, ui_callbacks=None):
        super().__init__(config or GenConfig(), ui_callbacks)

    # ------------------------------------------------------------------
    # BaseImageGenerator interface
    # ------------------------------------------------------------------

    def _get_workflows(self) -> dict:
        return {
            WorkflowType.SIMPLE_IMAGE_GEN: self.simple_image_gen,
            WorkflowType.SIMPLE_IMAGE_GEN_LORA: self.simple_image_gen,
        }

    def prompt_setup(self, workflow_type, action, prompt, model, vae=None, resolution=None, **kw):
        self.print_pre(action=action, model=model, resolution=resolution, **kw)
        return None, model, vae

    def simple_image_gen(
        self,
        prompt=None,
        resolution=None,
        model=None,
        vae=None,
        n_latents=1,
        positive=None,
        negative=None,
        **kw,
    ):
        self.queue_prompt(
            model=model,
            resolution=resolution,
            n_latents=n_latents,
            positive=positive or "",
            negative=negative or "",
        )

    def simple_image_gen_lora(
        self,
        prompt=None,
        resolution=None,
        model=None,
        vae=None,
        n_latents=1,
        positive=None,
        negative=None,
        lora=None,
        **kw,
    ):
        self.queue_prompt(
            model=model,
            resolution=resolution,
            n_latents=n_latents,
            positive=positive or "",
            negative=negative or "",
        )

    # ------------------------------------------------------------------
    # API call
    # ------------------------------------------------------------------

    def queue_prompt(
        self,
        model: Optional[Model] = None,
        resolution: Optional[Resolution] = None,
        n_latents: int = 1,
        positive: str = "",
        negative: str = "",
        **kw,
    ):
        model_id = model.id if model else "fal-ai/flux/dev"
        width = 1024
        height = 1024
        if isinstance(resolution, Resolution):
            width = resolution.width
            height = resolution.height
        seed = self.gen_config.get_seed()
        api_key = self._api_key()
        url = f"{_BASE_URL}/{model_id}"

        try:
            payload: dict = {
                "prompt": positive,
                "image_size": {"width": width, "height": height},
                "num_images": max(n_latents or 1, 1),
            }
            if seed != -1:
                payload["seed"] = seed
            if negative:
                payload["negative_prompt"] = negative

            body = json.dumps(payload).encode()
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Key {api_key}",
            }
            response_data = self._post_with_retry(url, body, headers)
            result = json.loads(response_data)

            images = result.get("images", [])
            for i, img in enumerate(images):
                img_url = img.get("url") if isinstance(img, dict) else img
                path = self._save_image_from_url(img_url, index=i)
                logger.info(f"Fal.ai: saved {path}")
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    # ------------------------------------------------------------------
    # Unsupported workflows
    # ------------------------------------------------------------------

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not supported for Fal.ai")

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                    positive=None, negative=None, lora=None, control_net=None, **kw):
        raise NotImplementedError("control_net is not supported for Fal.ai")

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                   positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("ip_adapter is not supported for Fal.ai")

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("img2img is not supported for Fal.ai")

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                     positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("instant_lora is not supported for Fal.ai")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not supported for Fal.ai")
