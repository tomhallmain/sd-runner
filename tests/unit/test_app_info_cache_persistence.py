"""
Cache persistence: atomic writes and change tracking.

Both exist to make saving more often safe and cheap. The atomic write means a
crash part-way through a save cannot corrupt the live cache, and the change
tracking lets the periodic timer skip a write when nothing has moved -- while
still writing unconditionally on the paths tied to a prompt execution, which is
where the blacklist history purge has to run.
"""

import os

import pytest

from lib.equivalence import are_equivalent
from sd_runner.persistence.app_info_cache import AppInfoCache


# ---------------------------------------------------------------------------
# are_equivalent — biased toward reporting a change
# ---------------------------------------------------------------------------

class TestAreEquivalent:
    def test_identical_scalars(self):
        assert are_equivalent(1, 1) is True

    def test_different_scalars(self):
        assert are_equivalent(1, 2) is False

    def test_bool_is_not_the_same_as_int(self):
        """True == 1 in Python; treating them as equal would drop a real change."""
        assert are_equivalent(True, 1) is False
        assert are_equivalent(False, 0) is False

    def test_none_is_not_empty_string(self):
        assert are_equivalent(None, "") is False

    def test_none_matches_none(self):
        assert are_equivalent(None, None) is True

    def test_dict_key_order_is_ignored(self):
        assert are_equivalent({"a": 1, "b": 2}, {"b": 2, "a": 1}) is True

    def test_dict_with_an_extra_key_differs(self):
        assert are_equivalent({"a": 1}, {"a": 1, "b": 2}) is False

    def test_nested_dict_change_is_detected(self):
        assert are_equivalent({"a": {"b": 1}}, {"a": {"b": 2}}) is False

    def test_list_order_matters(self):
        assert are_equivalent([1, 2], [2, 1]) is False

    def test_list_of_dicts_compared_structurally(self):
        assert are_equivalent([{"x": 1}], [{"x": 1}]) is True

    def test_uncomparable_values_report_a_change(self):
        class Explodes:
            def __eq__(self, other):
                raise RuntimeError("nope")
        assert are_equivalent(Explodes(), 1) is False


# ---------------------------------------------------------------------------
# Change tracking
# ---------------------------------------------------------------------------

@pytest.fixture
def cache(app_cache):
    """The isolated AppInfoCache, with any load-time changes already settled."""
    app_cache.store()
    return app_cache


class TestHasChanges:
    def test_clean_after_a_store(self, cache):
        assert cache.has_changes is False

    def test_set_marks_dirty(self, cache):
        cache.set("some_key", "some_value")
        assert cache.has_changes is True

    def test_setting_the_same_value_again_stays_clean(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        cache.set("some_key", "some_value")
        assert cache.has_changes is False

    def test_setting_a_different_value_marks_dirty(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        cache.set("some_key", "other_value")
        assert cache.has_changes is True

    def test_equivalent_dict_value_stays_clean(self, cache):
        cache.set("some_key", {"a": 1, "b": 2})
        cache.store()
        cache.set("some_key", {"b": 2, "a": 1})
        assert cache.has_changes is False

    def test_store_clears_the_flag(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        assert cache.has_changes is False

    def test_set_directory_marks_dirty(self, cache, tmp_path):
        cache.set_directory(str(tmp_path), "some_key", "some_value")
        assert cache.has_changes is True

    def test_repeated_set_directory_stays_clean(self, cache, tmp_path):
        cache.set_directory(str(tmp_path), "some_key", "some_value")
        cache.store()
        cache.set_directory(str(tmp_path), "some_key", "some_value")
        assert cache.has_changes is False

    def test_prompt_history_entry_marks_dirty(self, cache):
        cache.add_prompt_history_entry(positive_tags="a sunset")
        assert cache.has_changes is True

    def test_record_edit_output_marks_dirty(self, cache):
        cache.record_edit_output("image_00001.png")
        assert cache.has_changes is True


class TestStoreOnlyIfChanged:
    def test_skips_when_clean(self, cache):
        assert cache.store(only_if_changed=True) is None

    def test_writes_when_dirty(self, cache):
        cache.set("some_key", "some_value")
        assert cache.store(only_if_changed=True) is True

    def test_unconditional_store_writes_even_when_clean(self, cache):
        """The run-execution save path relies on this: it must always write."""
        assert cache.store() is True

    def test_skipped_store_leaves_the_file_untouched(self, cache):
        path = cache._cache_loc
        before = os.path.getmtime(path)
        cache.store(only_if_changed=True)
        assert os.path.getmtime(path) == before

    def test_a_skipped_store_does_not_lose_the_pending_change(self, cache):
        """A clean skip must not be mistaken for having written."""
        cache.set("some_key", "some_value")
        cache.store(only_if_changed=True)
        assert cache.has_changes is False
        assert cache.get("some_key") == "some_value"


# ---------------------------------------------------------------------------
# Atomic write
# ---------------------------------------------------------------------------

class TestAtomicWrite:
    def test_store_produces_a_readable_cache(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        assert os.path.isfile(cache._cache_loc)
        assert os.path.getsize(cache._cache_loc) > 0

    def test_no_temp_files_are_left_behind(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        leftovers = [
            name for name in os.listdir(os.path.dirname(cache._cache_loc))
            if name.startswith(".app_info_cache_") and name.endswith(".tmp")
        ]
        assert leftovers == []

    def test_a_failed_write_leaves_the_previous_file_intact(self, cache, monkeypatch):
        """The point of the temp-file dance: a mid-write failure is survivable."""
        cache.set("some_key", "original_value")
        cache.store()
        with open(cache._cache_loc, "rb") as f:
            original_bytes = f.read()

        import sd_runner.persistence.app_info_cache as module

        def boom(*args, **kwargs):
            raise RuntimeError("encryption exploded mid-write")

        monkeypatch.setattr(module, "encrypt_data_to_file", boom)
        cache.set("some_key", "new_value")
        cache.store()  # falls back to the JSON store rather than raising

        with open(cache._cache_loc, "rb") as f:
            assert f.read() == original_bytes

    def test_a_failed_write_cleans_up_its_temp_file(self, cache, monkeypatch):
        import sd_runner.persistence.app_info_cache as module

        def boom(*args, **kwargs):
            raise RuntimeError("encryption exploded mid-write")

        monkeypatch.setattr(module, "encrypt_data_to_file", boom)
        cache.set("some_key", "new_value")
        cache.store()

        leftovers = [
            name for name in os.listdir(os.path.dirname(cache._cache_loc))
            if name.startswith(".app_info_cache_") and name.endswith(".tmp")
        ]
        assert leftovers == []

    def test_stored_values_survive_a_reload(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        reloaded = AppInfoCache()
        assert reloaded.get("some_key") == "some_value"


# ---------------------------------------------------------------------------
# Wiped-cache guard
#
# Shutdown empties the cache from memory after its final write. Anything that
# stores afterwards -- the atexit hook, or an excepthook firing during the rest
# of shutdown -- would otherwise write nothing over good data.
# ---------------------------------------------------------------------------

class TestWipedCacheIsNotStored:
    def test_store_after_wipe_is_refused(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        cache.wipe_instance()
        assert cache.store() is None

    def test_conditional_store_after_wipe_is_refused(self, cache):
        cache.wipe_instance()
        assert cache.store(only_if_changed=True) is None

    def test_the_saved_file_survives_a_wipe(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        cache.wipe_instance()
        cache.store()

        reloaded = AppInfoCache()
        assert reloaded.get("some_key") == "some_value"

    def test_file_is_untouched_by_a_refused_store(self, cache):
        cache.set("some_key", "some_value")
        cache.store()
        before = os.path.getmtime(cache._cache_loc)
        cache.wipe_instance()
        cache.store()
        assert os.path.getmtime(cache._cache_loc) == before
