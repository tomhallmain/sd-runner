"""Stability AI image generation backend (v2beta REST API)."""

from typing import Optional

from sd_runner.gen_config import GenConfig
from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("stability_ai_gen")

_BASE_URL = "https://api.stability.ai/v2beta/stable-image/generate"
_ASPECT_RATIOS = ["1:1", "16:9", "9:16", "4:5", "5:4", "2:3", "3:2", "21:9", "9:21"]


def _multipart_body(fields: dict) -> tuple[bytes, str]:
    """Build a multipart/form-data body from a flat dict of string fields."""
    boundary = "FormBoundaryStabilityAIGen"
    body = b""
    for name, value in fields.items():
        if value is None:
            continue
        body += f"--{boundary}\r\n".encode()
        body += f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode()
        body += str(value).encode() + b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return body, f"multipart/form-data; boundary={boundary}"


class StabilityAIGen(CloudGenBase):
    """Generator for the Stability AI REST API (v2beta).

    ``model.id`` should match the API model slug: ``"core"``, ``"ultra"``,
    ``"sd3-large"``, ``"sd3-large-turbo"``, or ``"sd3-medium"``.
    """

    BACKEND_NAME = "stability_ai"

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
        model_id = model.id if model else "core"
        aspect_ratio = "1:1"
        if isinstance(resolution, Resolution):
            aspect_ratio = resolution.to_aspect_ratio_string(_ASPECT_RATIOS)
        seed = self.gen_config.get_seed()
        url = f"{_BASE_URL}/{model_id}"
        api_key = self._api_key()

        try:
            for i in range(max(n_latents or 1, 1)):
                fields = {
                    "prompt": positive,
                    "aspect_ratio": aspect_ratio,
                    "output_format": "png",
                    "seed": seed if seed != -1 else 0,
                }
                if negative:
                    fields["negative_prompt"] = negative
                body, content_type = _multipart_body(fields)
                headers = {
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "image/*",
                    "Content-Type": content_type,
                }
                image_data = self._post_with_retry(url, body, headers)
                path = self._save_image_bytes(image_data, index=i)
                logger.info(f"Stability AI: saved {path}")
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    # ------------------------------------------------------------------
    # Unsupported workflows
    # ------------------------------------------------------------------

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not supported for Stability AI")

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                    positive=None, negative=None, lora=None, control_net=None, **kw):
        raise NotImplementedError("control_net is not supported for Stability AI")

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                   positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("ip_adapter is not supported for Stability AI")

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("img2img is not supported for Stability AI")

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                     positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("instant_lora is not supported for Stability AI")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not supported for Stability AI")
