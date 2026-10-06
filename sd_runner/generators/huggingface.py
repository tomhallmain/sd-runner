"""HuggingFace Inference API image generation backend."""

import json
import time
from typing import Optional
from urllib import error as urllib_error, request as urllib_request

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

logger = get_logger("huggingface_gen")

_BASE_URL = "https://api-inference.huggingface.co/models"
_MODEL_LOADING_POLL_INTERVAL = 10.0
_MODEL_LOADING_TIMEOUT = 600.0


class HuggingFaceGen(CloudGenBase):
    """Generator for the HuggingFace Inference API.

    ``model.id`` should be the HuggingFace model repository ID, e.g.
    ``"stabilityai/stable-diffusion-xl-base-1.0"`` or
    ``"black-forest-labs/FLUX.1-dev"``.  The API returns raw binary image
    bytes (PNG or JPEG).  A 503 response indicates the model is still
    loading; this generator waits and retries automatically.
    """

    BACKEND_NAME = "huggingface"
    DISPLAY_NAME = "HuggingFace"

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
        model_id = model.id if model else ""
        if not model_id:
            raise ValueError("HuggingFace generator requires a model ID (e.g. 'stabilityai/stable-diffusion-xl-base-1.0')")

        width = 1024
        height = 1024
        if isinstance(resolution, Resolution):
            width = resolution.width
            height = resolution.height
        seed = self.gen_config.get_seed()
        api_key = self._api_key()
        url = f"{_BASE_URL}/{model_id}"

        try:
            for i in range(max(n_latents or 1, 1)):
                image_data = self._generate_one(
                    url=url,
                    api_key=api_key,
                    positive=positive,
                    negative=negative,
                    width=width,
                    height=height,
                    seed=seed if seed != -1 else None,
                )
                path = self._save_image_bytes(image_data, index=i)
                logger.info(f"HuggingFace: saved {path}")
        finally:
            self.release_pending()

    def _generate_one(
        self,
        url: str,
        api_key: str,
        positive: str,
        negative: str,
        width: int,
        height: int,
        seed,
    ) -> bytes:
        """POST to the inference API, waiting for model load if needed."""
        parameters: dict = {"width": width, "height": height}
        if negative:
            parameters["negative_prompt"] = negative
        if seed is not None:
            parameters["seed"] = seed

        payload = {"inputs": positive, "parameters": parameters}
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }

        deadline = time.monotonic() + _MODEL_LOADING_TIMEOUT
        while time.monotonic() < deadline:
            req = urllib_request.Request(url, data=body, headers=headers, method="POST")
            try:
                with urllib_request.urlopen(req) as resp:
                    return resp.read()
            except urllib_error.HTTPError as exc:
                if exc.code == 503:
                    wait = _MODEL_LOADING_POLL_INTERVAL
                    try:
                        body_text = exc.read().decode("utf-8", errors="ignore")
                        estimated = json.loads(body_text).get("estimated_time")
                        if estimated:
                            wait = max(float(estimated), _MODEL_LOADING_POLL_INTERVAL)
                    except Exception:
                        pass
                    logger.info(f"HuggingFace: model loading, retrying in {wait:.0f}s")
                    time.sleep(min(wait, deadline - time.monotonic()))
                else:
                    raise

        raise TimeoutError(f"HuggingFace model at {url} did not finish loading within {_MODEL_LOADING_TIMEOUT:.0f}s")
