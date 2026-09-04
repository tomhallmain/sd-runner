"""Run a diffusion backend as a managed subprocess.

SD Runner starts the backend, pipes its output into the app log, waits for it
to answer, and shuts it down on exit. Opt-in per backend: a backend with no
launch command configured is never touched, and one that is already running is
adopted rather than started a second time. A backend starts the first time a
run needs it, so an install with several configured backends warms up only the
ones that session actually uses.

**Launch commands are the user's, not ours.** There are no built-in defaults.
Install layouts differ too much for a guessed command to be right -- venv or
system Python, ``launch.py`` or ``webui.sh``, a wrapper script that spawns its
own console -- and a wrong guess fails only after a long startup wait, which is
worse than not trying. The command given is the one the user would type.

**Only processes we started are stopped.** A backend that was already up when
SD Runner launched is left running when it exits; taking down something the
user started themselves would be a surprise.
"""

import os
import re
import signal
import subprocess
import sys
import threading
import time
from typing import Optional

from extensions.backend_health import check, is_reachable
from sd_runner.globals import SoftwareType
from lib.logging_setup import get_logger

logger = get_logger("backend_process")

#: Colour and cursor codes. Backends draw progress bars; the log wants text.
_ANSI = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

#: Seconds between readiness polls while waiting for a backend to come up.
POLL_INTERVAL = 2

#: Seconds to let a process exit on its own before killing it.
#:
#: Deliberately short, and coupled to something outside this module:
#: ``AppWindow.on_closing`` arms a 10 second ``os._exit`` failsafe against
#: stranded threads, and every managed backend is stopped inside that window.
#: A per-backend grace anywhere near 10s means two backends overrun it, the
#: process is killed mid-teardown, and the child outlives the app holding its
#: port and the GPU -- the exact thing stopping it was meant to prevent.
#: Nothing is lost by being impatient here: the grace only buys a *clean* exit,
#: and a force kill follows either way.
STOP_GRACE = 3

#: Config field holding each backend's install directory, used as the working
#: directory its launch command runs from. Absent means run wherever SD Runner
#: is, which suits a backend installed as a command rather than a checkout.
LOC_FIELDS = {
    SoftwareType.ComfyUI: "comfyui_loc",
    SoftwareType.SDWebUI: "sd_webui_loc",
    SoftwareType.Forge: "forge_loc",
    SoftwareType.SDNext: "sdnext_loc",
    SoftwareType.Fooocus: "fooocus_loc",
    SoftwareType.InvokeAI: "invokeai_loc",
    SoftwareType.SwarmUI: "swarmui_loc",
}


class BackendStartError(Exception):
    """The backend could not be started, or never became reachable."""


class BackendProcess:
    """One backend's subprocess, from launch to shutdown."""

    def __init__(
        self,
        software_type: SoftwareType,
        launch_cmd: str,
        cwd: Optional[str] = None,
        startup_timeout: int = 300,
        log_output: bool = False,
    ):
        self.software_type = software_type
        self.launch_cmd = launch_cmd
        self.cwd = cwd
        self.startup_timeout = startup_timeout
        self.log_output = log_output
        self._proc: Optional[subprocess.Popen] = None
        self._adopted = False
        self._ready = False
        # Guards start(): the run path calls it whenever it needs the backend,
        # so two runs arriving close together must not race into spawning it
        # twice.
        self._start_lock = threading.Lock()

    @property
    def name(self) -> str:
        return self.software_type.value

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self, on_state=None) -> bool:
        """Launch the backend and wait until it answers.

        Safe to call more than once, and expected to be: the run path calls it
        whenever it needs the backend. The first call starts it; later ones are
        nearly free -- already adopted or already spawned by us, they return
        without touching the network or launching a second copy.

        Returns True when the backend is usable, which includes the case where
        it was already running and nothing was launched. Raises
        ``BackendStartError`` if it could not be started or never came up.

        *on_state* is called with ``"starting"``, then one of ``"ready"``,
        ``"timeout"`` or ``"failed"``, and **only when this call actually
        spawns something**. The paths that return without waiting -- adopted,
        already ours -- report nothing, so a caller showing progress does not
        flash it up for a wait that never happens. It runs on the calling
        thread, which is a worker; anything it touches must say so.
        """
        with self._start_lock:
            if self._adopted:
                return True
            if self._proc is not None:
                return self.is_running()

            if is_reachable(self.software_type):
                logger.info(f"{self.name} is already running; adopting it")
                self._adopted = True
                return True

            self._spawn()
            self._pipe_output()
            self._report_state(on_state, "starting")
            try:
                self._ready = self._await_ready()
            except Exception:
                self._report_state(on_state, "failed")
                raise
            self._report_state(on_state, "ready" if self._ready else "timeout")
            return self._ready

    def _report_state(self, on_state, state: str) -> None:
        """Tell the caller where the launch got to, never raising for it.

        A display that fails must not take the launch down with it: the backend
        is the point, the progress report is not.
        """
        if on_state is None:
            return
        try:
            on_state(state)
        except Exception as e:
            logger.warning(f"Backend state callback failed for {self.name}: {e}")

    def _spawn(self) -> None:
        if self.cwd and not os.path.isdir(self.cwd):
            raise BackendStartError(
                f"{self.name} launch directory does not exist: {self.cwd}"
            )
        if not self.launch_cmd.strip():
            raise BackendStartError(f"{self.name} launch command is empty")
        args = self._parse_command()

        logger.info(f"Starting {self.name}: {self.launch_cmd}"
                    + (f" (in {self.cwd})" if self.cwd else ""))
        try:
            self._proc = subprocess.Popen(
                args,
                cwd=self.cwd or None,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                # Explicit, and lenient. text=True would decode using the
                # locale encoding, and these backends print UTF-8 freely --
                # progress bars, box drawing, non-ASCII paths in a traceback.
                # A decode error would raise out of the read loop, stop the
                # pipe being drained, and hang the backend on its next write.
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                # Own process group, so stop() can signal the shell and the
                # backend under it together. Without this a POSIX terminate()
                # reaches only the shell and orphans the backend holding the
                # GPU. The Windows equivalent is taskkill /T.
                start_new_session=(sys.platform != "win32"),
                # No console window on Windows; the output is piped into the
                # app log instead, where it can actually be found later.
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
                if sys.platform == "win32" else 0,
            )
        except OSError as e:
            raise BackendStartError(f"Could not start {self.name}: {e}")

    def _parse_command(self):
        """The launch command, wrapped in a shell.

        Run through a shell rather than executed directly, because the
        recommended way to start several of these backends *is* a script:
        ``run_nvidia_gpu.bat``, ``webui-user.bat``, ``launch-windows.bat``.
        They exist to set environment variables, choose arguments and handle
        updates, and a user should not have to reverse-engineer one into an
        equivalent command line. ``CreateProcess`` cannot execute a ``.bat``
        at all, so without this those backends simply could not be launched.

        It also removes the need to split the command ourselves, which no
        library does correctly for Windows: ``shlex`` in POSIX mode eats the
        backslashes out of ``envs\\comfy\\python.exe``, and in non-POSIX mode
        leaves the quotes inside a token so a quoted path becomes a filename
        containing quote characters.

        The shell is why ``stop()`` kills a process *tree* rather than a
        process: what we hold is the shell, and the backend is its child.

        ``/s /c`` is the robust form on Windows -- it tells cmd to strip
        exactly the outer quotes and run the rest verbatim, rather than
        applying its own quote-pairing rules to what is inside.
        """
        if sys.platform == "win32":
            # A string, not a list: Popen hands it to CreateProcess as-is,
            # where list2cmdline would backslash-escape inner quotes, which cmd
            # does not understand.
            return f'cmd.exe /s /c "{self.launch_cmd}"'
        return ["/bin/sh", "-c", self.launch_cmd]

    def _pipe_output(self) -> None:
        """Forward the backend's output into the app log, on its own thread.

        A daemon thread, and one that never raises: it exists to make a failed
        startup diagnosable, so it must not itself become the failure. Reading
        also matters mechanically -- a full pipe buffer would block the backend.

        ``log_output`` selects the level, never whether to read: a backend
        serving requests prints continuously, and at info that buries the app's
        own lines. Off, the lines are still there at debug.
        """
        log = logger.info if self.log_output else logger.debug

        def pump():
            try:
                for line in self._proc.stdout:
                    # Guarded per line, not around the loop. Logging a line can
                    # fail on its own -- a console handler under a legacy code
                    # page raises on characters a backend prints freely -- and
                    # abandoning the loop for that would stop draining the pipe
                    # entirely. The backend then blocks on its next write once
                    # the buffer fills, looks hung, and gets killed for it. The
                    # failure most likely to trigger it is a plugin dumping a
                    # long traceback at startup, which is exactly when the
                    # output matters.
                    try:
                        line = _ANSI.sub("", line).rstrip()
                        if line:
                            log(f"[{self.name}] {line}")
                    except Exception:
                        pass
            except Exception as e:
                # The stream itself ended badly. Nothing to do but stop; the
                # process is watched separately.
                logger.debug(f"{self.name} output stream ended: {e}")

        threading.Thread(target=pump, daemon=True,
                         name=f"{self.name}-output").start()

    def _await_ready(self) -> bool:
        """Poll until the backend answers, it exits, or the timeout passes.

        Polling starts immediately. There is no grace period and none is
        needed: a port with nothing listening refuses at once, so an early
        poll costs a failed connection rather than a wait. The number that
        matters is the total budget, ``backend_startup_timeout``.
        """
        deadline = time.time() + self.startup_timeout
        while time.time() < deadline:
            exit_code = self._proc.poll()
            if exit_code is not None:
                # Exited on its own: waiting out the full timeout would tell
                # the user nothing they cannot already see in the piped output.
                raise BackendStartError(
                    f"{self.name} exited during startup with code {exit_code}; "
                    "see the log above for its output"
                )
            result = check(self.software_type)
            if result.reachable:
                logger.info(f"{self.name} is ready at {result.url}")
                return True
            time.sleep(POLL_INTERVAL)

        # Deliberately left running. It has not exited, so it is still working
        # -- compiling, downloading a model, loading weights -- and killing it
        # here throws away however many minutes of that it has done, for a
        # backend that may be seconds from listening. Running out of patience
        # is not evidence of failure. It stays in the managed list, so it is
        # still stopped on exit, and the health check will report it the moment
        # it starts answering.
        raise BackendStartError(
            f"{self.name} did not respond within {self.startup_timeout}s and has "
            "been left running. Raise backend_startup_timeout if it is simply "
            "slow to start; stop it yourself if it is stuck."
        )

    def stop(self) -> None:
        """Stop the backend, if we were the ones who started it."""
        if self._adopted or self._proc is None or self._proc.poll() is not None:
            return
        logger.info(f"Stopping {self.name}")
        try:
            if sys.platform == "win32":
                self._stop_windows()
            else:
                self._stop_posix()
        except Exception as e:
            logger.warning(f"Could not stop {self.name} cleanly: {e}")
        finally:
            self._proc = None

    def _stop_posix(self) -> None:
        """Signal the whole process group, not just the shell we hold.

        The backend runs under a shell, so terminating only our direct child
        would leave it running -- and holding the GPU. The group was created
        for this at spawn.
        """
        self._signal_group(signal.SIGTERM)
        try:
            self._proc.wait(STOP_GRACE)
        except subprocess.TimeoutExpired:
            logger.warning(f"{self.name} ignored terminate; killing it")
            self._signal_group(signal.SIGKILL)
            try:
                self._proc.wait(STOP_GRACE)
            except subprocess.TimeoutExpired:
                self._proc.kill()

    def _signal_group(self, sig) -> None:
        """Send *sig* to the backend's process group, falling back to the child."""
        try:
            os.killpg(os.getpgid(self._proc.pid), sig)
        except Exception:
            # No group (a spawn that did not get one), or it is already gone.
            try:
                self._proc.send_signal(sig)
            except Exception:
                pass

    def _stop_windows(self) -> None:
        """Kill the whole process tree.

        terminate() reaches only the process we launched, and these backends
        spawn children -- ComfyUI forks multiprocessing workers, and some
        launchers are wrappers around the real server. Killing the parent alone
        leaves those holding the port and the GPU, so the next launch fails on
        a port that looks occupied by nothing.
        """
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(self._proc.pid)],
                capture_output=True,
                check=False,
                timeout=STOP_GRACE,
            )
        except subprocess.TimeoutExpired:
            # taskkill itself hanging is unusual, but waiting on it counts
            # against the shutdown failsafe like everything else here.
            logger.warning(f"taskkill did not return for {self.name}")
        try:
            self._proc.wait(STOP_GRACE)
        except subprocess.TimeoutExpired:
            self._proc.kill()

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def is_starting(self) -> bool:
        """Launched by us, still alive, and not yet confirmed ready.

        Derived rather than flagged, so it stays true past a startup timeout --
        running out of patience does not mean the backend stopped starting, and
        a client asking then should still hear "not yet" rather than "broken".
        It goes false on its own when the process exits or first answers.
        """
        return (self._proc is not None
                and not self._adopted
                and not self._ready
                and self.is_running())


def starting_backends(backends) -> set:
    """Which of *backends* are mid-startup, as SoftwareType values.

    Read from the listener thread while the launch threads write it, so this
    reads a plain flag rather than taking a lock: a health check that catches
    the flag a moment late reports "starting" instead of "ok", which is the
    harmless direction to be wrong in.
    """
    return {
        backend.software_type for backend in (backends or [])
        if backend.is_starting()
    }


def configured_backends(config) -> list:
    """The backends the user has asked SD Runner to launch.

    Keyed by ``SoftwareType`` name in ``backend_launch_commands``. An unknown
    or cloud name is reported and skipped rather than failing startup -- a typo
    in config should not stop the app from opening.
    """
    commands = getattr(config, "backend_launch_commands", None) or {}
    if not isinstance(commands, dict):
        logger.warning("backend_launch_commands is not a mapping; ignoring it")
        return []

    backends = []
    for name, command in commands.items():
        if not command or not str(command).strip():
            continue
        try:
            software_type = SoftwareType[str(name)]
        except KeyError:
            logger.warning(f"backend_launch_commands: unknown backend {name!r}")
            continue
        if software_type not in LOC_FIELDS:
            logger.warning(
                f"backend_launch_commands: {name} is a cloud backend, "
                "there is nothing to launch"
            )
            continue
        backends.append(BackendProcess(
            software_type,
            str(command).strip(),
            cwd=getattr(config, LOC_FIELDS[software_type], None),
            startup_timeout=getattr(config, "backend_startup_timeout", 300),
            log_output=bool(getattr(config, "log_backend_output", False)),
        ))
    return backends
