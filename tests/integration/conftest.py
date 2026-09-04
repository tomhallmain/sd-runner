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


class _FakeModel:
    architecture_type = None

    def __str__(self):
        return "fake"


@pytest.fixture
def executed():
    """Runs that reached execution, in order. Paired with ``run_stubs``."""
    return []


@pytest.fixture
def run_stubs(monkeypatch, executed):
    """The run machinery, with no backend and nothing on another thread.

    Shared rather than repeated per file: three suites drive a request through
    to ``Run.execute`` and they have to stub the same things to do it, so a
    divergence between copies would mean two of them were testing subtly
    different run paths.

    ``start_thread`` runs inline, which is what makes a request fully served by
    the time the call returns.
    """
    import time as time_module

    from lib.utils import Utils
    from sd_runner.models.model import Model
    from sd_runner.models.resolution import Resolution
    from sd_runner.presets.timed_schedules_manager import timed_schedules_manager
    from sd_runner.runs.run import Run
    from sd_runner.runs.run_config import RunConfig
    from sd_runner.runs.time_estimator import TimeEstimator

    def fake_execute(self):
        executed.append(self)
        self.is_complete = True

    monkeypatch.setattr(Run, "execute", fake_execute)
    monkeypatch.setattr(
        Utils, "start_thread", lambda fn, use_asyncio=False, args=[]: fn(*args)
    )
    monkeypatch.setattr(
        Model, "get_models",
        lambda tags, default_tag=None, inpainting=False, **kw: [_FakeModel()],
    )
    monkeypatch.setattr(
        Resolution, "get_resolutions",
        lambda tags, architecture_type=None, resolution_group=None: [object()],
    )
    monkeypatch.setattr(RunConfig, "validate", lambda self: True)
    # Both estimate entry points, or a run long enough to cross
    # TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS would raise a modal.
    # latents is optional on the real signature; callers pass either shape.
    monkeypatch.setattr(TimeEstimator, "estimate_queue_time", lambda images, latents=1.0: 0)
    monkeypatch.setattr(TimeEstimator, "estimate_run_seconds", lambda gen_config, images: 0)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)
    monkeypatch.setattr(
        timed_schedules_manager, "check_for_shutdown_request", lambda dt: None
    )


@pytest.fixture
def app_window(qapp):
    from PySide6.QtWidgets import QApplication
    from sd_runner.ui.app_window.app_window import AppWindow
    from sd_runner.runs.ui_responsiveness import NullResponsiveness
    win = AppWindow()
    # Run the work inline. There is no one watching this window, so keeping it
    # painting buys nothing, and a worker thread under a nested event loop
    # would make an otherwise synchronous assertion depend on scheduling.
    win.responsiveness = NullResponsiveness()
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
