"""
Root conftest for the sd-runner test suite.

Config and AppInfoCache read SD_RUNNER_CONFIGS_DIR / SD_RUNNER_CACHE_DIR env
vars at instantiation time (see utils/config.py and utils/app_info_cache.py).
The module-level bootstrap sets those vars to a throwaway temp directory before
the singletons are first imported, so the real files are never touched.

Each test then gets its own clean directory via the isolated_singletons fixture.
"""

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
# Ephemeral port (OS-assigned) so any AppWindow built during tests never
# contends for the real app's server port (see extensions/sd_runner_server.py).
os.environ["SD_RUNNER_SERVER_PORT"] = "0"

# Imported for the side effect: both modules construct their singleton at import
# time, and this forces that to happen now, with the env vars above in place.
from utils.config import Config  # noqa: F401
from utils.app_info_cache import AppInfoCache  # noqa: F401

import atexit
atexit.register(shutil.rmtree, _bootstrap_tmp, True)

# ---------------------------------------------------------------------------
# Locale: force English for the entire test run so that any assertion that
# compares against a translated string is deterministic regardless of the
# host system locale (e.g. Windows with a German UI language).
# install_locale() replaces the class-level I18N.translate object, which
# I18N._() always dereferences at call time, so this covers all future calls.
# ---------------------------------------------------------------------------
from utils.translations import I18N
I18N.install_locale("en", verbose=False)


# ---------------------------------------------------------------------------
# Singleton patch helpers
# ---------------------------------------------------------------------------

def repoint_singleton_bindings(monkeypatch, attr_name, old_obj, new_obj) -> None:
    """Repoint every module-level binding of *old_obj* to *new_obj*.

    A module doing ``from utils.config import config`` at import time holds its
    own reference to the singleton, so patching the source module alone leaves
    that binding stale and the module keeps reading the un-isolated instance --
    which is never reset between tests, so its values leak into whatever runs
    next. That surfaces as a test passing for the wrong reason, not as an error.

    Sweeping sys.modules replaces the per-module list this used to need, which
    had already gone out of date: 20 of the 32 modules holding a module-level
    ``config`` binding were unpatched, including every backend generator (whose
    bindings carry the user's real backend URLs and save paths) and
    ``utils.cloud_image_saver``. The identity check touches only bindings to the
    exact old object, and modules imported later reach the new object through
    the already-patched source module. Test modules are swept too, so a
    module-level import in a test file no longer writes to a different object
    than the code under test reads.

    Two things it cannot reach: a reference copied onto an instance attribute
    (``self.config = config``), which needs its owner rebuilt; and a module
    imported for the first time *during* a test, which binds that test's
    instance -- monkeypatch never set that binding, so it survives teardown and
    later sweeps no longer recognise it. The second only bites a module reached
    exclusively by a lazy import; anything a test module imports at the top is
    already in sys.modules before the first sweep runs.
    """
    for module in list(sys.modules.values()):
        try:
            if getattr(module, attr_name, None) is old_obj:
                monkeypatch.setattr(module, attr_name, new_obj)
        except Exception:
            continue


# ---------------------------------------------------------------------------
# Class-level state reset
# ---------------------------------------------------------------------------

_original_concepts_dir = None
_original_prompter_tags = None


def _default_concepts_dir() -> str:
    """Concepts.CONCEPTS_DIR as computed at class-definition time.

    Captured on first use -- which is the first _reset_class_state call, before
    any test body has had a chance to redirect it.
    """
    global _original_concepts_dir
    if _original_concepts_dir is None:
        from sd_runner.concepts import Concepts
        _original_concepts_dir = Concepts.CONCEPTS_DIR
    return _original_concepts_dir


def _default_prompter_tags() -> dict:
    """Prompter's tag attributes as bound at class-definition time.

    POSITIVE_TAGS and NEGATIVE_TAGS come from config there, so they are captured
    rather than hardcoded to "". Restoring them centrally means a test that
    injects tags cannot leak them into whatever generates a prompt next.
    """
    global _original_prompter_tags
    if _original_prompter_tags is None:
        from sd_runner.prompter import Prompter
        _original_prompter_tags = {
            "POSITIVE_TAGS": Prompter.POSITIVE_TAGS,
            "NEGATIVE_TAGS": Prompter.NEGATIVE_TAGS,
            "EXCLUSION_TAGS": Prompter.EXCLUSION_TAGS,
            "TAGS_APPLY_TO_START": Prompter.TAGS_APPLY_TO_START,
            "POSITIVE_TAGS_INLINE_VARS": dict(Prompter.POSITIVE_TAGS_INLINE_VARS),
        }
    return _original_prompter_tags


def _reset_if_imported(module_name: str, class_name: str, **attrs) -> None:
    """Reset class attributes, but only on an already-imported module.

    Importing is deliberately not forced: several of these live in ui_qt and
    would pull PySide6 into every unit test just to clear a list that only a UI
    test could have populated.

    Note the Resolution.*_TOTAL_PIXELS_TOLERANCE_RANGE caches are left alone on
    purpose -- they memoise a pure function of the architecture and resolution
    group, so a leaked value is always the value the next test would compute.
    """
    module = sys.modules.get(module_name)
    if module is None:
        return
    owner = getattr(module, class_name, None)
    if owner is None:
        return
    for name, value in attrs.items():
        # Copy containers so callers cannot share one instance across tests;
        # anything else (None, bools, numbers) is assigned as given.
        fresh = type(value)(value) if isinstance(value, (list, dict, set)) else value
        try:
            setattr(owner, name, fresh)
        except Exception:
            continue


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
        Blacklist.SIMILARITY_PHRASE_ITEMS = []
        Blacklist.similarity_threshold = 0.85
        Blacklist.similarity_enabled = False
        Blacklist._similarity_engine = None
        # The filter cache keys only on the concept list, never on blacklist
        # contents, so a result cached under one blacklist is returned verbatim
        # under another. Without this a test that filters the same concepts as
        # an earlier test gets that test's answer, and its assertions pass or
        # fail on execution order.
        Blacklist.reset_filter_cache()
    except Exception:
        pass

    try:
        from sd_runner.concepts import Concepts
        Concepts.ALL_WORDS_LIST = []
        # Lazily filled from a ~34MB corpus on the first NSFW random-words draw.
        Concepts.URBAN_DICTIONARY_CORPUS = []
        # Mutated in place by Concepts.__init__ -> set_concepts_dir, so a test
        # that redirects it can leave the next one pointing at a temp dir.
        Concepts.CONCEPTS_DIR = _default_concepts_dir()
    except Exception:
        pass

    try:
        from sd_runner.expansion import Expansion
        Expansion.expansions = []
    except Exception:
        pass

    try:
        from sd_runner.models import Model
        # Populated by scanning config.models_dir, which points at a real
        # directory on the developer's machine. A scan triggered by one test
        # would otherwise be visible to every test after it.
        Model.CHECKPOINTS = {}
        Model.LORAS = {}
    except Exception:
        pass

    try:
        from sd_runner.timed_schedules_manager import TimedSchedulesManager
        TimedSchedulesManager.schedule_history = []
    except Exception:
        pass

    # Caches whether a password exists, so one test setting a password would
    # otherwise leave every later test believing security is configured.
    _reset_if_imported("ui_qt.auth.password_core", "PasswordManager",
                       _security_configured_cache=None)

    # Window-level history lists, all restored from app_info_cache on open. Only
    # reset if the module is already imported: touching them unconditionally
    # would drag PySide6 into every pure-logic unit test.
    _reset_if_imported("ui_qt.presets.schedules_window", "SchedulesWindow",
                       recent_schedules=[], schedule_history=[])
    _reset_if_imported("ui_qt.presets.presets_window", "PresetsWindow",
                       recent_presets=[], preset_history=[])
    _reset_if_imported("ui_qt.prompts.blacklist_window", "BlacklistWindow",
                       item_history=[])
    _reset_if_imported("ui_qt.prompts.concept_editor_window", "ConceptEditorWindow",
                       concept_change_history=[])
    _reset_if_imported("ui_qt.prompts.expansions_window", "ExpansionsWindow",
                       expansion_history=[])
    _reset_if_imported("ui_qt.prompts.frequent_prompt_tags_window", "FrequentPromptTagsWindow",
                       tag_history=[])

    # Websockets, so close them rather than dropping the list on the floor.
    _comfy = sys.modules.get("sd_runner.generators.comfy")
    if _comfy is not None and getattr(_comfy, "ComfyGen", None) is not None:
        try:
            _comfy.ComfyGen.close_all_connections()
        except Exception:
            pass

    try:
        from sd_runner.prompter import Prompter
        for name, value in _default_prompter_tags().items():
            setattr(Prompter, name, dict(value) if isinstance(value, dict) else value)
    except Exception:
        pass

    try:
        from sd_runner.gen_config import GenConfig
        from utils.config import config as _config
        GenConfig.REDO_PARAMETERS = list(getattr(_config, "redo_parameters", []) or [])
    except Exception:
        pass

    try:
        from sd_runner.timed_schedules_manager import TimedSchedulesManager
        TimedSchedulesManager.recent_timed_schedules = []
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def isolated_singletons(tmp_path, monkeypatch):
    """Give each test a clean Config and AppInfoCache backed by a fresh temp dir.

    Sets SD_RUNNER_CONFIGS_DIR and SD_RUNNER_CACHE_DIR so the constructors pick
    up the temp paths, then sweeps sys.modules to repoint every module-level
    binding of the old singletons, so no test reads from or writes to the real
    cache/config.
    """
    configs_dir = tmp_path / "configs"
    cache_dir = tmp_path / "cache"
    configs_dir.mkdir()
    cache_dir.mkdir()
    if os.path.isfile(_config_example_src):
        shutil.copy(_config_example_src, configs_dir / "config.json")

    monkeypatch.setenv("SD_RUNNER_CONFIGS_DIR", str(configs_dir))
    monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("SD_RUNNER_SERVER_PORT", "0")

    import utils.config as cfg_mod
    import utils.app_info_cache as aic_mod

    old_config = cfg_mod.config
    repoint_singleton_bindings(monkeypatch, "config", old_config, cfg_mod.Config())

    old_cache = aic_mod.app_info_cache
    repoint_singleton_bindings(monkeypatch, "app_info_cache", old_cache, aic_mod.AppInfoCache())

    yield


@pytest.fixture(autouse=True)
def reset_class_state(isolated_singletons):
    """Reset class-level mutable state before and after every test.

    Depends on isolated_singletons rather than relying on autouse declaration
    order: Blacklist.reset_filter_cache() resolves its path from
    SD_RUNNER_CACHE_DIR at call time, so the per-test env var has to be set
    first or the filter cache lands in the session-wide bootstrap directory.
    """
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
