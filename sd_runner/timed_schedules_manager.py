
import datetime

from sd_runner.timed_schedule import TimedSchedule
from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._

logger = get_logger(__name__)

class ScheduledShutdownException(Exception):
    """Exception raised when a scheduled shutdown is requested."""
    
    def __init__(self, message, schedule=None):
        super().__init__(message)
        self.schedule = schedule


class TimedSchedulesManager:
    default_schedule = TimedSchedule(name=_("Default"), enabled=True, weekday_options=[0,1,2,3,4,5,6])
    recent_timed_schedules = []
    last_set_schedule = None
    MAX_PRESETS = 50
    schedule_history = []

    def __init__(self):
        pass

    @staticmethod
    def get_tomorrow(now):
       try:
           return datetime.datetime(now.year, now.month, (now.day if now.hour < 5 else now.day + 1), hour=7, tzinfo=now.tzinfo)
       except Exception as e:
           try:
               return datetime.datetime(now.year, now.month + 1, 1, hour=7, tzinfo=now.tzinfo)
           except Exception as e:
               return datetime.datetime(now.year + 1, 1, 1, hour=7, tzinfo=now.tzinfo)

    @staticmethod
    def set_schedules():
        for schedule_dict in list(app_info_cache.get("recent_timed_schedules", default_val=[])):
            TimedSchedulesManager.recent_timed_schedules.append(TimedSchedule.from_dict(schedule_dict))
        
        # Add default shutdown schedule if no schedules exist
        if len(TimedSchedulesManager.recent_timed_schedules) == 0:
            default_shutdown_schedule = TimedSchedule(
                name=_("Default Shutdown"),
                enabled=True,
                weekday_options=[0, 1, 2, 3, 4, 5, 6],  # Every day
                shutdown_time=TimedSchedule.get_time(23, 0)  # 11:00 PM
            )
            TimedSchedulesManager.recent_timed_schedules.append(default_shutdown_schedule)
            TimedSchedulesManager.store_schedules()

    @staticmethod
    def store_schedules():
        schedule_dicts = []
        for schedule in TimedSchedulesManager.recent_timed_schedules:
            schedule_dicts.append(schedule.to_dict())
        app_info_cache.set("recent_timed_schedules", schedule_dicts)

    @staticmethod
    def get_schedule_by_name(name):
        for schedule in TimedSchedulesManager.recent_timed_schedules:
            if name == schedule.name:
                return schedule
        raise Exception(f"No schedule found with name: {name}. Set it on the Schedules Window.")

    @staticmethod
    def get_history_schedule(start_index=0):
        # Get a previous schedule.
        schedule = None
        for i in range(len(TimedSchedulesManager.schedule_history)):
            if i < start_index:
                continue
            schedule = TimedSchedulesManager.schedule_history[i]
            break
        return schedule

    @staticmethod
    def update_history(schedule):
        if len(TimedSchedulesManager.schedule_history) > 0 and \
                schedule == TimedSchedulesManager.schedule_history[0]:
            return
        TimedSchedulesManager.schedule_history.insert(0, schedule)
        if len(TimedSchedulesManager.schedule_history) > TimedSchedulesManager.MAX_PRESETS:
            del TimedSchedulesManager.schedule_history[-1]

    @staticmethod
    def next_schedule(alert_callback):
        if len(TimedSchedulesManager.recent_timed_schedules) == 0:
            alert_callback(_("Not enough schedules found."))
        next_schedule = TimedSchedulesManager.recent_timed_schedules[-1]
        TimedSchedulesManager.recent_timed_schedules.remove(next_schedule)
        TimedSchedulesManager.recent_timed_schedules.insert(0, next_schedule)
        return next_schedule

    @staticmethod
    def refresh_schedule(schedule):
        TimedSchedulesManager.update_history(schedule)
        if schedule in TimedSchedulesManager.recent_timed_schedules:
            TimedSchedulesManager.recent_timed_schedules.remove(schedule)
        TimedSchedulesManager.recent_timed_schedules.insert(0, schedule)
        TimedSchedulesManager.store_schedules()

    @staticmethod
    def delete_schedule(schedule):
        if schedule is not None and schedule in TimedSchedulesManager.recent_timed_schedules:
            TimedSchedulesManager.recent_timed_schedules.remove(schedule)
            TimedSchedulesManager.store_schedules()

    @staticmethod
    def clear_all_schedules():
        TimedSchedulesManager.recent_timed_schedules.clear()
        TimedSchedulesManager.store_schedules()

    @staticmethod
    def get_active_schedule(datetime):
        assert datetime is not None
        day_index = datetime.weekday()
        current_time = TimedSchedule.get_time(datetime.hour, datetime.minute)
        partially_applicable = []
        no_specific_times = []
        for schedule in TimedSchedulesManager.recent_timed_schedules:
            skip = False
            if not schedule.enabled:
                skip = True
            if schedule.shutdown_time is not None:
                logger.debug(f"Skipping schedule {schedule} - a shutdown time is set on this schedule and it is assumed to be for shutdown purposes only.")
                skip = True
            if day_index not in schedule.weekday_options:
                logger.debug(f"Skipping schedule {schedule} - today is index {day_index} - schedule weekday options {schedule.weekday_options}")
                skip = True
            if skip:
                continue
            if schedule.start_time is not None and schedule.start_time < current_time:
                if schedule.end_time is not None and schedule.end_time > current_time:
                    logger.info(f"Schedule {schedule} is applicable")
                    return schedule
                else:
                    partially_applicable.append(schedule)
            elif schedule.end_time is not None and schedule.end_time > current_time:
                partially_applicable.append(schedule)
            elif (schedule.start_time is None and schedule.end_time is None) or \
                    (schedule.start_time == 0 and schedule.end_time == 0):
                no_specific_times.append(schedule)
        if len(partially_applicable) >= 1:
            partially_applicable.sort(key=lambda schedule: schedule.calculate_generality())
            schedules_text = "\n".join([str(schedule) for schedule in partially_applicable])
            logger.info(f"Schedules are partially applicable:\n{schedules_text}")
            return partially_applicable[0]
        elif len(no_specific_times) >= 1:
            no_specific_times.sort(key=lambda schedule: schedule.calculate_generality())
            schedules_text = "\n".join([str(schedule) for schedule in no_specific_times])
            logger.info(f"Schedules are applicable to today but have no specific times:\n{schedules_text}")
            return no_specific_times[0]
        else:
            return TimedSchedulesManager.default_schedule


    @staticmethod
    def get_closest_weekday_index_to_datetime(schedule, datetime, total_days=False):
        assert isinstance(schedule, TimedSchedule) and datetime is not None
        datetime_index = datetime.weekday()
        for i in schedule.weekday_options:
            if i >= datetime_index:
                return i
        for i in schedule.weekday_options:
            return i + 7 if total_days else i
        raise Exception("Invalid schedule, no weekday options found")

    @staticmethod
    def check_for_shutdown_request(datetime):
        schedule_requesting_shutdown = TimedSchedulesManager._check_for_shutdown_request(datetime)
        if schedule_requesting_shutdown is not None:
            message = _("Shutdown scheduled: {}").format(schedule_requesting_shutdown.name)
            raise ScheduledShutdownException(message, schedule_requesting_shutdown)

    @staticmethod
    def _check_for_shutdown_request(datetime):
        assert datetime is not None
        day_index = datetime.weekday()
        current_time = TimedSchedule.get_time(datetime.hour, datetime.minute)
        
        for schedule in TimedSchedulesManager.recent_timed_schedules:
            if not schedule.enabled or schedule.shutdown_time is None:
                continue
            
            # Check if current day is in the schedule's weekday options
            if day_index in schedule.weekday_options:
                # Check if current time is past the shutdown time on the same day
                # This covers the period from shutdown time until midnight
                if schedule.shutdown_time < current_time:
                    return schedule
            
            # Check if we're in the shutdown period of the previous day
            # This covers the period from midnight until 6 AM (6 * 60 = 360 minutes)
            previous_day_index = (day_index - 1) % 7
            if previous_day_index in schedule.weekday_options:
                # If current time is before 6 AM (360 minutes), we're still in the shutdown period
                if current_time < 6 * 60:  # 6 AM = 360 minutes
                    return schedule
        
        return None

    @staticmethod
    def get_hour():
        return datetime.datetime.now().hour


timed_schedules_manager = TimedSchedulesManager()

