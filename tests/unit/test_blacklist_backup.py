"""Backing up a cleared blacklist so the clear can be undone.

A clear empties the list and writes it straight to disk, so these cover the
snapshot taken just before that, the grace period it survives for, and the
restore that puts it back. The helpers are plain functions on
``sd_runner.prompts.blacklist_state``, so none of this needs a window.
"""

import datetime

import pytest

from sd_runner.prompts import blacklist_state
from sd_runner.prompts.blacklist import BlacklistItem


def _items(*strings):
    return [BlacklistItem(string=s) for s in strings]


def _aged(days: int) -> str:
    return (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()


@pytest.fixture
def retention(isolated_singletons, monkeypatch):
    """Set the grace period on the Config object the helpers actually read.

    Depends on isolated_singletons rather than relying on autouse declaration
    order: that fixture swaps in a fresh Config and repoints every module-level
    binding of the old one, so patching before it runs would set the attribute
    on the discarded instance and get_clear_backup would never see it.

    Set explicitly rather than left to the copied example config, so these keep
    testing the same thing if that default ever changes.
    """
    def _set(days):
        monkeypatch.setattr(blacklist_state.config,
                            "blacklist_backup_retention_days", days)
    _set(30)
    return _set


@pytest.fixture
def key():
    return blacklist_state.BLACKLIST_BACKUP_KEY


# ---------------------------------------------------------------------------
# Taking the snapshot
# ---------------------------------------------------------------------------

class TestStoringABackup:
    def test_the_cleared_items_are_kept(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, _items("alpha", "beta"))
        backup = blacklist_state.get_clear_backup(key)
        assert {i["string"] for i in backup["items"]} == {"alpha", "beta"}

    def test_it_records_when_the_clear_happened(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, _items("alpha"))
        stored = blacklist_state.get_clear_backup(key)["cleared_at"]
        assert datetime.datetime.fromisoformat(stored)

    def test_clearing_an_empty_list_stores_nothing(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, [])
        assert blacklist_state.get_clear_backup(key) is None

    def test_the_two_blacklists_back_up_independently(self, app_cache, retention):
        blacklist_state.store_clear_backup(blacklist_state.BLACKLIST_BACKUP_KEY, _items("tag"))
        assert blacklist_state.get_clear_backup(blacklist_state.MODEL_BLACKLIST_BACKUP_KEY) is None


# ---------------------------------------------------------------------------
# Clearing twice inside one window
# ---------------------------------------------------------------------------

class TestReclearing:
    def test_the_earlier_clear_is_not_lost(self, app_cache, retention, key):
        """The whole point of merging: a second clear must not discard the
        first clear's items, which are usually the larger set."""
        blacklist_state.store_clear_backup(key, _items("alpha", "beta"))
        blacklist_state.store_clear_backup(key, _items("gamma"))
        backup = blacklist_state.get_clear_backup(key)
        assert {i["string"] for i in backup["items"]} == {"alpha", "beta", "gamma"}

    def test_a_repeated_string_keeps_its_latest_form(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, [BlacklistItem(string="alpha", use_regex=True)])
        blacklist_state.store_clear_backup(key, [BlacklistItem(string="alpha", use_regex=False)])
        items = blacklist_state.get_clear_backup(key)["items"]
        assert len(items) == 1
        assert items[0]["use_regex"] is False

    def test_the_window_runs_from_the_latest_clear(self, app_cache, retention, key):
        """Otherwise a fresh clear would inherit an almost-expired window."""
        app_cache.set(key, {"items": [BlacklistItem(string="old").to_dict()],
                            "cleared_at": _aged(29)})
        blacklist_state.store_clear_backup(key, _items("new"))
        cleared_at = datetime.datetime.fromisoformat(blacklist_state.get_clear_backup(key)["cleared_at"])
        assert (datetime.datetime.now() - cleared_at).days == 0


# ---------------------------------------------------------------------------
# Grace period
# ---------------------------------------------------------------------------

class TestExpiry:
    def test_a_backup_inside_its_window_survives(self, app_cache, retention, key):
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": _aged(29)})
        assert blacklist_state.get_clear_backup(key) is not None

    def test_a_backup_past_its_window_is_gone(self, app_cache, retention, key):
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": _aged(30)})
        assert blacklist_state.get_clear_backup(key) is None

    def test_expiry_deletes_the_key_rather_than_hiding_it(self, app_cache, retention, key):
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": _aged(31)})
        blacklist_state.get_clear_backup(key)
        assert app_cache.get(key) is None

    def test_an_unreadable_timestamp_keeps_the_backup(self, app_cache, retention, key):
        """Losing the items is worse than keeping one that should have gone."""
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": "not a date"})
        assert blacklist_state.get_clear_backup(key) is not None

    def test_zero_retention_never_expires(self, app_cache, retention, key):
        retention(0)
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": _aged(9999)})
        assert blacklist_state.get_clear_backup(key) is not None

    def test_the_startup_sweep_drops_stale_backups(self, app_cache, retention, key):
        app_cache.set(key, {"items": [BlacklistItem(string="alpha").to_dict()],
                            "cleared_at": _aged(31)})
        blacklist_state.expire_stale_backups()
        assert app_cache.get(key) is None


# ---------------------------------------------------------------------------
# Restoring
# ---------------------------------------------------------------------------

class TestRestoring:
    def test_it_returns_the_backed_up_items(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, _items("alpha", "beta"))
        merged = blacklist_state.take_clear_backup(key, [])
        assert {i["string"] for i in merged} == {"alpha", "beta"}

    def test_items_added_since_the_clear_survive(self, app_cache, retention, key):
        """Restoring is additive -- it must not undo work done after the clear."""
        blacklist_state.store_clear_backup(key, _items("alpha"))
        merged = blacklist_state.take_clear_backup(key, _items("added-later"))
        assert {i["string"] for i in merged} == {"alpha", "added-later"}

    def test_the_current_version_of_a_repeated_item_wins(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, [BlacklistItem(string="alpha", enabled=False)])
        merged = blacklist_state.take_clear_backup(key, [BlacklistItem(string="alpha", enabled=True)])
        assert len(merged) == 1
        assert merged[0]["enabled"] is True

    def test_the_backup_is_spent_once_restored(self, app_cache, retention, key):
        blacklist_state.store_clear_backup(key, _items("alpha"))
        blacklist_state.take_clear_backup(key, [])
        assert app_cache.get(key) is None

    def test_restoring_nothing_reports_nothing(self, app_cache, retention, key):
        assert blacklist_state.take_clear_backup(key, _items("current")) is None


# ---------------------------------------------------------------------------
# The cache primitive the discard action needs
# ---------------------------------------------------------------------------

class TestCacheRemove:
    def test_it_deletes_the_key(self, app_cache):
        app_cache.set("some_key", {"a": 1})
        app_cache.remove("some_key")
        assert app_cache.get("some_key", default_val="absent") == "absent"

    def test_it_reports_whether_there_was_anything_to_remove(self, app_cache):
        app_cache.set("some_key", 1)
        assert app_cache.remove("some_key") is True
        assert app_cache.remove("some_key") is False

    def test_removing_an_unknown_key_is_harmless(self, app_cache):
        assert app_cache.remove("never_set") is False
