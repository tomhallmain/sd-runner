"""SD.Next (vladmandic/automatic) backend."""

import threading

from sd_runner.generators.sdwebui import SDWebuiGen
from utils.config import config


class SDNextGen(SDWebuiGen):
    """Generator for SD.Next (vladmandic/automatic).

    SD.Next exposes the same ``sdapi/v1/`` REST API as Automatic1111 with
    additional extensions.  The practical differences from ``SDWebuiGen`` are:

    - Different server URL (default port 7862).
    - A wider set of supported sampler names — if a sampler configured in
      A1111 style isn't accepted, check ``/sdapi/v1/samplers`` on the
      running SD.Next instance for the exact name strings.

    Set ``sdnext_url`` and optionally ``sdnext_save_path`` in ``config.json``.
    All workflows supported by ``SDWebuiGen`` carry over unchanged.
    """

    BASE_URL = config.sdnext_url
    SAVE_PATH = config.sdnext_save_path
    FILE_PREFIX = "SDNext"
    _has_run_txt2img = False
    _txt2img_lock = threading.Lock()
