"""Google Imagen image generation backend (Google AI Studio / Gemini API)."""

import base64
import json
from typing import Optional
from urllib.parse import urlencode

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

logger = get_logger("google_imagen_gen")

_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_DEFAULT_MODEL = "imagen-3.0-generate-001"
_ASPECT_RATIOS = ["1:1", "3:4", "4:3", "9:16", "16:9"]


class GoogleImagenGen(CloudGenBase):
    """Generator for the Google Imagen API (via Google AI Studio).

    Uses the ``predict`` endpoint of the Generative Language API; no GCP
    project or OAuth2 is required — a plain AI Studio API key suffices.

    ``model.id`` should be one of:

    - ``"imagen-3.0-generate-001"`` — Imagen 3 (default, highest quality)
    - ``"imagen-3.0-fast-generate-001"`` — Imagen 3 Fast (lower latency)

    The API key is sent as a ``?key=`` query parameter.  Resolution is mapped
    to the nearest supported aspect ratio from ``["1:1", "3:4", "4:3", "9:16",
    "16:9"]``.  Responses contain inline base64-encoded PNG data.
    """

    BACKEND_NAME = "google"
    DISPLAY_NAME = "Google Imagen"

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
        model_id = (model.id if model else "") or _DEFAULT_MODEL
        aspect_ratio = "1:1"
        if isinstance(resolution, Resolution):
            aspect_ratio = resolution.to_aspect_ratio_string(_ASPECT_RATIOS)
        seed = self.gen_config.get_seed()
        api_key = self._api_key()
        count = max(n_latents or 1, 1)

        url = f"{_BASE_URL}/{model_id}:predict?{urlencode({'key': api_key})}"

        parameters: dict = {
            "sampleCount": count,
            "aspectRatio": aspect_ratio,
        }
        if negative:
            parameters["negativePrompt"] = negative
        if seed != -1:
            parameters["seed"] = seed

        payload = {
            "instances": [{"prompt": positive}],
            "parameters": parameters,
        }
        body = json.dumps(payload).encode()
        headers = {"Content-Type": "application/json"}

        try:
            response_data = self._post_with_retry(url, body, headers)
            predictions = json.loads(response_data).get("predictions", [])
            for i, pred in enumerate(predictions):
                image_data = base64.b64decode(pred["bytesBase64Encoded"])
                path = self._save_image_bytes(image_data, index=i)
                logger.info(f"Google Imagen: saved {path}")
        finally:
            self.release_pending()
