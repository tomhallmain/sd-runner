"""Ideogram image generation backend (v2 / v3 API)."""

import json
from typing import Optional

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

logger = get_logger("ideogram_gen")

_ENDPOINT = "https://api.ideogram.ai/generate"
_DEFAULT_MODEL = "V_2"

# Supported aspect ratios and their API string equivalents.
_ASPECT_RATIO_MAP = {
    "1:1":   "ASPECT_1_1",
    "16:9":  "ASPECT_16_9",
    "9:16":  "ASPECT_9_16",
    "4:3":   "ASPECT_4_3",
    "3:4":   "ASPECT_3_4",
    "3:2":   "ASPECT_3_2",
    "2:3":   "ASPECT_2_3",
    "16:10": "ASPECT_16_10",
    "10:16": "ASPECT_10_16",
}
_ASPECT_RATIOS = list(_ASPECT_RATIO_MAP.keys())


class IdeogramGen(CloudGenBase):
    """Generator for the Ideogram image API.

    ``model.id`` selects the model version:

    - ``"V_2"`` — Ideogram v2 (default, excellent text rendering)
    - ``"V_2_TURBO"`` — Ideogram v2 Turbo (faster, lower quality)
    - ``"V_3"`` — Ideogram v3 (latest)

    Resolution is mapped to the nearest Ideogram aspect ratio string
    (e.g. ``"ASPECT_16_9"``).  ``num_images`` maps to ``n_latents``.
    Ideogram is notable for generating legible text inside images.
    """

    BACKEND_NAME = "ideogram"
    DISPLAY_NAME = "Ideogram"

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
        model_name = (model.id if model else "") or _DEFAULT_MODEL
        ratio_key = "1:1"
        if isinstance(resolution, Resolution):
            ratio_key = resolution.to_aspect_ratio_string(_ASPECT_RATIOS)
        aspect_ratio = _ASPECT_RATIO_MAP[ratio_key]
        seed = self.gen_config.get_seed()
        api_key = self._api_key()

        image_request: dict = {
            "prompt": positive,
            "model": model_name,
            "aspect_ratio": aspect_ratio,
            "num_images": max(n_latents or 1, 1),
            "magic_prompt_option": "AUTO",
        }
        if negative:
            image_request["negative_prompt"] = negative
        if seed != -1:
            image_request["seed"] = seed

        payload = {"image_request": image_request}
        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Api-Key": api_key,
        }

        try:
            response_data = self._post_with_retry(_ENDPOINT, body, headers)
            items = json.loads(response_data).get("data", [])
            for i, item in enumerate(items):
                url = item.get("url", "")
                if not url:
                    logger.warning(f"Ideogram: no URL in response item {i}")
                    continue
                path = self._save_image_from_url(url, index=i)
                logger.info(f"Ideogram: saved {path}")
        finally:
            self.release_pending()
