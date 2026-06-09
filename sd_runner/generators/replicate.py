"""Replicate cloud image generation backend."""

import json
from typing import Optional
from urllib import request as urllib_request

from sd_runner.gen_config import GenConfig
from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("replicate_gen")

_BASE_URL = "https://api.replicate.com/v1"


def _parse_model_id(model_id: str) -> tuple[str | None, str | None]:
    """Split 'owner/model:version' into (model_ref, version_hash).

    Returns (model_ref, None) when no version hash is present — the newer
    Replicate API accepts ``{"model": "owner/name"}`` without a version hash,
    using the model's current default deployment.
    """
    if ":" in model_id:
        ref, version = model_id.split(":", 1)
        return ref, version
    return model_id, None


class ReplicateGen(CloudGenBase):
    """Generator for the Replicate cloud API.

    ``model.id`` accepts two formats:

    - ``"owner/model-name"`` — uses the model's current default deployment
      (no version hash required for Replicate's official models, e.g.
      ``"black-forest-labs/flux-dev"``).
    - ``"owner/model-name:version-hash"`` — pins to a specific version, which
      is required for community models.

    Both formats are submitted to ``POST /v1/predictions``; the generator
    then polls ``GET /v1/predictions/{id}`` until status is ``"succeeded"``
    and downloads each URL in the output list.
    """

    BACKEND_NAME = "replicate"

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
    # API calls
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
        model_id = model.id if model else ""
        if not model_id:
            raise ValueError("Replicate generator requires a model ID (e.g. 'black-forest-labs/flux-dev')")

        width = 1024
        height = 1024
        if isinstance(resolution, Resolution):
            width = resolution.width
            height = resolution.height
        seed = self.gen_config.get_seed()
        api_key = self._api_key()

        try:
            model_ref, version_hash = _parse_model_id(model_id)
            inputs: dict = {
                "prompt": positive,
                "width": width,
                "height": height,
                "num_outputs": max(n_latents or 1, 1),
            }
            if negative:
                inputs["negative_prompt"] = negative
            if seed != -1:
                inputs["seed"] = seed

            output_urls = self._run_prediction(model_ref, version_hash, inputs, api_key)
            for i, url in enumerate(output_urls):
                path = self._save_image_from_url(url, index=i)
                logger.info(f"Replicate: saved {path}")
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    def _run_prediction(
        self, model_ref: str, version_hash: Optional[str], inputs: dict, api_key: str
    ) -> list[str]:
        """Submit a prediction and poll until it succeeds; return output URL list."""
        payload: dict = {"input": inputs}
        if version_hash:
            payload["version"] = version_hash
        else:
            payload["model"] = model_ref

        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
            "Prefer": "wait",  # ask Replicate to wait up to 60 s before returning
        }
        response_data = self._post_with_retry(f"{_BASE_URL}/predictions", body, headers)
        prediction = json.loads(response_data)
        pred_id = prediction["id"]

        if prediction.get("status") == "succeeded":
            return prediction.get("output") or []

        logger.debug(f"Replicate: submitted prediction {pred_id}, polling...")
        return self._poll_until_ready(
            lambda: self._check_prediction(pred_id, api_key),
            timeout=300.0,
            interval=2.0,
        )

    def _check_prediction(self, pred_id: str, api_key: str):
        url = f"{_BASE_URL}/predictions/{pred_id}"
        req = urllib_request.Request(url, headers={"Authorization": f"Bearer {api_key}"})
        with urllib_request.urlopen(req) as resp:
            data = json.loads(resp.read())
        status = data.get("status", "")
        if status == "succeeded":
            return True, data.get("output") or []
        if status in ("failed", "canceled"):
            raise RuntimeError(f"Replicate prediction {pred_id} {status}: {data.get('error')}")
        return False, None

    # ------------------------------------------------------------------
    # Unsupported workflows
    # ------------------------------------------------------------------

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not supported for Replicate")

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                    positive=None, negative=None, lora=None, control_net=None, **kw):
        raise NotImplementedError("control_net is not supported for Replicate")

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                   positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("ip_adapter is not supported for Replicate")

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("img2img is not supported for Replicate")

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                     positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("instant_lora is not supported for Replicate")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not supported for Replicate")
