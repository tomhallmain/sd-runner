"""build_exe.py's lists and helpers, without running a build.

The script is loaded by file path with a run name other than ``__main__``, so
only its definitions execute.
"""

import os
import runpy

import pytest

from sd_runner.app_paths import REPO_ROOT
from sd_runner.runtime.unpack_cleanup import UNPACK_DIR_PREFIXES


@pytest.fixture(scope="module")
def build_exe():
    return runpy.run_path(os.path.join(REPO_ROOT, "build_exe.py"), run_name="build_exe_under_test")


class TestDataFiles:
    def test_every_listed_file_exists(self, build_exe):
        for path in build_exe["_data_files"]():
            assert os.path.isfile(os.path.join(REPO_ROOT, path)), path

    def test_translation_sources_are_left_out(self, build_exe):
        files = build_exe["_data_files"]()
        assert any(f.endswith(".mo") for f in files)
        assert not [f for f in files if f.endswith((".po", ".pot"))]

    def test_the_last_prompt_and_plaintext_corpus_are_left_out(self, build_exe):
        names = {os.path.basename(f) for f in build_exe["_data_files"]()}
        assert "test.json" not in names
        assert "urban_dictionary.txt" not in names
        assert "pending_translation.json" not in names

    def test_both_concept_sets_are_shipped_without_their_subfolders(self, build_exe):
        files = build_exe["_data_files"]()
        for set_dir in ("concepts", "Konzepte"):
            listed = [f for f in files if f.split(os.sep)[0] == set_dir]
            assert listed
            assert all(len(f.split(os.sep)) == 2 for f in listed)

    def test_the_bundled_files_the_app_reads_are_listed(self, build_exe):
        files = set(build_exe["_data_files"]())
        for path in (
            os.path.join("assets", "icon.png"),
            os.path.join("sd_runner", "data", "blacklist_default.enc"),
            os.path.join("sd_runner", "data", "urban_dictionary.enc"),
            os.path.join("sd_runner", "data", "config_example.json"),
        ):
            assert path in files
        assert os.path.join("lib", "sounds") in build_exe["DATA_DIRS"]


class TestTargets:
    def test_unpack_prefixes_match_the_cleanup(self, build_exe):
        prefixes = {prefix + "-" for _name, _entry, prefix, _args in build_exe["TARGETS"]}
        assert prefixes == set(UNPACK_DIR_PREFIXES)

    def test_entry_scripts_exist(self, build_exe):
        for _name, entry, _prefix, _args in build_exe["TARGETS"]:
            assert os.path.isfile(os.path.join(REPO_ROOT, entry))

    def test_the_headless_build_leaves_qt_out(self, build_exe):
        assert "--nofollow-import-to=PySide6" in build_exe["_headless_args"]()

    def test_the_unpack_folder_is_in_the_app_data_dir(self, build_exe):
        spec = build_exe["APP_DATA_SPEC"]
        assert spec.startswith("{HOME}/") and spec.endswith("/sd_runner")


class TestHelpers:
    def test_app_version_is_valid_file_version(self, build_exe):
        version = build_exe["_app_version"]()
        assert 1 <= len(version.split(".")) <= 4
        assert all(part.isdigit() for part in version.split("."))

    def test_lock_has(self, build_exe, tmp_path):
        lock = tmp_path / "lock.txt"
        lock.write_text(
            "liboqs-python @ git+https://example/liboqs-python.git\nPySide6==6.10.1\n",
            encoding="utf-8",
        )
        assert build_exe["_lock_has"](str(lock), "liboqs_python")
        assert build_exe["_lock_has"](str(lock), "pyside6")
        assert not build_exe["_lock_has"](str(lock), "torch")

    def test_pop_option(self, build_exe):
        args = ["--lock=x.txt", "--jobs=4"]
        assert build_exe["_pop_option"](args, "--lock") == "x.txt"
        assert args == ["--jobs=4"]
        assert build_exe["_pop_option"](args, "--lock") is None
