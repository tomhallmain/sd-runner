import pytest
from unittest.mock import patch
from ui_qt.presets.schedule import PresetTask, Schedule


def make_schedule(name="Test Schedule") -> Schedule:
    s = Schedule()
    s.name = name
    return s


class TestPresetTask:
    def test_stores_name_and_count(self):
        t = PresetTask("MyPreset", 5)
        assert t.name == "MyPreset"
        assert t.count_runs == 5


class TestScheduleAddAndGet:
    def test_add_preset_task_appends(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 3))
        s.add_preset_task(PresetTask("B", 2))
        assert len(s.get_tasks()) == 2

    def test_get_tasks_returns_in_order(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("first", 1))
        s.add_preset_task(PresetTask("second", 2))
        tasks = s.get_tasks()
        assert tasks[0].name == "first"
        assert tasks[1].name == "second"

    def test_set_preset_task_updates_existing(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("old", 1))
        s.set_preset_task(0, "new", 5)
        assert s.get_tasks()[0].name == "new"
        assert s.get_tasks()[0].count_runs == 5

    def test_set_preset_task_appends_at_end(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.set_preset_task(1, "B", 2)  # idx == len → append
        assert len(s.get_tasks()) == 2
        assert s.get_tasks()[1].name == "B"

    def test_set_preset_task_invalid_index_raises(self):
        s = make_schedule()
        with pytest.raises(IndexError):
            s.set_preset_task(5, "X", 1)


class TestScheduleDeleteIndex:
    def test_delete_removes_correct_item(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.add_preset_task(PresetTask("B", 2))
        s.delete_index(0)
        assert len(s.get_tasks()) == 1
        assert s.get_tasks()[0].name == "B"

    def test_delete_last_item_empties_schedule(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("only", 1))
        s.delete_index(0)
        assert len(s.get_tasks()) == 0

    def test_delete_invalid_index_raises(self):
        s = make_schedule()
        with pytest.raises(IndexError):
            s.delete_index(0)


class TestScheduleMoveIndex:
    def test_move_forward_one(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.add_preset_task(PresetTask("B", 2))
        s.add_preset_task(PresetTask("C", 3))
        s.move_index(0, 1)  # move A one forward
        names = [t.name for t in s.get_tasks()]
        assert names[0] == "B"
        assert names[1] == "A"

    def test_move_backward_one(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.add_preset_task(PresetTask("B", 2))
        s.add_preset_task(PresetTask("C", 3))
        s.move_index(2, -1)  # move C one backward
        names = [t.name for t in s.get_tasks()]
        assert names[1] == "C"
        assert names[2] == "B"

    def test_move_wraps_around_end(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.add_preset_task(PresetTask("B", 2))
        s.move_index(1, 1)  # B wraps to front
        names = [t.name for t in s.get_tasks()]
        assert names[0] == "B"

    def test_move_wraps_around_start(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("A", 1))
        s.add_preset_task(PresetTask("B", 2))
        s.move_index(0, -1)  # A wraps to end
        names = [t.name for t in s.get_tasks()]
        assert names[-1] == "A"


class TestScheduleSerialization:
    def test_to_dict_from_dict_round_trip(self):
        s = make_schedule(name="Evening")
        s.add_preset_task(PresetTask("preset_a", 3))
        s.add_preset_task(PresetTask("preset_b", 1))

        restored = Schedule.from_dict(s.to_dict())
        assert restored.name == s.name
        assert len(restored.get_tasks()) == 2
        assert restored.get_tasks()[0].name == "preset_a"
        assert restored.get_tasks()[0].count_runs == 3
        assert restored.get_tasks()[1].name == "preset_b"

    def test_to_dict_includes_name_and_schedule(self):
        s = make_schedule(name="Morning")
        d = s.to_dict()
        assert "name" in d and "schedule" in d


class TestScheduleEqualityAndHash:
    def test_equal_by_name(self):
        a = make_schedule(name="Alpha")
        b = make_schedule(name="Alpha")
        assert a == b

    def test_not_equal_different_name(self):
        a = make_schedule(name="Alpha")
        b = make_schedule(name="Beta")
        assert a != b

    def test_hash_consistent(self):
        a = make_schedule(name="X")
        b = make_schedule(name="X")
        assert hash(a) == hash(b)

    def test_usable_in_set(self):
        a = make_schedule(name="A")
        b = make_schedule(name="A")
        c = make_schedule(name="B")
        assert len({a, b, c}) == 2


class TestScheduleTotalGenerations:
    def test_counts_runs_for_found_presets(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("p1", 3))
        s.add_preset_task(PresetTask("p2", 2))

        # Patch PresetsWindow.get_preset_by_name to return a truthy object for any name
        with patch("ui_qt.presets.schedule.PresetsWindow.get_preset_by_name", return_value=object()):
            total = s.total_generations(starting_total=10)
        assert total == 5  # 3 + 2

    def test_uses_starting_total_when_count_is_zero(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("p1", 0))

        with patch("ui_qt.presets.schedule.PresetsWindow.get_preset_by_name", return_value=object()):
            total = s.total_generations(starting_total=7)
        assert total == 7

    def test_skips_missing_presets(self):
        s = make_schedule()
        s.add_preset_task(PresetTask("missing", 5))

        with patch("ui_qt.presets.schedule.PresetsWindow.get_preset_by_name", side_effect=Exception("not found")):
            total = s.total_generations(starting_total=10)
        assert total == 0
