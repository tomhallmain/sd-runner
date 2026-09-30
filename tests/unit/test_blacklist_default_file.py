"""
The default blacklist file carries the tag and model blacklists together.

One file, written by one encryption run and read by one decryption, so the
first-load default and "Load Default" restore both lists. A file written before
model items were included holds a bare list of tag items and must still load.
"""

import json

import pytest

from lib.encryptor import symmetric_encrypt_data_to_file
from lib.utils import Utils
from sd_runner.globals import Globals
from sd_runner.prompts import blacklist_state
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem, ModelBlacklistItem


@pytest.fixture
def default_file(tmp_path, monkeypatch):
    path = tmp_path / "blacklist_default.enc"
    monkeypatch.setattr(Blacklist, "DEFAULT_BLACKLIST_FILE_LOC", str(path))
    return path


def write_legacy_file(path, tag_strings):
    """A default file in the format written before model items were included."""
    data = json.dumps([BlacklistItem(s).to_dict() for s in tag_strings])
    symmetric_encrypt_data_to_file(
        Utils.preprocess_data_for_encryption(data),
        str(path),
        (Globals.APP_IDENTIFIER + "_blacklist").encode("utf-8"),
    )


def tag_strings():
    return sorted(item.string for item in Blacklist.get_items())


def model_strings():
    return sorted(item.string for item in Blacklist.get_model_items())


class TestRoundTrip:
    @pytest.fixture(autouse=True)
    def _encrypted(self, default_file):
        Blacklist.set_blacklist([BlacklistItem("tag one"), BlacklistItem("tag two")])
        Blacklist.set_model_blacklist([ModelBlacklistItem("model one")])
        Blacklist.encrypt_blacklist()
        Blacklist.set_blacklist([])
        Blacklist.set_model_blacklist([])

    def test_tag_items_are_restored(self):
        Blacklist.decrypt_blacklist()
        assert tag_strings() == ["tag one", "tag two"]

    def test_model_items_are_restored(self):
        Blacklist.decrypt_blacklist()
        assert model_strings() == ["model one"]

    def test_decryption_replaces_the_model_list(self):
        Blacklist.set_model_blacklist([ModelBlacklistItem("stale model")])
        Blacklist.decrypt_blacklist()
        assert model_strings() == ["model one"]

    def test_model_item_settings_survive(self):
        Blacklist.set_model_blacklist([ModelBlacklistItem("pattern.*", enabled=False, use_regex=True)])
        Blacklist.encrypt_blacklist()
        Blacklist.set_model_blacklist([])
        Blacklist.decrypt_blacklist()
        (item,) = Blacklist.get_model_items()
        assert isinstance(item, ModelBlacklistItem)
        assert (item.enabled, item.use_regex) == (False, True)

    def test_the_first_load_default_includes_model_items(self):
        # Through the module: the isolated instance is swapped in per test.
        import sd_runner.persistence.app_info_cache as aic_mod
        aic_mod.app_info_cache.set(blacklist_state.DEFAULT_BLACKLIST_KEY, False)
        blacklist_state.set_blacklist()
        assert model_strings() == ["model one"]

    def test_load_default_includes_model_items(self):
        assert blacklist_state.load_default_blacklist()
        assert model_strings() == ["model one"]


class TestLegacyFile:
    def test_tag_items_load(self, default_file):
        write_legacy_file(default_file, ["old tag"])
        Blacklist.decrypt_blacklist()
        assert tag_strings() == ["old tag"]

    def test_the_model_list_is_left_as_it_is(self, default_file):
        write_legacy_file(default_file, ["old tag"])
        Blacklist.set_model_blacklist([ModelBlacklistItem("kept model")])
        Blacklist.decrypt_blacklist()
        assert model_strings() == ["kept model"]
