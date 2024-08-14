import os

from tkinter import Frame, Label, filedialog, messagebox, LEFT, W
from tkinter.ttk import Button

from utils.app_info_cache import app_info_cache
from utils.config import config


class Preset:
    def __init__(self) -> None:
        pass

    def is_valid(self):
        return True

class Presets:
    presets = []

    @staticmethod
    def set_presets(presets):
        Presets.presets = list(presets)


class PresetsWindow():
    recent_directories = []
    last_set_preset = None

    preset_history = []
    MAX_PRESETS = 50

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_recent_directories(recent_directories):
        Presets.presets = recent_directories

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
        width = 300
        height = 100
        return f"{width}x{height}"

    def __init__(self, master, app_master, app_actions, base_dir=".", run_compare_image=None):
        self.master = master
#        self.app_master = master
        self.run_compare_image = run_compare_image
        self.app_actions = app_actions
        self.base_dir = os.path.normpath(base_dir)
        self.filter_text = ""
        self.starting_target = None

        # Use the last set target directory as a base if any directories have been set
        if len(Presets.presets) > 0 and Presets.presets[0].is_valid():
            self.starting_target = Presets.presets[0]

        self.filtered_prompt_tags = Presets.presets[:]
        self.add_tag_btn_list = []
        self.label_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_preset_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, "Set a new preset", row=0, wraplength=PresetsWindow.COL_0_WIDTH)
        self.add_preset_btn = None
        self.add_btn("add_preset_btn", "Add preset", self.handle_preset, column=1)
        self.clear_recent_presets_btn = None
        self.add_btn("clear_recent_presets_btn", "Clear presets", self.clear_recent_directories, column=3)
        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_presets)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_preset_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_prompt_tags)):
            if i >= PresetsWindow.N_TAGS_CUTOFF * 2:
                row = i-PresetsWindow.N_TAGS_CUTOFF*2+1
                base_col = 4
            elif i >= PresetsWindow.N_TAGS_CUTOFF:
                row = i-PresetsWindow.N_TAGS_CUTOFF+1
                base_col = 2
            else:
                row = i+1
            _dir = self.filtered_prompt_tags[i]
            self._label_info = Label(self.frame)
            self.label_list.append(self._label_info)
            self.add_label(self._label_info, _dir, row=row, column=base_col, wraplength=PresetsWindow.COL_0_WIDTH)
            add_tag_btn = Button(self.frame, text="Set")
            self.add_tag_btn_list.append(add_tag_btn)
            add_tag_btn.grid(row=row, column=base_col+1)
            def set_dir_handler(event, self=self, _dir=_dir):
                return self.set_preset(event, _dir)
            add_tag_btn.bind("<Button-1>", set_dir_handler)

    @staticmethod
    def get_preset(preset, toast_callback):
        """
        Add a new preset
        """
        if preset:
            if preset.is_valid():
                return preset, True
            else:
                if preset in Presets.presets:
                    Presets.presets.remove(preset)
                toast_callback(_("Invalid preset: %s").format(preset))
        preset = Preset()
        return preset, False


    def handle_preset(self, event=None, preset=None):
        """
        Have to call this when user is setting a new preset as well, in which case preset will be None.
        
        In this case we will need to add the new preset to the list of valid presets.
        
        Also in this case, this function will call itself by calling set_preset(),
        just this time with the directory set.
        """
        preset, was_valid = PresetsWindow.get_preset(preset, self.app_actions.toast)
        if not os.path.isdir(preset):
            self.close_windows()
            raise Exception("Failed to set target directory to receive marked files.")
        if was_valid and preset is not None:
            if preset in Presets.presets:
                Presets.presets.remove(preset)
            Presets.presets.insert(0, preset)
            return preset

        preset = os.path.normpath(preset)
        # NOTE don't want to sort here, instead keep the most recent presets at the top
        if preset in Presets.presets:
            Presets.presets.remove(preset)
        Presets.presets.insert(0, preset)
        self.set_preset(preset=preset)

    def set_preset(self, event=None, preset=None):
        preset = self.handle_preset(preset=preset)
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        PresetsWindow.update_history(preset)
        PresetsWindow.last_set_preset = preset
        self.close_windows()

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
                    self.filtered_prompt_tags = self.filtered_prompt_tags[1:] + [self.filtered_prompt_tags[0]]
                else:  # keysym == "Up"
                    self.filtered_prompt_tags = [self.filtered_prompt_tags[-1]] + self.filtered_prompt_tags[:-1]
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
            self.filtered_prompt_tags.clear()
            self.filtered_prompt_tags = Presets.presets[:]
        else:
            temp = []
            # First pass try to match directory basename
            for preset in Presets.presets:
                if preset == self.filter_text:
                    temp.append(preset)
            for preset in Presets.presets:
                if not preset in temp:
                    if preset.startswith(self.filter_text):
                        temp.append(preset)
            # Third pass try to match part of the basename
            for preset in Presets.presets:
                if not preset in temp:
                    if preset and (f" {self.filter_text}" in preset.lower() or f"_{self.filter_text}" in preset.lower()):
                        temp.append(preset)
            self.filtered_prompt_tags = temp[:]

        self.clear_widget_lists()
        self.add_preset_widgets()
        self.master.update()


    def do_action(self, event=None):
        """
        The user has requested to set a preset. Based on the context, figure out what to do.

        If no presets exist, call handle_preset() with _dir=None to set a new preset.

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
        elif len(self.filtered_prompt_tags) == 0 or control_key_pressed:
            self.handle_preset()
        else:
            if len(self.filtered_prompt_tags) == 1 or self.filter_text.strip() != "":
                _dir = self.filtered_prompt_tags[0]
            else:
                _dir = PresetsWindow.last_set_preset
            self.set_preset(preset=_dir)

    def clear_recent_directories(self, event=None):
        self.clear_widget_lists()
        Presets.presets.clear()
        self.filtered_prompt_tags.clear()
        self.add_preset_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for btn in self.add_tag_btn_list:
            btn.destroy()
        for label in self.label_list:
            label.destroy()
        self.add_tag_btn_list = []
        self.label_list = []

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

