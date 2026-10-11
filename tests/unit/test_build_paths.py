"""Where bundled and user files resolve, in a checkout and in a compiled build.

Build-only branches are reached by patching ``sd_runner.app_paths.IS_BUILD``
and ``RESOURCE_ROOT``; ``REPO_ROOT`` is patched to a fake repo whenever a test
lets a legacy migration run, so nothing in the real checkout is moved.
"""

import os

import pytest

import sd_runner.app_paths as app_paths
from lib.logging_setup import adopt_legacy_file
from sd_runner.config import Config


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    root = tmp_path / "app_data"
    monkeypatch.setenv("SD_RUNNER_APP_DATA_DIR", str(root))
    return root


@pytest.fixture
def fake_repo(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(app_paths, "REPO_ROOT", str(repo))
    return repo


@pytest.fixture
def fake_bundle(tmp_path, monkeypatch):
    """A build's resource root with one concept set, and IS_BUILD on."""
    bundle = tmp_path / "unpacked" / "sdrunner-20260101-000000"
    concepts = bundle / "concepts"
    concepts.mkdir(parents=True)
    (concepts / "colors.txt").write_text("blue\nred\n", encoding="utf-8")
    (concepts / "animals.txt").write_text("cat\n", encoding="utf-8")
    monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(bundle))
    monkeypatch.setattr(app_paths, "IS_BUILD", True)
    monkeypatch.setattr(app_paths, "_seeded", set())
    return bundle


class TestResolution:
    def test_resource_path_is_under_the_resource_root(self):
        assert app_paths.resource_path("locale") == os.path.join(app_paths.RESOURCE_ROOT, "locale")

    def test_the_resource_root_is_the_repo_in_a_checkout(self):
        assert os.path.isfile(app_paths.resource_path("app_gui.py"))
        assert app_paths.IS_BUILD is False

    def test_a_relative_user_path_is_under_the_app_data_dir(self, app_data):
        assert app_paths.resolve_user_path("out") == os.path.join(str(app_data), "out")
        assert app_paths.resolve_user_path(".") == os.path.normpath(str(app_data))

    def test_an_absolute_user_path_is_unchanged(self, tmp_path):
        assert app_paths.resolve_user_path(str(tmp_path)) == str(tmp_path)

    def test_cache_dir_honours_the_override(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path / "cache_override"))
        assert app_paths.cache_dir() == str(tmp_path / "cache_override")
        assert os.path.isdir(tmp_path / "cache_override")


class TestLegacyMigrationAllowed:
    def test_not_while_the_override_is_set(self, monkeypatch):
        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", "/somewhere")
        assert not app_paths.legacy_migration_allowed()

    def test_not_in_a_build(self, monkeypatch):
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        monkeypatch.setattr(app_paths, "IS_BUILD", True)
        assert not app_paths.legacy_migration_allowed()

    def test_from_a_checkout_without_the_override(self, monkeypatch):
        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        assert app_paths.legacy_migration_allowed()


class TestAdoptLegacyFile:
    def test_an_older_legacy_file_replaces_the_target(self, tmp_path):
        """A build started first leaves defaults there; the user's data wins."""
        legacy = tmp_path / "legacy.json"
        target = tmp_path / "data" / "target.json"
        target.parent.mkdir()
        legacy.write_text("user data", encoding="utf-8")
        target.write_text("default", encoding="utf-8")
        os.utime(legacy, (1000, 1000))
        os.utime(target, (2000, 2000))
        adopt_legacy_file(str(legacy), str(target))
        assert target.read_text(encoding="utf-8") == "user data"
        assert not legacy.exists()

    def test_a_newer_legacy_file_leaves_both(self, tmp_path):
        legacy = tmp_path / "legacy.json"
        target = tmp_path / "target.json"
        legacy.write_text("newer", encoding="utf-8")
        target.write_text("older", encoding="utf-8")
        os.utime(target, (1000, 1000))
        os.utime(legacy, (2000, 2000))
        adopt_legacy_file(str(legacy), str(target))
        assert target.read_text(encoding="utf-8") == "older"
        assert legacy.exists()

    def test_a_missing_target_folder_is_created(self, tmp_path):
        legacy = tmp_path / "legacy.json"
        legacy.write_text("x", encoding="utf-8")
        target = tmp_path / "new" / "dir" / "target.json"
        adopt_legacy_file(str(legacy), str(target))
        assert target.read_text(encoding="utf-8") == "x"

    def test_a_folder_at_the_target_is_left_alone(self, tmp_path):
        legacy = tmp_path / "legacy.json"
        legacy.write_text("x", encoding="utf-8")
        target = tmp_path / "target.json"
        target.mkdir()
        adopt_legacy_file(str(legacy), str(target))
        assert legacy.exists()
        assert target.is_dir()


class TestAppInfoCacheLocation:
    def test_the_override_wins(self, tmp_path, monkeypatch):
        from sd_runner.persistence import app_info_cache as module

        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path / "override"))
        assert module._cache_dir() == str(tmp_path / "override")

    def test_legacy_files_move_into_the_app_data_dir(self, monkeypatch, app_data, fake_repo):
        from sd_runner.persistence import app_info_cache as module

        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        for name in ("app_info_cache.enc", "app_info_cache.enc.bak", "app_info_cache.enc.bak2"):
            (fake_repo / name).write_bytes(name.encode("utf-8"))
        target = module._cache_dir()
        assert target == str(app_data)
        for name in ("app_info_cache.enc", "app_info_cache.enc.bak", "app_info_cache.enc.bak2"):
            assert (app_data / name).read_bytes() == name.encode("utf-8")
            assert not (fake_repo / name).exists()

    def test_nothing_moves_in_a_build(self, monkeypatch, app_data, fake_repo):
        from sd_runner.persistence import app_info_cache as module

        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        monkeypatch.setattr(app_paths, "IS_BUILD", True)
        (fake_repo / "app_info_cache.enc").write_bytes(b"x")
        module._cache_dir()
        assert (fake_repo / "app_info_cache.enc").exists()


class TestOtherUserFiles:
    def test_pending_translations_go_to_the_override(self, tmp_path, monkeypatch):
        from sd_runner.prompts.pending_translation import resolve_pending_translation_file

        monkeypatch.setenv("SD_RUNNER_CACHE_DIR", str(tmp_path))
        assert resolve_pending_translation_file() == str(tmp_path / "pending_translation.json")

    def test_pending_translations_default_to_the_app_data_dir(self, monkeypatch, app_data):
        from sd_runner.prompts.pending_translation import resolve_pending_translation_file

        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        assert resolve_pending_translation_file() == os.path.join(str(app_data), "pending_translation.json")

    def test_the_last_prompt_moves_out_of_the_workflows_folder(self, monkeypatch, app_data, fake_repo):
        from sd_runner.workflow_prompts.base import WorkflowPrompt

        monkeypatch.delenv("SD_RUNNER_CACHE_DIR", raising=False)
        legacy = fake_repo / WorkflowPrompt.LEGACY_LAST_PROMPT_FILE
        legacy.parent.mkdir(parents=True)
        legacy.write_text("{}", encoding="utf-8")
        path = WorkflowPrompt.last_prompt_file()
        assert path == os.path.join(str(app_data), "cache", WorkflowPrompt.LAST_PROMPT_FILENAME)
        assert open(path, encoding="utf-8").read() == "{}"
        assert not legacy.exists()

    def test_shipped_files_resolve_through_the_resource_root(self):
        from sd_runner.prompts.blacklist import Blacklist
        from sd_runner.prompts.concepts import Concepts
        from sd_runner.workflow_prompts.base import WorkflowPrompt

        root = app_paths.RESOURCE_ROOT
        assert Blacklist.DEFAULT_BLACKLIST_FILE_LOC.startswith(root)
        assert Concepts.URBAN_DICTIONARY_CORPUS_PATH.startswith(root)
        assert WorkflowPrompt.PROMPTS_LOC == os.path.join(root, "sd_runner", "data", "workflows")
        assert Config.EXAMPLE_CONFIG_LOC == os.path.join(root, "sd_runner", "data", "config_example.json")


class TestConceptSets:
    def test_a_checkout_uses_the_repo_folder(self):
        assert app_paths.concepts_dir("concepts") == app_paths.resource_path("concepts")

    def test_a_build_seeds_a_copy_in_the_app_data_dir(self, app_data, fake_bundle):
        path = app_paths.concepts_dir("concepts")
        assert path == os.path.join(str(app_data), "concepts")
        assert sorted(os.listdir(path)) == ["animals.txt", "colors.txt"]

    def test_seeding_keeps_edits_and_adds_new_lists(self, app_data, fake_bundle, monkeypatch):
        edited = app_data / "concepts" / "colors.txt"
        edited.parent.mkdir(parents=True)
        edited.write_text("green\n", encoding="utf-8")
        app_paths.concepts_dir("concepts")
        assert edited.read_text(encoding="utf-8") == "green\n"
        assert (app_data / "concepts" / "animals.txt").exists()

    def test_seeding_runs_once_per_process(self, app_data, fake_bundle):
        app_paths.concepts_dir("concepts")
        (app_data / "concepts" / "animals.txt").unlink()
        app_paths.concepts_dir("concepts")
        assert not (app_data / "concepts" / "animals.txt").exists()


class TestConfigPaths:
    def test_a_relative_directory_resolves_against_the_app_data_dir(self, app_config, app_data):
        (app_data / "out").mkdir(parents=True)
        app_config.dict["sd_webui_save_path"] = "out"
        app_config.set_directories("sd_webui_save_path")
        assert app_config.sd_webui_save_path == os.path.join(str(app_data), "out")

    def test_the_default_save_path_is_the_app_data_dir(self, app_config):
        app_config.dict["forge_save_path"] = "."
        app_config.set_directories("forge_save_path")
        assert app_config.forge_save_path == os.path.normpath(os.environ["SD_RUNNER_APP_DATA_DIR"])

    def test_an_absolute_directory_is_unchanged(self, app_config, tmp_path):
        app_config.dict["img_dir"] = str(tmp_path)
        app_config.set_directories("img_dir")
        assert app_config.img_dir == str(tmp_path)

    def test_a_bundled_concept_set_named_relatively_is_that_set(self, app_config):
        assert app_config._resolve_concepts_dir("Konzepte") == app_paths.resource_path("Konzepte")
