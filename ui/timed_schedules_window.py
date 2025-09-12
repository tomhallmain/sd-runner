import os

from tkinter import Toplevel, Frame, Label, Checkbutton, OptionMenu, StringVar, BooleanVar, LEFT, W
import tkinter.font as fnt
from tkinter.ttk import Entry, Button

from sd_runner.timed_schedule import TimedSchedule
from sd_runner.timed_schedules_manager import timed_schedules_manager
from ui.auth.password_utils import require_password
from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.globals import ProtectedActions
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

_ = I18N._


class TimedScheduleModifyWindow():
    top_level = None
    COL_0_WIDTH = 600

    def __init__(self, master, refresh_callback, schedule, dimensions="600x600"):
        TimedScheduleModifyWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        TimedScheduleModifyWindow.top_level.geometry(dimensions)
        self.master = TimedScheduleModifyWindow.top_level
        self.refresh_callback = refresh_callback
        self.schedule = schedule if schedule is not None else TimedSchedule()
        TimedScheduleModifyWindow.top_level.title(_("Modify Preset Schedule: {0}").format(self.schedule.name))

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)

        self._label_name = Label(self.frame)
        self.add_label(self._label_name, _("Schedule Name"), row=0, wraplength=TimedScheduleModifyWindow.COL_0_WIDTH)
        self.new_schedule_name = StringVar(self.master, value=_("New Schedule") if schedule is None else schedule.name)
        self.new_schedule_name_entry = Entry(self.frame, textvariable=self.new_schedule_name, width=50, font=fnt.Font(size=8))
        self.new_schedule_name_entry.grid(row=0, column=1, sticky="w")

        self.add_schedule_btn = None
        self.add_btn("add_schedule_btn", _("Add schedule"), self.finalize_schedule, column=2)

        self.days_of_the_week_var_list = []
        self.days_of_the_week_widget_list = []

        row = 3

        self.all_days_var = BooleanVar(self.master, value=False)
        self.all_days_widget  = Checkbutton(self.frame, text=_("Every day"), variable=self.all_days_var, command=self._toggle_all_days)
        self.all_days_widget.grid(row=row, column=0)
        row += 1

        for i in range(7):
            days_of_the_week_var = BooleanVar(self.master, value=False)
            day_text = I18N.day_of_the_week(i)
            days_of_the_week_widget  = Checkbutton(self.frame, text=day_text, variable=days_of_the_week_var)
            days_of_the_week_widget.grid(row=row, column=0)
            self.days_of_the_week_widget_list.append(days_of_the_week_widget)
            self.days_of_the_week_var_list.append(days_of_the_week_var)
            row += 1

        self._label_start_time = Label(self.frame)
        self.add_label(self._label_start_time, _("Start Time"), row=row, wraplength=TimedScheduleModifyWindow.COL_0_WIDTH)
        self.start_time_hour_var = StringVar(self.master, value="0")
        self.start_time_min_var = StringVar(self.master, value="0")
        self.start_time_hour_choice = OptionMenu(self.frame, self.start_time_hour_var, "0", *list(map(str, range(24))))
        self.start_time_min_choice = OptionMenu(self.frame, self.start_time_min_var, "0", *list(map(str, range(0, 61, 15))))
        self.start_time_hour_choice.grid(row=row, column=1)
        self.start_time_min_choice.grid(row=row, column=2)
        row += 1

        self._label_end_time = Label(self.frame)
        self.add_label(self._label_end_time, _("End Time"), row=row, wraplength=TimedScheduleModifyWindow.COL_0_WIDTH)
        self.end_time_hour_var = StringVar(self.master, value="0")
        self.end_time_min_var = StringVar(self.master, value="0")
        self.end_time_hour_choice = OptionMenu(self.frame, self.end_time_hour_var, "0", *list(map(str, range(24))))
        self.end_time_min_choice = OptionMenu(self.frame, self.end_time_min_var, "0", *list(map(str, range(0, 61, 15))))
        self.end_time_hour_choice.grid(row=row, column=1)
        self.end_time_min_choice.grid(row=row, column=2)
        row += 1

        self._label_shutdown_time = Label(self.frame)
        self.add_label(self._label_shutdown_time, _("Shutdown Time"), row=row, wraplength=TimedScheduleModifyWindow.COL_0_WIDTH)
        self.shutdown_time_hour_var = StringVar(self.master, value="")
        self.shutdown_time_min_var = StringVar(self.master, value="")
        self.shutdown_time_hour_choice = OptionMenu(self.frame, self.shutdown_time_hour_var, "", *list(map(str, range(24))))
        self.shutdown_time_min_choice = OptionMenu(self.frame, self.shutdown_time_min_var, "", *list(map(str, range(0, 61, 15))))
        self.shutdown_time_hour_choice.grid(row=row, column=1)
        self.shutdown_time_min_choice.grid(row=row, column=2)
        row += 1

        self.master.update()

    def refresh(self):
        self.master.update()

    def _toggle_all_days(self):
        set_to = self.all_days_var.get()
        for var in self.days_of_the_week_var_list:
            var.set(set_to)

    def get_active_weekday_indices(self):
        return [i for i, var in enumerate(self.days_of_the_week_var_list) if var.get()]

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def finalize_schedule(self, event=None):
        self.schedule.name = self.new_schedule_name.get()
        self.schedule.weekday_options = self.get_active_weekday_indices()
        if len(self.schedule.weekday_options) == 0:
            raise Exception("No days selected")
        if self.start_time_hour_var.get() != "":
            self.schedule.set_start_time(int(self.start_time_hour_var.get()), int(self.start_time_min_var.get()))
        if self.end_time_hour_var.get() != "":
            self.schedule.set_end_time(int(self.end_time_hour_var.get()), int(self.end_time_min_var.get()))
        if self.shutdown_time_hour_var.get() != "":
            self.schedule.set_shutdown_time(int(self.shutdown_time_hour_var.get()), int(self.shutdown_time_min_var.get()))
        self.close_windows()
        self.refresh_callback(self.schedule)

    def close_windows(self, event=None):
        self.master.destroy()

    def add_label(self, label_ref, text, row=0, column=0, wraplength=500):
        label_ref['text'] = text
        label_ref.grid(column=column, row=row, sticky=W)
        label_ref.config(wraplength=wraplength, justify=LEFT, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

    def add_btn(self, button_ref_name, text, command, row=0, column=0):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.frame, text=text, command=command)
            setattr(self, button_ref_name, button)
            button # for some reason this is necessary to maintain the reference?
            button.grid(row=row, column=column)



class TimedSchedulesWindow():
    top_level = None
    schedule_modify_window = None

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def get_geometry(is_gui=True):
        width = 900
        height = 400
        return f"{width}x{height}"

    def __init__(self, master, app_actions, runner_app_config=RunnerAppConfig()):
        TimedSchedulesWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        TimedSchedulesWindow.top_level.geometry(TimedSchedulesWindow.get_geometry())
        TimedSchedulesWindow.top_level.title(_("Preset Schedules"))
        self.master = TimedSchedulesWindow.top_level
        self.app_actions = app_actions
        self.filter_text = ""
        self.filtered_schedules = timed_schedules_manager.recent_timed_schedules[:]
        self.label_list = []
        self.set_schedule_btn_list = []
        self.modify_schedule_btn_list = []
        self.delete_schedule_btn_list = []
        self.enabled_checkbutton_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)
        self.frame.columnconfigure(4, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Create and modify schedules"), row=0, wraplength=TimedSchedulesWindow.COL_0_WIDTH)
        self.add_schedule_btn = None
        self.add_btn("add_schedule_btn", _("Add schedule"), self.open_schedule_modify_window, column=1)
        self.clear_recent_timed_schedules_btn = None
        self.add_btn("clear_recent_timed_schedules_btn", _("Clear schedules"), self.clear_recent_timed_schedules, column=2)

        self.add_schedule_widgets()

        # self.master.bind("<Key>", self.filter_schedules)
        # self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)
        self.master.update()
        self.frame.after(1, lambda: self.frame.focus_force())

    def add_schedule_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_schedules)):
            row = i+1
            schedule = self.filtered_schedules[i]
            label_name = Label(self.frame)
            self.label_list.append(label_name)
            self.add_label(label_name, str(schedule), row=row, column=base_col, wraplength=TimedSchedulesWindow.COL_0_WIDTH)

            modify_schedule_btn = Button(self.frame, text=_("Modify"))
            self.set_schedule_btn_list.append(modify_schedule_btn)
            modify_schedule_btn.grid(row=row, column=base_col+1)
            def modify_schedule_handler(event, self=self, schedule=schedule):
                return self.open_schedule_modify_window(event, schedule)
            modify_schedule_btn.bind("<Button-1>", modify_schedule_handler)

            delete_schedule_btn = Button(self.frame, text=_("Delete"))
            self.delete_schedule_btn_list.append(delete_schedule_btn)
            delete_schedule_btn.grid(row=row, column=base_col+2)
            def delete_schedule_handler(event, self=self, schedule=schedule):
                return self.delete_schedule(event, schedule)
            delete_schedule_btn.bind("<Button-1>", delete_schedule_handler)

            # Add enabled/disabled checkbutton
            enabled_var = BooleanVar(self.master, value=schedule.enabled)
            enabled_checkbutton = Checkbutton(self.frame, text=_("Enabled"), variable=enabled_var)
            self.enabled_checkbutton_list.append((enabled_checkbutton, enabled_var, schedule))
            enabled_checkbutton.grid(row=row, column=base_col+3)
            def toggle_enabled_handler(event, self=self, schedule=schedule, var=enabled_var):
                schedule.enabled = var.get()
                timed_schedules_manager.store_schedules()
                return None
            enabled_checkbutton.bind("<Button-1>", toggle_enabled_handler)

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def open_schedule_modify_window(self, event=None, schedule=None):
        if TimedSchedulesWindow.schedule_modify_window is not None:
            TimedSchedulesWindow.schedule_modify_window.master.destroy()
        TimedSchedulesWindow.schedule_modify_window = TimedScheduleModifyWindow(self.master, self.refresh_schedules, schedule)

    def refresh_schedules(self, schedule):
        timed_schedules_manager.refresh_schedule(schedule)
        self.filtered_schedules = timed_schedules_manager.recent_timed_schedules[:]
        self.refresh()

    def set_schedule(self, schedule):
        pass

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def delete_schedule(self, event=None, schedule=None):
        timed_schedules_manager.delete_schedule(schedule)
        self.refresh()

    def filter_schedules(self, event):
        """
        TODO

        Rebuild the filtered schedules list based on the filter string and update the UI.
        """
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    self.filtered_schedules = self.filtered_schedules[1:] + [self.filtered_schedules[0]]
                else:  # keysym == "Up"
                    self.filtered_schedules = [self.filtered_schedules[-1]] + self.filtered_schedules[:-1]
                self.clear_widget_lists()
                self.add_schedule_widgets()
                self.master.update()
            if event.keysym != "BackSpace":
                return
        if event.keysym == "BackSpace":
            if len(self.filter_text) > 0:
                self.filter_text = self.filter_text[:-1]
        elif event.char:
            self.filter_text += event.char
        else:
            return
        if self.filter_text.strip() == "":
            print("Filter unset")
            # Restore the list of target directories to the full list
            self.filtered_schedules.clear()
            self.filtered_schedules = timed_schedules_manager.recent_timed_schedules[:]
        else:
            temp = []
            return # TODO
            for schedule in timed_schedules_manager.recent_timed_schedules:
                if schedule not in temp:
                    if schedule and (f" {self.filter_text}" in schedule.lower() or f"_{self.filter_text}" in schedule.lower()):
                        temp.append(schedule)
            self.filtered_schedules = temp[:]

        self.refresh()


    def do_action(self, event=None):
        """
        The user has requested to set a schedule. Based on the context, figure out what to do.

        If no schedules exist, call handle_schedule() with schedule=None to set a new schedule.

        If schedules exist, call set_schedule() to set the first schedule.

        If control key pressed, ignore existing and add a new schedule.

        If alt key pressed, use the penultimate schedule.

        The idea is the user can filter the directories using keypresses, then press enter to
        do the action on the first filtered tag.
        """
#        shift_key_pressed = (event.state & 0x1) != 0
        control_key_pressed = (event.state & 0x4) != 0
        alt_key_pressed = (event.state & 0x20000) != 0
        if alt_key_pressed:
            penultimate_schedule = timed_schedules_manager.get_history_schedule(start_index=1)
            if penultimate_schedule is not None and os.path.isdir(penultimate_schedule):
                pass
                self.set_schedule(schedule=penultimate_schedule)
        elif len(self.filtered_schedules) == 0 or control_key_pressed:
            self.open_schedule_modify_window()
        else:
            if len(self.filtered_schedules) == 1 or self.filter_text.strip() != "":
                schedule = self.filtered_schedules[0]
            else:
                schedule = timed_schedules_manager.last_set_schedule
            self.set_schedule(schedule=schedule)

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def clear_recent_timed_schedules(self, event=None):
        self.clear_widget_lists()
        timed_schedules_manager.clear_all_schedules()
        self.filtered_schedules.clear()
        self.add_schedule_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for label in self.label_list:
            label.destroy()
        for btn in self.set_schedule_btn_list:
            btn.destroy()
        for btn in self.modify_schedule_btn_list:
            btn.destroy()
        for btn in self.delete_schedule_btn_list:
            btn.destroy()
        for checkbutton, var, schedule in self.enabled_checkbutton_list:
            checkbutton.destroy()
        self.set_schedule_btn_list = []
        self.modify_schedule_btn_list = []
        self.delete_schedule_btn_list = []
        self.label_list = []
        self.enabled_checkbutton_list = []

    def refresh(self, refresh_list=True):
        self.filtered_schedules = timed_schedules_manager.recent_timed_schedules[:]
        self.clear_widget_lists()
        self.add_schedule_widgets()
        self.master.update()

    def close_windows(self, event=None):
        self.master.destroy()

    def add_label(self, label_ref, text, row=0, column=0, wraplength=500):
        label_ref['text'] = text
        label_ref.grid(column=column, row=row, sticky=W)
        label_ref.config(wraplength=wraplength, justify=LEFT, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

    def add_btn(self, button_ref_name, text, command, row=0, column=0):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.frame, text=text, command=command)
            setattr(self, button_ref_name, button)
            button # for some reason this is necessary to maintain the reference?
            button.grid(row=row, column=column)
