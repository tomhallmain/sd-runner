"""
Integration tests for the run dispatch system.

Tests the full chain from calling run_ctrl.run() through to Run.execute(),
covering both the normal run path and the preset schedule path.

Run.execute() is stubbed so no backend connection is needed.
Utils.start_thread() is replaced with a direct synchronous call so all state
changes are visible to the test thread immediately after run() returns.
time.sleep() is patched to a no-op so the wait-loop in run_preset_async
exits without delay.

Normal run path
---------------
run_ctrl.run()
  → args built from sidebar widgets
  → args.validate()
  → Utils.start_thread(_run_async)        ← synchronous in tests
      → Run(args).execute()               ← stubbed: marks is_complete=True

Preset schedule path (run_preset_schedule_check checked, schedule set)
-----------------------------------------------------------------------
run_ctrl.run()
  → run_preset_schedule()
      → Utils.start_thread(run_preset_async)  ← synchronous in tests
          → for each preset_task:
              PresetsState.get_preset_by_name(task.name)
              sp.set_widgets_from_preset(preset)
              sp.total_combo.setCurrentText(str(task.count_runs))
              run_ctrl.run()               ← recursive; hits normal path
                  → Run(args).execute()   ← stubbed
              wait for is_complete        ← exits immediately (already True)
          → restore total_combo
"""

import time as time_module
import pytest
from unittest.mock import MagicMock

from sd_runner.run import Run
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from sd_runner.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
from tests.utils import make_schedule
from sd_runner.schedule import Schedule
from sd_runner.schedules_state import SchedulesState
from sd_runner.ui.presets.schedules_window import SchedulesWindow
from sd_runner.presets_state import PresetsState
from utils.translations import I18N
from utils.utils import Utils
from utils.time_estimator import TimeEstimator

_ = I18N._


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# Autouse fixture: reset schedule class state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_schedules_state():
    SchedulesState.recent_schedules = []
    SchedulesState.current_schedule = Schedule()
    SchedulesWindow.schedule_history = []
    SchedulesWindow._modify_window = None
    yield
    SchedulesState.recent_schedules = []
    SchedulesState.current_schedule = Schedule()
    SchedulesWindow.schedule_history = []


# ---------------------------------------------------------------------------
# Core run stubs fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def execute_calls():
    return []


_FAKE_MODEL = Model(id="test_model.safetensors", path="/fake/models/test_model.safetensors")
_FAKE_RESOLUTION = Resolution(width=1024, height=1024)


@pytest.fixture
def run_stubs(monkeypatch, execute_calls):
    """
    Patch the run machinery so tests run synchronously without a backend.

    - Run.execute()              → records the Run instance; marks is_complete=True
    - Utils.start_thread()      → calls the function synchronously (no real thread)
    - Model.get_models()        → returns a single fake model
    - Resolution.get_resolutions() → returns a single fake resolution
    - RunConfig.validate()      → returns True unconditionally
    - TimeEstimator.estimate_queue_time() → 0  (skips long-run confirmation dialog)
    - time.sleep()              → no-op (exit wait-loop in run_preset_async instantly)
    """
    def fake_execute(self):
        execute_calls.append(self)
        self.is_complete = True

    monkeypatch.setattr(Run, "execute", fake_execute)
    monkeypatch.setattr(
        Utils, "start_thread",
        lambda fn, use_asyncio=False, args=[]: fn(*args),
    )
    monkeypatch.setattr(
        Model, "get_models",
        lambda tags, default_tag=None, inpainting=False, **kw: [_FAKE_MODEL],
    )
    monkeypatch.setattr(
        Resolution, "get_resolutions",
        lambda tags, architecture_type=None, resolution_group=None: [_FAKE_RESOLUTION],
    )
    monkeypatch.setattr(RunConfig, "validate", lambda self: True)
    # Both estimate entry points, or a run long enough to cross
    # TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS would raise a modal.
    # latents is optional on the real signature; callers pass either shape.
    monkeypatch.setattr(TimeEstimator, "estimate_queue_time", lambda images, latents=1.0: 0)
    monkeypatch.setattr(TimeEstimator, "estimate_run_seconds", lambda gen_config, images: 0)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)
    # Suppress the default 11 PM schedule that set_schedules() creates for an
    # empty cache — these tests cover dispatch logic, not shutdown behavior.
    monkeypatch.setattr(timed_schedules_manager, "check_for_shutdown_request", lambda dt: None)

    return execute_calls


# ---------------------------------------------------------------------------
# Normal run dispatch
# ---------------------------------------------------------------------------

class TestNormalRunDispatch:
    def test_run_calls_execute_once(self, app_window, run_stubs):
        """Clicking Run with no preset schedule triggers exactly one Run.execute()."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 1

    def test_run_marks_current_run_complete(self, app_window, run_stubs):
        """After run() the current Run object is marked complete."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.run_ctrl.run()
        assert app_window.current_run.is_complete is True

    def test_job_queue_not_running_after_run(self, app_window, run_stubs):
        """job_queue.job_running is False once the run finishes."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.run_ctrl.run()
        assert app_window.job_queue.job_running is False

    def test_run_uses_total_from_sidebar(self, app_window, run_stubs):
        """The Run receives the total shown in total_combo at call time."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.sidebar_panel.total_combo.setCurrentText("3")
        app_window.run_ctrl.run()
        assert run_stubs[0].args.total == 3

    def test_second_run_while_running_is_enqueued(self, app_window, run_stubs):
        """A second run() call while a job is already running enqueues it."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.job_queue.job_running = True
        app_window.run_ctrl.run()
        assert len(app_window.job_queue.pending_jobs) == 1
        app_window.job_queue.cancel()

    def test_run_creates_new_run_object(self, app_window, run_stubs):
        """Each run() call creates a distinct Run instance."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.run_ctrl.run()
        first_id = run_stubs[0].id
        app_window.run_ctrl.run()
        second_id = run_stubs[1].id
        assert first_id != second_id


# ---------------------------------------------------------------------------
# Backend lazy start
# ---------------------------------------------------------------------------

class TestBackendLazyStart:
    """The run path is what asks for a managed backend, when a run needs it."""

    def test_run_asks_to_start_the_selected_backend(self, app_window, run_stubs, monkeypatch):
        from utils.globals import SoftwareType

        started = []
        monkeypatch.setattr(
            app_window, "ensure_backend_started", lambda st: started.append(st)
        )
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        expected = SoftwareType[app_window.sidebar_panel.software_combo.currentText()]

        app_window.run_ctrl.run()

        assert started == [expected]

    def test_an_unrecognized_software_type_is_left_to_run_construction(
        self, app_window, monkeypatch
    ):
        """A bogus software_type isn't this method's job to report -- Run
        already raises a clear "Unhandled software type" for it.
        """
        from types import SimpleNamespace

        started = []
        monkeypatch.setattr(
            app_window, "ensure_backend_started", lambda st: started.append(st)
        )

        app_window.run_ctrl._ensure_backend_started(
            SimpleNamespace(software_type="NotARealBackend")
        )

        assert started == []


# ---------------------------------------------------------------------------
# Preset schedule dispatch helpers
# ---------------------------------------------------------------------------

def _install_schedule(app_window, schedule, monkeypatch):
    """
    Set schedule as current, check the checkbox, stub preset lookup and
    widget application. Returns (fake_preset, applications_list).
    """
    SchedulesState.current_schedule = schedule
    app_window.sidebar_panel.run_preset_schedule_check.setChecked(True)
    # Ensure no schedule already pending
    app_window.job_queue_preset_schedules.cancel()

    fake_preset = MagicMock()
    monkeypatch.setattr(PresetsState, "get_preset_by_name", lambda name: fake_preset)

    applications = []
    monkeypatch.setattr(
        app_window.sidebar_panel, "set_widgets_from_preset",
        lambda preset, manual=True: applications.append(preset),
    )
    return fake_preset, applications


# ---------------------------------------------------------------------------
# Dialogs raised from worker threads
# ---------------------------------------------------------------------------

@pytest.fixture
def bridged_calls(app_window, monkeypatch):
    """Every callable routed through _MainThreadBridge, in order.

    ``start_thread`` is synchronous here, so a test cannot tell a worker thread
    from the main one by asking which thread it is on. What it can check is
    whether the call went *through* the bridge -- which is the invariant, and
    the one that was broken.
    """
    bridge = app_window._thread_bridge
    seen = []
    real_invoke = bridge.invoke

    def spy(func, *args, **kwargs):
        seen.append(func)
        return real_invoke(func, *args, **kwargs)

    monkeypatch.setattr(bridge, "invoke", spy)
    return seen


@pytest.fixture
def alerts(app_window, monkeypatch):
    """Records alerts instead of showing them.

    Without this a failing run builds a real modal and blocks on exec(), so
    these tests would hang rather than fail.
    """
    calls = []

    def fake_alert(title, message, kind="info", severity="normal", master=None):
        calls.append((title, message, kind))
        return True

    monkeypatch.setattr(app_window.notification_ctrl, "alert", fake_alert)
    return calls


class TestWorkerThreadDialogs:
    """A dialog is widget construction, so it belongs on the GUI thread.

    Both call sites below sit in a ``Utils.start_thread`` body and reached
    ``NotificationController`` directly, bypassing the wrapped ``AppActions``
    route. The bridge boundary is ``AppActions``, and an attribute access on
    ``self._app.notification_ctrl`` does not look like it crosses it.
    """

    def test_a_failed_run_alerts_through_the_bridge(
        self, app_window, run_stubs, alerts, bridged_calls, monkeypatch
    ):
        def explode(self):
            raise RuntimeError("backend went away")

        monkeypatch.setattr(Run, "execute", explode)
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)

        app_window.run_ctrl.run()

        assert len(alerts) == 1
        assert app_window.notification_ctrl.alert in bridged_calls

    def test_the_failure_alert_says_which_error(
        self, app_window, run_stubs, alerts, monkeypatch
    ):
        def explode(self):
            raise RuntimeError("backend went away")

        monkeypatch.setattr(Run, "execute", explode)
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)

        app_window.run_ctrl.run()

        title, message, kind = alerts[0]
        assert title == _("Run Error")
        assert "backend went away" in message
        assert kind == "error"

    def test_a_failed_run_still_finishes_its_teardown(
        self, app_window, run_stubs, alerts, monkeypatch
    ):
        """The alert is not allowed to leave the queue thinking a job is live."""
        def explode(self):
            raise RuntimeError("backend went away")

        monkeypatch.setattr(Run, "execute", explode)
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)

        app_window.run_ctrl.run()

        assert app_window.job_queue.job_running is False

    def test_a_preset_lookup_failure_reports_through_the_bridge(
        self, app_window, run_stubs, alerts, bridged_calls, monkeypatch
    ):
        schedule = make_schedule(tasks=[("A", 1)])
        _install_schedule(app_window, schedule, monkeypatch)

        def missing(name):
            raise Exception("no such preset")

        monkeypatch.setattr(PresetsState, "get_preset_by_name", missing)

        # run_preset_async re-raises after reporting, and start_thread is
        # synchronous here, so the exception surfaces to the caller.
        with pytest.raises(Exception, match="no such preset"):
            app_window.run_ctrl.run()

        assert app_window.notification_ctrl.handle_error in bridged_calls

    def test_the_preset_failure_title_is_translated(
        self, app_window, run_stubs, alerts, monkeypatch
    ):
        schedule = make_schedule(tasks=[("A", 1)])
        _install_schedule(app_window, schedule, monkeypatch)

        def missing(name):
            raise Exception("no such preset")

        monkeypatch.setattr(PresetsState, "get_preset_by_name", missing)

        with pytest.raises(Exception, match="no such preset"):
            app_window.run_ctrl.run()

        # handle_error passes its title straight to alert.
        assert alerts[0][0] == _("Preset Schedule Error")

    def test_a_successful_run_raises_no_dialog(
        self, app_window, run_stubs, alerts, monkeypatch
    ):
        """Guards against a bridging change turning the happy path noisy."""
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)

        app_window.run_ctrl.run()

        assert alerts == []


# ---------------------------------------------------------------------------
# Preset schedule dispatch
# ---------------------------------------------------------------------------

class TestPresetScheduleDispatch:
    def test_two_task_schedule_calls_execute_twice(self, app_window, run_stubs, monkeypatch):
        """A schedule with 2 tasks triggers 2 Run.execute() calls."""
        schedule = make_schedule(tasks=[("A", 1), ("B", 1)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 2

    def test_three_task_schedule_calls_execute_three_times(self, app_window, run_stubs, monkeypatch):
        """A schedule with 3 tasks triggers 3 Run.execute() calls."""
        schedule = make_schedule(tasks=[("X", 1), ("Y", 1), ("Z", 1)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 3

    def test_schedule_applies_preset_for_each_task(self, app_window, run_stubs, monkeypatch):
        """set_widgets_from_preset is called once per task."""
        schedule = make_schedule(tasks=[("A", 1), ("B", 1), ("C", 1)])
        _, applications = _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert len(applications) == 3

    def test_schedule_takes_precedence_over_normal_run(self, app_window, run_stubs, monkeypatch):
        """When the schedule checkbox is checked, the schedule path runs, not a bare run."""
        schedule = make_schedule(tasks=[("A", 1)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        # schedule path was taken: exactly one execute (from the task's run, not a direct run)
        assert len(run_stubs) == 1

    def test_count_runs_applied_to_run_total(self, app_window, run_stubs, monkeypatch):
        """Each task's count_runs is set on total_combo before the run is started."""
        schedule = make_schedule(tasks=[("A", 5)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert run_stubs[0].args.total == 5

    def test_count_runs_applied_per_task_independently(self, app_window, run_stubs, monkeypatch):
        """Different tasks get their own count_runs applied before their run."""
        schedule = make_schedule(tasks=[("A", 3), ("B", 7)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert run_stubs[0].args.total == 3
        assert run_stubs[1].args.total == 7

    def test_count_runs_minus_one_uses_starting_total(self, app_window, run_stubs, monkeypatch):
        """count_runs=-1 means 'use the starting total' — the run gets the sidebar's original value."""
        app_window.sidebar_panel.total_combo.setCurrentText("4")
        schedule = make_schedule(tasks=[("A", -1)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert run_stubs[0].args.total == 4

    def test_total_combo_restored_after_schedule(self, app_window, run_stubs, monkeypatch):
        """total_combo is set back to its pre-schedule value once all tasks finish."""
        app_window.sidebar_panel.total_combo.setCurrentText("2")
        schedule = make_schedule(tasks=[("A", 9), ("B", 6)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert app_window.sidebar_panel.total_combo.currentText() == "2"

    def test_empty_schedule_does_not_call_execute(self, app_window, run_stubs, monkeypatch):
        """A schedule with no tasks produces no Run.execute() calls."""
        schedule = make_schedule(tasks=[])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 0

    def test_preset_schedule_queue_not_running_after_completion(self, app_window, run_stubs, monkeypatch):
        """job_queue_preset_schedules.job_running is False once the schedule finishes."""
        schedule = make_schedule(tasks=[("A", 1)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert app_window.job_queue_preset_schedules.job_running is False

    def test_mixed_count_runs_and_starting_total(self, app_window, run_stubs, monkeypatch):
        """Mix of explicit count_runs and -1 (starting total) in the same schedule."""
        app_window.sidebar_panel.total_combo.setCurrentText("10")
        schedule = make_schedule(tasks=[("A", 3), ("B", -1), ("C", 5)])
        _install_schedule(app_window, schedule, monkeypatch)
        app_window.run_ctrl.run()
        assert run_stubs[0].args.total == 3
        assert run_stubs[1].args.total == 10   # -1 → starting total
        assert run_stubs[2].args.total == 5


# ---------------------------------------------------------------------------
# Scheduled-shutdown gating
# ---------------------------------------------------------------------------

class TestScheduledShutdownGating:
    """run() must abort before execute() when a shutdown schedule is active."""

    def test_run_aborted_when_shutdown_requested(self, app_window, run_stubs, monkeypatch):
        """run() returns without calling execute() if check_for_shutdown_request raises."""
        def raise_shutdown(dt):
            raise ScheduledShutdownException("shutdown", None)

        monkeypatch.setattr(timed_schedules_manager, "check_for_shutdown_request", raise_shutdown)
        # Suppress the dialog that would otherwise block the test thread.
        monkeypatch.setattr(app_window.run_ctrl, "_handle_scheduled_shutdown", lambda e: None)
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(False)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 0

    def test_preset_schedule_run_aborted_when_shutdown_requested(self, app_window, run_stubs, monkeypatch):
        """run_preset_schedule() aborts without any execute() if shutdown fires."""
        schedule = make_schedule(tasks=[("A", 1)])
        _install_schedule(app_window, schedule, monkeypatch)

        def raise_shutdown(dt):
            raise ScheduledShutdownException("shutdown", None)

        monkeypatch.setattr(timed_schedules_manager, "check_for_shutdown_request", raise_shutdown)
        monkeypatch.setattr(app_window.run_ctrl, "_handle_scheduled_shutdown", lambda e: None)
        app_window.run_ctrl.run()
        assert len(run_stubs) == 0


# ---------------------------------------------------------------------------
# Paused queue resume
# ---------------------------------------------------------------------------

class TestResumePausedQueue:
    def test_noop_when_idle(self, app_window, run_stubs, monkeypatch):
        """resume_paused_queue does nothing when both queues are empty."""
        callbacks = []
        monkeypatch.setattr(
            app_window.run_ctrl, "_promote_staged_request",
            lambda cmd, args, client_id="": callbacks.append((cmd, args)),
        )
        app_window.run_ctrl.resume_paused_queue()
        assert len(run_stubs) == 0
        assert callbacks == []

    def test_noop_when_job_running(self, app_window, run_stubs, monkeypatch):
        """resume_paused_queue does nothing while a job is already running."""
        from extensions.sd_runner_server import CommandType

        callbacks = []
        monkeypatch.setattr(
            app_window.run_ctrl, "_promote_staged_request",
            lambda cmd, args, client_id="": callbacks.append((cmd, args)),
        )
        app_window.job_queue.job_running = True
        app_window.server_staging_queue.add(CommandType.RENOISER, {"image": "test.png"})
        app_window.run_ctrl.resume_paused_queue()
        assert len(run_stubs) == 0
        assert callbacks == []
        assert app_window.server_staging_queue.pending_count() == 1

    def test_resumes_pending_job(self, app_window, run_stubs):
        """resume_paused_queue starts the first pending SD run."""
        args, _ = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)
        app_window.job_queue.paused = True
        app_window.run_ctrl.resume_paused_queue()
        assert app_window.job_queue.paused is False
        assert len(app_window.job_queue.pending_jobs) == 0
        assert len(run_stubs) == 1

    def test_promotes_staging_when_job_queue_empty(self, app_window, run_stubs, monkeypatch):
        """resume_paused_queue promotes a staged server request when no SD runs are pending."""
        from extensions.sd_runner_server import CommandType

        staged_args = {"image": "staged.png"}
        app_window.server_staging_queue.add(CommandType.RENOISER, staged_args)
        app_window.job_queue.paused = True

        callbacks = []
        monkeypatch.setattr(
            app_window.run_ctrl, "_promote_staged_request",
            lambda cmd, args, client_id="": callbacks.append((cmd, args)),
        )

        app_window.run_ctrl.resume_paused_queue()

        assert app_window.job_queue.paused is False
        assert app_window.server_staging_queue.pending_count() == 0
        assert len(callbacks) == 1
        assert callbacks[0] == (CommandType.RENOISER, staged_args)
        assert len(run_stubs) == 0

    def test_pending_jobs_take_priority_over_staging(self, app_window, run_stubs, monkeypatch):
        """When both queues have work, resume starts the pending SD run first."""
        from extensions.sd_runner_server import CommandType

        callbacks = []
        monkeypatch.setattr(
            app_window.run_ctrl, "_promote_staged_request",
            lambda cmd, args, client_id="": callbacks.append((cmd, args)),
        )
        args, _ = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)
        app_window.server_staging_queue.add(CommandType.RENOISER, {"image": "staged.png"})
        app_window.job_queue.paused = True

        app_window.run_ctrl.resume_paused_queue()

        assert len(run_stubs) == 1
        assert callbacks == []
        assert app_window.server_staging_queue.pending_count() == 1

