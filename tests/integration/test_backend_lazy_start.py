"""Managed backends are started on demand, not when SD Runner opens.

``AppWindow`` only reads which backends the user has configured a launch
command for at construction time -- launching one is deferred to
``ensure_backend_started``, which the run path calls the first time it
actually needs that backend. Nothing here spawns a real process.
"""

from extensions.backend_process import BackendProcess, BackendStartError
from utils.globals import SoftwareType


class TestEnsureBackendStarted:
    def test_starts_the_matching_backend(self, app_window, monkeypatch):
        started = []
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        monkeypatch.setattr(backend, "start", lambda: started.append(True) or True)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert started == [True]

    def test_a_second_call_starts_it_again_cheaply(self, app_window, monkeypatch):
        """start() itself is what makes the second call a no-op; this only
        confirms ensure_backend_started calls through every time rather than
        remembering on its own and skipping the call entirely.
        """
        calls = []
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        monkeypatch.setattr(backend, "start", lambda: calls.append(1) or True)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)
        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert calls == [1, 1]

    def test_a_backend_with_no_launch_command_is_left_alone(self, app_window):
        """No matching entry in backend_processes -- nothing to start, and
        nothing raised.
        """
        app_window.backend_processes = []
        app_window.ensure_backend_started(SoftwareType.ComfyUI)

    def test_a_different_configured_backend_is_not_touched(self, app_window, monkeypatch):
        started = []
        backend = BackendProcess(SoftwareType.SDWebUI, "python launch.py")
        monkeypatch.setattr(backend, "start", lambda: started.append(True) or True)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert started == []

    def test_a_launch_failure_is_reported_not_raised(self, app_window, monkeypatch):
        """Mirrors the old startup-thread behaviour: log and toast, don't
        crash the caller -- ensure_backend_started now runs on the run
        thread, which must survive a failed launch the same way.
        """
        toasted = []
        monkeypatch.setitem(
            app_window.app_actions._actions, "toast",
            lambda *a, **k: toasted.append((a, k)),
        )
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")

        def explode():
            raise BackendStartError("no such backend")

        monkeypatch.setattr(backend, "start", explode)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert len(toasted) == 1
