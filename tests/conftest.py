"""
Root conftest for the sd-runner test suite.

Config and AppInfoCache read SD_RUNNER_CONFIGS_DIR / SD_RUNNER_CACHE_DIR env
vars at instantiation time (see utils/config.py and utils/app_info_cache.py).
The module-level bootstrap sets those vars to a throwaway temp directory before
the singletons are first imported, so the real files are never touched.

Each test then gets its own clean directory via the isolated_singletons fixture.
"""

import importlib
import os
import shutil
import sys
import tempfile

import pytest

# ---------------------------------------------------------------------------
# Project root on sys.path
# ---------------------------------------------------------------------------
_project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# Prevent Qt from trying to open a display during headless test runs.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ---------------------------------------------------------------------------
# Module-level bootstrap: point env vars at a throwaway dir before first import
# ---------------------------------------------------------------------------
_bootstrap_tmp = tempfile.mkdtemp(prefix="sd_runner_tests_")
_bootstrap_configs_dir = os.path.join(_bootstrap_tmp, "configs")
_bootstrap_cache_dir = os.path.join(_bootstrap_tmp, "cache")
os.makedirs(_bootstrap_configs_dir, exist_ok=True)
os.makedirs(_bootstrap_cache_dir, exist_ok=True)

_config_example_src = os.path.join(_project_root, "configs", "config example.json")
if os.path.isfile(_config_example_src):
    shutil.copy(_config_example_src, os.path.join(_bootstrap_configs_dir, "config.json"))

# Must be set before Config() and AppInfoCache() are first instantiated.
os.environ["SD_RUNNER_CONFIGS_DIR"] = _bootstrap_configs_dir
os.environ["SD_RUNNER_CACHE_DIR"] = _bootstrap_cache_dir

from utils.config import Config
from utils.app_info_cache import AppInfoCache

import atexit
atexit.register(shutil.rmtree, _bootstrap_tmp, True)


# ---------------------------------------------------------------------------
# Singleton patch helpers
# ---------------------------------------------------------------------------

def _patch_app_info_cache(monkeypatch, cache_instance) -> None:
    """Redirect all known module-level app_info_cache bindings to cache_instance."""
    import utils.app_info_cache as aic_mod
    monkeypatch.setattr(aic_mod, "app_info_cache", cache_instance)

    for module_name in (
        "ui_qt.app_window.cache_controller",
        "ui_qt.app_window.app_window",
        "ui_qt.auth.password_core",
        "ui_qt.models.recent_adapters_window",
        "ui_qt.prompts.concept_editor_window",
        "ui_qt.prompts.image_to_prompt_window",
        "ui_qt.prompts.prompt_generator_window",
        "ui_qt.runs.runs_window",
        "sd_runner.timed_schedules_manager",
    ):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        if hasattr(mod, "app_info_cache"):
            monkeypatch.setattr(mod, "app_info_cache", cache_instance)


def _patch_config(monkeypatch, config_instance) -> None:
    """Redirect all known module-level config bindings to config_instance."""
    import utils.config as cfg_mod
    monkeypatch.setattr(cfg_mod, "config", config_instance)

    for module_name in (
        "utils.app_info_cache",
        "utils.globals",
        "utils.job_queue",
        "utils.utils",
        "sd_runner.concepts",
        "sd_runner.gen_config",
        "sd_runner.model_adapters",
        "sd_runner.models",
        "sd_runner.prompter",
        "sd_runner.prompter_configuration",
        "sd_runner.generators.base",
        "ui_qt.app_window.app_window",
    ):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        if hasattr(mod, "config"):
            monkeypatch.setattr(mod, "config", config_instance)


# ---------------------------------------------------------------------------
# Class-level state reset
# ---------------------------------------------------------------------------

def _reset_class_state() -> None:
    try:
        from sd_runner.run_config import RunConfig
        RunConfig.previous_model_tags = None
        RunConfig.model_switch_detected = False
        RunConfig.has_warned_about_prompt_massage_text_mismatch = False
    except Exception:
        pass

    try:
        from sd_runner.blacklist import Blacklist
        from utils.globals import BlacklistMode, BlacklistPromptMode, ModelBlacklistMode
        Blacklist.TAG_BLACKLIST = []
        Blacklist.MODEL_BLACKLIST = []
        Blacklist.blacklist_mode = BlacklistMode.REMOVE_ENTIRE_TAG
        Blacklist.blacklist_prompt_mode = BlacklistPromptMode.DISALLOW
        Blacklist.model_blacklist_mode = ModelBlacklistMode.ALLOW_IN_NSFW
        Blacklist.blacklist_silent_removal = False
        Blacklist.model_blacklist_all_prompt_modes = False
    except Exception:
        pass

    try:
        from sd_runner.concepts import Concepts
        Concepts.ALL_WORDS_LIST = []
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_singletons(tmp_path, monkeypatch):
    """Give each test a clean Config and AppInfoCache backed by a fresh temp dir.

    Sets SD_RUNNER_CONFIGS_DIR and SD_RUNNER_CACHE_DIR so the constructors pick
    up the temp paths, then patches every known module-level binding so no test
    ever reads from or writes to the real cache/config.
    """
    configs_dir = tmp_path / "configs"
    cache_dir = tmp_path / "cache"
    configs_dir.mkdir()
    cache_dir.mkdir()
    if os.path.isfile(_config_example_src):
        shutil.copy(_config_example_src, configs_dir / "config.json")

    monkeypatch.setenv("SD_RUNNER_CONFIGS_DIR", str(configs_dir))
    monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(cache_dir))

    import utils.config as cfg_mod
    import utils.app_info_cache as aic_mod

    new_config = cfg_mod.Config()
    _patch_config(monkeypatch, new_config)

    new_cache = aic_mod.AppInfoCache()
    _patch_app_info_cache(monkeypatch, new_cache)

    yield


@pytest.fixture(autouse=True)
def reset_class_state():
    """Reset class-level mutable state before and after every test."""
    _reset_class_state()
    yield
    _reset_class_state()


@pytest.fixture
def app_config(isolated_singletons):
    """Return the isolated Config instance for the current test."""
    from utils.config import config
    return config


@pytest.fixture
def app_cache(isolated_singletons):
    """Return the isolated AppInfoCache instance for the current test."""
    from utils.app_info_cache import app_info_cache
    return app_info_cache
