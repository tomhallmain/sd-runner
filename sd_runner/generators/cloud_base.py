"""Intermediate base class for cloud/API-based image generation backends.

Concrete cloud generators (Stability AI, BFL Flux, Replicate, Fal.ai, …) should
subclass ``CloudGenBase`` instead of ``BaseImageGenerator`` directly.  This class
implements the whole ``BaseImageGenerator`` workflow interface -- simple image
generation routed to the subclass's ``queue_prompt``, every other workflow
raising ``NotImplementedError`` -- and adds three shared capabilities:

1. **API-key retrieval** — ``_api_key()`` reads the key for this backend from
   ``config.cloud_backends`` and raises with a clear message when it is absent.

2. **HTTP POST with retry** — ``_post_with_retry()`` handles transient 429 and 503
   responses using exponential back-off without duplicating that logic in every
   subclass.

3. **Async poll loop** — ``_poll_until_ready()`` repeatedly calls a caller-supplied
   function until it signals completion, with a configurable timeout.
"""

import time
from abc import ABC, abstractmethod
from typing import Any, Callable, Optional, Tuple
from urllib import error as urllib_error, request as urllib_request

from sd_runner.generators.base import BaseImageGenerator
from sd_runner.globals import WorkflowType
from sd_runner.runs.gen_config import GenConfig
from sd_runner.config import config
from lib.logging_setup import get_logger

logger = get_logger("cloud_gen_base")

# HTTP status codes that warrant a retry rather than an immediate failure.
_RETRYABLE_CODES = {429, 503}


class CloudGenBase(BaseImageGenerator, ABC):
    """Abstract base for all cloud image-generation backends.

    Subclasses **must** set ``BACKEND_NAME`` to the short identifier used in
    ``config.json``'s ``cloud_backends`` subdict (e.g. ``"bfl"`` to resolve
    ``bfl_api_key``), set ``DISPLAY_NAME`` for messages, and implement
    ``queue_prompt``.
    """

    BACKEND_NAME: str = ""
    DISPLAY_NAME: str = ""

    def __init__(self, config: GenConfig = None, ui_callbacks=None):
        super().__init__(config or GenConfig(), ui_callbacks)

    @abstractmethod
    def queue_prompt(self, model=None, resolution=None, n_latents: int = 1,
                     positive: str = "", negative: str = "", **kw):
        """Generate and save *n_latents* images for one prompt."""

    # ------------------------------------------------------------------
    # BaseImageGenerator interface
    # ------------------------------------------------------------------

    def _get_workflows(self) -> dict:
        # LoRA runs go to the plain method: no cloud queue_prompt is sent a LoRA.
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
        self.simple_image_gen(
            resolution=resolution,
            model=model,
            n_latents=n_latents,
            positive=positive,
            negative=negative,
        )

    # ------------------------------------------------------------------
    # Unsupported workflows
    # ------------------------------------------------------------------
    # Not reachable through a run: validate_workflow rejects any workflow
    # missing from _get_workflows before dispatch. They exist to satisfy
    # BaseImageGenerator's abstract methods.

    def _unsupported(self, workflow: str):
        return NotImplementedError(
            f"{workflow} is not supported for {self.DISPLAY_NAME or type(self).__name__}"
        )

    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        raise self._unsupported("upscale_simple")

    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                    positive=None, negative=None, lora=None, control_net=None, **kw):
        raise self._unsupported("control_net")

    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                   positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise self._unsupported("ip_adapter")

    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise self._unsupported("img2img")

    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None,
                     positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        raise self._unsupported("instant_lora")

    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        raise self._unsupported("redo_with_different_parameter")

    # ------------------------------------------------------------------
    # API key
    # ------------------------------------------------------------------

    def _api_key(self) -> str:
        """Return the API key for this backend, raising if not configured."""
        if not self.BACKEND_NAME:
            raise ValueError(
                f"{type(self).__name__} must define BACKEND_NAME to use _api_key()."
            )
        return config.require_api_key(self.BACKEND_NAME)

    # ------------------------------------------------------------------
    # Image saving helpers
    # ------------------------------------------------------------------

    def _save_image_bytes(
        self,
        data: bytes,
        index: int = 0,
        save_dir: Optional[str] = None,
    ) -> str:
        """Save raw image bytes and return the local path."""
        from sd_runner.generators.cloud_image_saver import save_image_bytes
        path = save_image_bytes(
            data,
            save_dir=save_dir,
            prefix=self.BACKEND_NAME or "cloud",
            index=index,
        )
        return self.finalize_output_path(path)

    def _save_image_from_url(
        self,
        url: str,
        index: int = 0,
        save_dir: Optional[str] = None,
        headers: Optional[dict] = None,
    ) -> str:
        """Download an image URL and save it locally, returning the local path."""
        from sd_runner.generators.cloud_image_saver import save_image_from_url
        path = save_image_from_url(
            url,
            save_dir=save_dir,
            prefix=self.BACKEND_NAME or "cloud",
            index=index,
            headers=headers,
        )
        return self.finalize_output_path(path)

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _post_with_retry(
        url: str,
        data: bytes,
        headers: dict,
        max_retries: int = 3,
        initial_delay: float = 2.0,
    ) -> bytes:
        """POST *data* to *url* with exponential back-off on 429/503.

        Args:
            url:           Full endpoint URL.
            data:          Encoded request body.
            headers:       HTTP headers dict (must include ``Content-Type``).
            max_retries:   Maximum number of retry attempts after the first failure.
            initial_delay: Seconds to wait before the first retry; doubles each time.

        Returns:
            Response body bytes.

        Raises:
            urllib.error.HTTPError: For non-retryable errors or after exhausting retries.
        """
        delay = initial_delay
        for attempt in range(max_retries + 1):
            req = urllib_request.Request(url, data=data, headers=headers, method="POST")
            try:
                with urllib_request.urlopen(req) as resp:
                    return resp.read()
            except urllib_error.HTTPError as exc:
                if exc.code in _RETRYABLE_CODES and attempt < max_retries:
                    retry_after = exc.headers.get("Retry-After")
                    wait = float(retry_after) if retry_after else delay
                    logger.warning(
                        f"HTTP {exc.code} from {url} — retrying in {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    delay *= 2
                else:
                    raise

    # ------------------------------------------------------------------
    # Async polling
    # ------------------------------------------------------------------

    @staticmethod
    def _poll_until_ready(
        poll_fn: Callable[[], Tuple[bool, Any]],
        timeout: float = 300.0,
        interval: float = 2.0,
    ) -> Any:
        """Poll *poll_fn* until it reports completion or *timeout* seconds elapse.

        ``poll_fn`` must be a zero-argument callable that returns a
        ``(is_done, result)`` tuple:

        - ``is_done=True``  → polling stops and *result* is returned to the caller.
        - ``is_done=False`` → polling continues; *result* is ignored.

        Args:
            poll_fn:  Callable returning ``(bool, Any)``.
            timeout:  Maximum total seconds to wait before raising ``TimeoutError``.
            interval: Seconds between consecutive calls to *poll_fn*.

        Returns:
            The *result* value from the first call where ``is_done`` is ``True``.

        Raises:
            TimeoutError: If the operation does not complete within *timeout* seconds.

        Example::

            def _check():
                resp = json.loads(urllib.request.urlopen(status_url).read())
                if resp["status"] == "Ready":
                    return True, resp["result"]["sample"]
                return False, None

            image_url = self._poll_until_ready(_check, timeout=120, interval=2)
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            is_done, result = poll_fn()
            if is_done:
                return result
            remaining = deadline - time.monotonic()
            time.sleep(min(interval, max(remaining, 0)))
        raise TimeoutError(
            f"Cloud generation did not complete within {timeout:.0f}s."
        )
