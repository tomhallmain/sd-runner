import os
from tkinter import Toplevel, Frame, Label, StringVar, BooleanVar, LEFT, W, E
import tkinter.font as fnt
from tkinter.ttk import Entry, Button, Checkbutton
from tkinter import messagebox

from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.globals import ProtectedActions
from utils.translations import I18N

_ = I18N._


class PasswordAdminWindow():
    top_level = None
    
    # Default password-protected actions
    DEFAULT_PROTECTED_ACTIONS = {
        ProtectedActions.NSFW_PROMPTS.value: True,
        ProtectedActions.EDIT_BLACKLIST.value: True,
        ProtectedActions.EDIT_SCHEDULES.value: True,
        ProtectedActions.EDIT_EXPANSIONS.value: True,
        ProtectedActions.EDIT_PRESETS.value: True,
        ProtectedActions.EDIT_CONCEPTS.value: True,
        ProtectedActions.ACCESS_ADMIN.value: True  # This window itself
    }
    protected_actions = DEFAULT_PROTECTED_ACTIONS.copy()

    @staticmethod
    def set_protected_actions():
        """Load protected actions from cache or use defaults."""
        return app_info_cache.get("protected_actions", default_val=PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS)

    @staticmethod
    def store_protected_actions():
        """Store protected actions to cache."""
        # Ensure protected_actions is initialized before storing
        if not PasswordAdminWindow.protected_actions:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        app_info_cache.set("protected_actions", PasswordAdminWindow.protected_actions)

    @staticmethod
    def is_action_protected(action_name):
        """Check if a specific action requires password authentication."""
        if not PasswordAdminWindow.protected_actions:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        return PasswordAdminWindow.protected_actions.get(action_name, False)

    @staticmethod
    def get_geometry(is_gui=True):
        width = 500
        height = 600
        return f"{width}x{height}"

    def __init__(self, master, app_actions):
        PasswordAdminWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        PasswordAdminWindow.top_level.title(_("Password Administration"))
        PasswordAdminWindow.top_level.geometry(PasswordAdminWindow.get_geometry(is_gui=True))

        self.master = PasswordAdminWindow.top_level
        self.app_actions = app_actions
        
        # Load protected actions
        PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        
        # Create variables for checkboxes
        self.action_vars = {}
        for action in PasswordAdminWindow.protected_actions.keys():
            self.action_vars[action] = BooleanVar(value=PasswordAdminWindow.protected_actions[action])

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.setup_ui()
        
        self.master.bind("<Escape>", self.close_window)
        self.master.protocol("WM_DELETE_WINDOW", self.close_window)

    def setup_ui(self):
        """Set up the UI components."""
        # Title
        title_label = Label(self.frame, text=_("Password Protection Settings"), 
                           font=fnt.Font(size=12, weight="bold"))
        title_label.grid(column=0, row=0, pady=(10, 20), sticky="w")
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Description
        desc_label = Label(self.frame, text=_("Select which actions require password authentication:"), 
                          wraplength=450)
        desc_label.grid(column=0, row=1, pady=(0, 10), sticky="w")
        desc_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Action checkboxes
        row = 2
        for action_enum in ProtectedActions:
            action = action_enum.value
            if action in self.action_vars:
                checkbox = Checkbutton(self.frame, text=action_enum.get_description(), 
                                     variable=self.action_vars[action],
                                     command=self.update_protected_actions)
                checkbox.grid(column=0, row=row, pady=5, sticky="w")
                checkbox.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                              selectcolor=AppStyle.BG_COLOR)
                row += 1

        # Buttons
        button_frame = Frame(self.frame)
        button_frame.grid(column=0, row=row, pady=(20, 10), sticky="ew")
        button_frame.config(bg=AppStyle.BG_COLOR)

        # Save button
        save_btn = Button(button_frame, text=_("Save Settings"), command=self.save_settings)
        save_btn.grid(column=0, row=0, padx=(0, 10))

        # Reset to defaults button
        reset_btn = Button(button_frame, text=_("Reset to Defaults"), command=self.reset_to_defaults)
        reset_btn.grid(column=1, row=0, padx=(0, 10))

        # Close button
        close_btn = Button(button_frame, text=_("Close"), command=self.close_window)
        close_btn.grid(column=2, row=0)

    def update_protected_actions(self):
        """Update the protected actions dictionary when checkboxes change."""
        for action, var in self.action_vars.items():
            PasswordAdminWindow.protected_actions[action] = var.get()

    def save_settings(self):
        """Save the current settings."""
        self.update_protected_actions()
        PasswordAdminWindow.store_protected_actions()
        self.app_actions.toast(_("Password protection settings saved."))

    def reset_to_defaults(self):
        """Reset all settings to their default values."""
        result = messagebox.askyesno(
            _("Reset to Defaults"),
            _("Are you sure you want to reset all password protection settings to their default values?")
        )
        
        if result:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS.copy()
            
            # Update checkboxes
            for action, var in self.action_vars.items():
                var.set(PasswordAdminWindow.protected_actions.get(action, False))
            
            self.app_actions.toast(_("Settings reset to defaults."))

    def close_window(self, event=None):
        """Close the window."""
        if PasswordAdminWindow.top_level:
            PasswordAdminWindow.top_level.destroy()
            PasswordAdminWindow.top_level = None


 