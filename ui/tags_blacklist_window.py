from tkinter import Toplevel, Entry, Frame, Label, StringVar, filedialog, LEFT, W, BooleanVar, Checkbutton
import tkinter.font as fnt
from tkinter.ttk import Button

from sd_runner.blacklist import BlacklistItem, Blacklist
from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N
from lib.aware_entry import AwareEntry

_ = I18N._


class BlacklistWindow():
    top_level = None
    recent_items = []
    last_set_item = None

    item_history = []
    MAX_ITEMS = 50

    MAX_HEIGHT = 900
    N_ITEMS_CUTOFF = 30
    COL_0_WIDTH = 600

    @staticmethod
    def set_blacklist():
        """Load blacklist from cache and validate items."""
        raw_blacklist = app_info_cache.get("tag_blacklist", default_val=[])
        validated_blacklist = []
        
        # Convert each item to a BlacklistItem
        for item in raw_blacklist:
            if isinstance(item, dict):
                blacklist_item = BlacklistItem.from_dict(item)
                if blacklist_item:
                    validated_blacklist.append(blacklist_item)
            elif isinstance(item, str):
                validated_blacklist.append(BlacklistItem(item))
            elif isinstance(item, BlacklistItem):
                validated_blacklist.append(item)
            else:
                print(f"Invalid blacklist item type: {type(item)}")
                
        Blacklist.set_blacklist(validated_blacklist)

    @staticmethod
    def store_blacklist():
        """Store blacklist to cache, converting items to dictionaries."""
        blacklist_dicts = [item.to_dict() for item in Blacklist.get_items()]
        app_info_cache.set("tag_blacklist", blacklist_dicts)

    @staticmethod
    def get_history_item(start_index=0):
        # Get a previous item.
        item = None
        for i in range(len(BlacklistWindow.item_history)):
            if i < start_index:
                continue
            item = BlacklistWindow.item_history[i]
            break
        return item

    @staticmethod
    def update_history(item):
        if len(BlacklistWindow.item_history) > 0 and \
                item == BlacklistWindow.item_history[0]:
            return
        BlacklistWindow.item_history.insert(0, item)
        if len(BlacklistWindow.item_history) > BlacklistWindow.MAX_ITEMS:
            del BlacklistWindow.item_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 500
        height = 800
        return f"{width}x{height}"

    def __init__(self, master, app_actions):
        BlacklistWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        BlacklistWindow.top_level.title(_("Tags Blacklist"))
        BlacklistWindow.top_level.geometry(BlacklistWindow.get_geometry(is_gui=True))

        self.master = BlacklistWindow.top_level
        self.app_actions = app_actions
        self.base_item = ""
        self.filter_text = ""
        self.filtered_items = Blacklist.get_items()[:]
        self.enable_item_btn_list = []
        self.remove_item_btn_list = []
        self.label_list = []

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0)
        self.frame.columnconfigure(0, weight=9)
        self.frame.columnconfigure(1, weight=1)
        self.frame.columnconfigure(2, weight=1)
        self.frame.columnconfigure(3, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.add_blacklist_widgets()

        self._label_info = Label(self.frame)
        self.add_label(self._label_info, _("Add to tag blacklist"), row=0, wraplength=BlacklistWindow.COL_0_WIDTH)
        self.add_item_btn = None
        self.add_btn("add_item_btn", _("Add item"), self.handle_item, column=1)
        self.item_var = StringVar(self.master)
        self.item_entry = self.new_entry(self.item_var)
        self.item_entry.grid(row=0, column=2)
        
        # Add regex checkbox
        self.use_regex_var = BooleanVar(value=False)
        self.regex_checkbox = Checkbutton(
            self.frame, 
            text=_("Use glob-based regex"), 
            variable=self.use_regex_var,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            selectcolor=AppStyle.BG_COLOR
        )
        self.regex_checkbox.grid(row=0, column=3)
        
        self.clear_blacklist_btn = None
        self.add_btn("clear_blacklist_btn", _("Clear items"), self.clear_items, column=4)

        # Add import/export buttons
        self.import_btn = None
        self.export_btn = None
        self.add_btn("import_btn", _("Import"), self.import_blacklist, column=5)
        self.add_btn("export_btn", _("Export"), self.export_blacklist, column=6)

        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_items)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_blacklist_widgets(self):
        row = 0
        base_col = 0
        for i in range(len(self.filtered_items)):
            row = i+1
            item = self.filtered_items[i]
            self._label_info = Label(self.frame)
            self.label_list.append(self._label_info)
            
            # Display item with regex indicator
            display_text = str(item)
            if item.use_regex:
                display_text += " [regex]"
            self.add_label(self._label_info, display_text, row=row, column=base_col, wraplength=BlacklistWindow.COL_0_WIDTH)
            
            # Add enable/disable toggle
            enabled_var = StringVar(value="✓" if item.enabled else "✗")
            toggle_btn = Button(self.frame, text=enabled_var.get())
            self.enable_item_btn_list.append(toggle_btn)
            toggle_btn.grid(row=row, column=base_col+1)
            def toggle_handler(event, self=self, item=item, enabled_var=enabled_var):
                return self.toggle_item(event, item, enabled_var)
            toggle_btn.bind("<Button-1>", toggle_handler)
            
            # Add remove button
            remove_item_btn = Button(self.frame, text=_("Remove"))
            self.remove_item_btn_list.append(remove_item_btn)
            remove_item_btn.grid(row=row, column=base_col+2)
            def remove_item_handler(event, self=self, item=item):
                return self.remove_item(event, item)
            remove_item_btn.bind("<Button-1>", remove_item_handler)

    def get_item(self, item):
        """
        Add or remove an item from the blacklist
        """
        if item is not None:
            Blacklist.remove_item(item)
            self.refresh()
            self.app_actions.toast(_("Removed item: {0}").format(item))
            return None
        item = self.item_var.get()
        return item

    def handle_item(self, event=None, item=None):
        item = self.get_item(item)
        if item is None:
            return
        if item.strip() == "":
            self.app_actions.alert(_("Warning"), _("Please enter a string to add to the blacklist."), kind="warning")
            return

        # Add item to blacklist with regex setting from checkbox
        Blacklist.add_to_blacklist(item, enabled=True, use_regex=self.use_regex_var.get())
        self.refresh()
        self.app_actions.toast(_("Added item to blacklist: {0}").format(item))
        return item

    def remove_item(self, event=None, item=None):
        item = self.handle_item(item=item)
        if item is None:
            return
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        BlacklistWindow.update_history(item)
        BlacklistWindow.last_set_item = item
        self.close_windows()

    def filter_items(self, event):
        """
        Rebuild the filtered items list based on the filter string and update the UI.
        """
        # Don't filter if an entry has focus (user is typing in entry field)
        if AwareEntry.an_entry_has_focus:
            return
            
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    self.filtered_items = self.filtered_items[1:] + [self.filtered_items[0]]
                else:  # keysym == "Up"
                    self.filtered_items = [self.filtered_items[-1]] + self.filtered_items[:-1]
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
            self.filtered_items.clear()
            self.filtered_items = Blacklist.get_items()[:]
        else:
            temp = []
            # First pass try to match directory basename
            for item in Blacklist.get_items():
                if item.string == self.filter_text:
                    temp.append(item)
            for item in Blacklist.get_items():
                if item not in temp:
                    if item.string.startswith(self.filter_text):
                        temp.append(item)
            # Third pass try to match part of the basename
            for item in Blacklist.get_items():
                if item not in temp:
                    if item and (f" {self.filter_text}" in item.string.lower() or f"_{self.filter_text}" in item.string.lower()):
                        temp.append(item)
            self.filtered_items = temp[:]

        self.refresh(refresh_list=False)

    def do_action(self, event=None):
        """
        The user has requested to set an item.
        If no items exist, call handle_item() with item=None to set a new item.
        """
        self.handle_item()

    def clear_items(self, event=None):
        Blacklist.clear()
        self.filtered_items.clear()
        self.refresh()
        self.app_actions.toast(_("Cleared item blacklist"))

    def clear_widget_lists(self):
        for btn in self.enable_item_btn_list:
            btn.destroy()
        for btn in self.remove_item_btn_list:
            btn.destroy()
        for label in self.label_list:
            label.destroy()
        self.enable_item_btn_list = []
        self.remove_item_btn_list = []
        self.label_list = []

    def refresh(self, refresh_list=True):
        if refresh_list:
            self.filtered_items = Blacklist.get_items()[:]
        self.clear_widget_lists()
        self.add_blacklist_widgets()
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
        return AwareEntry(self.frame, text=text, textvariable=text_variable, width=width, font=fnt.Font(size=8), **kw)

    def toggle_item(self, event=None, item=None, enabled_var=None):
        """Toggle the enabled state of an item."""
        if item is None or enabled_var is None:
            return
            
        # Find the item in the blacklist
        for blacklist_item in Blacklist.get_items():
            if blacklist_item == item:
                blacklist_item.enabled = not blacklist_item.enabled
                enabled_var.set("✓" if blacklist_item.enabled else "✗")
                self.store_blacklist()
                self.app_actions.toast(_("Item \"{0}\" is now {1}").format(
                    blacklist_item.string,
                    _("enabled") if blacklist_item.enabled else _("disabled")
                ))
                break

    def import_blacklist(self, event=None):
        """Import blacklist from a file."""
        filetypes = [
            ("All supported", "*.csv;*.json;*.txt"),
            ("CSV files", "*.csv"),
            ("JSON files", "*.json"),
            ("Text files", "*.txt")
        ]
        filename = filedialog.askopenfilename(
            title=_("Import Blacklist"),
            filetypes=filetypes
        )
        if not filename:
            return

        try:
            if filename.endswith('.csv'):
                Blacklist.import_blacklist_csv(filename)
            elif filename.endswith('.json'):
                Blacklist.import_blacklist_json(filename)
            else:  # .txt
                Blacklist.import_blacklist_txt(filename)
            
            self.refresh()
            self.app_actions.toast(_("Successfully imported blacklist"))
        except Exception as e:
            self.app_actions.alert(_("Import Error"), str(e), kind="error")

    def export_blacklist(self, event=None):
        """Export blacklist to a file."""
        filetypes = [
            ("CSV files", "*.csv"),
            ("JSON files", "*.json"),
            ("Text files", "*.txt")
        ]
        filename = filedialog.asksaveasfilename(
            title=_("Export Blacklist"),
            filetypes=filetypes,
            defaultextension=".csv"
        )
        if not filename:
            return

        try:
            if filename.endswith('.csv'):
                Blacklist.export_blacklist_csv(filename)
            elif filename.endswith('.json'):
                Blacklist.export_blacklist_json(filename)
            else:  # .txt
                Blacklist.export_blacklist_txt(filename)
            
            self.app_actions.toast(_("Successfully exported blacklist"))
        except Exception as e:
            self.app_actions.alert(_("Export Error"), str(e), kind="error")

