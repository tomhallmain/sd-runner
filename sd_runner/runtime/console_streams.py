"""Lets native code write bytes to the console a windowed build attaches to.

Started from a console, a build made with ``--windows-console-mode=attach``
has Nuitka connect the C runtime's stdout and stderr to that console in
wide-character mode (``_O_U8TEXT``). A native library that writes a byte
string there (``fprintf``, ``std::cerr``) makes the C runtime end the process
with ``0xc0000409``, which runs no handler and leaves no trace in the log or
the fault log. Python's own console output goes through ``WriteConsoleW`` and
does not depend on the mode, so the entry point switches both streams to
binary mode before anything else runs. Streams in any other mode (redirected
to a file, or no console at all) are left as they are.

Imports nothing from the project, so it can run before the logging setup.
"""

import os
import sys

#: The C runtime's wide-character modes (fcntl.h): _O_WTEXT, _O_U16TEXT, _O_U8TEXT.
_WIDE_MODES = (0x10000, 0x20000, 0x40000)
_O_BINARY = getattr(os, "O_BINARY", 0x8000)

_IS_BUILD = "__compiled__" in globals()


def make_console_streams_byte_safe(is_build: bool = _IS_BUILD, platform: str = sys.platform) -> list:
    """Switch stdout and stderr out of wide-character mode; returns the fds changed."""
    if not is_build or platform != "win32":
        return []
    import msvcrt

    changed = []
    for fd in (1, 2):
        try:
            previous = msvcrt.setmode(fd, _O_BINARY)
        except OSError:
            continue  # no such stream
        if previous in _WIDE_MODES:
            changed.append(fd)
        else:
            msvcrt.setmode(fd, previous)
    return changed
