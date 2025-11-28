import os

from tkinter import Frame, Label, OptionMenu, StringVar, LEFT, W
import tkinter.font as fnt
from tkinter.ttk import Entry, Button

from lib.multi_display import SmartToplevel
from ui.app_style import AppStyle
from ui.presets_window import PresetsWindow
from ui.schedule import PresetTask, Schedule
from ui.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.app_info_cache import app_info_cache
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

_ = I18N._


class ScheduleModifyWindow():
    top_level = None
    COL_0_WIDTH = 600

    def __init__(self, master, refresh_callback, schedule, dimensions="600x600"):
        self.schedule = schedule if schedule is not None else Schedule()
        ScheduleModifyWindow.top_level = SmartToplevel(persistent_parent=master,
                                                      title=_("Modify Preset Schedule: {0}").format(self.schedule.name),
                                                      geometry=dimensions)
        self.master = ScheduleModifyWindow.top_level
        self.refresh_callback = refresh_callback

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)
        self.frame.columnconfigure(4, weight=1)

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Modify Schedule"), row=0, wraplength=ScheduleModifyWindow.COL_0_WIDTH)

        self.new_schedule_name = StringVar(self.master, value=_("New Schedule") if schedule is None else schedule.name)
        self.new_schedule_name_entry = Entry(self.frame, textvariable=self.new_schedule_name, width=50, font=fnt.Font(size=8))
        self.new_schedule_name_entry.grid(column=1, row=0, sticky="w")

        self.add_schedule_btn = None
        self.add_btn("add_schedule_btn", _("Add schedule"), self.finalize_schedule, column=2)

        self.add_preset_task_btn = None
        self.add_btn("add_preset_task_btn", _("Add Preset Task"), self.add_preset_task, column=3)

        self.name_var_list = []
        self.name_widget_list = []
        self.count_var_list = []
        self.count_widget_list = []
        self.delete_task_btn_list = []
        self.move_down_btn_list = []

        self.add_widgets()
        self.master.update()

    def add_widgets(self):
        row = 0
        base_col = 0
        preset_options = PresetsWindow.get_preset_names() # TODO handling for no preset set case

        for i in range(len(self.schedule.schedule)):
            row = i+1
            preset_task = self.schedule.schedule[i]

            name_var = StringVar(self.master, value=preset_task.name)
            self.name_var_list.append(name_var)
            preset_count_var = StringVar(self.master, value=str(preset_task.count_runs))
            self.count_var_list.append(preset_count_var)

            def set_task(event, self=self, name_var=name_var, preset_count_var=preset_count_var, idx=i):
                self.schedule.set_preset_task(idx, name_var.get(), preset_count_var.get())
                self.refresh()

            preset_choice = OptionMenu(self.frame, name_var, preset_task.name, *preset_options, command=set_task)
            preset_choice.grid(row=row, column=base_col+1, sticky=W)
            self.name_widget_list.append(preset_choice)

            count_options = [str(i) for i in list(range(101))]
            count_options.insert(0, "-1")
            count_choice = OptionMenu(self.frame, preset_count_var, str(preset_task.count_runs), *count_options, command=set_task)
            count_choice.grid(row=row, column=base_col+2, sticky=W)
            self.count_widget_list.append(count_choice)

            delete_task_btn = Button(self.frame, text=_("Delete"))
            self.delete_task_btn_list.append(delete_task_btn)
            delete_task_btn.grid(row=row, column=base_col+3)
            def delete_task_handler(event, self=self, idx=i):
                self._delete_task(idx)
            delete_task_btn.bind("<Button-1>", delete_task_handler)

            move_down_btn = Button(self.frame, text=_("Move Down"))
            self.move_down_btn_list.append(move_down_btn)
            move_down_btn.grid(row=row, column=base_col+4)
            def move_down_handler(event, self=self, idx=i):
                self._move_task_down(idx)
            move_down_btn.bind("<Button-1>", move_down_handler)

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def add_preset_task(self):
        self.schedule.add_preset_task(PresetTask(PresetsWindow.get_most_recent_preset_name(), 1))
        self.refresh()

    def refresh(self):
        self.clear_widget_lists()
        self.add_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for wgt in self.name_widget_list:
            wgt.destroy()
        for wgt in self.count_widget_list:
            wgt.destroy()
        for btn in self.delete_task_btn_list:
            btn.destroy()
        for btn in self.move_down_btn_list:
            btn.destroy()
        self.name_var_list.clear()
        self.count_var_list.clear()
        self.name_widget_list = []
        self.count_widget_list = []
        self.delete_task_btn_list = []
        self.move_down_btn_list = []

    def move_index(self, idx, direction_count=1):
        self.schedule.move_index(idx, direction_count)

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _delete_task(self, idx):
        self.schedule.delete_index(idx)
        self.refresh()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _move_task_down(self, idx):
        self.schedule.move_index(idx, 1)
        self.refresh()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def finalize_schedule(self, event=None):
        self.schedule.name = self.new_schedule_name.get()
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



class SchedulesWindow():
    top_level = None
    schedule_modify_window = None
    current_schedule = Schedule()
    recent_schedules = []
    last_set_schedule = None

    schedule_history = []
    MAX_PRESETS = 50

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_schedules():
        for schedule_dict in list(app_info_cache.get("recent_schedules", default_val=[])):
            SchedulesWindow.recent_schedules.append(Schedule.from_dict(schedule_dict))
        current_schedule_dict = app_info_cache.get("current_schedule", default_val=None)
        if current_schedule_dict is not None:
            SchedulesWindow.current_schedule = Schedule.from_dict(current_schedule_dict)

    @staticmethod
    def store_schedules():
        schedule_dicts = []
        for schedule in SchedulesWindow.recent_schedules:
            schedule_dicts.append(schedule.to_dict())
        app_info_cache.set("recent_schedules", schedule_dicts)
        if SchedulesWindow.current_schedule is not None:
            app_info_cache.set("current_schedule", SchedulesWindow.current_schedule.to_dict())

    @staticmethod
    def get_schedule_by_name(name):
        for schedule in SchedulesWindow.recent_schedules:
            if name == schedule.name:
                return schedule
        raise Exception(f"No schedule found with name: {name}. Set it on the Schedules Window.")

    @staticmethod
    def get_history_schedule(start_index=0):
        # Get a previous schedule.
        schedule = None
        for i in range(len(SchedulesWindow.schedule_history)):
            if i < start_index:
                continue
            schedule = SchedulesWindow.schedule_history[i]
            break
        return schedule

    @staticmethod
    def update_history(schedule):
        if len(SchedulesWindow.schedule_history) > 0 and \
                schedule == SchedulesWindow.schedule_history[0]:
            return
        SchedulesWindow.schedule_history.insert(0, schedule)
        if len(SchedulesWindow.schedule_history) > SchedulesWindow.MAX_PRESETS:
            del SchedulesWindow.schedule_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 700
        height = 400
        return f"{width}x{height}"

    @staticmethod
    def next_schedule(alert_callback):
        if len(SchedulesWindow.recent_schedules) == 0:
            alert_callback(_("Not enough schedules found."))
        next_schedule = SchedulesWindow.recent_schedules[-1]
        SchedulesWindow.recent_schedules.remove(next_schedule)
        SchedulesWindow.recent_schedules.insert(0, next_schedule)
        return next_schedule

    def __init__(self, master, app_actions, runner_app_config=RunnerAppConfig()):
        SchedulesWindow.top_level = SmartToplevel(persistent_parent=master,
                                                title=_("Preset Schedules"),
                                                geometry=SchedulesWindow.get_geometry())
        self.master = SchedulesWindow.top_level
        self.app_actions = app_actions
        self.filter_text = ""
        self.filtered_schedules = SchedulesWindow.recent_schedules[:]
        self.label_list = []
        self.set_schedule_btn_list = []
        self.modify_schedule_btn_list = []
        self.delete_schedule_btn_list = []

        # Configure window grid to allow frame expansion
        self.master.columnconfigure(0, weight=1)
        self.master.rowconfigure(0, weight=1)
        self.master.config(bg=AppStyle.BG_COLOR)
        
        self.frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, self.get_current_schedule_label_text(), row=0, wraplength=SchedulesWindow.COL_0_WIDTH)
        self.add_schedule_btn = None
        self.add_btn("add_schedule_btn", _("Add schedule"), self.open_schedule_modify_window, column=1)
        self.clear_recent_schedules_btn = None
        self.add_btn("clear_recent_schedules_btn", _("Clear schedules"), self.clear_recent_schedules, column=2)

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
            self.add_label(label_name, str(schedule), row=row, column=base_col, wraplength=SchedulesWindow.COL_0_WIDTH)

            set_schedule_btn = Button(self.frame, text=_("Set"))
            self.set_schedule_btn_list.append(set_schedule_btn)
            set_schedule_btn.grid(row=row, column=base_col+1)
            def set_schedule_handler(event, self=self, schedule=schedule):
                return self.set_schedule(event, schedule)
            set_schedule_btn.bind("<Button-1>", set_schedule_handler)

            modify_schedule_btn = Button(self.frame, text=_("Modify"))
            self.set_schedule_btn_list.append(modify_schedule_btn)
            modify_schedule_btn.grid(row=row, column=base_col+2)
            def modify_schedule_handler(event, self=self, schedule=schedule):
                return self.open_schedule_modify_window(event, schedule)
            modify_schedule_btn.bind("<Button-1>", modify_schedule_handler)

            delete_schedule_btn = Button(self.frame, text=_("Delete"))
            self.delete_schedule_btn_list.append(delete_schedule_btn)
            delete_schedule_btn.grid(row=row, column=base_col+3)
            def delete_schedule_handler(event, self=self, schedule=schedule):
                return self.delete_schedule(event, schedule)
            delete_schedule_btn.bind("<Button-1>", delete_schedule_handler)

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def open_schedule_modify_window(self, event=None, schedule=None):
        if SchedulesWindow.schedule_modify_window is not None:
            SchedulesWindow.schedule_modify_window.master.destroy()
        SchedulesWindow.schedule_modify_window = ScheduleModifyWindow(self.master, self.refresh_schedules, schedule)

    def refresh_schedules(self, schedule):
        SchedulesWindow.update_history(schedule)
        if schedule in SchedulesWindow.recent_schedules:
            SchedulesWindow.recent_schedules.remove(schedule)
        SchedulesWindow.recent_schedules.insert(0, schedule)
        self.filtered_schedules = SchedulesWindow.recent_schedules[:]
        self.set_schedule(schedule)

    def get_current_schedule_label_text(self):
        return _("Current schedule: {0}").format(SchedulesWindow.current_schedule)

    def set_schedule(self, event=None, schedule=None):
        SchedulesWindow.current_schedule = schedule
        self._label_info["text"] = self.get_current_schedule_label_text()
        self.app_actions.toast(_("Set schedule: {0}").format(schedule))
        self.refresh()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def delete_schedule(self, event=None, schedule=None):
        if schedule is not None and schedule in SchedulesWindow.recent_schedules:
            SchedulesWindow.recent_schedules.remove(schedule)
            self.app_actions.toast(_("Deleted schedule: {0}").format(schedule))
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
            self.filtered_schedules = SchedulesWindow.recent_schedules[:]
        else:
            temp = []
            return # TODO
            for schedule in SchedulesWindow.recent_schedules:
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
            penultimate_schedule = SchedulesWindow.get_history_schedule(start_index=1)
            if penultimate_schedule is not None and os.path.isdir(penultimate_schedule):
                self.set_schedule(schedule=penultimate_schedule)
        elif len(self.filtered_schedules) == 0 or control_key_pressed:
            self.open_schedule_modify_window()
        else:
            if len(self.filtered_schedules) == 1 or self.filter_text.strip() != "":
                schedule = self.filtered_schedules[0]
            else:
                schedule = SchedulesWindow.last_set_schedule
            self.set_schedule(schedule=schedule)

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def clear_recent_schedules(self, event=None):
        self.clear_widget_lists()
        SchedulesWindow.recent_schedules.clear()
        self.filtered_schedules.clear()
        self.add_schedule_widgets()
        self.master.update()
        self.app_actions.toast(_("Cleared schedules"))

    def clear_widget_lists(self):
        for label in self.label_list:
            label.destroy()
        for btn in self.set_schedule_btn_list:
            btn.destroy()
        for btn in self.modify_schedule_btn_list:
            btn.destroy()
        for btn in self.delete_schedule_btn_list:
            btn.destroy()
        self.set_schedule_btn_list = []
        self.modify_schedule_btn_list = []
        self.delete_schedule_btn_list = []
        self.label_list = []

    def refresh(self, refresh_list=True):
        self.filtered_schedules = SchedulesWindow.recent_schedules[:]
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
