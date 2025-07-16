"""
Application startup authentication module.
This module handles password protection for the entire application startup.
It creates the application in a hidden state and only shows it after password verification.
Only shows a password dialog if startup protection is enabled and a password is configured.
"""

import tkinter as tk
from tkinter import messagebox
import tkinter.font as fnt

from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager
from ui.auth.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions
from utils.translations import I18N

_ = I18N._


class StartupPasswordDialog:
    """Password dialog for application startup authentication."""
    
    def __init__(self, root, callback=None):
        self.root = root
        self.callback = callback
        self.result = False
        
        # Create dialog window
        self.dialog = tk.Toplevel(root)
        self.dialog.title(_("Application Password Required"))
        self.dialog.geometry("500x300")
        self.dialog.resizable(False, False)
        self.dialog.transient(root)
        self.dialog.grab_set()
        
        # Center the dialog
        self.dialog.update_idletasks()
        x = (self.dialog.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (300 // 2)
        self.dialog.geometry(f"500x300+{x}+{y}")
        
        self.setup_ui()
        
        # Bind events
        self.dialog.bind("<Return>", self.verify_password)
        self.dialog.bind("<Escape>", self.cancel)
        self.dialog.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Focus on password entry
        self.password_entry.focus()
    

    
    def setup_ui(self):
        """Set up the UI components."""
        # Main frame
        main_frame = tk.Frame(self.dialog, bg=AppStyle.BG_COLOR)
        main_frame.pack(fill="both", expand=True, padx=20, pady=20)
        
        self._setup_password_ui(main_frame)
    
    def _setup_password_ui(self, main_frame):
        """Set up UI for password entry."""
        # Title
        title_label = tk.Label(main_frame, text=_("Application Password Required"), 
                              font=fnt.Font(size=14, weight="bold"))
        title_label.pack(pady=(0, 10))
        title_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Description
        desc_label = tk.Label(main_frame, 
                             text=_("A password is required to open this application."),
                             wraplength=450)
        desc_label.pack(pady=(0, 20))
        desc_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        # Password entry
        password_frame = tk.Frame(main_frame, bg=AppStyle.BG_COLOR)
        password_frame.pack(pady=(0, 20))
        
        password_label = tk.Label(password_frame, text=_("Password:"))
        password_label.pack(anchor="w")
        password_label.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        
        self.password_var = tk.StringVar()
        self.password_entry = tk.Entry(password_frame, textvariable=self.password_var, 
                                      show="*", width=30, font=fnt.Font(size=10))
        self.password_entry.pack(fill="x", pady=(5, 0))
        
        # Buttons
        button_frame = tk.Frame(main_frame, bg=AppStyle.BG_COLOR)
        button_frame.pack(fill="x")
        
        ok_button = tk.Button(button_frame, text=_("OK"), command=self.verify_password)
        ok_button.pack(side="right", padx=(10, 0))
        
        cancel_button = tk.Button(button_frame, text=_("Cancel"), command=self.cancel)
        cancel_button.pack(side="right")
    

    
    def verify_password(self, event=None):
        """Verify the entered password."""
        password = self.password_var.get()
        
        print(f"DEBUG: Verifying password...")
        # Check if password is correct
        if self.check_password(password):
            print("DEBUG: Password correct, destroying dialog and calling callback")
            self.result = True
            self.dialog.destroy()
            if self.callback:
                self.callback(True)
        else:
            print("DEBUG: Password incorrect, showing error and staying open")
            messagebox.showerror(_("Error"), _("Incorrect password"))
            self.password_var.set("")
            self.password_entry.focus()
    
    def check_password(self, password):
        """Check if the password is correct."""
        return PasswordManager.verify_password(password)
    

    

    
    def cancel(self, event=None):
        """Cancel the password dialog."""
        print("DEBUG: User cancelled password dialog")
        self.result = False
        self.dialog.destroy()
        if self.callback:
            self.callback(False)
    
    @staticmethod
    def prompt_password(root, callback=None):
        """Static method to prompt for password."""
        dialog = StartupPasswordDialog(root, callback)
        return dialog.result


def check_startup_password_required(root, callback=None):
    """
    Check if application startup requires password authentication.
    
    Args:
        root: The root window (will be hidden initially if password required)
        callback: Optional callback function to call after password verification
        
    Returns:
        bool: True if password was verified or not required, False if cancelled
    """
    from ui.auth.password_core import get_security_config
    
    print("DEBUG: check_startup_password_required called")
    
    config = get_security_config()
    
    # Debug: Check what the current protection status is
    is_protected = config.is_action_protected(ProtectedActions.OPEN_APPLICATION.value)
    print(f"DEBUG: OPEN_APPLICATION protection status: {is_protected}")
    print(f"DEBUG: All protected actions: {config.protected_actions}")
    
    # Check if application startup is protected
    if not is_protected:
        print("DEBUG: Startup protection not enabled, proceeding immediately")
        # No password required, proceed immediately
        if callback:
            print("DEBUG: Calling callback with True (no protection)")
            callback(True)
        return True
    
    # Check if a password is configured
    if not PasswordManager.is_security_configured():
        print("DEBUG: Startup protection enabled but no password configured, proceeding without protection")
        # Startup protection is enabled but no password is configured
        # This is an invalid state - proceed without protection
        if callback:
            print("DEBUG: Calling callback with True (no password configured)")
            callback(True)
        return True
    
    # Check if session timeout is enabled and session is still valid
    if config.is_session_timeout_enabled():
        timeout_minutes = config.get_session_timeout_minutes()
        if PasswordSessionManager.is_session_valid(ProtectedActions.OPEN_APPLICATION, timeout_minutes):
            print("DEBUG: Valid session found, proceeding without password prompt")
            # Session is still valid, proceed without password prompt
            if callback:
                print("DEBUG: Calling callback with True (valid session)")
                callback(True)
            return True
    
    print("DEBUG: Password required, hiding main window and showing dialog")
    # Password required, hide the main window and show dialog
    
    def password_callback(result):
        print(f"DEBUG: Password dialog callback called with result: {result}")
        if result:
            # Password verified successfully, record the session
            if config.is_session_timeout_enabled():
                PasswordSessionManager.record_successful_verification(ProtectedActions.OPEN_APPLICATION)
        if callback:
            print(f"DEBUG: Calling main callback with result: {result}")
            callback(result)
    
    return StartupPasswordDialog.prompt_password(root, password_callback) 