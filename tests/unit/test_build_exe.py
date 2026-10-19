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
            build_exe["VERSION_FILE"],
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

    def test_the_headless_build_is_only_made_on_request(self, build_exe):
        assert [t[0] for t in build_exe["_targets"](False)] == ["SDRunner"]
        assert [t[0] for t in build_exe["_targets"](True)] == ["SDRunner", "SDRunnerHeadless"]

    def test_the_headless_build_leaves_qt_out(self, build_exe):
        assert "--nofollow-import-to=PySide6" in build_exe["_headless_args"]()

    def test_the_unpack_folder_is_in_the_app_data_dir(self, build_exe):
        spec = build_exe["APP_DATA_SPEC"]
        assert spec.startswith("{HOME}/") and spec.endswith("/sd_runner")

    def test_the_package_configuration_is_passed_and_exists(self, build_exe):
        path = build_exe["PACKAGE_CONFIG"]
        assert os.path.isfile(path)
        args = build_exe["_common_args"]("SDRunner.exe", "sdrunner", "1.0.0", "20260101-000000")
        assert f"--user-package-configuration-file={path}" in args


class TestHelpers:
    def test_app_version_is_valid_file_version(self, build_exe):
        version = build_exe["_app_version"]()
        assert 1 <= len(version.split(".")) <= 4
        assert all(part.isdigit() for part in version.split("."))

    def test_app_version_matches_what_the_app_reads(self, build_exe):
        from sd_runner.runtime.version import app_version

        assert build_exe["_app_version"]() == app_version()

    def test_version_module_still_provides_source_state(self, build_exe):
        assert callable(build_exe["_version_module"]()["source_state"])

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


class TestMemoryWait:
    def test_the_plugin_is_loaded(self, build_exe, tmp_path):
        plugin = str(tmp_path / "nuitka_memory_wait.py")
        args = build_exe["_common_args"]("SDRunner.exe", "sdrunner", "1.0.0", "20260101-000000", plugin)
        assert build_exe["_pop_option"](args, "--user-plugin") == plugin

    def test_no_plugin_leaves_the_argument_out(self, build_exe):
        args = build_exe["_common_args"]("SDRunner.exe", "sdrunner", "1.0.0", "20260101-000000", None)
        assert build_exe["_pop_option"](args, "--user-plugin") is None

    @staticmethod
    def _no_tool(build_exe, monkeypatch, tools=None):
        """No variable, *tools* ({command: path}) as what shutil.which finds."""
        monkeypatch.delenv(build_exe["MEMORY_WAIT_PLUGIN_ENV"], raising=False)
        monkeypatch.setattr(build_exe["shutil"], "which", lambda name: (tools or {}).get(name))

    def test_the_variable_names_the_plugin(self, build_exe, monkeypatch, tmp_path):
        plugin = tmp_path / "nuitka_memory_wait.py"
        plugin.write_text("", encoding="utf-8")
        self._no_tool(build_exe, monkeypatch)
        monkeypatch.setenv(build_exe["MEMORY_WAIT_PLUGIN_ENV"], str(plugin))
        assert build_exe["_memory_wait_plugin"]() == str(plugin)

    def test_an_installed_tool_names_the_plugin(self, build_exe, monkeypatch, tmp_path):
        import subprocess

        plugin = tmp_path / "nuitka_memory_wait.py"
        plugin.write_text("", encoding="utf-8")
        self._no_tool(build_exe, monkeypatch, tools={"app-release": "/bin/app-release"})
        calls = []

        def fake_run(args, **kwargs):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, stdout=f"{plugin}\n", stderr="")

        monkeypatch.setattr(build_exe["subprocess"], "run", fake_run)
        assert build_exe["_memory_wait_plugin"]() == str(plugin)
        assert calls == [["/bin/app-release", "--memory-wait-plugin"]]

    def test_no_plugin_anywhere_builds_without_it(self, build_exe, monkeypatch, caplog):
        self._no_tool(build_exe, monkeypatch)
        with caplog.at_level("WARNING", logger="build_exe"):
            assert build_exe["_memory_wait_plugin"]() is None
        assert any("app-release" in message for message in caplog.messages)

    def test_min_free_memory_reaches_nuitka(self, build_exe, monkeypatch):
        name = build_exe["MIN_FREE_MEMORY_ENV"]
        monkeypatch.delenv(name, raising=False)
        assert build_exe["_nuitka_env"]("12")[name] == "12"
        assert name not in build_exe["_nuitka_env"](None)

    @pytest.mark.parametrize("value", ["0", "12", "2.5"])
    def test_min_free_memory_accepts_gib(self, build_exe, value):
        assert build_exe["_min_free_memory"](value) == value

    @pytest.mark.parametrize("value", ["-1", "lots", ""])
    def test_min_free_memory_refuses_other_values(self, build_exe, value):
        with pytest.raises(SystemExit):
            build_exe["_min_free_memory"](value)

    def test_the_variable_is_the_one_the_plugin_reads(self, build_exe):
        # app-release's tests pin the plugin's side of this name.
        assert build_exe["MIN_FREE_MEMORY_ENV"] == "BUILD_MIN_FREE_MEMORY_GB"


class TestTiming:
    @pytest.mark.parametrize("seconds, text", [
        (0, "0s"), (59.6, "1m 00s"), (125, "2m 05s"), (2 * 3600 + 5, "2h 00m 05s"),
    ])
    def test_duration(self, build_exe, seconds, text):
        assert build_exe["_duration"](seconds) == text

    def test_timed_logs_the_duration_of_a_step(self, build_exe, caplog):
        with caplog.at_level("INFO", logger="build_exe"):
            with build_exe["_timed"]("Compiling"):
                pass
        assert caplog.messages[0] == "Compiling..."
        assert caplog.messages[-1].startswith("Compiling done in ")

    def test_timed_logs_a_failed_step(self, build_exe, caplog):
        with caplog.at_level("INFO", logger="build_exe"):
            with pytest.raises(SystemExit):
                with build_exe["_timed"]("Compiling"):
                    raise SystemExit("broken")
        assert caplog.messages[-1].startswith("Compiling failed after ")
