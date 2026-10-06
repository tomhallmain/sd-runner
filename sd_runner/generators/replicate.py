"""Replicate cloud image generation backend."""

import json
from typing import Optional
from urllib import request as urllib_request

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

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
    DISPLAY_NAME = "Replicate"

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
            self.release_pending()

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
