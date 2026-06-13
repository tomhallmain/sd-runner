"""
UI-test subdirectory conftest — isolation safety net + QApplication fixture.

Same isolation guard as tests/unit/conftest.py. Also provides a session-scoped
QApplication and a factory for no-op AppActions mocks so individual tests don't
have to set those up themselves.
"""
import atexit
import os
import shutil
import sys
import tempfile

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

if not os.environ.get("SD_RUNNER_CONFIGS_DIR") or not os.environ.get("SD_RUNNER_CACHE_DIR"):
    _fb_tmp = tempfile.mkdtemp(prefix="sd_runner_ui_fb_")
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
    """Session-scoped QApplication for all UI tests."""
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv[:1])
    yield app


def make_app_actions():
    """Return an AppActions instance with no-op callbacks for all required actions."""
    from ui_qt.app_actions import AppActions
    noop = lambda *a, **kw: None
    return AppActions({action: noop for action in AppActions.REQUIRED_ACTIONS})


@pytest.fixture
def app_window(qapp):
    """Function-scoped real AppWindow.  Tears down without the os._exit failsafe."""
    from PySide6.QtWidgets import QApplication
    from ui_qt.app_window.app_window import AppWindow
    win = AppWindow()
    QApplication.processEvents()
    yield win
    # Stop background tasks safely — do NOT call on_closing() (it has an os._exit failsafe).
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
