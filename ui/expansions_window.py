import os

from tkinter import Toplevel, Frame, Label, StringVar, LEFT, W
import tkinter.font as fnt
from tkinter.ttk import Entry, Button

from ui.app_style import AppStyle
from ui.expansion import Expansion
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._



class ExpansionModifyWindow():
    top_level = None
    COL_0_WIDTH = 600

    def __init__(self, master, refresh_callback, expansion, dimensions="600x600"):
        ExpansionModifyWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        ExpansionModifyWindow.top_level.geometry(dimensions)
        self.master = ExpansionModifyWindow.top_level
        self.refresh_callback = refresh_callback
        self.expansion = expansion if expansion is not None else Expansion("", "")
        ExpansionModifyWindow.top_level.title(_("Modify Expansion: {0}").format(self.expansion.id))

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Expansion ID"), row=0, wraplength=ExpansionModifyWindow.COL_0_WIDTH)

        self.new_expansion_name = StringVar(self.master, value="NewExp"if expansion is None else expansion.id)
        self.new_expansion_name_entry = Entry(self.frame, textvariable=self.new_expansion_name, width=50, font=fnt.Font(size=8))
        self.new_expansion_name_entry.grid(column=0, row=1, sticky="w")

        self._label_text = Label(self.frame)
        self.add_label(self._label_text, _("Expansion Text"), row=2, wraplength=ExpansionModifyWindow.COL_0_WIDTH)

        self.new_expansion_text = StringVar(self.master, value=_("New Expansion Text") if expansion is None else expansion.text)
        self.new_expansion_text_entry = Entry(self.frame, textvariable=self.new_expansion_text, width=50, font=fnt.Font(size=8))
        self.new_expansion_text_entry.grid(column=0, row=3, sticky="w")

        self.add_expansion_btn = None
        self.add_btn("add_expansion_btn", _("Done"), self.finalize_expansion, row=4, column=0)

        self.master.update()

    def finalize_expansion(self, event=None):
        self.expansion.id = self.new_expansion_name.get()
        self.expansion.text = self.new_expansion_text.get()
        self.close_windows()
        self.refresh_callback(self.expansion)

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




class ExpansionsWindow():
    expansion_modify_window = None
    last_set_expansion = None
    expansion_history = []
    MAX_EXPANSIONS = 50

    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_expansions():
        for expansion_dict in list(app_info_cache.get("expansions", default_val=[])):
            Expansion.expansions.append(Expansion.from_dict(expansion_dict))

    @staticmethod
    def store_expansions():
        expansion_dicts = []
        for expansion in Expansion.expansions:
            expansion_dicts.append(expansion.to_dict())
        app_info_cache.set("expansions", expansion_dicts)

    @staticmethod
    def get_expansion_names():
        return sorted(list(map(lambda x: x.name, Expansion.expansions)))

    @staticmethod
    def get_most_recent_expansion_name():
        Expansion.expansions[0] if len(Expansion.expansions) > 0 else _("New Expansion (ERROR no expansions found)")

    @staticmethod
    def get_history_expansion(start_index=0):
        # Get a previous expansion.
        expansion = None
        for i in range(len(ExpansionsWindow.expansion_history)):
            if i < start_index:
                continue
            expansion = ExpansionsWindow.expansion_history[i]
            break
        return expansion

    @staticmethod
    def update_history(expansion):
        if len(ExpansionsWindow.expansion_history) > 0 and \
                expansion == ExpansionsWindow.expansion_history[0]:
            return
        ExpansionsWindow.expansion_history.insert(0, expansion)
        if len(ExpansionsWindow.expansion_history) > ExpansionsWindow.MAX_EXPANSIONS:
            del ExpansionsWindow.expansion_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 700
        height = 400
        return f"{width}x{height}"

    @staticmethod
    def next_expansion(alert_callback):
        if len(Expansion.expansions) == 0:
            alert_callback(_("Not enough expansions found."))
        next_expansion = Expansion.expansions[-1]
        Expansion.expansions.remove(next_expansion)
        Expansion.expansions.insert(0, next_expansion)
        return next_expansion

    def __init__(self, master, toast_callback):
        self.master = master
        self.toast_callback = toast_callback
        self.filter_text = ""
        self.filtered_expansions = Expansion.expansions[:]
        self.expansion_id_label_list = []
        self.expansion_text_label_list = []
        self.set_expansion_btn_list = []
        self.delete_expansion_btn_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_expansion_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Add or update expansions"), row=0, wraplength=ExpansionsWindow.COL_0_WIDTH)
        self.add_expansion_btn = None
        self.add_btn("add_expansion_btn", _("Add expansion"), self.add_empty_expansion, column=1)
        self.clear_expansions_btn = None
        self.add_btn("clear_expansions_btn", _("Clear expansions"), self.clear_expansions, column=2)
        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_expansions)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_expansion_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_expansions)):
            row = i+1
            expansion = self.filtered_expansions[i]

            id_label = Label(self.frame)
            self.expansion_id_label_list.append(id_label)
            self.add_label(id_label, str(expansion.id), row=row, column=base_col, wraplength=ExpansionsWindow.COL_0_WIDTH)

            text_label = Label(self.frame)
            self.expansion_text_label_list.append(text_label)
            expansion_text = Utils.get_centrally_truncated_string(expansion.text, 30)
            self.add_label(text_label, expansion_text, row=row, column=base_col+1, wraplength=ExpansionsWindow.COL_0_WIDTH)

            set_expansion_btn = Button(self.frame, text=_("Modify"))
            self.set_expansion_btn_list.append(set_expansion_btn)
            set_expansion_btn.grid(row=row, column=base_col+2)
            def set_expansion_handler(event, self=self, expansion=expansion):
                self.open_expansion_modify_window(expansion=expansion)
            set_expansion_btn.bind("<Button-1>", set_expansion_handler)

            delete_expansion_btn = Button(self.frame, text=_("Delete"))
            self.delete_expansion_btn_list.append(delete_expansion_btn)
            delete_expansion_btn.grid(row=row, column=base_col+3)
            def delete_expansion_handler(event, self=self, expansion=expansion):
                return self.delete_expansion(event, expansion)
            delete_expansion_btn.bind("<Button-1>", delete_expansion_handler)

    def open_expansion_modify_window(self, event=None, expansion=None):
        if ExpansionsWindow.expansion_modify_window is not None:
            ExpansionsWindow.expansion_modify_window.master.destroy()
        ExpansionsWindow.expansion_modify_window = ExpansionModifyWindow(self.master, self.refresh_expansions, expansion)

    def refresh_expansions(self, expansion):
        ExpansionsWindow.update_history(expansion)
        if expansion in Expansion.expansions:
            Expansion.expansions.remove(expansion)
        Expansion.expansions.insert(0, expansion)
        self.filtered_expansions = Expansion.expansions[:]
        self.set_expansion(expansion)

    def add_empty_expansion(self, event=None):
        Expansion.expansions.insert(0, Expansion("", ""))
        self.refresh()

    def get_expansion(self, expansion=None, id="", text="", toast_callback=None):
        was_valid = False
        if expansion is None:
            expansion = Expansion(id, text)
        else:
            was_valid = True
        expansion.id = id
        expansion.text = text
        if expansion.is_valid():
            return expansion, was_valid
        assert toast_callback is not None
        text = _("Invalid expansion ID \"{0}\" or text \"{1}\"").format(id, text)
        toast_callback(text)
        raise Exception(text)


    def handle_expansion(self, event=None, expansion=None, id="", text=""):
        """
        Have to call this when user is setting a new expansion as well, in which case expansion will be None.

        In this case we will need to add the new expansion to the list of valid expansions.

        Also in this case, this function will call itself by calling set_expansion(),
        just this time with the directory set.
        """
        expansion, was_valid = self.get_expansion(expansion, id, text, self.toast_callback)
        if was_valid and expansion is not None:
            if expansion in Expansion.expansions:
                Expansion.expansions.remove(expansion)
            Expansion.expansions.insert(0, expansion)
            return expansion

        # NOTE don't want to sort here, instead keep the most recent expansions at the top
        if expansion in Expansion.expansions:
            Expansion.expansions.remove(expansion)
        Expansion.expansions.insert(0, expansion)
        self.set_expansion(expansion=expansion)

    def set_expansion(self, event=None, expansion=None, id="", text=""):
        expansion = self.handle_expansion(expansion=expansion)
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        ExpansionsWindow.update_history(expansion)
        ExpansionsWindow.last_set_expansion = expansion
        self.refresh()
#        self.close_windows()

    def delete_expansion(self, event=None, expansion=None):
        if expansion is not None and expansion in Expansion.expansions:
            Expansion.expansions.remove(expansion)
        self.refresh()

    def filter_expansions(self, event):
        """
        Rebuild the filtered expansions list based on the filter string and update the UI.
        """
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    self.filtered_expansions = self.filtered_expansions[1:] + [self.filtered_expansions[0]]
                else:  # keysym == "Up"
                    self.filtered_expansions = [self.filtered_expansions[-1]] + self.filtered_expansions[:-1]
                self.clear_widget_lists()
                self.add_expansion_widgets()
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
            self.filtered_expansions.clear()
            self.filtered_expansions = Expansion.expansions[:]
        else:
            temp = []
            return # TODO
            for expansion in Expansion.expansions:
                if expansion not in temp:
                    if expansion and (f" {self.filter_text}" in expansion.lower() or f"_{self.filter_text}" in expansion.lower()):
                        temp.append(expansion)
            self.filtered_expansions = temp[:]

        self.refresh()


    def do_action(self, event=None):
        """
        The user has requested to set a expansion. Based on the context, figure out what to do.

        If no expansions exist, call handle_expansion() with expansion=None to set a new expansion.

        If expansions exist, call set_expansion() to set the first expansion.

        If control key pressed, ignore existing and add a new expansion.

        If alt key pressed, use the penultimate expansion.

        The idea is the user can filter the directories using keypresses, then press enter to
        do the action on the first filtered tag.
        """
#        shift_key_pressed = (event.state & 0x1) != 0
        control_key_pressed = (event.state & 0x4) != 0
        alt_key_pressed = (event.state & 0x20000) != 0
        if alt_key_pressed:
            penultimate_expansion = ExpansionsWindow.get_history_expansion(start_index=1)
            if penultimate_expansion is not None and os.path.isdir(penultimate_expansion):
                self.set_expansion(expansion=penultimate_expansion)
        elif len(self.filtered_expansions) == 0 or control_key_pressed:
            self.handle_expansion()
        else:
            if len(self.filtered_expansions) == 1 or self.filter_text.strip() != "":
                expansion = self.filtered_expansions[0]
            else:
                expansion = ExpansionsWindow.last_set_expansion
            self.set_expansion(expansion=expansion)

    def clear_expansions(self, event=None):
        self.clear_widget_lists()
        Expansion.expansions.clear()
        self.filtered_expansions.clear()
        self.add_expansion_widgets()
        self.master.update()

    def clear_widget_lists(self):
        for label in self.expansion_id_label_list:
            label.destroy()
        for label in self.expansion_text_label_list:
            label.destroy()        
        for btn in self.set_expansion_btn_list:
            btn.destroy()
        for btn in self.delete_expansion_btn_list:
            btn.destroy()
        self.expansion_id_label_list = []
        self.expansion_text_label_list = []
        self.set_expansion_btn_list = []
        self.delete_expansion_btn_list = []

    def refresh(self, refresh_list=True):
        self.filtered_expansions = Expansion.expansions[:]
        self.clear_widget_lists()
        self.add_expansion_widgets()
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
