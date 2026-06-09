"""Stable Diffusion WebUI Forge backend (fork of Automatic1111)."""

import threading

from sd_runner.generators.sdwebui import SDWebuiGen
from utils.config import config


class ForgeGen(SDWebuiGen):
    """Generator for SD WebUI Forge.

    Forge is a direct fork of Automatic1111 that exposes the same
    ``sdapi/v1/`` REST API surface.  The only runtime difference is the
    server URL (default port 7861 to avoid clashing with A1111 on 7860)
    and the output save path.

    Set ``forge_url`` and optionally ``forge_save_path`` in ``config.json``.
    All workflows and parameters supported by ``SDWebuiGen`` work unchanged.
    """

    BASE_URL = config.forge_url
    SAVE_PATH = config.forge_save_path
    FILE_PREFIX = "Forge"
    _has_run_txt2img = False
    _txt2img_lock = threading.Lock()
