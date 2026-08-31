"""Answering a client that asks whether a backend is operational.

The HTTP side is covered in tests/unit/test_backend_health.py. What matters
here is the routing around it: which backend gets checked, and the cases
answered without touching the network at all.
"""

import pytest


class _AliveProc:
    """Stands in for a launched process that has not exited."""

    def poll(self):
        return None


class TestServerHealthCheck:
    def stub_health(self, monkeypatch, reachable=True, detail=""):
        """Replace both check levels with a fixed answer.

        run_controller imports these inside the method, so patching the module
        attribute reaches the call.
        """
        from extensions import backend_health

        def fake(software_type, timeout=2):
            return backend_health.HealthResult(
                software_type, "http://localhost/x", reachable, detail
            )

        monkeypatch.setattr(backend_health, "check", fake)
        monkeypatch.setattr(backend_health, "check_functional", fake)

    def test_a_reachable_backend_is_ok(self, app_window, monkeypatch):
        self.stub_health(monkeypatch)
        assert app_window.run_ctrl.server_health_check()["status"] == "ok"

    def test_an_unreachable_backend_is_an_error(self, app_window, monkeypatch):
        self.stub_health(monkeypatch, reachable=False, detail="connection refused")
        response = app_window.run_ctrl.server_health_check()
        assert response["status"] == "error"
        assert response["error"] == "connection refused"

    def test_it_reports_which_backend_it_checked(self, app_window, monkeypatch):
        self.stub_health(monkeypatch)
        response = app_window.run_ctrl.server_health_check(software="ComfyUI")
        assert response["backend"] == "ComfyUI"

    def test_a_named_backend_overrides_the_selected_one(self, app_window, monkeypatch):
        """Asking about one backend must not require selecting it first."""
        self.stub_health(monkeypatch)
        app_window.sidebar_panel.software_combo.setCurrentText("ComfyUI")
        response = app_window.run_ctrl.server_health_check(software="SDWebUI")
        assert response["backend"] == "SDWebUI"

    def test_without_a_name_the_selected_backend_is_checked(self, app_window, monkeypatch):
        self.stub_health(monkeypatch)
        app_window.sidebar_panel.software_combo.setCurrentText("SDWebUI")
        assert app_window.run_ctrl.server_health_check()["backend"] == "SDWebUI"

    def test_an_unknown_backend_name_is_an_error(self, app_window, monkeypatch):
        self.stub_health(monkeypatch)
        response = app_window.run_ctrl.server_health_check(software="Nonsense")
        assert response["status"] == "error"

    def test_a_cloud_backend_is_ok_without_a_request(self, app_window, monkeypatch):
        """There is no local process, and the hosted API is not ours to speak to."""
        from extensions import backend_health

        def explode(*a, **k):
            raise AssertionError("should not have made a request")

        monkeypatch.setattr(backend_health, "check", explode)
        monkeypatch.setattr(backend_health, "check_functional", explode)
        response = app_window.run_ctrl.server_health_check(software="OpenAI")
        assert response["status"] == "ok"
        assert response["note"] == "cloud_backend_no_local_check"

    @pytest.mark.parametrize("level", [1, 2])
    def test_the_level_is_echoed_back(self, app_window, monkeypatch, level):
        self.stub_health(monkeypatch)
        assert app_window.run_ctrl.server_health_check(level=level)["level"] == level

    def test_level_two_uses_the_functional_check(self, app_window, monkeypatch):
        from extensions import backend_health

        called = []
        self.stub_health(monkeypatch)
        real = backend_health.check_functional
        monkeypatch.setattr(
            backend_health, "check_functional",
            lambda s, timeout=2: (called.append(s), real(s, timeout))[1],
        )
        app_window.run_ctrl.server_health_check(level=2)
        assert called

    def test_it_reports_how_long_the_check_took(self, app_window, monkeypatch):
        self.stub_health(monkeypatch)
        assert app_window.run_ctrl.server_health_check()["latency_ms"] >= 0

    def test_a_detail_from_the_check_is_passed_on_as_a_note(self, app_window, monkeypatch):
        self.stub_health(monkeypatch, detail="connectivity only")
        assert app_window.run_ctrl.server_health_check()["note"] == "connectivity only"

    def test_a_run_of_our_own_explains_a_busy_backend(self, app_window, monkeypatch):
        """Activity is evidence of health, not a fault to be diagnosed."""
        self.stub_health(monkeypatch)
        app_window.job_queue.job_running = True
        response = app_window.run_ctrl.server_health_check()
        assert response["status"] == "ok"
        assert response["note"] == "generation_in_progress"

    def test_an_unreachable_backend_stays_an_error_while_busy(self, app_window, monkeypatch):
        """A queued run of ours says nothing about a backend that will not answer."""
        self.stub_health(monkeypatch, reachable=False, detail="connection refused")
        app_window.job_queue.job_running = True
        assert app_window.run_ctrl.server_health_check()["status"] == "error"


class TestStatusesAreDistinguished:
    """Four answers, because a client does different things with each.

    ok and starting mean wait; timeout means retry with more patience; only
    error means something needs looking at.
    """

    def stub(self, monkeypatch, **result_fields):
        from extensions import backend_health

        def fake(software_type, timeout=2):
            return backend_health.HealthResult(
                software_type, "http://localhost/x", **result_fields
            )

        monkeypatch.setattr(backend_health, "check", fake)
        monkeypatch.setattr(backend_health, "check_functional", fake)

    def starting_backend(self, app_window, software_type):
        """A managed backend stuck mid-startup, as autolaunch would leave one."""
        from extensions.backend_process import BackendProcess

        backend = BackendProcess(software_type, "python main.py")
        backend._proc = _AliveProc()
        app_window.backend_processes = [backend]
        return backend

    def test_a_slow_backend_is_a_timeout_not_an_error(self, app_window, monkeypatch):
        self.stub(monkeypatch, reachable=False, detail="no response in 30s",
                  timed_out=True)
        assert app_window.run_ctrl.server_health_check()["status"] == "timeout"

    def test_a_refused_backend_is_an_error(self, app_window, monkeypatch):
        self.stub(monkeypatch, reachable=False, detail="connection refused")
        assert app_window.run_ctrl.server_health_check()["status"] == "error"

    def test_a_backend_we_are_launching_is_starting(self, app_window, monkeypatch):
        """Not broken -- it will answer shortly, and a client told error gives up."""
        from utils.globals import SoftwareType

        self.stub(monkeypatch, reachable=False, detail="connection refused")
        self.starting_backend(app_window, SoftwareType.ComfyUI)
        response = app_window.run_ctrl.server_health_check(software="ComfyUI")
        assert response["status"] == "starting"

    def test_starting_wins_over_timeout_too(self, app_window, monkeypatch):
        from utils.globals import SoftwareType

        self.stub(monkeypatch, reachable=False, detail="slow", timed_out=True)
        self.starting_backend(app_window, SoftwareType.ComfyUI)
        assert app_window.run_ctrl.server_health_check(
            software="ComfyUI")["status"] == "starting"

    def test_a_different_backend_starting_does_not_excuse_this_one(
        self, app_window, monkeypatch
    ):
        from utils.globals import SoftwareType

        self.stub(monkeypatch, reachable=False, detail="connection refused")
        self.starting_backend(app_window, SoftwareType.SDWebUI)
        assert app_window.run_ctrl.server_health_check(
            software="ComfyUI")["status"] == "error"

    def test_a_finished_launch_no_longer_excuses_a_failure(self, app_window, monkeypatch):
        from utils.globals import SoftwareType

        self.stub(monkeypatch, reachable=False, detail="connection refused")
        backend = self.starting_backend(app_window, SoftwareType.ComfyUI)
        backend._ready = True
        assert app_window.run_ctrl.server_health_check(
            software="ComfyUI")["status"] == "error"

    def test_a_reachable_backend_is_ok_even_while_starting(self, app_window, monkeypatch):
        """It answered, which settles the question whatever else is going on."""
        from utils.globals import SoftwareType

        self.stub(monkeypatch, reachable=True)
        self.starting_backend(app_window, SoftwareType.ComfyUI)
        assert app_window.run_ctrl.server_health_check(
            software="ComfyUI")["status"] == "ok"

    def test_no_managed_backends_is_not_an_error(self, app_window, monkeypatch):
        """Autolaunch is opt-in; most installs have no managed backends at all."""
        self.stub(monkeypatch, reachable=False, detail="connection refused")
        app_window.backend_processes = []
        assert app_window.run_ctrl.server_health_check()["status"] == "error"
