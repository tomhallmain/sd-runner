
from utils.translations import I18N

_ = I18N._


class PresetTask:
    def __init__(self, name, count_runs):
        self.name = name
        self.count_runs = count_runs

class Schedule:
    def __init__(self):
        self.name = _('New Schedule')
        self.schedule = []

    def get_tasks(self):
        return self.schedule

    def add_preset_task(self, task):
        self.schedule.append(task)

    def set_preset_task(self, idx, task_name, count_runs):
        if idx > len(self.schedule) or idx < 0:
            raise IndexError(f'Invalid index: {idx} - only {len(self.schedule)} tasks available')
        if idx == len(self.schedule):
            self.schedule.append(PresetTask(task_name, int(count_runs)))
        else:
            self.schedule[idx].name = task_name
            self.schedule[idx].count_runs = int(count_runs)

    def delete_index(self, idx):
        if idx > len(self.schedule) or idx < 0:
            raise IndexError(f'Invalid index: {idx} - only {len(self.schedule)} tasks available')
        del self.schedule[idx]

    def move_index(self, idx, direction_count=1):
        unit = 1 if direction_count > 0 else -1
        direction_count = abs(direction_count)
        replacement_idx = idx
        while direction_count > 0:
            replacement_idx += unit
            direction_count -= 1
            if replacement_idx >= len(self.schedule):
                replacement_idx = 0
            elif replacement_idx < 0:
                replacement_idx = len(self.schedule) - 1
        # if replacement_idx >= idx:
        #     replacement_idx -= 1
        move_item = self.schedule[idx]
        del self.schedule[idx]
        self.schedule.insert(replacement_idx, move_item)

    def is_valid(self):
        return True

    @staticmethod
    def from_dict(_dict):
        schedule = Schedule()
        schedule.name = _dict['name']
        for task in _dict['schedule']:
            schedule.add_preset_task(PresetTask(**task))
        return schedule

    def to_dict(self):
        return {
            'schedule': [task.__dict__ for task in self.schedule],
            'name': self.name
        }

    def __str__(self):
        return _("{0} ({1} runs)").format(self.name, len(self.schedule))

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Schedule) and self.name == other.name

    def __hash__(self) -> int:
        return hash(self.name)

