"""Nuitka user plugin (``--user-plugin=``) that waits for free memory before
the onefile payload is compressed.

Compression is the last step of a build, after the C compilation, and at
level 22 with one zstd worker per Nuitka job it can need several GiB; when an
allocation fails the build is lost. Before compressing, the plugin estimates
the memory needed from the payload size and Nuitka's job limit, and waits until
that much is free (on Windows, the commit memory left, which allocations draw
from). BUILD_MIN_FREE_MEMORY_GB sets the amount instead; 0 turns the check off.
It also reports the least free memory seen while compressing.

The helpers above the plugin class work without Nuitka, for tests.
"""

import atexit
import os
import sys
import threading
import time

MIN_FREE_ENV = "BUILD_MIN_FREE_MEMORY_GB"
GIB = 1024 ** 3
# zstd at level 22 with worker threads splits the input into 512 MiB jobs
# (2 ** (windowLog 27 + 2)). Per busy worker: that input, an output buffer of
# about the same size, the 128 MiB window overlap and 640 MiB of match tables
# (chainLog 27, hashLog 25). Estimated from the level's parameters, not measured.
JOB_BYTES = 512 * 1024 ** 2
PER_WORKER_BYTES = 2 * GIB
POLL_SECONDS = 5
REPORT_SECONDS = 60


def required_bytes(payload_bytes: int, workers: int) -> int:
    """Memory estimated for compressing *payload_bytes* with *workers* threads."""
    jobs = max(1, -(-payload_bytes // JOB_BYTES))
    return min(max(1, workers), jobs) * PER_WORKER_BYTES


def folder_size(path: str) -> int:
    total = 0
    for folder, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(folder, name))
            except OSError:
                pass
    return total


def free_memory():
    """(free bytes, the most that could be free) or None when unknown. On
    Windows these are the commit memory left and the commit limit (RAM plus
    page files); elsewhere available and total RAM."""
    if sys.platform == "win32":
        import ctypes

        class MemoryStatusEx(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MemoryStatusEx()
        status.dwLength = ctypes.sizeof(MemoryStatusEx)
        if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return None
        return status.ullAvailPageFile, status.ullTotalPageFile
    try:
        import psutil
    except ImportError:
        return None
    memory = psutil.virtual_memory()
    return memory.available, memory.total


def duration(seconds: float) -> str:
    seconds = int(round(seconds))
    hours, rest = divmod(seconds, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}h {minutes:02d}m {seconds:02d}s"
    if minutes:
        return f"{minutes}m {seconds:02d}s"
    return f"{seconds}s"


def _gib(n: int) -> str:
    return f"{n / GIB:.1f} GiB"


def _enter_pressed() -> bool:
    """Whether Enter was pressed in the console; consumes the input."""
    if sys.platform == "win32":
        import msvcrt
        pressed = False
        while msvcrt.kbhit():
            pressed = msvcrt.getwch() in ("\r", "\n") or pressed
        return pressed
    import select
    if select.select([sys.stdin], [], [], 0)[0]:
        sys.stdin.readline()
        return True
    return False


def wait_for_memory(required: int, info, warning, read=free_memory, interactive=None,
                    enter_pressed=_enter_pressed, sleep=time.sleep, now=time.monotonic) -> None:
    """Return once *required* bytes are free, Enter is pressed (when
    *interactive*), or waiting cannot help."""
    state = read()
    if state is None:
        warning("Cannot read the free memory; compressing without checking it.")
        return
    free, limit = state
    if free >= required:
        info(f"Compressing: about {_gib(required)} needed, {_gib(free)} free.")
        return
    if limit < required:
        warning(f"Compressing may need about {_gib(required)}, more than this system's limit of "
                f"{_gib(limit)}; compressing anyway. If it fails, build with fewer jobs (--jobs=N) "
                "or with --low-memory.")
        return
    if interactive is None:
        interactive = sys.stdin is not None and sys.stdin.isatty()
    warning(f"Waiting for about {_gib(required)} of free memory before compressing ({_gib(free)} free); "
            "close other programs" + (", or press Enter to compress now" if interactive else "")
            + f". build_exe.py's --min-free-memory=<GiB> ({MIN_FREE_ENV}) sets the amount; "
            "0 turns the check off.")
    if interactive:
        enter_pressed()  # Discards keys pressed during the compile.
    started = last_report = now()
    while True:
        sleep(POLL_SECONDS)
        if interactive and enter_pressed():
            info("Compressing now, as requested.")
            break
        state = read()
        if state is None:
            break
        free = state[0]
        if free >= required:
            break
        if now() - last_report >= REPORT_SECONDS:
            info(f"Still waiting for free memory: {_gib(free)} of {_gib(required)} "
                 f"({duration(now() - started)} so far).")
            last_report = now()
    info(f"Waited {duration(now() - started)} for memory; compressing with {_gib(free)} free.")


class LowestFreeMemory:
    """Samples the free memory on a background thread and keeps the lowest value."""

    def __init__(self, read=free_memory, interval=1.0):
        self._read = read
        self._interval = interval
        self._stop = threading.Event()
        self.lowest = None
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def stop(self):
        self._stop.set()

    def _run(self):
        while not self._stop.is_set():
            state = self._read()
            if state is not None and (self.lowest is None or state[0] < self.lowest):
                self.lowest = state[0]
            self._stop.wait(self._interval)


try:
    from nuitka.plugins.PluginBase import NuitkaPluginBase
except ImportError:
    NuitkaPluginBase = None

if NuitkaPluginBase is not None:
    class MemoryWaitPlugin(NuitkaPluginBase):
        plugin_name = "build-memory-wait"
        plugin_desc = "Waits for free memory before compressing the onefile payload."

        def __init__(self):
            self._sampler = None
            self._started = None

        def onStandaloneDistributionFinished(self, dist_dir):
            from nuitka.options.Options import (
                getJobLimit,
                isLowMemory,
                isOnefileMode,
                shallNotCompressOnefile,
            )

            # --low-memory compresses at level 3 on one thread.
            if not isOnefileMode() or shallNotCompressOnefile() or isLowMemory():
                return
            setting = os.environ.get(MIN_FREE_ENV)
            if setting is not None:
                required = int(float(setting) * GIB)
                if required <= 0:
                    self.info(f"{MIN_FREE_ENV} is 0: not checking free memory.")
                    return
            else:
                payload = folder_size(dist_dir)
                required = required_bytes(payload, getJobLimit())
                self.info(f"Onefile payload: {_gib(payload)}, {getJobLimit()} compression thread(s).")
            wait_for_memory(required, self.info, self.warning)
            self._sampler = LowestFreeMemory()
            self._sampler.start()
            self._started = time.monotonic()
            atexit.register(self._report)

        def onOnefileFinished(self, filename):
            self._report()

        def _report(self):
            if self._sampler is None:
                return
            sampler, self._sampler = self._sampler, None
            sampler.stop()
            if sampler.lowest is not None:
                self.info(f"Onefile step took {duration(time.monotonic() - self._started)}; "
                          f"least free memory during it: {_gib(sampler.lowest)}.")
