"""Fal.ai image generation backend (synchronous REST API)."""

import json
from typing import Optional

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

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
    DISPLAY_NAME = "Fal.ai"

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
            self.release_pending()
