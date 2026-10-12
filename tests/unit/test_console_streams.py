"""make_console_streams_byte_safe against a stand-in for msvcrt."""

import sys
import types

import pytest

from sd_runner.runtime import console_streams

U8TEXT = 0x40000
TEXT = 0x4000


@pytest.fixture
def fake_msvcrt(monkeypatch):
    modes = {}

    def setmode(fd, mode):
        if fd not in modes:
            raise OSError(9, "Bad file descriptor")
        previous, modes[fd] = modes[fd], mode
        return previous

    monkeypatch.setitem(sys.modules, "msvcrt", types.SimpleNamespace(setmode=setmode))
    return modes


def test_wide_streams_become_binary(fake_msvcrt):
    fake_msvcrt.update({1: U8TEXT, 2: U8TEXT})
    assert console_streams.make_console_streams_byte_safe(is_build=True, platform="win32") == [1, 2]
    assert fake_msvcrt == {1: console_streams._O_BINARY, 2: console_streams._O_BINARY}


def test_other_modes_are_restored(fake_msvcrt):
    fake_msvcrt.update({1: TEXT, 2: U8TEXT})
    assert console_streams.make_console_streams_byte_safe(is_build=True, platform="win32") == [2]
    assert fake_msvcrt[1] == TEXT


def test_a_missing_stream_is_skipped(fake_msvcrt):
    fake_msvcrt.update({2: U8TEXT})
    assert console_streams.make_console_streams_byte_safe(is_build=True, platform="win32") == [2]


def test_nothing_happens_outside_a_windows_build(fake_msvcrt):
    fake_msvcrt.update({1: U8TEXT, 2: U8TEXT})
    assert console_streams.make_console_streams_byte_safe(is_build=False, platform="win32") == []
    assert console_streams.make_console_streams_byte_safe(is_build=True, platform="linux") == []
    assert fake_msvcrt == {1: U8TEXT, 2: U8TEXT}
