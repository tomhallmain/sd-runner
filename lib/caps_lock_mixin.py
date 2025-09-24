"""
Caps lock detection mixin for password dialogs.
This mixin provides shared functionality for detecting and displaying caps lock state.
"""

import tkinter.font as fnt
from utils.utils import ModifierKey
from utils.translations import I18N

_ = I18N._


class CapsLockMixin:
    """Mixin class providing caps lock detection functionality for password dialogs."""
    
    def setup_caps_lock_detection(self, password_frame, password_entry, dialog_root):
        """
        Set up caps lock detection for a password dialog.
        
        Args:
            password_frame: The frame containing the password entry
            password_entry: The password entry widget
            dialog_root: The root window/dialog for event binding
        """
        # Store references for caps lock detection
        self.password_entry = password_entry
        self.dialog_root = dialog_root
        
        # Caps lock indicator
        self.caps_lock_label = self._create_caps_lock_label(password_frame)
        
        # Bind key events to detect caps lock state changes
        self.dialog_root.bind("<KeyPress>", self.on_key_press)
        self.dialog_root.bind("<KeyRelease>", self.on_key_release)
        
        # Check initial caps lock state after a short delay to ensure UI is ready
        self.dialog_root.after(100, self.check_initial_caps_lock_state)
    
    def _create_caps_lock_label(self, parent_frame):
        """Create the caps lock indicator label."""
        from tkinter import Label
        from ui.app_style import AppStyle
        
        # Create a Label widget (not using parent_frame.__class__)
        caps_lock_label = Label(parent_frame, text="", 
                                  font=fnt.Font(size=9, slant="italic"))
        caps_lock_label.pack(anchor="w", pady=(5, 0))
        caps_lock_label.config(bg=AppStyle.BG_COLOR, fg="#FF6B6B")  # Red color for warning
        return caps_lock_label
    
    def on_key_press(self, event):
        """Handle key press events to detect caps lock state."""
        self.update_caps_lock_indicator(event)
    
    def on_key_release(self, event):
        """Handle key release events to detect caps lock state."""
        self.update_caps_lock_indicator(event)
    
    def update_caps_lock_indicator(self, event):
        """Update the caps lock indicator based on current state."""
        if hasattr(self, 'caps_lock_label'):
            caps_lock_on = self.is_caps_lock_on(event)
            if caps_lock_on:
                self.caps_lock_label.config(text=_("⚠ Caps Lock is ON"), fg="#FF6B6B")
            else:
                self.caps_lock_label.config(text="", fg="#FF6B6B")
    
    def is_caps_lock_on(self, event):
        """Check if caps lock is currently enabled."""
        return bool(event.state & ModifierKey.CAPS_LOCK.value)
    
    def check_initial_caps_lock_state(self):
        """Check the initial caps lock state when the dialog opens."""
        # We'll rely on the user's first actual keypress to detect caps lock state
        # This avoids leaving unwanted characters in the password field
        pass
