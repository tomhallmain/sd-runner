"""Intermediate base class for cloud/API-based image generation backends.

Concrete cloud generators (Stability AI, BFL Flux, Replicate, Fal.ai, …) should
subclass ``CloudGenBase`` instead of ``BaseImageGenerator`` directly.  This class
adds three shared capabilities on top of the local-generator base:

1. **API-key retrieval** — ``_api_key()`` reads the key for this backend from
   ``config.cloud_backends`` and raises with a clear message when it is absent.

2. **HTTP POST with retry** — ``_post_with_retry()`` handles transient 429 and 503
   responses using exponential back-off without duplicating that logic in every
   subclass.

3. **Async poll loop** — ``_poll_until_ready()`` repeatedly calls a caller-supplied
   function until it signals completion, with a configurable timeout.
"""

import time
from abc import ABC
from typing import Any, Callable, Optional, Tuple
from urllib import error as urllib_error, request as urllib_request

from sd_runner.generators.base import BaseImageGenerator
from utils.config import config
from utils.logging_setup import get_logger

logger = get_logger("cloud_gen_base")

# HTTP status codes that warrant a retry rather than an immediate failure.
_RETRYABLE_CODES = {429, 503}


class CloudGenBase(BaseImageGenerator, ABC):
    """Abstract base for all cloud image-generation backends.

    Subclasses **must** set ``BACKEND_NAME`` to the short identifier used in
    ``config.json``'s ``cloud_backends`` subdict (e.g. ``"bfl"`` to resolve
    ``bfl_api_key``).
    """

    BACKEND_NAME: str = ""

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
        from utils.cloud_image_saver import save_image_bytes
        return save_image_bytes(
            data,
            save_dir=save_dir,
            prefix=self.BACKEND_NAME or "cloud",
            index=index,
        )

    def _save_image_from_url(
        self,
        url: str,
        index: int = 0,
        save_dir: Optional[str] = None,
        headers: Optional[dict] = None,
    ) -> str:
        """Download an image URL and save it locally, returning the local path."""
        from utils.cloud_image_saver import save_image_from_url
        return save_image_from_url(
            url,
            save_dir=save_dir,
            prefix=self.BACKEND_NAME or "cloud",
            index=index,
            headers=headers,
        )

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
