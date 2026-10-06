"""``Utils.isdir_with_retry`` / ``isfile_with_retry`` / ``exists_with_retry``.

A path on an internal drive is checked once. A path on an external drive is
retried, after a probe of the drive root meant to wake it, because a sleeping
drive reports its paths missing until it spins up. The three differ only in
which ``os.path`` check they run.
"""

import os

import pytest

from lib.utils import Utils

PATH = "/media/usb/images/a.png"
ROOT = "/media/usb"

PUBLIC = [
    ("isdir_with_retry", "isdir"),
    ("isfile_with_retry", "isfile"),
    ("exists_with_retry", "exists"),
]
PUBLIC_IDS = [p[0] for p in PUBLIC]


class FakeFilesystem:
    """Answers ``os.path`` checks for PATH and ROOT; anything else passes through."""

    def __init__(self, monkeypatch, external, succeed_on=None):
        self.calls = []
        self.sleeps = []
        self.succeed_on = succeed_on
        self.checks = 0
        monkeypatch.setattr(Utils, "_get_external_drive_root", staticmethod(lambda p: ROOT if external else None))
        monkeypatch.setattr("time.sleep", lambda seconds: self.sleeps.append(seconds))
        for name in ("isdir", "isfile", "exists"):
            monkeypatch.setattr(os.path, name, self._fake(name, getattr(os.path, name)))

    def _fake(self, name, real):
        def check(path):
            if path not in (PATH, ROOT):
                return real(path)
            self.calls.append((name, path))
            if path == ROOT:
                return True
            self.checks += 1
            return self.succeed_on is not None and self.checks >= self.succeed_on
        return check

    def checked(self):
        return [call for call in self.calls if call[1] == PATH]

    def probed(self):
        return [call for call in self.calls if call[1] == ROOT]


@pytest.mark.parametrize("method, check", PUBLIC, ids=PUBLIC_IDS)
def test_internal_path_is_checked_once(monkeypatch, method, check):
    fs = FakeFilesystem(monkeypatch, external=False)
    assert getattr(Utils, method)(PATH) is False
    assert fs.checked() == [(check, PATH)]
    assert fs.probed() == []
    assert fs.sleeps == []


@pytest.mark.parametrize("method, check", PUBLIC, ids=PUBLIC_IDS)
def test_external_path_is_retried_after_a_wake_probe(monkeypatch, method, check):
    fs = FakeFilesystem(monkeypatch, external=True)
    assert getattr(Utils, method)(PATH, max_retries=2, retry_delay=0.5) is False
    assert fs.checked() == [(check, PATH)] * 3
    assert fs.probed() == [("exists", ROOT)]
    assert fs.calls[0] == ("exists", ROOT)
    assert fs.sleeps == [0.5, 0.5]


@pytest.mark.parametrize("method, check", PUBLIC, ids=PUBLIC_IDS)
def test_stops_at_the_first_success(monkeypatch, method, check):
    fs = FakeFilesystem(monkeypatch, external=True, succeed_on=2)
    assert getattr(Utils, method)(PATH, max_retries=3, retry_delay=1.0) is True
    assert len(fs.checked()) == 2
    assert fs.sleeps == [1.0]


@pytest.mark.parametrize("method, check", PUBLIC, ids=PUBLIC_IDS)
def test_wake_drive_off_skips_the_probe_but_still_retries(monkeypatch, method, check):
    fs = FakeFilesystem(monkeypatch, external=True)
    assert getattr(Utils, method)(PATH, max_retries=1, retry_delay=0.1, wake_drive=False) is False
    assert fs.probed() == []
    assert len(fs.checked()) == 2
    assert fs.sleeps == [0.1]


@pytest.mark.parametrize("method, check", PUBLIC, ids=PUBLIC_IDS)
def test_success_on_first_check(monkeypatch, method, check):
    fs = FakeFilesystem(monkeypatch, external=False, succeed_on=1)
    assert getattr(Utils, method)(PATH) is True
    assert fs.checked() == [(check, PATH)]
