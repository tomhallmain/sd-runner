"""UI tests for RunsWindow — queue/history browser dialog."""
import pytest
from PySide6.QtWidgets import QApplication

from ui_qt.runs.runs_window import RunsWindow, _fmt_timestamp, _short


# ---------------------------------------------------------------------------
# Pure helper functions — no Qt needed
# ---------------------------------------------------------------------------

class TestFmtTimestamp:
    def test_iso_string_trimmed_to_seconds(self):
        assert _fmt_timestamp("2024-03-15T10:30:45.123456") == "2024-03-15 10:30:45"

    def test_short_string_returned_as_is(self):
        assert _fmt_timestamp("2024-03-15") == "2024-03-15"

    def test_non_string_returns_str(self):
        assert isinstance(_fmt_timestamp(None), str)

    def test_empty_string(self):
        assert _fmt_timestamp("") == ""


class TestShort:
    def test_short_string_unchanged(self):
        assert _short("hello", 10) == "hello"

    def test_long_string_truncated_with_ellipsis(self):
        result = _short("a" * 50, 10)
        assert len(result) == 10
        assert result.endswith("…")

    def test_exact_limit_unchanged(self):
        assert _short("hello", 5) == "hello"

    def test_empty_string(self):
        assert _short("", 10) == ""

    def test_none_treated_as_empty(self):
        assert _short(None, 10) == ""


# ---------------------------------------------------------------------------
# RunsWindow widget — opened from a real AppWindow
# ---------------------------------------------------------------------------

class TestRunsWindowTabs:
    def test_has_three_tabs(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert win._tabs.count() == 3
        finally:
            win.close()

    def test_tab_labels_include_queue_and_history(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            labels = [win._tabs.tabText(i) for i in range(win._tabs.count())]
            assert any("Queue" in lbl or "queue" in lbl.lower() for lbl in labels)
            assert any("History" in lbl or "history" in lbl.lower() for lbl in labels)
        finally:
            win.close()


class TestRunsWindowQueue:
    def test_status_idle_when_no_job_running(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert "Idle" in win._queue_status_label.text()
        finally:
            win.close()

    def test_running_tree_empty_on_open(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert win._running_tree.topLevelItemCount() == 0
        finally:
            win.close()

    def test_pending_tree_empty_on_open(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert win._pending_tree.topLevelItemCount() == 0
        finally:
            win.close()


class TestRunsWindowHistory:
    def test_history_tab_shows_at_least_one_entry(self, app_window):
        # Empty cache still returns a default RunnerAppConfig entry at index 0.
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._tabs.setCurrentIndex(1)
            QApplication.processEvents()
            assert win._hist_tree.topLevelItemCount() >= 1
        finally:
            win.close()

    def test_filter_hides_nonmatching_entries(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._tabs.setCurrentIndex(1)
            QApplication.processEvents()
            win._hist_filter.setText("xyz_nonexistent_9876zyx")
            QApplication.processEvents()
            assert win._hist_tree.topLevelItemCount() == 0
        finally:
            win.close()

    def test_filter_shows_match_on_workflow_name(self, app_window):
        # Default history entry has workflow_type = "SIMPLE_IMAGE_GEN_LORA".
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._tabs.setCurrentIndex(1)
            QApplication.processEvents()
            win._hist_filter.setText("SIMPLE")
            QApplication.processEvents()
            assert win._hist_tree.topLevelItemCount() >= 1
        finally:
            win.close()

    def test_clearing_filter_restores_all_entries(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._tabs.setCurrentIndex(1)
            QApplication.processEvents()
            initial_count = win._hist_tree.topLevelItemCount()
            win._hist_filter.setText("xyz_nonexistent_9876zyx")
            QApplication.processEvents()
            assert win._hist_tree.topLevelItemCount() == 0
            win._hist_filter.clear()
            QApplication.processEvents()
            assert win._hist_tree.topLevelItemCount() == initial_count
        finally:
            win.close()

    def test_restore_button_toasts_when_nothing_selected(self, app_window):
        toasts = []
        app_window.app_actions._actions["toast"] = lambda msg, **kw: toasts.append(msg)
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._tabs.setCurrentIndex(1)
            QApplication.processEvents()
            win._hist_tree.clearSelection()
            win._restore_selected()
            assert len(toasts) == 1
        finally:
            win.close()
