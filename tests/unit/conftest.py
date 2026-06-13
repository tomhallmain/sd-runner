"""
Unit-test subdirectory conftest — isolation safety net.

The root tests/conftest.py sets SD_RUNNER_CONFIGS_DIR and SD_RUNNER_CACHE_DIR
at module level, which runs before test collection under normal pytest operation.
This file provides a fallback in case of unusual invocation order (e.g. running
pytest directly inside tests/unit/) so Config() and AppInfoCache() never touch
real files regardless of how pytest is launched.
"""
import atexit
import os
import shutil
import tempfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if not os.environ.get("SD_RUNNER_CONFIGS_DIR") or not os.environ.get("SD_RUNNER_CACHE_DIR"):
    _fb_tmp = tempfile.mkdtemp(prefix="sd_runner_unit_fb_")
    if not os.environ.get("SD_RUNNER_CONFIGS_DIR"):
        _fb_configs = os.path.join(_fb_tmp, "configs")
        os.makedirs(_fb_configs, exist_ok=True)
        # Copy example config if available
        _example = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "configs", "config example.json",
        )
        if os.path.isfile(_example):
            import shutil as _sh
            _sh.copy(_example, os.path.join(_fb_configs, "config.json"))
        os.environ["SD_RUNNER_CONFIGS_DIR"] = _fb_configs
    if not os.environ.get("SD_RUNNER_CACHE_DIR"):
        _fb_cache = os.path.join(_fb_tmp, "cache")
        os.makedirs(_fb_cache, exist_ok=True)
        os.environ["SD_RUNNER_CACHE_DIR"] = _fb_cache
    atexit.register(shutil.rmtree, _fb_tmp, True)


import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_app_actions():
    """Plain MagicMock for AppActions — no spec so injected action attributes work."""
    return MagicMock()
