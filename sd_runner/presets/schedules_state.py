"""Preset schedules as they are stored and restored.

Run configuration: the saved schedules, and the one a run follows. A test or a
server running without a window reaches them through here; ``SchedulesWindow``
is the editor for the same state.

The ``app_info_cache`` import stays inside each function: it builds its
singleton at import time, and importing this module should not force that.
"""

from sd_runner.presets.schedule import Schedule


class SchedulesState:
    """The saved schedules, and the one a run follows."""

    #: Set to a fresh Schedule() by set_schedules when the cache holds none.
    current_schedule = None
    recent_schedules = []

    @staticmethod
    def set_schedules():
        from utils.app_info_cache import app_info_cache
        for schedule_dict in list(app_info_cache.get("recent_schedules", default_val=[])):
            SchedulesState.recent_schedules.append(Schedule.from_dict(schedule_dict))
        current_schedule_dict = app_info_cache.get("current_schedule", default_val=None)
        if current_schedule_dict is not None:
            SchedulesState.current_schedule = Schedule.from_dict(current_schedule_dict)
        else:
            SchedulesState.current_schedule = Schedule()

    @staticmethod
    def store_schedules(persist: bool = True):
        """Store schedules to cache.

        Writes through to disk unless *persist* is False. The write is skipped
        when nothing actually changed, so calling this from an edit handler is
        cheap even when the edit was a no-op. store_info_cache passes False
        because it writes once itself after collecting every subsystem.
        """
        from utils.app_info_cache import app_info_cache
        schedule_dicts = []
        for schedule in SchedulesState.recent_schedules:
            schedule_dicts.append(schedule.to_dict())
        app_info_cache.set("recent_schedules", schedule_dicts)
        if SchedulesState.current_schedule is not None:
            app_info_cache.set("current_schedule", SchedulesState.current_schedule.to_dict())

        if persist:
            app_info_cache.store(only_if_changed=True)
