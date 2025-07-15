from tkinter import Toplevel, Entry, Frame, Label, StringVar, filedialog, LEFT, W, BooleanVar, Checkbutton, Scrollbar, Listbox, IntVar, messagebox
import tkinter.font as fnt
from tkinter.ttk import Button, Combobox

from sd_runner.blacklist import BlacklistItem, Blacklist
from sd_runner.concepts import Concepts
from ui.app_style import AppStyle
from ui.auth.password_utils import require_password
from utils.globals import ProtectedActions, BlacklistMode
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N
from lib.aware_entry import AwareEntry
from lib.tk_scroll_demo import ScrollFrame
from lib.tooltip import Tooltip

_ = I18N._


class BlacklistModifyWindow():
    top_level = None
    COL_0_WIDTH = 600

    def __init__(self, master, refresh_callback, blacklist_item, dimensions="600x400"):
        BlacklistModifyWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        BlacklistModifyWindow.top_level.geometry(dimensions)
        self.master = BlacklistModifyWindow.top_level
        self.refresh_callback = refresh_callback
        self.is_new_item = blacklist_item is None
        self.original_string = "" if self.is_new_item else blacklist_item.string
        self.blacklist_item = BlacklistItem("", enabled=True, use_regex=False, use_word_boundary=True) if self.is_new_item else blacklist_item
        BlacklistModifyWindow.top_level.title(_("Modify Blacklist Item: {0}").format(self.blacklist_item.string))

        # Store original values for change tracking
        self.original_values = {
            'string': self.original_string,
            'enabled': self.blacklist_item.enabled,
            'use_regex': self.blacklist_item.use_regex,
            'use_word_boundary': self.blacklist_item.use_word_boundary
        }

        self.frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew")
        self.master.grid_rowconfigure(0, weight=1)
        self.master.grid_columnconfigure(0, weight=1)

        # String field
        self._label_string = Label(self.frame, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self._label_string, _("Blacklist String"), row=0, wraplength=BlacklistModifyWindow.COL_0_WIDTH)

        self.new_string = StringVar(self.master, value=self.original_string)
        self.new_string_entry = Entry(self.frame, textvariable=self.new_string, width=50, font=fnt.Font(size=8))
        self.new_string_entry.grid(column=0, row=1, sticky="w")

        # Enabled checkbox
        self.enabled_var = BooleanVar(value=self.blacklist_item.enabled)
        self.enabled_checkbox = Checkbutton(
            self.frame, 
            text=_("Enabled"), 
            variable=self.enabled_var,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            selectcolor=AppStyle.BG_COLOR
        )
        self.enabled_checkbox.grid(row=2, column=0, sticky="w")

        # Use regex checkbox
        self.use_regex_var = BooleanVar(value=self.blacklist_item.use_regex)
        self.regex_checkbox = Checkbutton(
            self.frame, 
            text=_("Use glob-based regex"), 
            variable=self.use_regex_var,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            selectcolor=AppStyle.BG_COLOR
        )
        self.regex_checkbox.grid(row=3, column=0, sticky="w")

        # Use word boundary checkbox
        self.use_word_boundary_var = BooleanVar(value=self.blacklist_item.use_word_boundary)
        self.word_boundary_checkbox = Checkbutton(
            self.frame, 
            text=_("Use word boundary matching"), 
            variable=self.use_word_boundary_var,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            selectcolor=AppStyle.BG_COLOR
        )
        self.word_boundary_checkbox.grid(row=4, column=0, sticky="w")

        # Preview and Done buttons
        self.preview_btn = None
        self.done_btn = None
        self.add_btn("preview_btn", _("Preview"), self.preview_blacklist_item, row=5, column=0)
        self.add_btn("done_btn", _("Done"), self.finalize_blacklist_item, row=5, column=1)

        # Set up window close protocol to handle unsaved changes
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

        self.master.update()

    def _has_changes(self):
        """Check if any changes have been made to the form"""
        current_values = {
            'string': self.new_string.get().strip(),
            'enabled': self.enabled_var.get(),
            'use_regex': self.use_regex_var.get(),
            'use_word_boundary': self.use_word_boundary_var.get()
        }
        return current_values != self.original_values

    def _validate_and_get_item(self):
        """Internal method to validate the form and create a BlacklistItem with current values"""
        string = self.new_string.get().strip()
        if not string:
            self.master.update()
            messagebox.showerror(_("Error"), _("Blacklist string cannot be empty."))
            return None

        # Create a blacklist item with current form values
        return BlacklistItem(
            string=string,
            enabled=self.enabled_var.get(),
            use_regex=self.use_regex_var.get(),
            use_word_boundary=self.use_word_boundary_var.get()
        )

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def preview_blacklist_item(self, event=None):
        """Preview the effects of the current blacklist item settings"""
        temp_item = self._validate_and_get_item()
        if temp_item is None:
            return
        
        # Open preview window with the temporary item
        BlacklistPreviewWindow(self.master, None, temp_item)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def finalize_blacklist_item(self, event=None):
        # Check if any changes were made
        if not self._has_changes():
            # No changes made, just close the window
            self.close_windows()
            # Show a toast message
            if hasattr(self.master, 'app_actions') and self.master.app_actions:
                self.master.app_actions.toast(_("No changes were made"))
            return

        blacklist_item = self._validate_and_get_item()
        if blacklist_item is None:
            return
        
        self.close_windows(override_check=True)
        self.refresh_callback(blacklist_item, self.is_new_item, self.original_string)

    def close_windows(self, event=None, override_check=False):
        if not override_check and self._has_changes():
            response = messagebox.askyesnocancel(_("Unsaved Changes"), _("Do you want to save changes before closing?"))
            if response is True:  # User clicked Yes
                self.finalize_blacklist_item()
            elif response is False:  # User clicked No
                self.master.destroy()
            # If response is None (Cancel), do nothing and keep window open
        else:
            self.master.destroy()

    def add_label(self, label_ref, text, row=0, column=0, wraplength=500, columnspan=1, **kw):
        label_ref['text'] = text
        label_ref.grid(column=column, row=row, sticky=W, columnspan=columnspan)
        label_ref.config(wraplength=wraplength, justify=LEFT, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, **kw)

    def add_btn(self, button_ref_name, text, command, row=0, column=0):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.frame, text=text, command=command)
            setattr(self, button_ref_name, button)
            button # for some reason this is necessary to maintain the reference?
            button.grid(row=row, column=column)


class BlacklistPreviewWindow:
    """Minimalist window to show the effects of blacklist items on concepts."""
    
    def __init__(self, master, app_actions, blacklist_item=None):
        self.master = Toplevel(master, bg=AppStyle.BG_COLOR)
        self.master.title(_("Blacklist Preview"))
        self.master.geometry("600x400")
        
        self.app_actions = app_actions
        self.blacklist_item = blacklist_item
        self.filtered_concepts = []
        
        # Define categories with their default checked state
        self.file_categories = {
            "SFW": True,
            "NSFW": False,
            "NSFL": False,
            "Art Styles": True,
            "Dictionary": True
        }
        self.category_vars = {}  # Store checkbox variables
        
        self.setup_ui()
        self.load_concepts()
        
    def setup_ui(self):
        # Title label
        if self.blacklist_item:
            title_text = _("Concepts filtered by: {0}").format(self.blacklist_item.string)
            if self.blacklist_item.use_regex:
                title_text += " [regex]"
        else:
            title_text = _("All filtered concepts")
            
        title_label = Label(self.master, text=title_text, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=10, weight='bold'))
        title_label.pack(pady=10)
        
        # Category checkboxes
        checkbox_frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        checkbox_frame.pack(pady=5)
        
        for i, (category, default_checked) in enumerate(self.file_categories.items()):
            var = IntVar(value=1 if default_checked else 0)
            self.category_vars[category] = var
            cb = Checkbutton(checkbox_frame, text=category, variable=var, command=self.load_concepts,
                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectcolor=AppStyle.BG_COLOR)
            cb.grid(row=0, column=i, padx=5)
        
        # Count label
        self.count_label = Label(self.master, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.count_label.pack(pady=5)
        
        # Listbox with scrollbar
        list_frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        list_frame.pack(fill='both', expand=True, padx=10, pady=10)
        
        self.listbox = Listbox(list_frame, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectmode='none')
        scrollbar = Scrollbar(list_frame, orient='vertical', command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scrollbar.set)
        
        self.listbox.pack(side='left', fill='both', expand=True)
        scrollbar.pack(side='right', fill='y')
        
        # Close button
        close_btn = Button(self.master, text=_("Close"), command=self.master.destroy)
        close_btn.pack(pady=10)
        
    def _get_category_states(self):
        """Get the current state of all category checkboxes"""
        return {name: bool(var.get()) for name, var in self.category_vars.items()}
        
    def load_concepts(self):
        """Load and filter concepts based on the blacklist item."""
        try:
            # Get category states from checkboxes
            category_states = self._get_category_states()
            
            # Use the Concepts class method to get filtered concepts
            self.filtered_concepts = Concepts.get_filtered_concepts_for_preview(
                self.blacklist_item, category_states
            )
            
            # Update UI
            self.count_label.config(text=_("Found {0} filtered concepts").format(len(self.filtered_concepts)))
            
            # Populate listbox
            self.listbox.delete(0, 'end')
            for concept in sorted(set(self.filtered_concepts)):  # Remove duplicates
                self.listbox.insert('end', concept)
                
        except Exception as e:
            error_msg = _("Error loading concepts: {0}").format(str(e))
            self.count_label.config(text=error_msg)
            if self.app_actions:
                self.app_actions.alert(_("Error"), error_msg, kind="error")


class BlacklistWindow():
    top_level = None
    blacklist_modify_window = None
    recent_items = []
    last_set_item = None

    item_history = []
    MAX_ITEMS = 50

    MAX_HEIGHT = 900
    N_ITEMS_CUTOFF = 30
    COL_0_WIDTH = 600

    # Cache keys
    BLACKLIST_CACHE_KEY = "tag_blacklist"
    DEFAULT_BLACKLIST_KEY = "blacklist_user_confirmed_non_default"
    BLACKLIST_MODE_KEY = "blacklist_mode"
    BLACKLIST_SILENT_KEY = "blacklist_silent_removal"
    warning_text = _("""WARNING: Are you sure you want to reveal the blacklist concepts? These concepts are damaging or offensive and WILL cause you severe psychological harm. Do not, under any circumstances, reveal these concepts to minors.

If you are young, not sure, or even an adult, click the close button on this window now and do something fun instead.""")

    @staticmethod
    def set_blacklist():
        """Load blacklist from cache, validate items, and load global blacklist settings."""
        # Check if user has explicitly confirmed they want a non-default blacklist state
        user_confirmed_non_default = app_info_cache.get(BlacklistWindow.DEFAULT_BLACKLIST_KEY, default_val=False)
        # Load blacklist mode
        mode_str = app_info_cache.get(BlacklistWindow.BLACKLIST_MODE_KEY, default_val=str(Blacklist.get_blacklist_mode()))
        try:
            mode = BlacklistMode(mode_str)
        except Exception:
            print(f"Invalid blacklist mode: {mode_str}")
        Blacklist.set_blacklist_mode(mode)
        # Load silent removal
        silent = app_info_cache.get(BlacklistWindow.BLACKLIST_SILENT_KEY, default_val=False)
        Blacklist.set_blacklist_silent_removal(silent)
        
        if not user_confirmed_non_default:
            # First time user opens blacklist window - load default encrypted blacklist
            # Hopefully, this is before the user has confirmed their intentions
            # for the defaults, unless they switched back to it.
            try:
                Blacklist.decrypt_blacklist()
                print("Loaded default encrypted blacklist for first-time user")
                return
            except Exception as e:
                print(f"Error loading default blacklist: {e}")
                # Fall back to normal load (a probably empty blacklist) if decryption fails
        
        # User has confirmed non-default state or decryption failed - load from cache
        raw_blacklist = app_info_cache.get(BlacklistWindow.BLACKLIST_CACHE_KEY, default_val=[])
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
        """Store blacklist to cache, converting items to dictionaries, and store global blacklist settings."""
        Blacklist.save_cache()
        blacklist_dicts = [item.to_dict() for item in Blacklist.get_items()]
        app_info_cache.set(BlacklistWindow.BLACKLIST_CACHE_KEY, blacklist_dicts)
        app_info_cache.set(BlacklistWindow.BLACKLIST_MODE_KEY, str(Blacklist.get_blacklist_mode()))
        app_info_cache.set(BlacklistWindow.BLACKLIST_SILENT_KEY, Blacklist.get_blacklist_silent_removal())

    @staticmethod
    def mark_user_confirmed_non_default():
        """Mark that the user has explicitly confirmed they want a non-default blacklist state."""
        app_info_cache.set(BlacklistWindow.DEFAULT_BLACKLIST_KEY, True)

    @staticmethod
    def is_in_default_state():
        """Check if the blacklist is in default state (user hasn't confirmed non-default)."""
        return not app_info_cache.get(BlacklistWindow.DEFAULT_BLACKLIST_KEY, default_val=False)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def load_default_blacklist(self, event=None):
        """Load the default encrypted blacklist."""
        # Show confirmation dialog before loading default if not in default state
        if not self.is_in_default_state() and len(Blacklist.get_items()) > 0:
            # There are items in the blacklist, so we need to confirm the user wants to load the default
            response = messagebox.askyesno(
                _("Confirm Load Default Blacklist"),
                _("Are you sure you want to load the default blacklist?\n\n"
                "⚠️ WARNING: This will erase your current blacklist and replace it with the default items.\n"
                "• All your current blacklist items will be permanently deleted\n"
                "• You will need to rebuild your blacklist from scratch if you want to restore it later\n\n"
                "Do you want to continue?"),
                icon='warning'
            )
            if not response:
                return  # User cancelled
        try:
            Blacklist.decrypt_blacklist()
            print("Loaded default encrypted blacklist")
            self.refresh()
            self.app_actions.toast(_("Loaded default blacklist"))
            # Mark that user has confirmed they want a non-default state
            app_info_cache.set(BlacklistWindow.DEFAULT_BLACKLIST_KEY, False)
        except Exception as e:
            self.app_actions.alert(_("Error loading default blacklist"), str(e), kind="error")

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
        width = 800
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
        self.preview_item_btn_list = []
        self.modify_item_btn_list = []
        self.reveal_concepts_btn = None
        self.concepts_revealed = False  # Track whether concepts have been revealed in this window instance

        # Create main frame for header and buttons
        self.header_frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.header_frame.grid(column=0, row=0, sticky="ew")
        self.header_frame.columnconfigure(0, weight=9)
        self.header_frame.columnconfigure(1, weight=1)
        self.header_frame.columnconfigure(2, weight=1)
        self.header_frame.columnconfigure(3, weight=1)
        self.header_frame.columnconfigure(4, weight=1)

        # Create scrollable frame for blacklist items
        self.frame = ScrollFrame(self.master, bg_color=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=1, sticky="nsew")
        self.master.grid_rowconfigure(1, weight=1)
        self.master.grid_columnconfigure(0, weight=1)

        self.add_blacklist_widgets()

        # Add a row for the blacklist global settings
        self.settings_label = Label(self.header_frame, text=_('Global Settings:'), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.settings_label.grid(row=0, column=0, sticky=W)
        Tooltip(self.settings_label, _('These settings affect how the blacklist is applied globally.'))

        # Blacklist mode dropdown
        self.blacklist_mode_var = StringVar(self.master)
        self.blacklist_mode_var.set(Blacklist.get_blacklist_mode().display())
        self.mode_dropdown = Combobox(self.header_frame, textvariable=self.blacklist_mode_var, state="readonly", width=22)
        self.mode_dropdown['values'] = BlacklistMode.display_values()
        self.mode_dropdown.grid(row=0, column=1, sticky=W)
        self.mode_dropdown.bind('<<ComboboxSelected>>', self.on_mode_change)
        Tooltip(self.mode_dropdown, _('Choose how the blacklist is enforced: block, warn, or allow.'))

        # Silent removal checkbox
        self.silent_var = BooleanVar(value=Blacklist.get_blacklist_silent_removal())
        self.silent_checkbox = Checkbutton(
            self.header_frame,
            text=_('Silent Removal'),
            variable=self.silent_var,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            selectcolor=AppStyle.BG_COLOR,
            command=self.on_silent_change
        )
        self.silent_checkbox.grid(row=0, column=2, sticky=W)
        Tooltip(self.silent_checkbox, _('If enabled, blacklisted words are removed silently without notification.'))

        # Add import/export/preview buttons on a new row
        self.import_btn = None
        self.export_btn = None
        self.preview_all_btn = None
        self.load_default_btn = None
        self.add_btn("import_btn", _("Import"), self.import_blacklist, row=1, column=0)
        self.add_btn("export_btn", _("Export"), self.export_blacklist, row=1, column=1)
        self.add_btn("preview_all_btn", _("Preview All"), self.preview_all, row=1, column=2)
        self.add_btn("load_default_btn", _("Load Default"), self.load_default_blacklist, row=1, column=3)

        # Add a row for the interface buttons
        self._label_info = Label(self.header_frame)
        self.add_label(self._label_info, _("Blacklist items"), row=2, wraplength=BlacklistWindow.COL_0_WIDTH)
        self.add_item_btn = None
        self.add_btn("add_item_btn", _("Add to tag blacklist"), self.add_new_item, row=2, column=1)
        
        self.clear_blacklist_btn = None
        self.add_btn("clear_blacklist_btn", _("Clear items"), self.clear_items, row=2, column=2)

        self.frame.after(1, lambda: self.frame.focus_force())

        self.master.bind("<Key>", self.filter_items)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def add_blacklist_widgets(self):
        # Always show reveal concepts button initially, unless concepts have already been revealed
        if not self.concepts_revealed:
            # Show reveal concepts button instead of blacklist items
            self._label_info = Label(self.frame.viewPort)
            self.label_list.append(self._label_info)
            if Blacklist.is_empty():
                label_text = _("No blacklist items found. You can add items by clicking the 'Add to tag blacklist' button below, or load the default blacklist.")
            else:
                label_text = _("Click below to reveal blacklist concepts.")
            if BlacklistWindow.is_in_default_state():
                label_text += "\n\n" + _("Default blacklist is loaded. You can load your own blacklist by editing the existing concepts, clearing the blacklist and adding your own, or importing concepts from a file.")
            self.add_label(self._label_info, label_text, row=1, column=0, columnspan=4)
            if Blacklist.is_empty():
                return

            # Add reveal concepts button
            reveal_btn = Button(self.frame.viewPort, text=_("Reveal Concepts"))
            self.reveal_concepts_btn = reveal_btn
            reveal_btn.grid(row=2, column=0, pady=20)
            def reveal_handler(event, self=self):
                return self.reveal_concepts(event)
            reveal_btn.bind("<Button-1>", reveal_handler)
            return
        
        # Normal blacklist items display (after concepts have been revealed)
        base_col = 0
        for i in range(len(self.filtered_items)):
            row = i+1
            item = self.filtered_items[i]
            self._label_info = Label(self.frame.viewPort)
            self.label_list.append(self._label_info)
            
            # Display item with regex indicator
            display_text = str(item)
            if item.use_regex:
                display_text += " " + _("[regex]")
            if not item.use_word_boundary:
                display_text += " " + _("[no boundary]")
            self.add_label(self._label_info, display_text, row=row, column=base_col, wraplength=BlacklistWindow.COL_0_WIDTH)
            
            # Add enable/disable toggle
            enabled_var = StringVar(value="✓" if item.enabled else "✗")
            toggle_btn = Button(self.frame.viewPort, text=enabled_var.get())
            self.enable_item_btn_list.append(toggle_btn)
            toggle_btn.grid(row=row, column=base_col+1)
            def toggle_handler(event, self=self, item=item, enabled_var=enabled_var):
                return self.toggle_item(event, item, enabled_var)
            toggle_btn.bind("<Button-1>", toggle_handler)
            
            # Add modify button
            modify_btn = Button(self.frame.viewPort, text=_("Modify"))
            self.modify_item_btn_list.append(modify_btn)
            modify_btn.grid(row=row, column=base_col+2)
            def modify_handler(event, self=self, item=item):
                return self.modify_item(event, item)
            modify_btn.bind("<Button-1>", modify_handler)
            
            # Add preview button
            preview_btn = Button(self.frame.viewPort, text=_("Preview"))
            self.preview_item_btn_list.append(preview_btn)
            preview_btn.grid(row=row, column=base_col+3)
            def preview_handler(event, self=self, item=item):
                return self.preview_item(event, item)
            preview_btn.bind("<Button-1>", preview_handler)
            
            # Add remove button
            remove_item_btn = Button(self.frame.viewPort, text=_("Remove"))
            self.remove_item_btn_list.append(remove_item_btn)
            remove_item_btn.grid(row=row, column=base_col+4)
            def remove_item_handler(event, self=self, item=item):
                return self.remove_item(event, item)
            remove_item_btn.bind("<Button-1>", remove_item_handler)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def open_blacklist_modify_window(self, event=None, blacklist_item=None):
        if BlacklistWindow.blacklist_modify_window is not None:
            BlacklistWindow.blacklist_modify_window.master.destroy()
        BlacklistWindow.blacklist_modify_window = BlacklistModifyWindow(self.master, self.refresh_blacklist_item, blacklist_item)

    def refresh_blacklist_item(self, blacklist_item, is_new_item, original_string):
        """Callback for when a blacklist item is created or modified"""
        BlacklistWindow.update_history(blacklist_item)
        
        # Mark that user has confirmed they want a non-default state
        BlacklistWindow.mark_user_confirmed_non_default()
        
        if is_new_item:
            # This is a new item, add it to the blacklist
            Blacklist.add_item(blacklist_item)
        else:
            # This is a modification of an existing item
            # Find and remove the original item
            original_item = None
            for item in Blacklist.get_items():
                if item.string == original_string:
                    original_item = item
                    break
            
            if original_item:
                Blacklist.remove_item(original_item, do_save=False)
            
            # Add the new/modified item
            Blacklist.add_item(blacklist_item)
        
        self.set_blacklist_item(blacklist_item=blacklist_item, is_new_item=is_new_item)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def add_new_item(self, event=None):
        """Add a new blacklist item"""
        self.open_blacklist_modify_window(blacklist_item=None)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def modify_item(self, event=None, item=None):
        """Modify an existing blacklist item"""
        if item is None:
            return
        self.open_blacklist_modify_window(blacklist_item=item)

    def set_blacklist_item(self, event=None, blacklist_item=None, is_new_item=False):
        """Set a blacklist item (called from refresh callback)"""
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        BlacklistWindow.update_history(blacklist_item)
        BlacklistWindow.last_set_item = blacklist_item
        self.refresh()
        
        # Show appropriate toast message
        if is_new_item:
            self.app_actions.toast(_("Added item to blacklist: {0}").format(blacklist_item.string))
        else:
            self.app_actions.toast(_("Modified blacklist item: {0}").format(blacklist_item.string))

    def get_item(self, item):
        """
        Add or remove an item from the blacklist
        """
        if item is not None:
            Blacklist.remove_item(item)
            self.refresh()
            
            # Mark that user has confirmed they want a non-default state
            BlacklistWindow.mark_user_confirmed_non_default()
            
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
        
        # Mark that user has confirmed they want a non-default state
        BlacklistWindow.mark_user_confirmed_non_default()
        
        self.app_actions.toast(_("Added item to blacklist: {0}").format(item))
        return item

    @require_password(ProtectedActions.EDIT_BLACKLIST)
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
        If no items exist, call add_new_item() to create a new item.
        """
        self.add_new_item()

    # Extra protection for clearing the blacklist
    @require_password(ProtectedActions.EDIT_BLACKLIST, ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def clear_items(self, event=None):
        # Show confirmation dialog before clearing
        response = messagebox.askyesno(
            _("Confirm Clear Blacklist"),
            _("Are you sure you want to clear all blacklist items?\n\n"
              "⚠️ WARNING: This action cannot be undone!\n"
              "• All blacklist items will be permanently deleted\n"
              "• The blacklist helps improve image output quality\n"
              "• You will need to rebuild your blacklist from scratch\n\n"
              "Do you want to continue?"),
            icon='warning'
        )
        
        if not response:
            return  # User cancelled
        
        Blacklist.clear()
        self.filtered_items.clear()
        self.refresh()
        
        # Mark that user has confirmed they want a non-default state
        BlacklistWindow.mark_user_confirmed_non_default()
        
        self.app_actions.toast(_("Cleared item blacklist"))

    def clear_widget_lists(self):
        for btn in self.enable_item_btn_list:
            btn.destroy()
        for btn in self.remove_item_btn_list:
            btn.destroy()
        for label in self.label_list:
            label.destroy()
        for btn in self.preview_item_btn_list:
            btn.destroy()
        for btn in self.modify_item_btn_list:
            btn.destroy()
        # Clear reveal concepts button if it exists
        if hasattr(self, 'reveal_concepts_btn') and self.reveal_concepts_btn:
            self.reveal_concepts_btn.destroy()
            self.reveal_concepts_btn = None
        self.enable_item_btn_list = []
        self.remove_item_btn_list = []
        self.label_list = []
        self.preview_item_btn_list = []
        self.modify_item_btn_list = []

    def refresh(self, refresh_list=True):
        if refresh_list:
            self.filtered_items = Blacklist.get_items()[:]
        self.clear_widget_lists()
        self.add_blacklist_widgets()
        self.master.update()

    def close_windows(self, event=None):
        self.master.destroy()

    def add_label(self, label_ref, text, row=0, column=0, wraplength=500, columnspan=1):
        label_ref['text'] = text
        label_ref.grid(column=column, row=row, sticky=W, columnspan=columnspan)
        label_ref.config(wraplength=wraplength, justify=LEFT, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

    def add_btn(self, button_ref_name, text, command, row=0, column=0):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.header_frame, text=text, command=command)
            setattr(self, button_ref_name, button)
            button # for some reason this is necessary to maintain the reference?
            button.grid(row=row, column=column)

    def new_entry(self, text_variable, text="", width=30, **kw):
        return AwareEntry(self.header_frame, text=text, textvariable=text_variable, width=width, font=fnt.Font(size=8), **kw)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
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

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS, custom_text=warning_text, allow_unauthenticated=False)
    def reveal_concepts(self, event=None):
        """Reveal concepts in blacklist - requires additional authentication."""
        self.concepts_revealed = True  # Set flag to indicate concepts have been revealed
        self.refresh()  # Refresh to show the blacklist items
        self.app_actions.toast(_("Concepts revealed"))

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def preview_item(self, event=None, item=None):
        """Show preview of concepts filtered by a specific blacklist item."""
        if item is None:
            return
        BlacklistPreviewWindow(self.master, self.app_actions, item)

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def preview_all(self, event=None):
        """Show preview of all concepts filtered by any blacklist item."""
        BlacklistPreviewWindow(self.master, self.app_actions, None)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
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
            
            # Mark that user has confirmed they want a non-default state
            BlacklistWindow.mark_user_confirmed_non_default()
            
            self.app_actions.toast(_("Successfully imported blacklist"))
        except Exception as e:
            self.app_actions.alert(_("Import Error"), str(e), kind="error")

    @require_password(ProtectedActions.EDIT_BLACKLIST)
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

    def on_mode_change(self, event=None):
        try:
            mode = BlacklistMode.from_display(self.blacklist_mode_var.get())
        except Exception:
            mode = BlacklistMode.REMOVE_WORD_OR_PHRASE
        Blacklist.set_blacklist_mode(mode)
        self.store_blacklist()
        if self.app_actions:
            self.app_actions.toast(_("Blacklist mode set to: {0}").format(mode.display()))

    def on_silent_change(self):
        Blacklist.set_blacklist_silent_removal(self.silent_var.get())
        self.store_blacklist()
        if self.app_actions:
            self.app_actions.toast(_("Silent removal set to: {0}").format(self.silent_var.get()))

