"""Launching a backend as a managed subprocess.

Nothing here spawns a process. What is worth asserting is the reading of
config into launch plans, and the guards around a launch: a backend that is
already up is adopted rather than started twice, and one that was adopted is
never stopped on exit.
"""

import sys
from types import SimpleNamespace

import pytest

from extensions import backend_process
from extensions.backend_process import (
    BackendProcess,
    BackendStartError,
    LOC_FIELDS,
    configured_backends,
)
from utils.globals import SoftwareType


class _AliveProc:
    """Stands in for a launched process that has not exited."""

    def poll(self):
        return None


def make_config(commands, **fields):
    defaults = {field: None for field in LOC_FIELDS.values()}
    defaults.update(
        backend_launch_commands=commands,
        backend_startup_timeout=300,
    )
    defaults.update(fields)
    return SimpleNamespace(**defaults)


# ---------------------------------------------------------------------------
# Reading config into launch plans
# ---------------------------------------------------------------------------

class TestConfiguredBackends:
    def test_nothing_configured_launches_nothing(self):
        """Opt-in: a backend absent from the mapping is never touched."""
        assert configured_backends(make_config({})) == []

    def test_a_configured_backend_becomes_a_launch_plan(self):
        backends = configured_backends(make_config({"ComfyUI": "python main.py"}))
        assert len(backends) == 1
        assert backends[0].software_type is SoftwareType.ComfyUI
        assert backends[0].launch_cmd == "python main.py"

    def test_the_install_directory_becomes_the_working_directory(self):
        backends = configured_backends(
            make_config({"ComfyUI": "python main.py"}, comfyui_loc="/opt/comfy")
        )
        assert backends[0].cwd == "/opt/comfy"

    def test_a_backend_with_no_install_directory_still_launches(self):
        """Some are installed as a command rather than a checkout."""
        backends = configured_backends(make_config({"InvokeAI": "invokeai-web"}))
        assert backends[0].cwd is None

    def test_the_timeout_comes_from_config(self):
        backends = configured_backends(
            make_config({"ComfyUI": "python main.py"}, backend_startup_timeout=42)
        )
        assert backends[0].startup_timeout == 42

    @pytest.mark.parametrize("command", ["", "   ", None])
    def test_a_blank_command_is_not_a_launch(self, command):
        assert configured_backends(make_config({"ComfyUI": command})) == []

    def test_an_unknown_backend_name_is_skipped(self):
        """A typo in config must not stop the app from opening."""
        assert configured_backends(make_config({"CmofyUI": "python main.py"})) == []

    def test_a_cloud_backend_is_skipped(self):
        """There is no local process to launch."""
        assert configured_backends(make_config({"OpenAI": "nonsense"})) == []

    def test_a_malformed_mapping_is_ignored(self):
        assert configured_backends(make_config("not a dict")) == []

    def test_a_missing_setting_is_ignored(self):
        assert configured_backends(SimpleNamespace()) == []

    def test_several_backends_are_all_planned(self):
        backends = configured_backends(make_config({
            "ComfyUI": "python main.py",
            "SDWebUI": "python launch.py",
        }))
        assert {b.software_type for b in backends} == {
            SoftwareType.ComfyUI, SoftwareType.SDWebUI
        }

    def test_every_local_backend_can_be_launched(self):
        """A local backend missing from LOC_FIELDS would be silently unlaunchable."""
        missing = [s for s in SoftwareType if not s.is_cloud() and s not in LOC_FIELDS]
        assert missing == []


# ---------------------------------------------------------------------------
# Starting
# ---------------------------------------------------------------------------

class TestAdoption:
    def test_a_running_backend_is_adopted_not_relaunched(self, monkeypatch):
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: True)
        spawned = []
        monkeypatch.setattr(
            BackendProcess, "_spawn", lambda self: spawned.append(self)
        )

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        assert backend.start() is True
        assert spawned == []

    def test_an_adopted_backend_is_not_stopped_on_exit(self, monkeypatch):
        """Taking down something the user started themselves is a surprise."""
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: True)
        killed = []
        monkeypatch.setattr(
            BackendProcess, "_stop_posix", lambda self: killed.append(self)
        )

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        backend.start()
        backend.stop()
        assert killed == []


class TestLaunchFailures:
    @pytest.fixture(autouse=True)
    def not_running(self, monkeypatch):
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: False)

    def test_a_missing_working_directory_is_reported(self, tmp_path):
        backend = BackendProcess(
            SoftwareType.ComfyUI, "python main.py", cwd=str(tmp_path / "nope")
        )
        with pytest.raises(BackendStartError, match="does not exist"):
            backend.start()

    def test_an_empty_command_is_reported(self):
        backend = BackendProcess(SoftwareType.ComfyUI, "   ")
        with pytest.raises(BackendStartError, match="empty"):
            backend.start()

    def test_a_command_that_cannot_run_is_reported(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise OSError("No such file or directory")

        monkeypatch.setattr(backend_process.subprocess, "Popen", refuse)
        backend = BackendProcess(SoftwareType.ComfyUI, "definitely-not-a-program")
        with pytest.raises(BackendStartError, match="Could not start"):
            backend.start()


class TestCommandGoesThroughAShell:
    """The recommended way to start several of these backends is a script.

    ComfyUI ships run_nvidia_gpu.bat, SDWebUI webui-user.bat, SwarmUI
    launch-windows.bat. They set environment variables and choose arguments,
    and CreateProcess cannot execute a .bat at all -- so without a shell those
    backends could not be launched from here.
    """

    def parsed(self, command="run_nvidia_gpu.bat"):
        return BackendProcess(SoftwareType.ComfyUI, command)._parse_command()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX form")
    def test_posix_runs_it_under_sh(self):
        assert self.parsed("./launch.sh --api") == [
            "/bin/sh", "-c", "./launch.sh --api"
        ]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX form")
    def test_posix_does_not_split_the_command(self):
        """Splitting is the shell's job, and it knows the quoting rules."""
        parsed = self.parsed('python main.py --dir "/a path/here"')
        assert parsed[-1] == 'python main.py --dir "/a path/here"'

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows form")
    def test_windows_runs_it_under_cmd(self):
        parsed = self.parsed()
        assert parsed.startswith("cmd.exe /s /c ")
        assert "run_nvidia_gpu.bat" in parsed

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows form")
    def test_windows_passes_a_string_not_a_list(self):
        """list2cmdline would backslash-escape inner quotes, which cmd cannot read."""
        assert isinstance(self.parsed(), str)

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows form")
    def test_windows_preserves_backslashes_in_paths(self):
        """The failure shlex would have caused: envs\\comfy\\python.exe."""
        parsed = self.parsed(r"C:\miniconda3\envs\comfy\python.exe main.py")
        assert r"C:\miniconda3\envs\comfy\python.exe" in parsed

    @pytest.mark.skipif(sys.platform != "win32", reason="Windows form")
    def test_windows_preserves_a_quoted_path(self):
        """The failure non-POSIX shlex would have caused: quotes left in a token."""
        parsed = self.parsed('"C:\\Program Files\\py.exe" main.py')
        assert '"C:\\Program Files\\py.exe" main.py' in parsed


class TestStartingState:
    """What a health check consults to answer "not yet" instead of "broken"."""

    def test_a_fresh_backend_is_not_starting(self):
        assert BackendProcess(SoftwareType.ComfyUI, "python main.py").is_starting() is False

    def test_it_is_clear_again_once_the_backend_answers(self, monkeypatch):
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: False)
        monkeypatch.setattr(
            BackendProcess, "_spawn",
            lambda self: setattr(self, "_proc", _AliveProc()),
        )
        monkeypatch.setattr(BackendProcess, "_pipe_output", lambda self: None)
        monkeypatch.setattr(BackendProcess, "_await_ready", lambda self: True)

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        backend.start()
        assert backend.is_starting() is False

    def test_it_is_clear_again_after_a_failed_launch(self, monkeypatch):
        """Otherwise a backend that never came up would excuse itself forever."""
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: False)

        backend = BackendProcess(SoftwareType.ComfyUI, "   ")
        with pytest.raises(BackendStartError):
            backend.start()
        assert backend.is_starting() is False

    def test_it_is_set_while_waiting_for_the_backend(self, monkeypatch):
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: False)
        # A spawn that leaves a live process behind, as the real one does.
        monkeypatch.setattr(
            BackendProcess, "_spawn",
            lambda self: setattr(self, "_proc", _AliveProc()),
        )
        monkeypatch.setattr(BackendProcess, "_pipe_output", lambda self: None)

        seen = []
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        monkeypatch.setattr(
            BackendProcess, "_await_ready",
            lambda self: (seen.append(self.is_starting()), True)[1],
        )
        backend.start()
        assert seen == [True]

    def test_it_stays_set_past_a_startup_timeout(self, monkeypatch):
        """Running out of patience does not mean the backend stopped starting.

        The process is left running on timeout, so a client asking afterwards
        should still hear "not yet" rather than "broken".
        """
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: False)
        monkeypatch.setattr(
            BackendProcess, "_spawn",
            lambda self: setattr(self, "_proc", _AliveProc()),
        )
        monkeypatch.setattr(BackendProcess, "_pipe_output", lambda self: None)

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py",
                                 startup_timeout=0)
        with pytest.raises(BackendStartError, match="left running"):
            backend.start()
        assert backend.is_starting() is True

    def test_an_adopted_backend_is_never_starting(self, monkeypatch):
        """It was already up; there is no startup window to explain."""
        monkeypatch.setattr(backend_process, "is_reachable", lambda *a, **k: True)
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        backend.start()
        assert backend.is_starting() is False


class TestStartingBackends:
    def test_it_reports_only_the_ones_mid_startup(self):
        from extensions.backend_process import starting_backends

        starting = BackendProcess(SoftwareType.ComfyUI, "cmd")
        starting._proc = _AliveProc()
        idle = BackendProcess(SoftwareType.SDWebUI, "cmd")
        assert starting_backends([starting, idle]) == {SoftwareType.ComfyUI}

    @pytest.mark.parametrize("backends", [None, []])
    def test_nothing_managed_is_an_empty_set(self, backends):
        from extensions.backend_process import starting_backends
        assert starting_backends(backends) == set()


class TestStopIsSafe:
    def test_stopping_something_never_started_does_nothing(self):
        BackendProcess(SoftwareType.ComfyUI, "python main.py").stop()

    def test_a_backend_that_never_started_is_not_running(self):
        assert BackendProcess(SoftwareType.ComfyUI, "python main.py").is_running() is False
