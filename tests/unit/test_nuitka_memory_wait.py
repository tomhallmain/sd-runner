"""Helpers of scripts/nuitka_memory_wait.py, loaded by file path; Nuitka is
not needed and no memory is read."""

import importlib.util
import os

import pytest

from sd_runner.app_paths import REPO_ROOT

_PLUGIN = os.path.join(REPO_ROOT, "scripts", "nuitka_memory_wait.py")
GIB = 1024 ** 3


@pytest.fixture(scope="module")
def memory_wait():
    spec = importlib.util.spec_from_file_location("nuitka_memory_wait_under_test", _PLUGIN)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_required_memory_is_capped_by_the_number_of_jobs(memory_wait):
    per_worker = memory_wait.PER_WORKER_BYTES
    job = memory_wait.JOB_BYTES
    assert memory_wait.required_bytes(10, 16) == per_worker
    assert memory_wait.required_bytes(3 * job, 16) == 3 * per_worker
    assert memory_wait.required_bytes(3 * job + 1, 16) == 4 * per_worker
    assert memory_wait.required_bytes(100 * job, 8) == 8 * per_worker
    assert memory_wait.required_bytes(100 * job, 0) == per_worker


def test_folder_size(memory_wait, tmp_path):
    # tmp_path also holds the conftest fixture's cache and configs folders.
    dist = tmp_path / "dist"
    (dist / "sub").mkdir(parents=True)
    (dist / "a.bin").write_bytes(b"x" * 10)
    (dist / "sub" / "b.bin").write_bytes(b"x" * 5)
    assert memory_wait.folder_size(str(dist)) == 15


@pytest.mark.parametrize("seconds, text", [
    (5, "5s"), (65, "1m 05s"), (3600 + 61, "1h 01m 01s"),
])
def test_duration(memory_wait, seconds, text):
    assert memory_wait.duration(seconds) == text


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.sleeps = 0

    def sleep(self, seconds):
        self.sleeps += 1
        self.now += seconds


def _wait(memory_wait, readings, required=4 * GIB, interactive=False, enter_after=None):
    """Run wait_for_memory against *readings* ((free, limit) pairs, the last
    repeated); returns (info messages, warnings, sleeps)."""
    readings = list(readings)
    clock = _Clock()
    info, warnings = [], []

    def read():
        return readings.pop(0) if len(readings) > 1 else readings[0]

    def enter_pressed():
        return enter_after is not None and clock.sleeps >= enter_after

    memory_wait.wait_for_memory(required, info.append, warnings.append, read=read,
                                interactive=interactive, enter_pressed=enter_pressed,
                                sleep=clock.sleep, now=lambda: clock.now)
    return info, warnings, clock.sleeps


def test_enough_free_memory_does_not_wait(memory_wait):
    info, warnings, sleeps = _wait(memory_wait, [(8 * GIB, 32 * GIB)])
    assert sleeps == 0 and warnings == []


def test_waits_until_memory_is_free(memory_wait):
    info, warnings, sleeps = _wait(memory_wait, [(1 * GIB, 32 * GIB)] * 3 + [(5 * GIB, 32 * GIB)])
    assert sleeps == 3
    assert len(warnings) == 1 and "Waiting" in warnings[0]
    assert "Waited" in info[-1]


def test_does_not_wait_when_the_limit_is_too_low(memory_wait):
    info, warnings, sleeps = _wait(memory_wait, [(1 * GIB, 2 * GIB)])
    assert sleeps == 0
    assert len(warnings) == 1 and "--jobs" in warnings[0]


def test_enter_stops_the_wait(memory_wait):
    info, warnings, sleeps = _wait(memory_wait, [(1 * GIB, 32 * GIB)], interactive=True, enter_after=2)
    assert sleeps == 2
    assert "press Enter" in warnings[0]
    assert any("as requested" in message for message in info)


def test_unreadable_memory_does_not_wait(memory_wait):
    info, warnings, sleeps = _wait(memory_wait, [None])
    assert sleeps == 0 and len(warnings) == 1


def test_progress_is_reported_while_waiting(memory_wait):
    polls = memory_wait.REPORT_SECONDS // memory_wait.POLL_SECONDS + 1
    info, warnings, sleeps = _wait(memory_wait, [(1 * GIB, 32 * GIB)] * (polls + 1) + [(5 * GIB, 32 * GIB)])
    assert any(message.startswith("Still waiting") for message in info)
