"""Helpers for saving cloud-generated images to a local directory."""

import os
import time
from urllib import request as urllib_request

from utils.config import config
from utils.logging_setup import get_logger

logger = get_logger("cloud_image_saver")


def _timestamp_str() -> str:
    ts = str(time.time()).replace(".", "")
    return ts.ljust(17, "0")[:17]


def _resolve_save_dir(save_dir: str | None) -> str:
    return save_dir or config.get_cloud_save_path()


def _unique_path(save_dir: str, prefix: str, index: int = 0) -> str:
    filename = f"{prefix}_{_timestamp_str()}_{index}.png"
    return os.path.join(save_dir, filename)


def save_image_bytes(
    data: bytes,
    save_dir: str | None = None,
    prefix: str = "cloud",
    index: int = 0,
) -> str:
    """Write raw PNG/JPEG *data* to *save_dir* and return the local path.

    Args:
        data:      Raw image bytes.
        save_dir:  Directory to write into.  Defaults to ``config.get_cloud_save_path()``.
        prefix:    Filename prefix (e.g. the backend name).
        index:     Per-batch index appended to the filename to avoid collisions.

    Returns:
        Absolute path of the saved file.
    """
    dest = _resolve_save_dir(save_dir)
    path = _unique_path(dest, prefix, index)
    with open(path, "wb") as fh:
        fh.write(data)
    logger.debug(f"Saved cloud image: {path}")
    return path


def save_image_from_url(
    url: str,
    save_dir: str | None = None,
    prefix: str = "cloud",
    index: int = 0,
    headers: dict | None = None,
) -> str:
    """Download the image at *url*, save it locally and return the local path.

    Args:
        url:       Publicly accessible image URL returned by a cloud API.
        save_dir:  Directory to write into.  Defaults to ``config.get_cloud_save_path()``.
        prefix:    Filename prefix (e.g. the backend name).
        index:     Per-batch index appended to the filename to avoid collisions.
        headers:   Optional extra HTTP headers for the download request (e.g. auth).

    Returns:
        Absolute path of the saved file.
    """
    req = urllib_request.Request(url, headers=headers or {})
    with urllib_request.urlopen(req) as resp:
        data = resp.read()
    return save_image_bytes(data, save_dir=save_dir, prefix=prefix, index=index)
