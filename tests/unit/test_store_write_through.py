"""
Write-through saving for user-authored data.

Blacklist, preset, schedule, expansion and adapter edits used to sit in memory
until the next periodic save. Each subsystem's ``store_*`` now writes through by
default, and ``CacheController.store_info_cache`` passes ``persist=False`` so it
still writes once for all of them rather than once each.

These import the ui_qt windows, so they need Qt importable but never build a
widget -- every method under test is a staticmethod over class-level state.
"""

import pytest

from utils.app_info_cache import app_info_cache


@pytest.fixture
def clean_cache(app_cache):
    """Cache with a settled dirty flag, plus a recorder of store() calls."""
    app_cache.store()
    return app_cache


@pytest.fixture
def store_calls(monkeypatch, clean_cache):
    """Record every store() call and whether it was conditional."""
    calls = []
    original = type(clean_cache).store

    def recording_store(self, only_if_changed=False):
        calls.append(only_if_changed)
        return original(self, only_if_changed=only_if_changed)

    monkeypatch.setattr(type(clean_cache), "store", recording_store)
    return calls


# ---------------------------------------------------------------------------
# Each subsystem writes through by default and can opt out
# ---------------------------------------------------------------------------

SUBSYSTEMS = [
    ("ui_qt.prompts.blacklist_window", "BlacklistWindow", "store_blacklist"),
    ("ui_qt.presets.presets_window", "PresetsWindow", "store_recent_presets"),
    ("ui_qt.presets.presets_window", "PresetsWindow", "store_stashed_configs"),
    ("ui_qt.presets.presets_window", "PresetsWindow", "store_intermediate_prompts"),
    ("ui_qt.presets.schedules_window", "SchedulesWindow", "store_schedules"),
    ("ui_qt.prompts.expansions_window", "ExpansionsWindow", "store_expansions"),
    ("ui_qt.models.recent_adapters_window", "RecentAdaptersWindow", "save_recent_adapters"),
]


def _store_method(module_name, class_name, method_name):
    import importlib
    module = importlib.import_module(module_name)
    return getattr(getattr(module, class_name), method_name)


@pytest.mark.parametrize(
    "module_name,class_name,method_name", SUBSYSTEMS,
    ids=[s[2] for s in SUBSYSTEMS],
)
class TestWriteThrough:
    def test_defaults_to_persisting(self, module_name, class_name, method_name, store_calls):
        _store_method(module_name, class_name, method_name)()
        assert store_calls, f"{method_name}() did not reach app_info_cache.store()"

    def test_persist_is_conditional(self, module_name, class_name, method_name, store_calls):
        """A write-through must not force a write when nothing changed."""
        _store_method(module_name, class_name, method_name)()
        assert all(only_if_changed for only_if_changed in store_calls)

    def test_persist_false_does_not_write(self, module_name, class_name, method_name, store_calls):
        _store_method(module_name, class_name, method_name)(persist=False)
        assert store_calls == []

    def test_cache_is_clean_afterwards(self, module_name, class_name, method_name, clean_cache):
        """The write must be the last thing the method does.

        Anything that sets a cache key after the write is both unpersisted and
        left dirty, which is how a persist call inserted mid-method shows up.
        """
        _store_method(module_name, class_name, method_name)()
        assert clean_cache.has_changes is False, (
            f"{method_name}() modified the cache after writing it"
        )


# ---------------------------------------------------------------------------
# The subsystems actually persist a real edit
# ---------------------------------------------------------------------------

class TestBlacklistEditPersists:
    def test_added_item_is_written_to_the_cache(self, clean_cache):
        from sd_runner.blacklist import Blacklist, BlacklistItem
        from ui_qt.prompts.blacklist_window import BlacklistWindow

        Blacklist.add_item(BlacklistItem("wolf"))
        BlacklistWindow.store_blacklist()

        stored = app_info_cache.get(BlacklistWindow.BLACKLIST_CACHE_KEY) or []
        assert any(entry.get("string") == "wolf" for entry in stored)

    def test_the_write_reaches_disk(self, clean_cache):
        from sd_runner.blacklist import Blacklist, BlacklistItem
        from ui_qt.prompts.blacklist_window import BlacklistWindow
        from utils.app_info_cache import AppInfoCache

        Blacklist.add_item(BlacklistItem("wolf"))
        BlacklistWindow.store_blacklist()

        reloaded = AppInfoCache()
        stored = reloaded.get(BlacklistWindow.BLACKLIST_CACHE_KEY) or []
        assert any(entry.get("string") == "wolf" for entry in stored)

    def test_cache_is_clean_after_the_edit(self, clean_cache):
        from sd_runner.blacklist import Blacklist, BlacklistItem
        from ui_qt.prompts.blacklist_window import BlacklistWindow

        Blacklist.add_item(BlacklistItem("wolf"))
        BlacklistWindow.store_blacklist()
        assert clean_cache.has_changes is False


class TestExpansionEditPersists:
    def test_expansion_reaches_disk(self, clean_cache):
        from sd_runner.expansion import Expansion
        from ui_qt.prompts.expansions_window import ExpansionsWindow
        from utils.app_info_cache import AppInfoCache

        Expansion.expansions = [Expansion("greeting", "hello there")]
        ExpansionsWindow.store_expansions()

        reloaded = AppInfoCache()
        stored = reloaded.get("expansions") or []
        assert any(entry.get("id") == "greeting" for entry in stored)


class TestPresetEditPersists:
    def test_recent_presets_reach_disk(self, clean_cache):
        from ui_qt.presets.presets_window import PresetsWindow
        from utils.app_info_cache import AppInfoCache

        PresetsWindow.store_recent_presets()
        reloaded = AppInfoCache()
        assert reloaded.get("recent_presets") is not None


class TestScheduleEditPersists:
    def test_recent_schedules_reach_disk(self, clean_cache):
        from tests.utils import make_schedule
        from ui_qt.presets.schedules_window import SchedulesWindow
        from utils.app_info_cache import AppInfoCache

        SchedulesWindow.recent_schedules = [make_schedule("Evening")]
        SchedulesWindow.store_schedules()

        reloaded = AppInfoCache()
        stored = reloaded.get("recent_schedules") or []
        assert any(entry.get("name") == "Evening" for entry in stored)
