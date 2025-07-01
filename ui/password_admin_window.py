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
        ProtectedActions.EDIT_SCHEDULES.value: False,
        ProtectedActions.EDIT_EXPANSIONS.value: False,
        ProtectedActions.EDIT_PRESETS.value: False,
        ProtectedActions.EDIT_CONCEPTS.value: False,
        ProtectedActions.ACCESS_ADMIN.value: True  # This window itself
    }
    protected_actions = DEFAULT_PROTECTED_ACTIONS.copy()
    
    # Default session timeout settings (in minutes)
    DEFAULT_SESSION_TIMEOUT_ENABLED = True
    DEFAULT_SESSION_TIMEOUT_MINUTES = 30  # 30 minutes default
    session_timeout_enabled = DEFAULT_SESSION_TIMEOUT_ENABLED
    session_timeout_minutes = DEFAULT_SESSION_TIMEOUT_MINUTES

    @staticmethod
    def set_protected_actions():
        """Load protected actions from cache or use defaults."""
        return app_info_cache.get("protected_actions", default_val=PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS)

    @staticmethod
    def set_session_settings():
        """Load session timeout settings from cache or use defaults."""
        PasswordAdminWindow.session_timeout_enabled = app_info_cache.get(
            "session_timeout_enabled", default_val=PasswordAdminWindow.DEFAULT_SESSION_TIMEOUT_ENABLED
        )
        PasswordAdminWindow.session_timeout_minutes = app_info_cache.get(
            "session_timeout_minutes", default_val=PasswordAdminWindow.DEFAULT_SESSION_TIMEOUT_MINUTES
        )

    @staticmethod
    def store_protected_actions():
        """Store protected actions to cache."""
        # Ensure protected_actions is initialized before storing
        if not PasswordAdminWindow.protected_actions:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        app_info_cache.set("protected_actions", PasswordAdminWindow.protected_actions)
        
        # Store session timeout settings
        app_info_cache.set("session_timeout_enabled", PasswordAdminWindow.session_timeout_enabled)
        app_info_cache.set("session_timeout_minutes", PasswordAdminWindow.session_timeout_minutes)

    @staticmethod
    def is_action_protected(action_name):
        """Check if a specific action requires password authentication."""
        if not PasswordAdminWindow.protected_actions:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        return PasswordAdminWindow.protected_actions.get(action_name, False)

    @staticmethod
    def is_session_timeout_enabled():
        """Check if session timeout is enabled."""
        if not hasattr(PasswordAdminWindow, 'session_timeout_enabled'):
            PasswordAdminWindow.set_session_settings()
        return PasswordAdminWindow.session_timeout_enabled

    @staticmethod
    def get_session_timeout_minutes():
        """Get the session timeout duration in minutes."""
        if not hasattr(PasswordAdminWindow, 'session_timeout_minutes'):
            PasswordAdminWindow.set_session_settings()
        return PasswordAdminWindow.session_timeout_minutes

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
        
        # Load protected actions and session settings
        PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        PasswordAdminWindow.set_session_settings()
        
        # Create variables for checkboxes
        self.action_vars = {}
        for action in PasswordAdminWindow.protected_actions.keys():
            self.action_vars[action] = BooleanVar(value=PasswordAdminWindow.protected_actions[action])
        
        # Create variables for session timeout settings
        self.session_timeout_enabled_var = BooleanVar(value=PasswordAdminWindow.session_timeout_enabled)
        self.session_timeout_minutes_var = StringVar(value=str(PasswordAdminWindow.session_timeout_minutes))

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

        # Session timeout section
        row += 1  # Add some spacing
        
        # Session timeout title
        session_title = Label(self.frame, text=_("Session Timeout Settings"), 
                             font=fnt.Font(size=11, weight="bold"))
        session_title.grid(column=0, row=row, pady=(20, 10), sticky="w")
        session_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        row += 1
        
        # Enable session timeout checkbox
        session_checkbox = Checkbutton(self.frame, text=_("Enable session timeout (remember password for a period)"), 
                                     variable=self.session_timeout_enabled_var,
                                     command=self.update_session_settings)
        session_checkbox.grid(column=0, row=row, pady=5, sticky="w")
        session_checkbox.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                              selectcolor=AppStyle.BG_COLOR)
        row += 1
        
        # Timeout duration frame
        timeout_frame = Frame(self.frame)
        timeout_frame.grid(column=0, row=row, pady=5, sticky="w")
        timeout_frame.config(bg=AppStyle.BG_COLOR)
        
        timeout_label = Label(timeout_frame, text=_("Session timeout duration (minutes):"))
        timeout_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
        timeout_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        timeout_entry = Entry(timeout_frame, textvariable=self.session_timeout_minutes_var, width=10)
        timeout_entry.grid(column=1, row=0, padx=5, sticky="w")
        timeout_entry.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        timeout_entry.bind('<KeyRelease>', self.update_session_settings)
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

    def update_session_settings(self, event=None):
        """Update the session timeout settings when UI elements change."""
        try:
            PasswordAdminWindow.session_timeout_enabled = self.session_timeout_enabled_var.get()
            timeout_minutes = int(self.session_timeout_minutes_var.get())
            if timeout_minutes > 0:
                PasswordAdminWindow.session_timeout_minutes = timeout_minutes
        except ValueError:
            # Invalid number entered, revert to current value
            self.session_timeout_minutes_var.set(str(PasswordAdminWindow.session_timeout_minutes))

    def save_settings(self):
        """Save the current settings."""
        self.update_protected_actions()
        self.update_session_settings()
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
            PasswordAdminWindow.session_timeout_enabled = PasswordAdminWindow.DEFAULT_SESSION_TIMEOUT_ENABLED
            PasswordAdminWindow.session_timeout_minutes = PasswordAdminWindow.DEFAULT_SESSION_TIMEOUT_MINUTES
            
            # Update checkboxes
            for action, var in self.action_vars.items():
                var.set(PasswordAdminWindow.protected_actions.get(action, False))
            
            # Update session timeout controls
            self.session_timeout_enabled_var.set(PasswordAdminWindow.session_timeout_enabled)
            self.session_timeout_minutes_var.set(str(PasswordAdminWindow.session_timeout_minutes))
            
            self.app_actions.toast(_("Settings reset to defaults."))

    def close_window(self, event=None):
        """Close the window."""
        if PasswordAdminWindow.top_level:
            PasswordAdminWindow.top_level.destroy()
            PasswordAdminWindow.top_level = None


 