"""
Integration test conftest — same isolation guard as tests/ui/conftest.py,
plus a session-scoped QApplication and a function-scoped AppWindow fixture.
"""
import atexit
import os
import shutil
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if not os.environ.get("SD_RUNNER_CONFIGS_DIR") or not os.environ.get("SD_RUNNER_CACHE_DIR"):
    _fb_tmp = tempfile.mkdtemp(prefix="sd_runner_integ_fb_")
    if not os.environ.get("SD_RUNNER_CONFIGS_DIR"):
        _fb_configs = os.path.join(_fb_tmp, "configs")
        os.makedirs(_fb_configs, exist_ok=True)
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


@pytest.fixture(scope="session")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


@pytest.fixture
def app_window(qapp):
    from PySide6.QtWidgets import QApplication
    from ui_qt.app_window.app_window import AppWindow
    win = AppWindow()
    QApplication.processEvents()
    yield win
    try:
        win.cache_ctrl.stop_periodic_store()
    except Exception:
        pass
    if getattr(win, "server", None) is not None:
        try:
            win.server.stop()
        except Exception:
            pass
    win.close()
    QApplication.processEvents()
