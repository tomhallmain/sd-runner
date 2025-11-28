import os
from tkinter import Frame, Label, StringVar, BooleanVar, LEFT, W, E, Checkbutton
import tkinter.font as fnt
from tkinter.ttk import Entry, Button
from tkinter import messagebox

from lib.multi_display import SmartToplevel
from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager, get_security_config
from ui.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N

_ = I18N._


class PasswordAdminWindow():
    top_level = None
    
    def __init__(self, master, app_actions):
        # Get parent window position to determine which display to use
        parent_x = master.winfo_x()
        parent_y = master.winfo_y()
        
        # For large windows, position at the top of the screen (Y=0) on the same display as parent
        # but slightly offset horizontally to avoid completely overlapping the parent window
        offset_x = 50  # Small horizontal offset from parent
        new_x = parent_x + offset_x
        new_y = 0  # Always position at the top of the screen
        
        # Create geometry string with custom positioning
        geometry = PasswordAdminWindow.get_geometry(is_gui=True)
        positioned_geometry = f"{geometry}+{new_x}+{new_y}"

        PasswordAdminWindow.top_level = SmartToplevel(persistent_parent=master, title=_("Password Administration"), geometry=positioned_geometry, auto_position=False)

        self.master = PasswordAdminWindow.top_level
        self.app_actions = app_actions
        
        # Get the centralized configuration
        self.config = get_security_config()
        
        # Create variables for checkboxes
        self.action_vars = {}
        
        for action_enum in ProtectedActions:
            action = action_enum.value
            # Add any new protected actions that aren't in config yet
            # Default to True for new actions (protected by default)
            self.action_vars[action] = BooleanVar(value=self.config.protected_actions.get(action, True))
        
        # Create variables for session timeout settings
        self.session_timeout_enabled_var = BooleanVar(value=self.config.session_timeout_enabled)
        self.session_timeout_minutes_var = StringVar(value=str(self.config.session_timeout_minutes))
        
        # Create variables for security advice settings
        self.show_security_advice_var = BooleanVar(value=self.config.is_security_advice_enabled())
        
        # Create variables for password setup
        self.new_password_var = StringVar()
        self.confirm_password_var = StringVar()

        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.columnconfigure(1, weight=1)
        self.frame.rowconfigure(1, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        self.setup_ui()
        
        self.master.bind("<Escape>", self.close_window)
        self.master.protocol("WM_DELETE_WINDOW", self.close_window)

    @staticmethod
    def get_geometry(is_gui=True):
        width = 900
        height = 700
        return f"{width}x{height}"

    def setup_ui(self):
        """Set up the UI components in a two-column layout."""
        # Title spanning both columns
        title_label = Label(self.frame, text=_("Password Protection Settings"), 
                           font=fnt.Font(size=12, weight="bold"))
        title_label.grid(column=0, row=0, columnspan=2, pady=(10, 20), sticky="w")
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Left column: Protected Actions
        left_frame = Frame(self.frame)
        left_frame.grid(column=0, row=1, sticky="nsew", padx=(0, 10))
        left_frame.config(bg=AppStyle.BG_COLOR)
        left_frame.columnconfigure(0, weight=1)

        # Left column title
        left_title = Label(left_frame, text=_("Protected Actions"), 
                          font=fnt.Font(size=11, weight="bold"))
        left_title.grid(column=0, row=0, pady=(0, 10), sticky="w")
        left_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Left column description
        left_desc = Label(left_frame, text=_("Select which actions require password authentication:"), 
                         wraplength=350)
        left_desc.grid(column=0, row=1, pady=(0, 10), sticky="w")
        left_desc.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Action checkboxes in left column
        row = 2
        for action_enum in ProtectedActions:
            action = action_enum.value
            if action in self.action_vars:
                # ACCESS_ADMIN should always be protected and cannot be disabled
                is_admin_action = action == ProtectedActions.ACCESS_ADMIN.value
                text = action_enum.get_description()

                # Add note for admin action
                if is_admin_action:
                    text = text + " " + _("(Always protected if a password is set)")

                checkbox = Checkbutton(left_frame, text=text, 
                                     variable=self.action_vars[action],
                                     command=self.update_protected_actions,
                                     bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                                     selectcolor=AppStyle.BG_COLOR,
                                     state="disabled" if is_admin_action else "normal")
                checkbox.grid(column=0, row=row, pady=2, sticky="w")
                
                row += 1

        # Right column: Other settings
        right_frame = Frame(self.frame)
        right_frame.grid(column=1, row=1, sticky="nsew", padx=(10, 0))
        right_frame.config(bg=AppStyle.BG_COLOR)
        right_frame.columnconfigure(0, weight=1)

        # Session timeout section
        session_title = Label(right_frame, text=_("Session Timeout Settings"), 
                             font=fnt.Font(size=11, weight="bold"))
        session_title.grid(column=0, row=0, pady=(0, 10), sticky="w")
        session_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Enable session timeout checkbox
        session_checkbox = Checkbutton(right_frame, text=_("Enable session timeout (remember password for a period)"), 
                                     variable=self.session_timeout_enabled_var,
                                     command=self.update_session_settings,
                                     bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                                     selectcolor=AppStyle.BG_COLOR)
        session_checkbox.grid(column=0, row=1, pady=5, sticky="w")

        # Timeout duration frame
        timeout_frame = Frame(right_frame)
        timeout_frame.grid(column=0, row=2, pady=5, sticky="w")
        timeout_frame.config(bg=AppStyle.BG_COLOR)
        
        timeout_label = Label(timeout_frame, text=_("Session timeout duration (minutes):"))
        timeout_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
        timeout_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        timeout_entry = Entry(timeout_frame, textvariable=self.session_timeout_minutes_var, width=10)
        timeout_entry.grid(column=1, row=0, padx=5, sticky="w")
        timeout_entry.bind('<KeyRelease>', self.update_session_settings)

        # Security advice section
        advice_title = Label(right_frame, text=_("Security Advice Settings"),
                            font=fnt.Font(size=11, weight="bold"))
        advice_title.grid(column=0, row=3, pady=(30, 10), sticky="w")
        advice_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)

        # Show security advice checkbox
        advice_checkbox = Checkbutton(right_frame, text=_("Show security advice when no password is configured"),
                                     variable=self.show_security_advice_var,
                                     command=self.update_security_advice_settings,
                                     bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                                     selectcolor=AppStyle.BG_COLOR)
        advice_checkbox.grid(column=0, row=4, pady=5, sticky="w")

        # Password setup section
        password_title = Label(right_frame, text=_("Password Setup"), 
                              font=fnt.Font(size=11, weight="bold"))
        password_title.grid(column=0, row=5, pady=(30, 10), sticky="w")
        password_title.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Check if password is already configured
        password_configured = PasswordManager.is_security_configured()
        
        if password_configured:
            # Show password status
            status_label = Label(right_frame, text=_("Password is configured"), 
                               fg="green")
            status_label.grid(column=0, row=6, pady=5, sticky="w")
            status_label.config(bg=AppStyle.BG_COLOR)

            # Change password button
            change_btn = Button(right_frame, text=_("Change Password"), 
                               command=self.show_change_password_dialog)
            change_btn.grid(column=0, row=7, pady=5, sticky="w")
            
            # Remove password button
            remove_btn = Button(right_frame, text=_("Remove Password"), 
                               command=self.remove_password)
            remove_btn.grid(column=0, row=8, pady=5, sticky="w")
        else:
            # Show password setup form
            setup_label = Label(right_frame, text=_("Set up a password to enable protection:"), 
                              wraplength=350)
            setup_label.grid(column=0, row=6, pady=(0, 10), sticky="w")
            setup_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            # New password entry
            new_pwd_frame = Frame(right_frame)
            new_pwd_frame.grid(column=0, row=7, pady=5, sticky="w")
            new_pwd_frame.config(bg=AppStyle.BG_COLOR)
            
            new_pwd_label = Label(new_pwd_frame, text=_("New Password:"))
            new_pwd_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
            new_pwd_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            new_pwd_entry = Entry(new_pwd_frame, textvariable=self.new_password_var, 
                                 show="*", width=20)
            new_pwd_entry.grid(column=1, row=0, padx=5, sticky="w")
            
            # Confirm password entry
            confirm_pwd_frame = Frame(right_frame)
            confirm_pwd_frame.grid(column=0, row=8, pady=5, sticky="w")
            confirm_pwd_frame.config(bg=AppStyle.BG_COLOR)
            
            confirm_pwd_label = Label(confirm_pwd_frame, text=_("Confirm Password:"))
            confirm_pwd_label.grid(column=0, row=0, padx=(20, 5), sticky="w")
            confirm_pwd_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
            
            confirm_pwd_entry = Entry(confirm_pwd_frame, textvariable=self.confirm_password_var, 
                                     show="*", width=20)
            confirm_pwd_entry.grid(column=1, row=0, padx=5, sticky="w")

            # Set password button
            set_pwd_btn = Button(right_frame, text=_("Set Password"), 
                                command=self.set_password)
            set_pwd_btn.grid(column=0, row=9, pady=5, sticky="w")

        # Bottom buttons spanning both columns
        button_frame = Frame(self.frame)
        button_frame.grid(column=0, row=2, columnspan=2, pady=(20, 10), sticky="ew")
        button_frame.config(bg=AppStyle.BG_COLOR)

        # Reset to defaults button
        reset_btn = Button(button_frame, text=_("Reset to Defaults"), command=self.reset_to_defaults)
        reset_btn.grid(column=0, row=0, padx=(0, 10))

        # Set to current button
        current_btn = Button(button_frame, text=_("Set to Current"), command=self.set_to_current)
        current_btn.grid(column=1, row=0, padx=(0, 10))

        # Save as JSON button
        save_json_btn = Button(button_frame, text=_("Export Cache as JSON"), command=self.export_cache_as_json)
        save_json_btn.grid(column=2, row=0, padx=(0, 10))

        # Save button
        save_btn = Button(button_frame, text=_("Save Settings"), command=self.save_settings)
        save_btn.grid(column=3, row=0, padx=(0, 10))

        # Close button
        close_btn = Button(button_frame, text=_("Close"), command=self.close_window)
        close_btn.grid(column=4, row=0)

    def update_protected_actions(self):
        """Update the protected actions dictionary when checkboxes change."""
        for action, var in self.action_vars.items():
            self.config.set_action_protected(action, var.get())

    def update_session_settings(self, event=None):
        """Update the session timeout settings when UI elements change."""
        try:
            self.config.set_session_timeout_enabled(self.session_timeout_enabled_var.get())
            timeout_minutes = int(self.session_timeout_minutes_var.get())
            self.config.set_session_timeout_minutes(timeout_minutes)
        except ValueError:
            # Invalid number entered, revert to current value
            self.session_timeout_minutes_var.set(str(self.config.session_timeout_minutes))

    def update_security_advice_settings(self):
        """Update security advice settings."""
        self.config.set_security_advice_enabled(self.show_security_advice_var.get())

    def clear_sessions(self):
        """Clear all sessions when settings change to ensure changes take effect immediately."""
        from ui.auth.password_session_manager import PasswordSessionManager
        PasswordSessionManager.clear_all_sessions()

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def save_settings(self):
        """Save the current settings."""
        self.update_protected_actions()
        self.update_session_settings()
        self.update_security_advice_settings()
        self.config.save_settings()

        self.clear_sessions()

        self._show_toast_or_messagebox(_("Password protection settings saved."))

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def reset_to_defaults(self):
        """Reset all settings to their default values."""
        result = messagebox.askyesno(
            _("Reset to Defaults"),
            _("Are you sure you want to reset all password protection settings to their default values?")
        )
        
        if result:
            self.config.reset_to_defaults()
            
            # Update checkboxes
            for action, var in self.action_vars.items():
                var.set(self.config.protected_actions.get(action, False))
            
            # Update session timeout controls
            self.session_timeout_enabled_var.set(self.config.session_timeout_enabled)
            self.session_timeout_minutes_var.set(str(self.config.session_timeout_minutes))

            # Update security advice controls
            self.show_security_advice_var.set(self.config.is_security_advice_enabled())

            self.clear_sessions()

            self._show_toast_or_messagebox(_("Settings reset to defaults."))

    def set_to_current(self):
        """Restore settings to their current saved state."""
        result = messagebox.askyesno(
            _("Set to Current"),
            _("Are you sure you want to restore all settings to their current saved state? This will discard any unsaved changes.")
        )
        
        if result:
            # Reload the current saved state
            self.config._load_settings()
            
            # Update checkboxes to reflect the current saved state
            for action, var in self.action_vars.items():
                var.set(self.config.protected_actions.get(action, False))
            
            # Update session timeout controls
            self.session_timeout_enabled_var.set(self.config.session_timeout_enabled)
            self.session_timeout_minutes_var.set(str(self.config.session_timeout_minutes))

            # Update security advice controls
            self.show_security_advice_var.set(self.config.is_security_advice_enabled())

            self._show_toast_or_messagebox(_("Settings restored to current saved state."))

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def set_password(self):
        """Set a new password."""
        new_password = self.new_password_var.get()
        confirm_password = self.confirm_password_var.get()
        
        if not new_password:
            self._show_toast_or_messagebox(_("Please enter a password."), error=True)
            return
        
        if new_password != confirm_password:
            self._show_toast_or_messagebox(_("Passwords do not match."), error=True)
            return
        
        if len(new_password) < 6:
            self._show_toast_or_messagebox(_("Password must be at least 6 characters long."), error=True)
            return
        
        if PasswordManager.set_password(new_password):
            self.clear_sessions()
            self._show_toast_or_messagebox(_("Password set successfully."))
            # Clear the password fields
            self.new_password_var.set("")
            self.confirm_password_var.set("")
            # Refresh the UI to show the password is configured
            self.refresh_ui()
        else:
            self._show_toast_or_messagebox(_("Failed to set password."), error=True)
    
    def show_change_password_dialog(self):
        """Show dialog to change password."""
        # Create a simple dialog for changing password
        dialog = SmartToplevel(persistent_parent=self.master, title=_("Change Password"), geometry="400x320")
        dialog.transient(self.master)
        dialog.grab_set()
        
        # Center the dialog
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (400 // 2)
        y = (dialog.winfo_screenheight() // 2) - (320 // 2)
        dialog.geometry(f"400x320+{x}+{y}")
        
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
                self._show_toast_or_messagebox(_("Current password is incorrect."), error=True)
                return
            
            if new_pwd != confirm_pwd:
                self._show_toast_or_messagebox(_("New passwords do not match."), error=True)
                return
            
            if len(new_pwd) < 6:
                self._show_toast_or_messagebox(_("Password must be at least 6 characters long."), error=True)
                return
            
            if PasswordManager.set_password(new_pwd):
                self.clear_sessions()
                self._show_toast_or_messagebox(_("Password changed successfully."))
                dialog.destroy()
            else:
                self._show_toast_or_messagebox(_("Failed to change password."), error=True)
        
        ok_button = Button(button_frame, text=_("Change Password"), command=change_password)
        ok_button.pack(side="right", padx=(10, 0))
        
        cancel_button = Button(button_frame, text=_("Cancel"), command=dialog.destroy)
        cancel_button.pack(side="right")
        
        # Focus on current password entry
        current_entry.focus()
    
    @require_password(ProtectedActions.ACCESS_ADMIN)
    def remove_password(self):
        """Remove the current password."""
        result = messagebox.askyesno(
            _("Remove Password"),
            _("Are you sure you want to remove password protection? This will disable all password requirements.")
        )
        
        if result:
            if PasswordManager.clear_password():
                self.clear_sessions()
                self._show_toast_or_messagebox(_("Password removed successfully."))
                # Refresh the UI to show the password setup form
                self.refresh_ui()
            else:
                self._show_toast_or_messagebox(_("Failed to remove password."), error=True)
    
    def refresh_ui(self):
        """Refresh the UI to reflect current state."""
        # This is a simple approach - recreate the window
        # In a more sophisticated implementation, might update specific widgets
        self.master.destroy()
        PasswordAdminWindow.top_level = None
        PasswordAdminWindow(self.master.master, self.app_actions)

    def close_window(self, event=None):
        """Close the window."""
        if PasswordAdminWindow.top_level:
            PasswordAdminWindow.top_level.destroy()
            PasswordAdminWindow.top_level = None

    def _show_toast_or_messagebox(self, message, error=False):
        """Show a toast if available, otherwise use a messagebox (info or error)."""
        if hasattr(self, 'app_actions') and hasattr(self.app_actions, 'toast'):
            if error:
                self.app_actions.alert("Administration Error", message, kind="error", master=self.master)
            else:
                self.app_actions.toast(message)
        else:
            if error:
                messagebox.showerror("Error", message)
            else:
                messagebox.showinfo("Info", message)

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def export_cache_as_json(self):
        """Export the app_info_cache as a JSON file (not encoded)."""
        from utils.app_info_cache import app_info_cache
        try:
            json_path = app_info_cache.export_as_json()
            self._show_toast_or_messagebox(_("Cache exported as JSON to:") + "\n" + json_path)
        except Exception as e:
            self._show_toast_or_messagebox(_("Failed to export cache as JSON:") + "\n" + str(e), error=True) 
