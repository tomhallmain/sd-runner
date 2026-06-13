"""
UI tests for SchedulesWindow and ScheduleModifyWindow.

These verify that the preset-schedule UI:
  - shows one row per saved schedule
  - updates the info label when a schedule is activated via Set
  - adds/removes rows when schedules are modified or deleted
  - supports multiple preset tasks, each with its own count_runs, inside a single schedule
  - reflects add / delete / move operations on tasks in ScheduleModifyWindow

No real Qt display is needed — QT_QPA_PLATFORM=offscreen is set in conftest.
The require_password decorator is a no-op in a fresh Config where no actions are
protected (EDIT_SCHEDULES defaults to False).
"""

import pytest
from PySide6.QtWidgets import QApplication, QComboBox, QLabel

from ui_qt.presets.schedule import PresetTask, Schedule
from ui_qt.presets.schedules_window import SchedulesWindow, ScheduleModifyWindow
from ui_qt.presets.presets_window import PresetsWindow


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_schedule(name="Test", tasks=None):
    s = Schedule()
    s.name = name
    for task_name, count in (tasks or []):
        s.add_preset_task(PresetTask(task_name, count))
    return s


def make_app_actions():
    from ui_qt.app_actions import AppActions
    noop = lambda *a, **kw: None
    return AppActions({action: noop for action in AppActions.REQUIRED_ACTIONS})


# ---------------------------------------------------------------------------
# Autouse fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_schedules_window_state():
    """Reset SchedulesWindow class-level state before and after every test."""
    SchedulesWindow.recent_schedules = []
    SchedulesWindow.schedule_history = []
    SchedulesWindow.current_schedule = Schedule()
    SchedulesWindow._modify_window = None
    yield
    if SchedulesWindow._modify_window is not None:
        try:
            SchedulesWindow._modify_window.close()
        except Exception:
            pass
        SchedulesWindow._modify_window = None
    SchedulesWindow.recent_schedules = []
    SchedulesWindow.schedule_history = []
    SchedulesWindow.current_schedule = Schedule()


@pytest.fixture(autouse=True)
def patch_presets_window(monkeypatch):
    """Prevent PresetsWindow from touching real data during schedule window tests."""
    monkeypatch.setattr(PresetsWindow, "get_preset_names",
                        staticmethod(lambda: ["Preset A", "Preset B"]))
    monkeypatch.setattr(PresetsWindow, "get_most_recent_preset_name",
                        staticmethod(lambda: "Preset A"))


# ---------------------------------------------------------------------------
# SchedulesWindow — display
# ---------------------------------------------------------------------------

class TestSchedulesWindowDisplay:
    def test_info_label_shows_current_schedule_name(self, qapp):
        SchedulesWindow.current_schedule = make_schedule("Evening")
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            assert "Evening" in win._info_label.text()
        finally:
            win.close()

    def test_no_rows_when_recent_schedules_empty(self, qapp):
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            assert win._rows_layout.count() == 0
        finally:
            win.close()

    def test_row_count_matches_recent_schedules(self, qapp):
        SchedulesWindow.recent_schedules = [make_schedule("A"), make_schedule("B"), make_schedule("C")]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            assert win._rows_layout.count() == 3
        finally:
            win.close()

    def test_schedule_labels_contain_schedule_names(self, qapp):
        SchedulesWindow.recent_schedules = [make_schedule("Morning"), make_schedule("Night")]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            all_label_text = ""
            for i in range(win._rows_layout.count()):
                row_widget = win._rows_layout.itemAt(i).widget()
                for lbl in row_widget.findChildren(QLabel):
                    all_label_text += lbl.text() + " "
            assert "Morning" in all_label_text
            assert "Night" in all_label_text
        finally:
            win.close()


# ---------------------------------------------------------------------------
# SchedulesWindow — set / activate a schedule
# ---------------------------------------------------------------------------

class TestSchedulesWindowSetSchedule:
    def test_set_schedule_updates_current_schedule(self, qapp):
        s = make_schedule("Afternoon")
        SchedulesWindow.recent_schedules = [s]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            win._set_schedule(s)
            assert SchedulesWindow.current_schedule == s
        finally:
            win.close()

    def test_set_schedule_updates_info_label(self, qapp):
        s = make_schedule("Night")
        SchedulesWindow.recent_schedules = [s]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            win._set_schedule(s)
            QApplication.processEvents()
            assert "Night" in win._info_label.text()
        finally:
            win.close()

    def test_set_schedule_calls_toast(self, qapp):
        toasts = []
        actions = make_app_actions()
        actions._actions["toast"] = lambda msg, **kw: toasts.append(msg)
        s = make_schedule("Work")
        SchedulesWindow.recent_schedules = [s]
        win = SchedulesWindow(parent=None, app_actions=actions)
        try:
            win._set_schedule(s)
            assert len(toasts) == 1
            assert "Work" in toasts[0]
        finally:
            win.close()

    def test_switching_schedule_changes_label(self, qapp):
        s1 = make_schedule("First")
        s2 = make_schedule("Second")
        SchedulesWindow.recent_schedules = [s1, s2]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            win._set_schedule(s1)
            assert "First" in win._info_label.text()
            win._set_schedule(s2)
            QApplication.processEvents()
            assert "Second" in win._info_label.text()
        finally:
            win.close()


# ---------------------------------------------------------------------------
# SchedulesWindow — modify / delete / clear
# ---------------------------------------------------------------------------

class TestSchedulesWindowModify:
    def test_on_schedule_modified_adds_to_recent(self, qapp):
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            s = make_schedule("New")
            win._on_schedule_modified(s)
            assert s in SchedulesWindow.recent_schedules
        finally:
            win.close()

    def test_on_schedule_modified_moves_new_schedule_to_front(self, qapp):
        existing = make_schedule("Old")
        SchedulesWindow.recent_schedules = [existing]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            new_s = make_schedule("New")
            win._on_schedule_modified(new_s)
            assert SchedulesWindow.recent_schedules[0] == new_s
        finally:
            win.close()

    def test_on_schedule_modified_replaces_by_name(self, qapp):
        s1 = make_schedule("Alpha")
        s1.add_preset_task(PresetTask("old_preset", 1))
        SchedulesWindow.recent_schedules = [s1]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            s2 = make_schedule("Alpha")
            s2.add_preset_task(PresetTask("new_preset", 5))
            win._on_schedule_modified(s2)
            alpha_list = [s for s in SchedulesWindow.recent_schedules if s.name == "Alpha"]
            assert len(alpha_list) == 1
        finally:
            win.close()

    def test_on_schedule_modified_sets_as_current(self, qapp):
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            s = make_schedule("Active")
            win._on_schedule_modified(s)
            assert SchedulesWindow.current_schedule == s
        finally:
            win.close()

    def test_on_schedule_modified_adds_row_to_layout(self, qapp):
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            assert win._rows_layout.count() == 0
            win._on_schedule_modified(make_schedule("Added"))
            QApplication.processEvents()
            assert win._rows_layout.count() == 1
        finally:
            win.close()

    def test_delete_schedule_removes_from_recent(self, qapp):
        s = make_schedule("ToDelete")
        SchedulesWindow.recent_schedules = [s]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            win._delete_schedule(s)
            assert s not in SchedulesWindow.recent_schedules
        finally:
            win.close()

    def test_delete_schedule_removes_its_row(self, qapp):
        s1 = make_schedule("Keep")
        s2 = make_schedule("Remove")
        SchedulesWindow.recent_schedules = [s1, s2]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            assert win._rows_layout.count() == 2
            win._delete_schedule(s2)
            QApplication.processEvents()
            assert win._rows_layout.count() == 1
        finally:
            win.close()

    def test_clear_removes_all_schedules_and_rows(self, qapp):
        SchedulesWindow.recent_schedules = [make_schedule("A"), make_schedule("B")]
        win = SchedulesWindow(parent=None, app_actions=make_app_actions())
        try:
            win._clear_recent_schedules()
            QApplication.processEvents()
            assert SchedulesWindow.recent_schedules == []
            assert win._rows_layout.count() == 0
        finally:
            win.close()


# ---------------------------------------------------------------------------
# ScheduleModifyWindow — display
# ---------------------------------------------------------------------------

class TestScheduleModifyWindowDisplay:
    def test_task_rows_shown_for_existing_schedule(self, qapp):
        s = make_schedule("Evening", tasks=[("Preset A", 3), ("Preset B", 5)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            assert win._rows_layout.count() == 2
        finally:
            win.close()

    def test_empty_schedule_has_no_rows(self, qapp):
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None,
                                   schedule=make_schedule())
        try:
            assert win._rows_layout.count() == 0
        finally:
            win.close()

    def test_name_entry_initialized_from_schedule(self, qapp):
        s = make_schedule("My Schedule")
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            assert win._name_entry.text() == "My Schedule"
        finally:
            win.close()

    def test_count_combo_reflects_task_count_runs(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 7)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            row_widget = win._rows_layout.itemAt(0).widget()
            count_texts = [c.currentText() for c in row_widget.findChildren(QComboBox)]
            assert "7" in count_texts
        finally:
            win.close()

    def test_multiple_tasks_with_different_count_runs(self, qapp):
        """Each task in a schedule can have a distinct run count."""
        s = make_schedule("multi", tasks=[("Preset A", 10), ("Preset B", 25), ("Preset A", 5)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            assert win._rows_layout.count() == 3
            all_count_texts = set()
            for i in range(win._rows_layout.count()):
                row_widget = win._rows_layout.itemAt(i).widget()
                for combo in row_widget.findChildren(QComboBox):
                    all_count_texts.add(combo.currentText())
            # All three distinct counts must be reachable from the combos
            assert "10" in all_count_texts
            assert "25" in all_count_texts
            assert "5" in all_count_texts
        finally:
            win.close()

    def test_negative_one_count_shown_as_minus_one(self, qapp):
        """count_runs=-1 means 'use the current run count' — must appear in the combo."""
        s = make_schedule("default_count", tasks=[("Preset A", -1)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            row_widget = win._rows_layout.itemAt(0).widget()
            count_texts = [c.currentText() for c in row_widget.findChildren(QComboBox)]
            assert "-1" in count_texts
        finally:
            win.close()

    def test_none_schedule_creates_empty_new_schedule(self, qapp):
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=None)
        try:
            assert win._rows_layout.count() == 0
        finally:
            win.close()


# ---------------------------------------------------------------------------
# ScheduleModifyWindow — add / delete / move / finalise
# ---------------------------------------------------------------------------

class TestScheduleModifyWindowActions:
    def test_add_preset_task_adds_row(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 1)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            assert win._rows_layout.count() == 1
            win._add_preset_task()
            QApplication.processEvents()
            assert win._rows_layout.count() == 2
        finally:
            win.close()

    def test_add_multiple_tasks_increments_rows_each_time(self, qapp):
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None,
                                   schedule=make_schedule())
        try:
            win._add_preset_task()
            win._add_preset_task()
            win._add_preset_task()
            QApplication.processEvents()
            assert win._rows_layout.count() == 3
        finally:
            win.close()

    def test_add_task_uses_most_recent_preset_name(self, qapp):
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None,
                                   schedule=make_schedule())
        try:
            win._add_preset_task()
            tasks = win._schedule.get_tasks()
            assert len(tasks) == 1
            assert tasks[0].name == "Preset A"  # patched get_most_recent_preset_name
        finally:
            win.close()

    def test_delete_task_removes_row(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 1), ("Preset B", 2)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            assert win._rows_layout.count() == 2
            win._delete_task(0)
            QApplication.processEvents()
            assert win._rows_layout.count() == 1
        finally:
            win.close()

    def test_delete_task_removes_correct_task(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 1), ("Preset B", 2)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            win._delete_task(0)
            remaining = s.get_tasks()
            assert len(remaining) == 1
            assert remaining[0].name == "Preset B"
        finally:
            win.close()

    def test_move_task_down_reorders_schedule(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 1), ("Preset B", 2)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            win._move_task_down(0)  # move "Preset A" past "Preset B"
            tasks = s.get_tasks()
            assert tasks[0].name == "Preset B"
            assert tasks[1].name == "Preset A"
        finally:
            win.close()

    def test_move_task_down_updates_row_count(self, qapp):
        s = make_schedule("test", tasks=[("Preset A", 1), ("Preset B", 2), ("Preset A", 3)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=lambda s: None, schedule=s)
        try:
            before = win._rows_layout.count()
            win._move_task_down(0)
            QApplication.processEvents()
            assert win._rows_layout.count() == before  # reorder doesn't change count
        finally:
            win.close()

    def test_finalize_schedule_calls_refresh_callback(self, qapp):
        callbacks = []
        s = make_schedule("my_schedule")
        win = ScheduleModifyWindow(parent=None, refresh_callback=callbacks.append, schedule=s)
        win._finalize_schedule()
        assert len(callbacks) == 1
        assert callbacks[0].name == "my_schedule"

    def test_finalize_schedule_updates_name_from_entry(self, qapp):
        callbacks = []
        s = make_schedule("original")
        win = ScheduleModifyWindow(parent=None, refresh_callback=callbacks.append, schedule=s)
        win._name_entry.setText("renamed")
        win._finalize_schedule()
        assert callbacks[0].name == "renamed"

    def test_finalize_schedule_passes_schedule_with_tasks(self, qapp):
        callbacks = []
        s = make_schedule("with_tasks", tasks=[("Preset A", 3), ("Preset B", 7)])
        win = ScheduleModifyWindow(parent=None, refresh_callback=callbacks.append, schedule=s)
        win._finalize_schedule()
        result = callbacks[0]
        assert len(result.get_tasks()) == 2
        assert result.get_tasks()[0].count_runs == 3
        assert result.get_tasks()[1].count_runs == 7
