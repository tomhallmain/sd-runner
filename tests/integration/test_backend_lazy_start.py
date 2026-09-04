"""Managed backends are started on demand.

``AppWindow`` reads which backends the user has configured a launch command
for at construction time; ``ensure_backend_started`` launches one, and the
run path calls it when it needs that backend. Nothing here spawns a real
process.
"""

from extensions.backend_process import BackendProcess, BackendStartError
from sd_runner.globals import SoftwareType


class TestEnsureBackendStarted:
    def test_starts_the_matching_backend(self, app_window, monkeypatch):
        started = []
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        monkeypatch.setattr(
            backend, "start",
            lambda on_state=None: started.append(True) or True,
        )
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
        monkeypatch.setattr(
            backend, "start", lambda on_state=None: calls.append(1) or True
        )
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
        monkeypatch.setattr(
            backend, "start",
            lambda on_state=None: started.append(True) or True,
        )
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert started == []

    def test_a_launch_failure_is_reported_not_raised(self, app_window, monkeypatch):
        """Log and toast, don't crash the caller: ensure_backend_started runs
        on the run thread, which has to survive a failed launch.
        """
        toasted = []
        monkeypatch.setitem(
            app_window.app_actions._actions, "toast",
            lambda *a, **k: toasted.append((a, k)),
        )
        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")

        def explode(on_state=None):
            raise BackendStartError("no such backend")

        monkeypatch.setattr(backend, "start", explode)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert len(toasted) == 1


class TestLaunchProgressIsShown:
    """A cold backend holds the run's worker thread for minutes, so the launch
    notice is the only sign anything is happening.

    ``_start_backend`` catches everything ``start()`` raises and reports it as
    a failed launch, which means a disagreement between the two -- a callback
    the signature does not accept -- looks like the backend refusing to start
    rather than like the wiring error it is. That is what this covers.
    """

    def _capture_toasts(self, app_window, monkeypatch, events):
        class FakeToast:
            def update(self, message):
                events.append(("update", message))

            def finish(self, message, linger_ms=0):
                events.append(("finish", message, linger_ms))

        def fake_status_toast(message, **kwargs):
            events.append(("open", message))
            return FakeToast()

        monkeypatch.setattr(
            app_window.notification_ctrl, "status_toast", fake_status_toast
        )

    def test_a_spawning_launch_opens_and_finishes_a_notice(self, app_window, monkeypatch):
        events = []
        self._capture_toasts(app_window, monkeypatch, events)

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")

        def fake_start(on_state=None):
            on_state("starting")
            on_state("ready")
            return True

        monkeypatch.setattr(backend, "start", fake_start)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert [e[0] for e in events] == ["open", "finish"]
        assert app_window.BACKEND_TOAST_LINGER_MS == events[-1][2]

    def test_a_launch_that_never_answers_says_so_rather_than_hanging_the_notice(
        self, app_window, monkeypatch
    ):
        """Timing out leaves the backend running, so the notice has to close
        itself on that path too -- otherwise it stays up for the session."""
        events = []
        self._capture_toasts(app_window, monkeypatch, events)

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")

        def fake_start(on_state=None):
            on_state("starting")
            on_state("timeout")
            return False

        monkeypatch.setattr(backend, "start", fake_start)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert [e[0] for e in events] == ["open", "finish"]

    def test_a_backend_already_up_shows_nothing(self, app_window, monkeypatch):
        """start() reports no state when it does not spawn, so no notice
        flashes up for a wait that never happens."""
        events = []
        self._capture_toasts(app_window, monkeypatch, events)

        backend = BackendProcess(SoftwareType.ComfyUI, "python main.py")
        monkeypatch.setattr(backend, "start", lambda on_state=None: True)
        app_window.backend_processes = [backend]

        app_window.ensure_backend_started(SoftwareType.ComfyUI)

        assert events == []
