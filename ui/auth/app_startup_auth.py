"""
Application startup authentication module.
This module handles password protection for the entire application startup.
It creates the application in a hidden state and only shows it after password verification.
Only shows a password dialog if startup protection is enabled and a password is configured.
"""
import time

import tkinter as tk
from tkinter import messagebox
import tkinter.font as fnt
from ttkthemes import ThemedTk

from lib.caps_lock_mixin import CapsLockMixin
from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager
from ui.auth.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions
from utils.translations import I18N

_ = I18N._


class StartupPasswordDialog(CapsLockMixin):
    """Password dialog for application startup authentication."""
    
    def __init__(self, root, callback=None):
        self.root = root
        self.callback = callback
        self.result = None
        
        # Configure the main window for password dialog
        self.root.title(_("Application Password Required"))
        self.root.geometry("500x300")
        self.root.resizable(False, False)
        
        # Center the dialog
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() // 2) - (500 // 2)
        y = (self.root.winfo_screenheight() // 2) - (300 // 2)
        self.root.geometry(f"500x300+{x}+{y}")
        
        self.setup_ui()
        
        # Bind events
        self.root.bind("<Return>", self.verify_password)
        self.root.bind("<Escape>", self.cancel)
        self.root.protocol("WM_DELETE_WINDOW", self.cancel)
        
        # Focus on password entry
        self.password_entry.focus()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Main frame
        main_frame = tk.Frame(self.root, bg=AppStyle.BG_COLOR)
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
        
        # Set up caps lock detection using mixin
        self.setup_caps_lock_detection(password_frame, self.password_entry, self.root)

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
        
        # Check if password is correct
        if self.check_password(password):
            self.result = True
            self.root.destroy()
            if self.callback:
                self.callback(True)
        else:
            messagebox.showerror(_("Error"), _("Incorrect password"))
            self.password_var.set("")
            self.password_entry.focus()
    
    def check_password(self, password):
        """Check if the password is correct."""
        return PasswordManager.verify_password(password)
    
    def cancel(self, event=None):
        """Cancel the password dialog."""
        self.result = False
        self.root.destroy()
        if self.callback:
            self.callback(False)
    
    @staticmethod
    def prompt_password(root, callback=None):
        """Static method to prompt for password."""
        dialog = StartupPasswordDialog(root, callback)
        # The dialog will handle its own lifecycle through the mainloop
        return dialog.result


def check_startup_password_required(callback=None):
    """
    Check if application startup requires password authentication.
    
    Args:
        callback: Optional callback function to call after password verification
        
    Returns:
        bool: True if password was verified or not required, False if cancelled
    """
    from ui.auth.password_core import get_security_config
    
    config = get_security_config()
    
    # Check if application startup is protected
    is_protected = config.is_action_protected(ProtectedActions.OPEN_APPLICATION.value)
    
    if not is_protected:
        # No password required, proceed immediately
        if callback:
            callback(True)
        return True
    
    # Check if a password is configured
    if not PasswordManager.is_security_configured():
        # Startup protection is enabled but no password is configured
        # This is an invalid state - proceed without protection
        if callback:
            callback(True)
        return True
    
    # Check if session timeout is enabled and session is still valid
    if config.is_session_timeout_enabled():
        timeout_minutes = config.get_session_timeout_minutes()
        if PasswordSessionManager.is_session_valid(ProtectedActions.OPEN_APPLICATION, timeout_minutes):
            # Session is still valid, proceed without password prompt
            if callback:
                callback(True)
            return True
    
    def password_callback(result):
        if result:
            # Password verified successfully, record the session
            if config.is_session_timeout_enabled():
                PasswordSessionManager.record_successful_verification(ProtectedActions.OPEN_APPLICATION)
        if callback:
            callback(result)
    
    # Create the intermediary root for the password dialog
    intermediary_root = ThemedTk(theme="black", themebg="black")
    
    # Create the password dialog
    dialog = StartupPasswordDialog(intermediary_root, password_callback)
    
    # Start the mainloop - this will show the password dialog
    intermediary_root.mainloop()
    
    return dialog.result 