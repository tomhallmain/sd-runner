"""Version information, the fault log, and the smoke test's bookkeeping."""

import json
import os

import pytest

import sd_runner.app_paths as app_paths
from sd_runner.runtime import crash_log, version
from sd_runner.runtime.smoke_test import SmokeTest


class TestVersion:
    def test_a_checkout_has_no_build_info(self):
        assert version.build_info() == {}
        assert version.describe() == f"SD Runner {version.APP_VERSION} (source checkout)"
        assert version.source_drift() is None

    def test_a_build_describes_itself_from_its_build_info(self, tmp_path, monkeypatch):
        (tmp_path / version.BUILD_INFO_FILE).write_text(json.dumps({
            "version": version.APP_VERSION,
            "build_id": "20260101-000000",
            "packages": {"PySide6": "6.10.1"},
            "source": {"repo": str(tmp_path), "commit": "0123456789abcdef", "changes": ""},
        }), encoding="utf-8")
        monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(tmp_path))
        line = version.describe()
        assert "build 20260101-000000" in line
        assert "0123456789" in line
        assert "PySide6 6.10.1" in line

    def test_read_git_commit_follows_a_ref(self, tmp_path):
        git = tmp_path / ".git"
        (git / "refs" / "heads").mkdir(parents=True)
        (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
        (git / "refs" / "heads" / "master").write_text("abc123\n", encoding="utf-8")
        assert version.read_git_commit(str(tmp_path)) == "abc123"

    def test_read_git_commit_falls_back_to_packed_refs(self, tmp_path):
        git = tmp_path / ".git"
        git.mkdir()
        (git / "HEAD").write_text("ref: refs/heads/master\n", encoding="utf-8")
        (git / "packed-refs").write_text("def456 refs/heads/master\n", encoding="utf-8")
        assert version.read_git_commit(str(tmp_path)) == "def456"


class TestFaultLog:
    def test_writes_a_start_line_and_enables_faulthandler(self, tmp_path, monkeypatch):
        enabled = []
        monkeypatch.setenv("SD_RUNNER_APP_DATA_DIR", str(tmp_path))
        monkeypatch.setattr(crash_log, "_fault_log", None)
        monkeypatch.setattr(crash_log.faulthandler, "enable", lambda **kwargs: enabled.append(kwargs))
        path = crash_log.enable_fault_log()
        try:
            assert path == os.path.join(str(tmp_path), "logs", crash_log.FAULT_LOG_NAME)
            assert enabled and enabled[0]["all_threads"]
            with open(path, encoding="utf-8") as f:
                assert "SD Runner" in f.read()
        finally:
            crash_log._fault_log.close()

    def test_the_name_is_outside_the_log_cleanup_pattern(self):
        assert not crash_log.FAULT_LOG_NAME.startswith("sd_runner_")


class TestSmokeTestBookkeeping:
    def test_a_raising_check_fails_and_the_rest_still_run(self):
        smoke = SmokeTest()
        smoke.check_call("raises", lambda: {}["missing"])
        smoke.check_call("passes", lambda: "fine")
        assert smoke.failures == ["raises"]
        assert smoke.result() == 1

    def test_system_exit_counts_as_a_failure(self):
        """Nuitka's metadata lookup exits the process from inside an import."""
        def exits():
            raise SystemExit(1)

        smoke = SmokeTest()
        smoke.check_call("exits", exits)
        assert smoke.failures == ["exits"]

    def test_all_passing_is_exit_code_zero(self):
        smoke = SmokeTest()
        smoke.check("ok", True)
        assert smoke.result() == 0
