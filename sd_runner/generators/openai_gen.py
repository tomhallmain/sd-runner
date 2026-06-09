"""OpenAI image generation backend (DALL-E 3, DALL-E 2, gpt-image-1)."""

import base64
import json
from typing import Optional

from sd_runner.gen_config import GenConfig
from sd_runner.generators.cloud_base import CloudGenBase
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("openai_gen")

_BASE_URL = "https://api.openai.com/v1/images/generations"

# Supported sizes per model.  We pick the entry whose aspect ratio is closest
# to the requested resolution.
_SIZES = {
    "dall-e-3":   ["1024x1024", "1792x1024", "1024x1792"],
    "dall-e-2":   ["256x256", "512x512", "1024x1024"],
    "gpt-image-1": ["1024x1024", "1536x1024", "1024x1536"],
}
_DEFAULT_MODEL = "dall-e-3"
# DALL-E 3 only supports n=1 per request.
_SINGLE_ONLY_MODELS = {"dall-e-3"}


def _nearest_size(width: int, height: int, sizes: list[str]) -> str:
    own_ratio = width / height
    def _ratio(s):
        w, h = s.split("x")
        return int(w) / int(h)
    return min(sizes, key=lambda s: abs(_ratio(s) - own_ratio))


class OpenAIGen(CloudGenBase):
    """Generator for the OpenAI Images API.

    Covers DALL-E 2, DALL-E 3, and the newer ``gpt-image-1`` model
    (GPT-4o-based, released 2025).  Set ``model_tags`` to the model name:

    - ``"dall-e-3"`` — DALL-E 3 (default; negative prompt ignored by API)
    - ``"dall-e-2"`` — DALL-E 2
    - ``"gpt-image-1"`` — GPT-4o image generation ("ChatGPT images")

    DALL-E 3 only accepts ``n=1``; the generator loops for ``n_latents > 1``.
    ``gpt-image-1`` supports native batching.

    Responses contain either a URL (``url``) or inline base64 (``b64_json``);
    both are handled automatically.
    """

    BACKEND_NAME = "openai"
    BASE_URL = _BASE_URL

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
        model_name = (model.id if model else "") or _DEFAULT_MODEL
        sizes = _SIZES.get(model_name, _SIZES[_DEFAULT_MODEL])
        width = 1024
        height = 1024
        if isinstance(resolution, Resolution):
            width = resolution.width
            height = resolution.height
        size = _nearest_size(width, height, sizes)
        seed = self.gen_config.get_seed()
        api_key = self._api_key()
        count = max(n_latents or 1, 1)
        single_only = model_name in _SINGLE_ONLY_MODELS

        try:
            if single_only:
                for i in range(count):
                    items = self._request(model_name, positive, size, n=1, seed=seed, api_key=api_key)
                    self._save_items(items, index_offset=i)
            else:
                items = self._request(model_name, positive, size, n=count, seed=seed, api_key=api_key)
                self._save_items(items, index_offset=0)
        finally:
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()

    def _request(
        self,
        model_name: str,
        prompt: str,
        size: str,
        n: int,
        seed: int,
        api_key: str,
    ) -> list[dict]:
        payload: dict = {
            "model": model_name,
            "prompt": prompt,
            "n": n,
            "size": size,
        }
        if seed != -1:
            payload["seed"] = seed

        body = json.dumps(payload).encode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        }
        response_data = self._post_with_retry(self.BASE_URL, body, headers)
        return json.loads(response_data).get("data", [])

    def _save_items(self, items: list[dict], index_offset: int = 0):
        for i, item in enumerate(items):
            idx = index_offset + i
            if "url" in item:
                path = self._save_image_from_url(item["url"], index=idx)
            elif "b64_json" in item:
                data = base64.b64decode(item["b64_json"])
                path = self._save_image_bytes(data, index=idx)
            else:
                logger.warning(f"OpenAI: unrecognised image item format at index {idx}")
                continue
            logger.info(f"OpenAI: saved {path}")

    # ------------------------------------------------------------------
    # Unsupported workflows
    # ------------------------------------------------------------------

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise NotImplementedError("upscale_simple is not supported for OpenAI")

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                    positive=None, negative=None, lora=None, control_net=None, **kw):
        raise NotImplementedError("control_net is not supported for OpenAI")

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                   positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("ip_adapter is not supported for OpenAI")

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("img2img is not supported for OpenAI")

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                     positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("instant_lora is not supported for OpenAI")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        raise NotImplementedError("redo_with_different_parameter is not supported for OpenAI")
