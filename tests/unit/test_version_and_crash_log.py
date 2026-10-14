"""Version information, the fault log, and the smoke test's bookkeeping."""

import json
import os

import pytest

import sd_runner.app_paths as app_paths
from sd_runner.runtime import crash_log, version
from sd_runner.runtime.smoke_test import SmokeTest


@pytest.fixture
def resources(tmp_path, monkeypatch):
    """A resource root in *tmp_path* holding VERSION_FILE, as a build's would."""
    monkeypatch.setattr(app_paths, "RESOURCE_ROOT", str(tmp_path))
    (tmp_path / version.VERSION_FILE).write_text("1.2.3\n", encoding="utf-8")
    return tmp_path


class TestVersion:
    def test_a_checkout_has_no_build_info(self):
        assert version.build_info() == {}
        assert version.describe() == f"SD Runner {version.app_version()} (source checkout)"
        assert version.source_drift() is None

    def test_the_version_is_read_from_the_version_file(self, resources):
        assert version.app_version() == "1.2.3"
        assert version.describe() == "SD Runner 1.2.3 (source checkout)"

    def test_a_missing_version_file_is_described_not_raised(self, resources):
        (resources / version.VERSION_FILE).unlink()
        assert "version unreadable" in version.describe()

    def test_a_build_describes_itself_from_its_build_info(self, resources):
        (resources / version.BUILD_INFO_FILE).write_text(json.dumps({
            "version": "1.2.3",
            "build_id": "20260101-000000",
            "packages": {"PySide6": "6.10.1"},
            "source": {"repo": str(resources), "commit": "0123456789abcdef", "changes": ""},
        }), encoding="utf-8")
        line = version.describe()
        assert line.startswith("SD Runner 1.2.3, ")
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


def _build_from_rewritten_commit(resources, tmp_path, monkeypatch, current_tree):
    """A build from commit d..., whose checkout is now at e... with tree *current_tree*,
    and in which git finds no commit d... (history rewritten, then gc)."""
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    (resources / version.BUILD_INFO_FILE).write_text(json.dumps({
        "source": {"repo": str(checkout), "commit": "d" * 40, "tree": "t" * 40, "changes": ""},
    }), encoding="utf-8")
    monkeypatch.setattr(version, "source_state",
                        lambda repo: {"commit": "e" * 40, "tree": current_tree, "changes": ""})
    monkeypatch.setattr(version, "run_git", lambda repo, *args: None)


class TestSourceDrift:
    def test_a_rewritten_commit_with_the_same_files_matches(self, resources, tmp_path, monkeypatch):
        _build_from_rewritten_commit(resources, tmp_path, monkeypatch, current_tree="t" * 40)
        drifted, message = version.source_drift()
        assert drifted is False
        assert "same files" in message

    def test_a_commit_missing_from_the_history_is_named(self, resources, tmp_path, monkeypatch):
        _build_from_rewritten_commit(resources, tmp_path, monkeypatch, current_tree="u" * 40)
        drifted, message = version.source_drift()
        assert drifted is True
        assert "not in its history" in message

    def test_source_state_records_the_tree(self, monkeypatch):
        answers = {("rev-parse", "HEAD"): "c" * 40 + "\n", ("rev-parse", "HEAD^{tree}"): "t" * 40 + "\n",
                   ("diff", "HEAD", "--binary"): ""}
        monkeypatch.setattr(version, "run_git", lambda repo, *args: answers.get(args))
        assert version.source_state("repo") == {"commit": "c" * 40, "tree": "t" * 40, "changes": ""}


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
