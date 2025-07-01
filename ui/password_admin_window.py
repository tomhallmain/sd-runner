import os
from tkinter import Toplevel, Frame, Label, StringVar, BooleanVar, LEFT, W, E, Checkbutton
import tkinter.font as fnt
from tkinter.ttk import Entry, Button
from tkinter import messagebox

from ui.app_style import AppStyle
from ui.password_utils import require_password, PasswordManager
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
        return PasswordAdminWindow.protected_actions.get(action_name, False)

    @staticmethod
    def is_session_timeout_enabled():
        """Check if session timeout is enabled."""
        return PasswordAdminWindow.session_timeout_enabled

    @staticmethod
    def get_session_timeout_minutes():
        """Get the session timeout duration in minutes."""
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
        
        # Create variables for password setup
        self.new_password_var = StringVar()
        self.confirm_password_var = StringVar()

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
                                     command=self.update_protected_actions,
                                     bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                                     selectcolor=AppStyle.BG_COLOR)
                checkbox.grid(column=0, row=row, pady=5, sticky="w")
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
                                     command=self.update_session_settings,
                                     bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                                     selectcolor=AppStyle.BG_COLOR)
        session_checkbox.grid(column=0, row=row, pady=5, sticky="w")
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
        timeout_entry.bind('<KeyRelease>', self.update_session_settings)
        row += 1

        # Password setup section
        row += 1  # Add some spacing
        
        # Password setup title
        password_title = Label(self.frame, text=_("Password Setup"), 
                              font=fnt.Font(size=11, weight="bold"))
        password_title.grid(column=0, row=row, pady=(20, 10), sticky="w")
        password_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        row += 1
        
        # Check if password is already configured
        password_configured = PasswordManager.is_password_configured()
        
        if password_configured:
            # Show password status
            status_label = Label(self.frame, text=_("Password is configured"), 
                               fg="green")
            status_label.grid(column=0, row=row, pady=5, sticky="w")
            status_label.config(bg=AppStyle.BG_COLOR)
            row += 1
            
            # Change password button
            change_btn = Button(self.frame, text=_("Change Password"), 
                               command=self.show_change_password_dialog)
            change_btn.grid(column=0, row=row, pady=5, sticky="w")
            row += 1
        else:
            # Show password setup form
            setup_label = Label(self.frame, text=_("Set up a password to enable protection:"), 
                              wraplength=450)
            setup_label.grid(column=0, row=row, pady=(0, 10), sticky="w")
            setup_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            row += 1
            
            # New password entry
            new_pwd_frame = Frame(self.frame)
            new_pwd_frame.grid(column=0, row=row, pady=5, sticky="w")
            new_pwd_frame.config(bg=AppStyle.BG_COLOR)
            
            new_pwd_label = Label(new_pwd_frame, text=_("New Password:"))
            new_pwd_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
            new_pwd_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            new_pwd_entry = Entry(new_pwd_frame, textvariable=self.new_password_var, 
                                 show="*", width=20)
            new_pwd_entry.grid(column=1, row=0, padx=5, sticky="w")
            row += 1
            
            # Confirm password entry
            confirm_pwd_frame = Frame(self.frame)
            confirm_pwd_frame.grid(column=0, row=row, pady=5, sticky="w")
            confirm_pwd_frame.config(bg=AppStyle.BG_COLOR)
            
            confirm_pwd_label = Label(confirm_pwd_frame, text=_("Confirm Password:"))
            confirm_pwd_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
            confirm_pwd_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            confirm_pwd_entry = Entry(confirm_pwd_frame, textvariable=self.confirm_password_var, 
                                     show="*", width=20)
            confirm_pwd_entry.grid(column=1, row=0, padx=5, sticky="w")
            row += 1
            
            # Set password button
            set_pwd_btn = Button(self.frame, text=_("Set Password"), 
                                command=self.set_password)
            set_pwd_btn.grid(column=0, row=row, pady=5, sticky="w")
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

        # Set to current button
        current_btn = Button(button_frame, text=_("Set to Current"), command=self.set_to_current)
        current_btn.grid(column=2, row=0, padx=(0, 10))

        # Close button
        close_btn = Button(button_frame, text=_("Close"), command=self.close_window)
        close_btn.grid(column=3, row=0)

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

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def save_settings(self):
        """Save the current settings."""
        self.update_protected_actions()
        self.update_session_settings()
        PasswordAdminWindow.store_protected_actions()
        self.app_actions.toast(_("Password protection settings saved."))

    @require_password(ProtectedActions.ACCESS_ADMIN)
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

    def set_to_current(self):
        """Restore settings to their current saved state."""
        result = messagebox.askyesno(
            _("Set to Current"),
            _("Are you sure you want to restore all settings to their current saved state? This will discard any unsaved changes.")
        )
        
        if result:
            # Reload the current saved state
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
            PasswordAdminWindow.set_session_settings()
            
            # Update checkboxes to reflect the current saved state
            for action, var in self.action_vars.items():
                var.set(PasswordAdminWindow.protected_actions.get(action, False))
            
            # Update session timeout controls
            self.session_timeout_enabled_var.set(PasswordAdminWindow.session_timeout_enabled)
            self.session_timeout_minutes_var.set(str(PasswordAdminWindow.session_timeout_minutes))
            
            self.app_actions.toast(_("Settings restored to current saved state."))

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def set_password(self):
        """Set a new password."""
        new_password = self.new_password_var.get()
        confirm_password = self.confirm_password_var.get()
        
        if not new_password:
            messagebox.showerror(_("Error"), _("Please enter a password."))
            return
        
        if new_password != confirm_password:
            messagebox.showerror(_("Error"), _("Passwords do not match."))
            return
        
        if len(new_password) < 6:
            messagebox.showerror(_("Error"), _("Password must be at least 6 characters long."))
            return
        
        if PasswordManager.set_password(new_password):
            self.app_actions.toast(_("Password set successfully."))
            # Clear the password fields
            self.new_password_var.set("")
            self.confirm_password_var.set("")
            # Refresh the UI to show the password is configured
            self.refresh_ui()
        else:
            messagebox.showerror(_("Error"), _("Failed to set password."))
    
    def show_change_password_dialog(self):
        """Show dialog to change password."""
        # Create a simple dialog for changing password
        dialog = Toplevel(self.master, bg=AppStyle.BG_COLOR)
        dialog.title(_("Change Password"))
        dialog.geometry("400x250")
        dialog.transient(self.master)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (250 // 2)
        dialog.geometry(f"400x250+{x}+{y}")
        
        # Main frame
        main_frame = Frame(dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        # Title
        title_label = Label(main_frame, text=_("Change Password"), 
                           font=fnt.Font(size=12, weight="bold"))
        title_label.pack(pady=(0, 15))
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Current password
        current_pwd_var = StringVar()
        current_label = Label(main_frame, text=_("Current Password:"))
        current_label.pack(anchor="w")
        current_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        current_entry = Entry(main_frame, textvariable=current_pwd_var, show="*", width=30)
        current_entry.pack(fill="x", pady=(5, 10))
        
        # New password
        new_pwd_var = StringVar()
        new_label = Label(main_frame, text=_("New Password:"))
        new_label.pack(anchor="w")
        new_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        new_entry = Entry(main_frame, textvariable=new_pwd_var, show="*", width=30)
        new_entry.pack(fill="x", pady=(5, 10))
        
        # Confirm new password
        confirm_pwd_var = StringVar()
        confirm_label = Label(main_frame, text=_("Confirm New Password:"))
        confirm_label.pack(anchor="w")
        confirm_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        confirm_entry = Entry(main_frame, textvariable=confirm_pwd_var, show="*", width=30)
        confirm_entry.pack(fill="x", pady=(5, 15))
        
        # Buttons
        button_frame = Frame(main_frame, bg=AppStyle.BG_COLOR)
        button_frame.pack(fill="x")
        
        def change_password():
            current_pwd = current_pwd_var.get()
            new_pwd = new_pwd_var.get()
            confirm_pwd = confirm_pwd_var.get()
            
            if not PasswordManager.verify_password(current_pwd):
                messagebox.showerror(_("Error"), _("Current password is incorrect."))
                return
            
            if new_pwd != confirm_pwd:
                messagebox.showerror(_("Error"), _("New passwords do not match."))
                return
            
            if len(new_pwd) < 6:
                messagebox.showerror(_("Error"), _("Password must be at least 6 characters long."))
                return
            
            if PasswordManager.set_password(new_pwd):
                self.app_actions.toast(_("Password changed successfully."))
                dialog.destroy()
            else:
                messagebox.showerror(_("Error"), _("Failed to change password."))
        
        ok_button = Button(button_frame, text=_("Change Password"), command=change_password)
        ok_button.pack(side="right", padx=(10, 0))
        
        cancel_button = Button(button_frame, text=_("Cancel"), command=dialog.destroy)
        cancel_button.pack(side="right")
        
        # Focus on current password entry
        current_entry.focus()
    
    def refresh_ui(self):
        """Refresh the UI to reflect current state."""
        # This is a simple approach - recreate the window
        # In a more sophisticated implementation, you might update specific widgets
        self.master.destroy()
        PasswordAdminWindow.top_level = None
        PasswordAdminWindow(self.master.master, self.app_actions)

    def close_window(self, event=None):
        """Close the window."""
        if PasswordAdminWindow.top_level:
            PasswordAdminWindow.top_level.destroy()
            PasswordAdminWindow.top_level = None


 