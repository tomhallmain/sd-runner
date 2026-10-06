"""Black Forest Labs (BFL) Flux image generation backend."""

import json
from typing import Optional
from urllib import request as urllib_request

from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from lib.logging_setup import get_logger

logger = get_logger("bfl_gen")

_SUBMIT_URL = "https://api.bfl.ai/v1/{model}"
_RESULT_URL = "https://api.bfl.ai/v1/get_result"


class BFLGen(CloudGenBase):
    """Generator for the Black Forest Labs Flux API (async submit → poll → download).

    ``model.id`` should match a BFL model name: ``"flux-pro-1.1"``,
    ``"flux-pro"``, ``"flux-dev"``, or ``"flux-schnell"``.
    """

    BACKEND_NAME = "bfl"
    DISPLAY_NAME = "BFL Flux"

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
        model_id = model.id if model else "flux-pro-1.1"
        width = 1024
        height = 1024
        if isinstance(resolution, Resolution):
            width = resolution.width
            height = resolution.height
        seed = self.gen_config.get_seed()
        api_key = self._api_key()

        try:
            for i in range(max(n_latents or 1, 1)):
                image_url = self._generate_one(
                    model_id=model_id,
                    positive=positive,
                    width=width,
                    height=height,
                    seed=seed if seed != -1 else None,
                    api_key=api_key,
                )
                path = self._save_image_from_url(image_url, index=i)
                logger.info(f"BFL: saved {path}")
        finally:
            self.release_pending()

    def _generate_one(
        self,
        model_id: str,
        positive: str,
        width: int,
        height: int,
        seed,
        api_key: str,
    ) -> str:
        """Submit a generation request and poll until the image URL is ready."""
        payload: dict = {
            "prompt": positive,
            "width": width,
            "height": height,
        }
        if seed is not None:
            payload["seed"] = seed

        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "x-key": api_key,
        }
        response_data = self._post_with_retry(
            _SUBMIT_URL.format(model=model_id), body, headers
        )
        task_id = json.loads(response_data)["id"]
        logger.debug(f"BFL: submitted task {task_id}")

        return self._poll_until_ready(
            lambda: self._check_result(task_id, api_key),
            timeout=300.0,
            interval=2.0,
        )

    def _check_result(self, task_id: str, api_key: str):
        url = f"{_RESULT_URL}?id={task_id}"
        req = urllib_request.Request(url, headers={"x-key": api_key})
        with urllib_request.urlopen(req) as resp:
            data = json.loads(resp.read())
        status = data.get("status", "")
        if status == "Ready":
            return True, data["result"]["sample"]
        if status in ("Error", "Failed"):
            raise RuntimeError(f"BFL generation failed: {data}")
        return False, None
