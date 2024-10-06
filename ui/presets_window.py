import os

from tkinter import Frame, Label, StringVar, LEFT, W
import tkinter.font as fnt
from tkinter.ttk import Entry, Button

from ui.app_style import AppStyle
from ui.preset import Preset
from utils.app_info_cache import app_info_cache
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

_ = I18N._


class PresetsWindow():
    recent_presets = []
    last_set_preset = None

    preset_history = []
    MAX_PRESETS = 50

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_recent_presets():
        for preset_dict in list(app_info_cache.get("recent_presets", default_val=[])):
            PresetsWindow.recent_presets.append(Preset.from_dict(preset_dict))

    @staticmethod
    def store_recent_presets():
        preset_dicts = []
        for preset in PresetsWindow.recent_presets:
            preset_dicts.append(preset.to_dict())
        app_info_cache.set("recent_presets", preset_dicts)

    @staticmethod
    def get_preset_by_name(name):
        for preset in PresetsWindow.recent_presets:
            if name == preset.name:
                return preset
        raise Exception(f"No preset found with name: {name}. Set it on the Presets Window.")

    @staticmethod
    def get_preset_names():
        return sorted(list(map(lambda x: x.name, PresetsWindow.recent_presets)))

    @staticmethod
    def get_most_recent_preset_name():
        PresetsWindow.recent_presets[0] if len(PresetsWindow.recent_presets) > 0 else _("New Preset (ERROR no presets found)")

    @staticmethod
    def get_history_preset(start_index=0):
        # Get a previous preset.
        preset = None
        for i in range(len(PresetsWindow.preset_history)):
            if i < start_index:
                continue
            preset = PresetsWindow.preset_history[i]
            break
        return preset

    @staticmethod
    def update_history(preset):
        if len(PresetsWindow.preset_history) > 0 and \
                preset == PresetsWindow.preset_history[0]:
            return
        PresetsWindow.preset_history.insert(0, preset)
        if len(PresetsWindow.preset_history) > PresetsWindow.MAX_PRESETS:
            del PresetsWindow.preset_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 700
        height = 400
        return f"{width}x{height}"

    @staticmethod
    def next_preset(alert_callback):
        if len(PresetsWindow.recent_presets) == 0:
            alert_callback(_("Not enough presets found."))
        next_preset = PresetsWindow.recent_presets[-1]
        PresetsWindow.recent_presets.remove(next_preset)
        PresetsWindow.recent_presets.insert(0, next_preset)
        return next_preset

    def __init__(self, master, toast_callback, construct_preset_callback,
                 set_widgets_from_preset_callback, runner_app_config=RunnerAppConfig()):
        self.master = master
        self.toast_callback = toast_callback
        self.construct_preset_callback = construct_preset_callback
        self.set_widgets_from_preset_callback = set_widgets_from_preset_callback
        self.filter_text = ""
        self.filtered_presets = PresetsWindow.recent_presets[:]
        self.set_preset_btn_list = []
        self.delete_preset_btn_list = []
        self.label_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_preset_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Set a new preset"), row=0, wraplength=PresetsWindow.COL_0_WIDTH)
        self.new_preset_name = StringVar(self.master, value=_("New Preset"))
        self.new_preset_name_entry = Entry(self.frame, textvariable=self.new_preset_name, width=50, font=fnt.Font(size=8))
        self.new_preset_name_entry.grid(column=1, row=0, sticky="w")
        self.add_preset_btn = None
        self.add_btn("add_preset_btn", _("Add preset"), self.handle_preset, column=2)
        self.clear_recent_presets_btn = None
        self.add_btn("clear_recent_presets_btn", _("Clear presets"), self.clear_recent_presets, column=3)
        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_presets)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_preset_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_presets)):
            row = i+1
            preset = self.filtered_presets[i]
            _label_info = Label(self.frame)
            self.label_list.append(_label_info)
            self.add_label(_label_info, str(preset), row=row, column=base_col, wraplength=PresetsWindow.COL_0_WIDTH)

            set_preset_btn = Button(self.frame, text=_("Set"))
            self.set_preset_btn_list.append(set_preset_btn)
            set_preset_btn.grid(row=row, column=base_col+1)
            def set_preset_handler(event, self=self, preset=preset):
                return self.set_preset(event, preset)
            set_preset_btn.bind("<Button-1>", set_preset_handler)

            delete_preset_btn = Button(self.frame, text=_("Delete"))
            self.delete_preset_btn_list.append(delete_preset_btn)
            delete_preset_btn.grid(row=row, column=base_col+2)
            def delete_preset_handler(event, self=self, preset=preset):
                return self.delete_preset(event, preset)
            delete_preset_btn.bind("<Button-1>", delete_preset_handler)

    def get_preset(self, preset, toast_callback):
        """
        Add a new preset
        """
        if preset:
            if preset.is_valid():
                return preset, True
            else:
                if preset in PresetsWindow.recent_presets:
                    PresetsWindow.recent_presets.remove(preset)
                toast_callback(_("Invalid preset: {0}").format(preset))
        return self.construct_preset_callback(self.new_preset_name.get()), False

    def handle_preset(self, event=None, preset=None):
        """
        Have to call this when user is setting a new preset as well, in which case preset will be None.

        In this case we will need to add the new preset to the list of valid presets.

        Also in this case, this function will call itself by calling set_preset(),
        just this time with the directory set.
        """
        preset, was_valid = self.get_preset(preset, self.toast_callback)
        if was_valid and preset is not None:
            if preset in PresetsWindow.recent_presets:
                PresetsWindow.recent_presets.remove(preset)
            PresetsWindow.recent_presets.insert(0, preset)
            return preset

        # NOTE don't want to sort here, instead keep the most recent presets at the top
        if preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        PresetsWindow.recent_presets.insert(0, preset)
        self.set_preset(preset=preset)

    def set_preset(self, event=None, preset=None):
        preset = self.handle_preset(preset=preset)
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        PresetsWindow.update_history(preset)
        PresetsWindow.last_set_preset = preset
        self.set_widgets_from_preset_callback(preset)
        self.refresh()
#        self.close_windows()

    def delete_preset(self, event=None, preset=None):
        if preset is not None and preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        self.refresh()

    def filter_presets(self, event):
        """
        Rebuild the filtered presets list based on the filter string and update the UI.
        """
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    self.filtered_presets = self.filtered_presets[1:] + [self.filtered_presets[0]]
                else:  # keysym == "Up"
                    self.filtered_presets = [self.filtered_presets[-1]] + self.filtered_presets[:-1]
                self.clear_widget_lists()
                self.add_preset_widgets()
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
            self.filtered_presets.clear()
            self.filtered_presets = PresetsWindow.recent_presets[:]
        else:
            temp = []
            return # TODO
            for preset in PresetsWindow.recent_presets:
                if preset not in temp:
                    if preset and (f" {self.filter_text}" in preset.lower() or f"_{self.filter_text}" in preset.lower()):
                        temp.append(preset)
            self.filtered_presets = temp[:]

        self.refresh()


    def do_action(self, event=None):
        """
        The user has requested to set a preset. Based on the context, figure out what to do.

        If no presets exist, call handle_preset() with preset=None to set a new preset.

        If presets exist, call set_preset() to set the first preset.

        If control key pressed, ignore existing and add a new preset.

        If alt key pressed, use the penultimate preset.

        The idea is the user can filter the directories using keypresses, then press enter to
        do the action on the first filtered tag.
        """
#        shift_key_pressed = (event.state & 0x1) != 0
        control_key_pressed = (event.state & 0x4) != 0
        alt_key_pressed = (event.state & 0x20000) != 0
        if alt_key_pressed:
            penultimate_preset = PresetsWindow.get_history_preset(start_index=1)
            if penultimate_preset is not None and os.path.isdir(penultimate_preset):
                self.set_preset(preset=penultimate_preset)
        elif len(self.filtered_presets) == 0 or control_key_pressed:
            self.handle_preset()
        else:
            if len(self.filtered_presets) == 1 or self.filter_text.strip() != "":
                preset = self.filtered_presets[0]
            else:
                preset = PresetsWindow.last_set_preset
            self.set_preset(preset=preset)

    def clear_recent_presets(self, event=None):
        self.clear_widget_lists()
        PresetsWindow.recent_presets.clear()
        self.filtered_presets.clear()
        self.add_preset_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for label in self.label_list:
            label.destroy()
        for btn in self.set_preset_btn_list:
            btn.destroy()
        for btn in self.delete_preset_btn_list:
            btn.destroy()
        self.set_preset_btn_list = []
        self.delete_preset_btn_list = []
        self.label_list = []

    def refresh(self, refresh_list=True):
        self.filtered_presets = PresetsWindow.recent_presets[:]
        self.clear_widget_lists()
        self.add_preset_widgets()
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
