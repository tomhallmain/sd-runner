"""Where config.json and the blacklist filter cache are stored.

Both live under the app data dir beside the logs, and both are moved out of the
repo's configs/ folder on first use. Tests that resolve those paths point
SD_RUNNER_APP_DATA_DIR and the legacy configs/ folder into tmp_path, so a
failure here cannot move the developer's real files.

The first test guards the suite's own isolation: the per-test teardown resets
the filter cache while a test's ``delenv("SD_RUNNER_CACHE_DIR")`` is still in
effect, so resolving the default path must not create or move anything.
"""

import logging
import os

import pytest

import sd_runner.prompts.blacklist as blacklist_mod
from lib.logging_setup import EncryptedFileHandler, adopt_legacy_file, app_data_dir
from sd_runner.config import Config

CACHE_NAME = "blacklist_filter_cache.pkl"


@pytest.fixture
def fake_app_data(tmp_path, monkeypatch):
    """Point the app data root inside tmp_path and return it, not yet created."""
    root = tmp_path / "app_data"
    monkeypatch.setenv("SD_RUNNER_APP_DATA_DIR", str(root))
    assert app_data_dir(create=False) == root
    return root


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    """A repo root whose legacy configs/ folder holds a config and cache, with
    the example config in sd_runner/data/. Returns the configs/ folder."""
    repo = tmp_path / "repo"
    configs = repo / "configs"
    data = repo / "sd_runner" / "data"
    configs.mkdir(parents=True)
    data.mkdir(parents=True)
    (configs / "config.json").write_text('{"legacy": true}', encoding="utf-8")
    (configs / CACHE_NAME).write_bytes(b"legacy cache")
    example = data / "config_example.json"
    example.write_text('{"example": true}', encoding="utf-8")
    monkeypatch.setattr(blacklist_mod, "_REPO_ROOT", str(repo))
    monkeypatch.setattr(Config, "LEGACY_CONFIGS_DIR", str(configs))
    monkeypatch.setattr(Config, "EXAMPLE_CONFIG_LOC", str(example))
    return configs


def test_log_files_are_written_inside_the_test_run():
    """The suite sets SD_RUNNER_APP_DATA_DIR before lib.logging_setup is first
    imported; if it is set too late, the handlers open files in the real logs
    folder instead."""
    root = os.path.realpath(os.environ["SD_RUNNER_APP_DATA_DIR"])
    handlers = [
        handler
        for name, logger in logging.Logger.manager.loggerDict.items()
        if name.startswith("sd_runner") and isinstance(logger, logging.Logger)
        for handler in logger.handlers
        if isinstance(handler, (logging.FileHandler, EncryptedFileHandler))
    ]
    assert handlers
    for handler in handlers:
        assert os.path.realpath(handler.baseFilename).startswith(root + os.sep)


class TestBlacklistCacheLocation:
    def test_resolving_the_default_path_touches_nothing(
        self, monkeypatch, fake_app_data, fake_repo
    ):
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        path = blacklist_mod._resolve_blacklist_cache_file()
        assert path == os.path.join(str(fake_app_data), "cache", CACHE_NAME)
        assert not fake_app_data.exists()
        assert (fake_repo / CACHE_NAME).exists()

    def test_override_wins(self, monkeypatch, tmp_path, fake_app_data):
        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path / "override"))
        path = blacklist_mod._resolve_blacklist_cache_file()
        assert path == os.path.join(str(tmp_path / "override"), CACHE_NAME)

    def test_prepare_moves_the_legacy_cache(self, monkeypatch, fake_app_data, fake_repo):
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        path = blacklist_mod._resolve_blacklist_cache_file()
        blacklist_mod._prepare_default_cache_dir(path)
        assert open(path, "rb").read() == b"legacy cache"
        assert not (fake_repo / CACHE_NAME).exists()

    def test_prepare_does_nothing_under_the_override(
        self, monkeypatch, tmp_path, fake_app_data, fake_repo
    ):
        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path / "override"))
        blacklist_mod._prepare_default_cache_dir(
            os.path.join(str(fake_app_data), "cache", CACHE_NAME)
        )
        assert not fake_app_data.exists()
        assert (fake_repo / CACHE_NAME).exists()


class TestConfigLocation:
    def test_override_wins_and_touches_nothing(
        self, monkeypatch, tmp_path, fake_app_data, fake_repo
    ):
        override = tmp_path / "override"
        override.mkdir()
        monkeypatch.setenv("SD_RUNNER_CONFIGS_DIR", str(override))
        assert Config.user_configs_dir() == str(override)
        assert not fake_app_data.exists()
        assert (fake_repo / "config.json").exists()

    def test_the_isolated_config_is_the_one_loaded(self, app_config):
        assert app_config.config_path == os.path.join(
            os.environ["SD_RUNNER_CONFIGS_DIR"], "config.json"
        )

    def test_legacy_config_is_moved_to_app_data(self, monkeypatch, fake_app_data, fake_repo):
        monkeypatch.delenv("SD_RUNNER_CONFIGS_DIR", raising=False)
        path = Config.resolve_config_path()
        assert path == os.path.join(str(fake_app_data), "configs", "config.json")
        assert open(path, encoding="utf-8").read() == '{"legacy": true}'
        assert not (fake_repo / "config.json").exists()

    def test_missing_config_is_seeded_from_the_example(
        self, monkeypatch, fake_app_data, fake_repo
    ):
        monkeypatch.delenv("SD_RUNNER_CONFIGS_DIR", raising=False)
        (fake_repo / "config.json").unlink()
        path = Config.resolve_config_path()
        assert open(path, encoding="utf-8").read() == '{"example": true}'
        assert os.path.exists(Config.EXAMPLE_CONFIG_LOC)


class TestAdoptLegacyFile:
    def test_an_existing_target_is_never_overwritten(self, tmp_path):
        legacy = tmp_path / "legacy.json"
        target = tmp_path / "target.json"
        legacy.write_text("old", encoding="utf-8")
        target.write_text("current", encoding="utf-8")
        adopt_legacy_file(str(legacy), str(target))
        assert target.read_text(encoding="utf-8") == "current"
        assert legacy.exists()


class TestMovedCacheFile:
    def test_a_moved_cache_saves_where_it_was_loaded_from(self, tmp_path):
        """The pickle records the path it was saved to; after the file is moved,
        a save must follow the file rather than recreate the old path."""
        from lib.pickleable_cache import SizeAwarePicklableCache

        old_path = tmp_path / "old" / CACHE_NAME
        new_path = tmp_path / "new" / CACHE_NAME
        old_path.parent.mkdir()
        new_path.parent.mkdir()
        cache = SizeAwarePicklableCache(maxsize=4, filename=str(old_path))
        cache.save()
        adopt_legacy_file(str(old_path), str(new_path))

        loaded = SizeAwarePicklableCache.load_or_create(str(new_path), maxsize=4)
        loaded.save()
        assert loaded.filename == str(new_path)
        assert not old_path.exists()
