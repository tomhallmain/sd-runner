"""Stability AI image generation backend (v2beta REST API)."""

from typing import Optional

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

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
    DISPLAY_NAME = "Stability AI"

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
            self.release_pending()
