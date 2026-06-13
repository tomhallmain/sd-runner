"""
Tests for sd_runner/timed_schedules_manager.py.

TimedSchedulesManager uses class-level mutable state; the autouse fixture resets it
before and after every test so tests remain independent.

All datetime objects use 2024-01-01 (Monday) as the base — adding timedelta(days=N)
gives a deterministic weekday without depending on the system clock.
"""

import datetime
import pytest
from sd_runner.timed_schedule import TimedSchedule
from sd_runner.timed_schedules_manager import (
    TimedSchedulesManager,
    ScheduledShutdownException,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_schedule(name="test", enabled=True, weekday_options=None,
                  start_time=None, end_time=None, shutdown_time=None):
    return TimedSchedule(
        name=name,
        enabled=enabled,
        weekday_options=weekday_options if weekday_options is not None else [0, 1, 2, 3, 4, 5, 6],
        start_time=start_time,
        end_time=end_time,
        shutdown_time=shutdown_time,
    )


def dt(weekday=0, hour=10, minute=0):
    """Return a naive datetime with the given weekday/time. 2024-01-01 is Monday (0)."""
    base = datetime.datetime(2024, 1, 1)
    return base + datetime.timedelta(days=weekday, hours=hour, minutes=minute)


@pytest.fixture(autouse=True)
def reset_manager_state():
    TimedSchedulesManager.recent_timed_schedules = []
    TimedSchedulesManager.schedule_history = []
    TimedSchedulesManager.last_set_schedule = None
    yield
    TimedSchedulesManager.recent_timed_schedules = []
    TimedSchedulesManager.schedule_history = []
    TimedSchedulesManager.last_set_schedule = None


# ---------------------------------------------------------------------------
# get_tomorrow
# ---------------------------------------------------------------------------

class TestGetTomorrow:
    def test_early_hour_returns_same_day_at_7am(self):
        now = datetime.datetime(2024, 6, 10, hour=4, tzinfo=datetime.timezone.utc)
        result = TimedSchedulesManager.get_tomorrow(now)
        assert result.day == 10 and result.hour == 7

    def test_late_hour_returns_next_day_at_7am(self):
        now = datetime.datetime(2024, 6, 10, hour=9, tzinfo=datetime.timezone.utc)
        result = TimedSchedulesManager.get_tomorrow(now)
        assert result.day == 11 and result.hour == 7

    def test_end_of_month_rolls_to_next_month(self):
        now = datetime.datetime(2024, 6, 30, hour=9, tzinfo=datetime.timezone.utc)
        result = TimedSchedulesManager.get_tomorrow(now)
        assert result.month == 7 and result.day == 1

    def test_end_of_year_rolls_to_next_year(self):
        now = datetime.datetime(2024, 12, 31, hour=9, tzinfo=datetime.timezone.utc)
        result = TimedSchedulesManager.get_tomorrow(now)
        assert result.year == 2025


# ---------------------------------------------------------------------------
# Schedule history — update_history / get_history_schedule
# ---------------------------------------------------------------------------

class TestScheduleHistory:
    def test_insert_at_front(self):
        s1 = make_schedule("first")
        s2 = make_schedule("second")
        TimedSchedulesManager.update_history(s1)
        TimedSchedulesManager.update_history(s2)
        assert TimedSchedulesManager.schedule_history[0] == s2

    def test_no_duplicate_at_front(self):
        s = make_schedule("dup")
        TimedSchedulesManager.update_history(s)
        TimedSchedulesManager.update_history(s)
        assert len(TimedSchedulesManager.schedule_history) == 1

    def test_history_limited_to_max_presets(self):
        for i in range(TimedSchedulesManager.MAX_PRESETS + 5):
            TimedSchedulesManager.update_history(make_schedule(f"s{i}"))
        assert len(TimedSchedulesManager.schedule_history) == TimedSchedulesManager.MAX_PRESETS

    def test_get_history_schedule_by_index(self):
        s0 = make_schedule("alpha")
        s1 = make_schedule("beta")
        TimedSchedulesManager.update_history(s1)
        TimedSchedulesManager.update_history(s0)
        assert TimedSchedulesManager.get_history_schedule(0) == s0
        assert TimedSchedulesManager.get_history_schedule(1) == s1

    def test_get_history_schedule_empty_returns_none(self):
        assert TimedSchedulesManager.get_history_schedule(0) is None


# ---------------------------------------------------------------------------
# Schedule list management — next / refresh / delete / clear
# ---------------------------------------------------------------------------

class TestScheduleManagement:
    def test_next_schedule_moves_last_to_front(self):
        s1 = make_schedule("A")
        s2 = make_schedule("B")
        TimedSchedulesManager.recent_timed_schedules = [s1, s2]
        result = TimedSchedulesManager.next_schedule(lambda msg: None)
        assert result == s2
        assert TimedSchedulesManager.recent_timed_schedules[0] == s2

    def test_next_schedule_empty_raises_and_calls_alert(self):
        # NOTE: Bug — next_schedule() calls alert_callback but then immediately
        # tries recent_timed_schedules[-1] on an empty list, raising IndexError
        # instead of returning early. Both the alert and the crash happen.
        alerts = []
        with pytest.raises(IndexError):
            TimedSchedulesManager.next_schedule(alerts.append)
        assert len(alerts) == 1

    def test_refresh_schedule_moves_to_front(self):
        s1 = make_schedule("A")
        s2 = make_schedule("B")
        TimedSchedulesManager.recent_timed_schedules = [s1, s2]
        TimedSchedulesManager.refresh_schedule(s2)
        assert TimedSchedulesManager.recent_timed_schedules[0] == s2

    def test_refresh_schedule_adds_to_history(self):
        s = make_schedule("X")
        TimedSchedulesManager.recent_timed_schedules = [s]
        TimedSchedulesManager.refresh_schedule(s)
        assert s in TimedSchedulesManager.schedule_history

    def test_delete_schedule_removes_it(self):
        s = make_schedule("to_delete")
        TimedSchedulesManager.recent_timed_schedules = [s]
        TimedSchedulesManager.delete_schedule(s)
        assert s not in TimedSchedulesManager.recent_timed_schedules

    def test_delete_none_is_safe(self):
        s = make_schedule("safe")
        TimedSchedulesManager.recent_timed_schedules = [s]
        TimedSchedulesManager.delete_schedule(None)
        assert len(TimedSchedulesManager.recent_timed_schedules) == 1

    def test_clear_all_schedules(self):
        TimedSchedulesManager.recent_timed_schedules = [make_schedule("A"), make_schedule("B")]
        TimedSchedulesManager.clear_all_schedules()
        assert TimedSchedulesManager.recent_timed_schedules == []

    def test_get_schedule_by_name_found(self):
        s = make_schedule("named_schedule")
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager.get_schedule_by_name("named_schedule") == s

    def test_get_schedule_by_name_not_found_raises(self):
        with pytest.raises(Exception):
            TimedSchedulesManager.get_schedule_by_name("missing")


# ---------------------------------------------------------------------------
# get_active_schedule
# ---------------------------------------------------------------------------

class TestGetActiveSchedule:
    def test_returns_default_when_no_schedules(self):
        result = TimedSchedulesManager.get_active_schedule(dt(0, 10))
        assert result == TimedSchedulesManager.default_schedule

    def test_disabled_schedule_skipped(self):
        s = make_schedule("disabled", enabled=False, weekday_options=[0])
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager.get_active_schedule(dt(0, 10)) == TimedSchedulesManager.default_schedule

    def test_wrong_weekday_skipped(self):
        s = make_schedule("tue_only", weekday_options=[1])
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager.get_active_schedule(dt(0, 10)) == TimedSchedulesManager.default_schedule

    def test_shutdown_time_schedule_skipped(self):
        s = make_schedule("shutdown_only", shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager.get_active_schedule(dt(0, 10)) == TimedSchedulesManager.default_schedule

    def test_exact_time_window_match_returned(self):
        s = make_schedule("work",
                          start_time=TimedSchedule.get_time(9, 0),
                          end_time=TimedSchedule.get_time(17, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        result = TimedSchedulesManager.get_active_schedule(dt(0, 12))
        assert result == s

    def test_no_time_constraint_returned_for_any_time(self):
        s = make_schedule("all_day")  # no start/end, all weekdays
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager.get_active_schedule(dt(0, 10)) == s

    def test_partially_applicable_returned_when_started_but_ended(self):
        # start < current_time, end < current_time → partially_applicable
        s = make_schedule("morning",
                          start_time=TimedSchedule.get_time(8, 0),
                          end_time=TimedSchedule.get_time(10, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        result = TimedSchedulesManager.get_active_schedule(dt(0, 12))
        assert result == s

    def test_partially_applicable_returned_when_not_yet_started_with_future_end(self):
        # start > current_time, end > current_time → partially_applicable via elif branch
        s = make_schedule("afternoon",
                          start_time=TimedSchedule.get_time(15, 0),
                          end_time=TimedSchedule.get_time(17, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        result = TimedSchedulesManager.get_active_schedule(dt(0, 12))
        assert result == s


# ---------------------------------------------------------------------------
# get_closest_weekday_index_to_datetime
# ---------------------------------------------------------------------------

class TestGetClosestWeekdayIndex:
    def test_same_day_returned_when_in_options(self):
        s = make_schedule(weekday_options=[0, 2, 4])
        result = TimedSchedulesManager.get_closest_weekday_index_to_datetime(s, dt(0))
        assert result == 0

    def test_next_available_weekday_returned(self):
        s = make_schedule(weekday_options=[2, 4])
        result = TimedSchedulesManager.get_closest_weekday_index_to_datetime(s, dt(0))
        assert result == 2

    def test_wraps_around_when_no_later_day_in_week(self):
        s = make_schedule(weekday_options=[1])  # Tuesday only
        result = TimedSchedulesManager.get_closest_weekday_index_to_datetime(s, dt(4), total_days=False)
        assert result == 1

    def test_total_days_adds_seven_on_wrap(self):
        s = make_schedule(weekday_options=[1])  # Tuesday only
        result = TimedSchedulesManager.get_closest_weekday_index_to_datetime(s, dt(4), total_days=True)
        assert result == 8  # 1 + 7


# ---------------------------------------------------------------------------
# _check_for_shutdown_request / check_for_shutdown_request
# ---------------------------------------------------------------------------

class TestCheckForShutdownRequest:
    def test_no_schedules_returns_none(self):
        assert TimedSchedulesManager._check_for_shutdown_request(dt(0, 10)) is None

    def test_schedule_without_shutdown_time_skipped(self):
        s = make_schedule("no_shutdown")
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager._check_for_shutdown_request(dt(0, 23)) is None

    def test_disabled_schedule_skipped(self):
        s = make_schedule("disabled", enabled=False, shutdown_time=TimedSchedule.get_time(22, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager._check_for_shutdown_request(dt(0, 23)) is None

    def test_after_shutdown_time_returns_schedule(self):
        s = make_schedule("shutdown_11pm", shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        result = TimedSchedulesManager._check_for_shutdown_request(dt(0, 23, 30))
        assert result == s

    def test_before_shutdown_time_returns_none(self):
        s = make_schedule("shutdown_11pm", shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        assert TimedSchedulesManager._check_for_shutdown_request(dt(0, 20)) is None

    def test_early_next_day_within_overnight_window_returns_schedule(self):
        # Shutdown day Monday (0); now Tuesday 3 AM — still in overnight window
        s = make_schedule("shutdown_mon", weekday_options=[0],
                          shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        result = TimedSchedulesManager._check_for_shutdown_request(dt(1, 3))
        assert result == s

    def test_after_6am_next_day_returns_none(self):
        # 7 AM Tuesday is past the overnight window
        s = make_schedule("shutdown_mon", weekday_options=[0],
                          shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        # Tuesday 7 AM: day_index=1 not in [0], prev_day=0 in [0] but current_time=420 >= 360
        assert TimedSchedulesManager._check_for_shutdown_request(dt(1, 7)) is None

    def test_check_for_shutdown_request_raises_exception(self):
        s = make_schedule("shutdown", shutdown_time=TimedSchedule.get_time(23, 0))
        TimedSchedulesManager.recent_timed_schedules = [s]
        with pytest.raises(ScheduledShutdownException) as exc_info:
            TimedSchedulesManager.check_for_shutdown_request(dt(0, 23, 30))
        assert exc_info.value.schedule == s
