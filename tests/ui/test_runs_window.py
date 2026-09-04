"""UI tests for RunsWindow — queue/history browser dialog."""
import pytest
from PySide6.QtWidgets import QApplication

from sd_runner.ui.runs.runs_window import RunsWindow, _fmt_timestamp, _origin, _short
from lib.translations import I18N

_ = I18N._


class _Stub:
    """Stands in for a RunConfig in the pure-helper tests."""

    def __init__(self, **attrs):
        self.__dict__.update(attrs)


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


class TestRunsWindowDismissal:
    """Escape reaches reject(), not closeEvent, so both must release resources.

    RunsWindow drives a repeating refresh timer. Left running on a dismissed
    window it keeps firing for the rest of the session, and reopening starts a
    second one -- so the timer has to stop on either path out.
    """

    def test_close_stops_the_refresh_timer(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        assert win._refresh_timer.isActive()
        win.close()
        assert not win._refresh_timer.isActive()

    def test_reject_stops_the_refresh_timer(self, app_window):
        """Regression: Escape used to leave the timer running forever."""
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        assert win._refresh_timer.isActive()
        win.reject()
        assert not win._refresh_timer.isActive()

    def test_close_clears_the_singleton_reference(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        win.close()
        assert RunsWindow._instance is None

    def test_reject_clears_the_singleton_reference(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        win.reject()
        assert RunsWindow._instance is None

    def test_release_is_idempotent(self, app_window):
        """Both paths can run for one dismissal, so cleanup must tolerate repeats."""
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        win.reject()
        win.close()
        assert RunsWindow._instance is None
        assert not win._refresh_timer.isActive()


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


# ---------------------------------------------------------------------------
# Origin column — which runs a request started
# ---------------------------------------------------------------------------

class TestOriginHelper:
    def test_server_run_is_labelled(self):
        assert _origin(_Stub(run_origin="weidr")) == "weidr"

    def test_user_run_is_blank(self):
        assert _origin(_Stub(run_origin="")) == ""

    def test_missing_attribute_is_blank(self):
        """A run built outside either run path may not set the flag at all."""
        assert _origin(_Stub()) == ""


class TestOriginColumn:
    def pending_row(self, win, row: int) -> list[str]:
        item = win._pending_tree.topLevelItem(row)
        return [item.text(i) for i in range(win._pending_tree.columnCount())]

    def test_header_is_present_on_both_run_trees(self, app_window):
        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            pending = [
                win._pending_tree.headerItem().text(i)
                for i in range(win._pending_tree.columnCount())
            ]
            running = [
                win._running_tree.headerItem().text(i)
                for i in range(win._running_tree.columnCount())
            ]
            assert _("Origin") in pending
            assert _("Origin") in running
        finally:
            win.close()

    def test_a_server_run_is_marked_in_the_pending_tree(self, app_window):
        args, _copy = app_window.get_args()
        args.run_origin = "weidr"
        app_window.job_queue.pending_jobs.append(args)

        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._refresh_queue()
            assert "weidr" in self.pending_row(win, 0)
        finally:
            win.close()

    def test_a_user_run_leaves_the_cell_blank(self, app_window):
        args, _copy = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)

        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._refresh_queue()
            assert self.pending_row(win, 0)[6] == ""
        finally:
            win.close()

    def test_row_width_matches_the_header(self, app_window):
        """A column added to one and not the other silently shifts every cell."""
        args, _copy = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)

        win = RunsWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._refresh_queue()
            item = win._pending_tree.topLevelItem(0)
            assert item.text(win._pending_tree.columnCount() - 1) is not None
            assert win._pending_tree.columnCount() == 8
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
