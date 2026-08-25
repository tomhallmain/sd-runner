"""
Optional Pillow plugin registration helpers.

Some formats (notably AVIF/HEIF) require runtime plugin registration even when
the pip packages are installed. Call :func:`ensure_pillow_plugins_registered`
before broad PIL decoding paths.
"""

from __future__ import annotations

import importlib
import threading

from utils.logging_setup import get_logger

logger = get_logger("pillow_plugins")

_register_lock = threading.Lock()
_registered = False

has_imported_pillow_jxl = False


def ensure_pillow_plugins_registered() -> None:
    """
    Register optional Pillow format plugins once per process.
    Safe to call repeatedly.
    """
    global _registered, has_imported_pillow_jxl
    if _registered:
        return
    with _register_lock:
        if _registered:
            return

        # AVIF plugin (pillow-avif-plugin)
        try:
            importlib.import_module("pillow_avif")
        except Exception as e:
            logger.debug("Optional Pillow AVIF plugin not active: %s", e)

        # HEIF/HEIC plugin (pillow-heif)
        try:
            heif_mod = importlib.import_module("pillow_heif")
            register = getattr(heif_mod, "register_heif_opener", None)
            if callable(register):
                register()
        except Exception as e:
            logger.debug("Optional Pillow HEIF plugin not active: %s", e)

        # JPEG XL plugin (pillow-jxl-plugin); static .jxl only — no Qt native reader
        try:
            importlib.import_module("pillow_jxl")
            has_imported_pillow_jxl = True
        except Exception as e:
            logger.debug("Optional Pillow JXL plugin not active: %s", e)

        _registered = True

