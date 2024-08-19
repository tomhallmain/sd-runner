import os

from tkinter import Frame, Label, filedialog, messagebox, LEFT, W
from tkinter.ttk import Button

from utils.app_info_cache import app_info_cache
from utils.config import config


class Blacklist:
    ls = []

    @staticmethod
    def set_blacklist(blacklist):
        Blacklist.ls = list(blacklist)


class BlacklistWindow():
    recent_tags = []
    last_set_tag = None

    tag_history = []
    MAX_PRESETS = 50

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_recent_tags(recent_tags):
        Blacklist.ls = recent_tags

    @staticmethod
    def get_history_tag(start_index=0):
        # Get a previous tag.
        tag = None
        for i in range(len(BlacklistWindow.tag_history)):
            if i < start_index:
                continue
            tag = BlacklistWindow.tag_history[i]
            break
        return tag

    @staticmethod
    def update_history(tag):
        if len(BlacklistWindow.tag_history) > 0 and \
                tag == BlacklistWindow.tag_history[0]:
            return
        BlacklistWindow.tag_history.insert(0, tag)
        if len(BlacklistWindow.tag_history) > BlacklistWindow.MAX_PRESETS:
            del BlacklistWindow.tag_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 300
        height = 100
        return f"{width}x{height}"

    def __init__(self, master, app_master, app_actions, run_compare_image=None):
        self.master = master
#        self.app_master = master
        self.run_compare_image = run_compare_image
        self.app_actions = app_actions
        self.base_tag = ""
        self.filter_text = ""
        self.starting_target = None

        # Use the last set target directory as a base if any directories have been set
        if len(Blacklist.ls) > 0:
            self.starting_target = Blacklist.ls[0]

        self.filtered_tags = Blacklist.ls[:]
        self.set_tag_btn_list = []
        self.label_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_blacklist_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, "Add to tag blacklist", row=0, wraplength=BlacklistWindow.COL_0_WIDTH)
        self.add_tag_btn = None
        self.add_btn("add_tag_btn", "Add tag", self.handle_tag, column=1)
        self.clear_blacklist_btn = None
        self.add_btn("clear_blacklist_btn", "Clear tags", self.clear_recent_tags, column=3)
        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_tags)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_blacklist_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_tags)):
            row = i+1
            tag = self.filtered_tags[i]
            self._label_info = Label(self.frame)
            self.label_list.append(self._label_info)
            self.add_label(self._label_info, str(tag), row=row, column=base_col, wraplength=BlacklistWindow.COL_0_WIDTH)
            set_tag_btn = Button(self.frame, text="Set")
            self.set_tag_btn_list.append(set_tag_btn)
            set_tag_btn.grid(row=row, column=base_col+1)
            def set_tag_handler(event, self=self, tag=tag):
                return self.set_tag(event, tag)
            set_tag_btn.bind("<Button-1>", set_tag_handler)

    @staticmethod
    def get_tag(tag, toast_callback):
        """
        Add a new tag
        """
        if tag:
            if tag.is_valid():
                return tag, True
            else:
                if tag in Blacklist.ls:
                    Blacklist.ls.remove(tag)
                toast_callback(_("Invalid tag: %s").format(tag))
        tag = "" #TODO:  Add tag validation
        return tag, False


    def handle_tag(self, event=None, tag=None):
        """
        Have to call this when user is setting a new tag as well, in which case tag will be None.

        In this case we will need to add the new tag to the list of valid tags.

        Also in this case, this function will call itself by calling set_tag(),
        just this time with the directory set.
        """
        tag, was_valid = BlacklistWindow.get_tag(tag, self.app_actions.toast)
        if not os.path.isdir(tag):
            self.close_windows()
            raise Exception("Failed to set target directory to receive marked files.")
        if was_valid and tag is not None:
            if tag in Blacklist.ls:
                Blacklist.ls.remove(tag)
            Blacklist.ls.insert(0, tag)
            return tag

        tag = os.path.normpath(tag)
        # NOTE don't want to sort here, instead keep the most recent tags at the top
        if tag in Blacklist.ls:
            Blacklist.ls.remove(tag)
        Blacklist.ls.insert(0, tag)
        self.set_tag(tag=tag)

    def set_tag(self, event=None, tag=None):
        tag = self.handle_tag(tag=tag)
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        BlacklistWindow.update_history(tag)
        BlacklistWindow.last_set_tag = tag
        self.close_windows()

    def filter_tags(self, event):
        """
        Rebuild the filtered tags list based on the filter string and update the UI.
        """
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    self.filtered_tags = self.filtered_tags[1:] + [self.filtered_tags[0]]
                else:  # keysym == "Up"
                    self.filtered_tags = [self.filtered_tags[-1]] + self.filtered_tags[:-1]
                self.clear_widget_lists()
                self.add_blacklist_widgets()
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
            self.filtered_tags.clear()
            self.filtered_tags = Blacklist.ls[:]
        else:
            temp = []
            # First pass try to match directory basename
            for tag in Blacklist.ls:
                if tag == self.filter_text:
                    temp.append(tag)
            for tag in Blacklist.ls:
                if tag not in temp:
                    if tag.startswith(self.filter_text):
                        temp.append(tag)
            # Third pass try to match part of the basename
            for tag in Blacklist.ls:
                if tag not in temp:
                    if tag and (f" {self.filter_text}" in tag.lower() or f"_{self.filter_text}" in tag.lower()):
                        temp.append(tag)
            self.filtered_tags = temp[:]

        self.clear_widget_lists()
        self.add_blacklist_widgets()
        self.master.update()


    def do_action(self, event=None):
        """
        The user has requested to set a tag. Based on the context, figure out what to do.

        If no tags exist, call handle_tag() with tag=None to set a new tag.

        If tags exist, call set_tag() to set the first tag.

        If control key pressed, ignore existing and add a new tag.

        If alt key pressed, use the penultimate tag.

        The idea is the user can filter the directories using keypresses, then press enter to
        do the action on the first filtered tag.
        """
#        shift_key_pressed = (event.state & 0x1) != 0
        control_key_pressed = (event.state & 0x4) != 0
        alt_key_pressed = (event.state & 0x20000) != 0
        if alt_key_pressed:
            penultimate_tag = BlacklistWindow.get_history_tag(start_index=1)
            if penultimate_tag is not None and os.path.isdir(penultimate_tag):
                self.set_tag(tag=penultimate_tag)
        elif len(self.filtered_tags) == 0 or control_key_pressed:
            self.handle_tag()
        else:
            if len(self.filtered_tags) == 1 or self.filter_text.strip() != "":
                tag = self.filtered_tags[0]
            else:
                tag = BlacklistWindow.last_set_tag
            self.set_tag(tag=tag)

    def clear_recent_tags(self, event=None):
        self.clear_widget_lists()
        Blacklist.ls.clear()
        self.filtered_tags.clear()
        self.add_blacklist_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for btn in self.set_tag_btn_list:
            btn.destroy()
        for label in self.label_list:
            label.destroy()
        self.set_tag_btn_list = []
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
