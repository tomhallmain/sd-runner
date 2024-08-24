
from tkinter import Entry, Frame, Label, StringVar, filedialog, messagebox, LEFT, W
import tkinter.font as fnt
from tkinter.ttk import Button

from sd_runner.concepts import Concepts
from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N

_ = I18N._

class ConceptEditorWindow():
    last_set_concept = None
    concept_change_history = []
    MAX_CONCEPTS = 50
    MAX_HEIGHT = 900
    N_CONCEPTS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_blacklist():
        ConceptEditorWindow.concept_change_history = app_info_cache.get("concept_changes", default_val=[])

    @staticmethod
    def store_concept_changes():
        app_info_cache.set("concept_changes", ConceptEditorWindow.concept_change_history)

    @staticmethod
    def get_history_concept_change(start_index=0):
        # Get a previous concept.
        concept = None
        for i in range(len(ConceptEditorWindow.concept_change_history)):
            if i < start_index:
                continue
            concept = ConceptEditorWindow.concept_change_history[i]
            break
        return concept

    @staticmethod
    def update_history(tag):
        if len(ConceptEditorWindow.concept_change_history) > 0 and \
                tag == ConceptEditorWindow.concept_change_history[0]:
            return
        ConceptEditorWindow.concept_change_history.insert(0, tag)
        if len(ConceptEditorWindow.concept_change_history) > ConceptEditorWindow.MAX_CONCEPTS:
            del ConceptEditorWindow.concept_change_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 500
        height = 800
        return f"{width}x{height}"

    def __init__(self, master, toast_callback):
        self.master = master
        self.toast = toast_callback
        self.base_tag = ""
        self.filter_text = ""
        self.filtered_tags = Concepts.TAG_BLACKLIST[:]
        self.remove_tag_btn_list = []
        self.label_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_concept_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, "Add to concepts", row=0, wraplength=ConceptEditorWindow.COL_0_WIDTH)
        self.add_concept_btn = None
        self.add_btn("add_concept_btn", "Add concept", self.handle_concept, column=1)
        self.concept_var = StringVar(self.master)
        self.concept_entry = self.new_entry(self.concept_var)
        self.concept_entry.grid(row=0, column=2)
        # self.clear_blacklist_btn = None
        # self.add_btn("clear_blacklist_btn", "Clear tags", self.clear_tags, column=3)
        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_tags)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_concept_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_tags)):
            row = i+1
            tag = self.filtered_tags[i]
            self._label_info = Label(self.frame)
            self.label_list.append(self._label_info)
            self.add_label(self._label_info, str(tag), row=row, column=base_col, wraplength=ConceptEditorWindow.COL_0_WIDTH)
            remove_tag_btn = Button(self.frame, text=_("Remove"))
            self.remove_tag_btn_list.append(remove_tag_btn)
            remove_tag_btn.grid(row=row, column=base_col+1)
            def remove_tag_handler(event, self=self, tag=tag):
                return self.remove_tag(event, tag)
            remove_tag_btn.bind("<Button-1>", remove_tag_handler)

    def get_concept(self, tag):
        """
        Add or remove a concept from files
        """
        if tag is not None:
            Concepts.remove_from_blacklist(tag)
            self.refresh()
            self.toast(_("Removed tag: {0}").format(tag))
            return None
        tag = self.concept_var.get()
        return tag

    def handle_concept(self, event=None, concept=None):
        concept = self.get_concept(concept)
        if concept is None:
            return
        if concept.strip() == "":
            self.close_windows()
            raise Exception("Failed to set tag for blacklist.")

        Concepts.add_to_blacklist(concept)
        self.refresh()
        self.toast(_("Added tag to blacklist: {0}").format(concept))
        return concept

    def remove_tag(self, event=None, tag=None):
        tag = self.handle_concept(concept=tag)
        if tag is None:
            return
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        ConceptEditorWindow.update_history(tag)
        ConceptEditorWindow.last_set_concept = tag
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
                self.add_concept_widgets()
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
            self.filtered_tags = Concepts.TAG_BLACKLIST[:]
        else:
            temp = []
            # First pass try to match directory basename
            for tag in Concepts.TAG_BLACKLIST:
                if tag == self.filter_text:
                    temp.append(tag)
            for tag in Concepts.TAG_BLACKLIST:
                if tag not in temp:
                    if tag.startswith(self.filter_text):
                        temp.append(tag)
            # Third pass try to match part of the basename
            for tag in Concepts.TAG_BLACKLIST:
                if tag not in temp:
                    if tag and (f" {self.filter_text}" in tag.lower() or f"_{self.filter_text}" in tag.lower()):
                        temp.append(tag)
            self.filtered_tags = temp[:]

        self.refresh(refresh_list=False)

    def do_action(self, event=None):
        """
        The user has requested to set a tag.
        If no tags exist, call handle_tag() with tag=None to set a new tag.
        """
        self.handle_concept()

    def clear_tags(self, event=None):
        Concepts.TAG_BLACKLIST.clear()
        self.filtered_tags.clear()
        self.refresh()
        self.toast(_("Cleared tag blacklist"))

    def clear_widget_lists(self):
        for btn in self.remove_tag_btn_list:
            btn.destroy()
        for label in self.label_list:
            label.destroy()
        self.remove_tag_btn_list = []
        self.label_list = []

    def refresh(self, refresh_list=True):
        if refresh_list:
            self.filtered_tags = Concepts.TAG_BLACKLIST[:]
        self.clear_widget_lists()
        self.add_concept_widgets()
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

    def new_entry(self, text_variable, text="", width=30, **kw):
        return Entry(self.frame, text=text, textvariable=text_variable, width=width, font=fnt.Font(size=8), **kw)

