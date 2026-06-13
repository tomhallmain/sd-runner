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
              PresetsWindow.get_preset_by_name(task.name)
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

from run import Run
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from ui_qt.presets.schedule import PresetTask, Schedule
from ui_qt.presets.schedules_window import SchedulesWindow
from ui_qt.presets.presets_window import PresetsWindow
from utils.utils import Utils
from utils.time_estimator import TimeEstimator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_schedule(name="Test Schedule", tasks=()):
    s = Schedule()
    s.name = name
    for task_name, count in tasks:
        s.add_preset_task(PresetTask(task_name, count))
    return s


# ---------------------------------------------------------------------------
# Autouse fixture: reset SchedulesWindow class state between tests
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_schedules_state():
    SchedulesWindow.recent_schedules = []
    SchedulesWindow.schedule_history = []
    SchedulesWindow.current_schedule = Schedule()
    SchedulesWindow._modify_window = None
    yield
    SchedulesWindow.recent_schedules = []
    SchedulesWindow.schedule_history = []
    SchedulesWindow.current_schedule = Schedule()


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
    monkeypatch.setattr(TimeEstimator, "estimate_queue_time", lambda images, latents: 0)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)

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
# Preset schedule dispatch helpers
# ---------------------------------------------------------------------------

def _install_schedule(app_window, schedule, monkeypatch):
    """
    Set schedule as current, check the checkbox, stub preset lookup and
    widget application. Returns (fake_preset, applications_list).
    """
    SchedulesWindow.current_schedule = schedule
    app_window.sidebar_panel.run_preset_schedule_check.setChecked(True)
    # Ensure no schedule already pending
    app_window.job_queue_preset_schedules.cancel()

    fake_preset = MagicMock()
    monkeypatch.setattr(PresetsWindow, "get_preset_by_name", lambda name: fake_preset)

    applications = []
    monkeypatch.setattr(
        app_window.sidebar_panel, "set_widgets_from_preset",
        lambda preset, manual=True: applications.append(preset),
    )
    return fake_preset, applications


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
