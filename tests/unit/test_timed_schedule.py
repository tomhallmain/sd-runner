import datetime
import pytest
from sd_runner.timed_schedule import TimedSchedule


def make_schedule(**kwargs):
    defaults = dict(
        name="Test Schedule",
        enabled=True,
        weekday_options=[0, 1, 2, 3, 4],  # Mon–Fri
        start_time=None,
        end_time=None,
        shutdown_time=None,
    )
    defaults.update(kwargs)
    return TimedSchedule(**defaults)


class TestTimedScheduleValidity:
    def test_valid_with_weekday_options(self):
        s = make_schedule(weekday_options=[0, 2, 4])
        assert s.is_valid() is True

    def test_invalid_with_empty_weekday_options(self):
        s = make_schedule(weekday_options=[])
        assert s.is_valid() is False

    def test_default_name_when_none(self):
        s = TimedSchedule(name=None, weekday_options=[0])
        assert s.name  # non-empty string


class TestGetTime:
    def test_converts_hours_and_minutes_to_total_minutes(self):
        assert TimedSchedule.get_time(hour=2, minute=30) == 150

    def test_midnight_is_zero(self):
        assert TimedSchedule.get_time(hour=0, minute=0) == 0

    def test_full_day_is_1440(self):
        assert TimedSchedule.get_time(hour=24, minute=0) == 1440


class TestSetTimes:
    def test_set_start_time(self):
        s = make_schedule()
        s.set_start_time(hour=9, minute=0)
        assert s.start_time == 540

    def test_set_end_time(self):
        s = make_schedule()
        s.set_end_time(hour=17, minute=30)
        assert s.end_time == 1050

    def test_set_shutdown_time(self):
        s = make_schedule()
        s.set_shutdown_time(hour=22, minute=0)
        assert s.shutdown_time == 1320


class TestNextEnd:
    def test_returns_end_time_string_when_set(self):
        s = make_schedule()
        s.set_end_time(hour=18, minute=0)
        result = s.next_end(datetime.date.today())
        assert isinstance(result, str) and result

    def test_returns_shutdown_time_string_when_no_end_time(self):
        s = make_schedule()
        s.set_shutdown_time(hour=23, minute=30)
        result = s.next_end(datetime.date.today())
        assert isinstance(result, str) and result

    def test_all_days_no_times_returns_unknown(self):
        s = make_schedule(weekday_options=list(range(7)))
        result = s.next_end(datetime.date.today())
        assert "unknown" in result.lower()

    def test_partial_days_no_times_returns_day_string(self):
        # schedule runs Mon–Fri; on a weekday it should say Tomorrow or a day name
        s = make_schedule(weekday_options=[0, 1, 2, 3, 4])
        monday = datetime.date(2026, 6, 1)  # known Monday
        result = s.next_end(monday)
        assert isinstance(result, str) and result


class TestCalculateGenerality:
    def test_all_day_no_times_returns_weekday_count(self):
        s = make_schedule(weekday_options=[0, 1, 2, 3, 4, 5, 6])
        assert s.calculate_generality() == 7.0

    def test_partial_day_with_both_times(self):
        s = make_schedule()
        s.set_start_time(hour=8, minute=0)   # 480 minutes
        s.set_end_time(hour=16, minute=0)    # 960 minutes
        # (960 - 480) / 1440 = 480/1440 = 1/3
        assert abs(s.calculate_generality() - (480 / 1440)) < 1e-9

    def test_no_start_time_uses_end_time_fraction(self):
        s = make_schedule()
        s.set_end_time(hour=12, minute=0)  # 720 minutes
        assert abs(s.calculate_generality() - (720 / 1440)) < 1e-9

    def test_no_end_time_uses_remaining_fraction(self):
        s = make_schedule()
        s.set_start_time(hour=12, minute=0)  # 720 minutes from midnight
        assert abs(s.calculate_generality() - ((1440 - 720) / 1440)) < 1e-9


class TestTimedScheduleSerialization:
    def test_to_dict_from_dict_round_trip(self):
        s = make_schedule(name="Evening Run")
        s.set_start_time(hour=20, minute=0)
        s.set_end_time(hour=23, minute=0)
        s.set_shutdown_time(hour=23, minute=30)
        restored = TimedSchedule.from_dict(s.to_dict())
        assert restored.name == s.name
        assert restored.start_time == s.start_time
        assert restored.end_time == s.end_time
        assert restored.shutdown_time == s.shutdown_time
        assert restored.weekday_options == s.weekday_options
        assert restored.enabled == s.enabled


class TestTimedScheduleEqualityAndHash:
    def test_equal_by_name(self):
        a = make_schedule(name="Alpha")
        b = make_schedule(name="Alpha")
        assert a == b

    def test_not_equal_different_name(self):
        a = make_schedule(name="Alpha")
        b = make_schedule(name="Beta")
        assert a != b

    def test_hash_consistent_with_equality(self):
        a = make_schedule(name="X")
        b = make_schedule(name="X")
        assert hash(a) == hash(b)

    def test_usable_in_set(self):
        a = make_schedule(name="A")
        b = make_schedule(name="A")
        c = make_schedule(name="B")
        assert len({a, b, c}) == 2


class TestReadableTime:
    def test_none_returns_na(self):
        s = make_schedule()
        assert s.readable_time(None) == "N/A"

    def test_negative_returns_na(self):
        s = make_schedule()
        assert s.readable_time(-1) == "N/A"

    def test_formats_hour_and_minute(self):
        s = make_schedule()
        # 90 minutes = 1 hour, 30 minutes
        result = s.readable_time(90)
        assert "1" in result and "30" in result
