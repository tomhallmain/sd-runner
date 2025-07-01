from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QCheckBox, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal

from ui.dialog_base import DialogBase
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class PasswordAdminWindow(DialogBase):
    """Window for managing password protection settings."""
    
    # Class variables
    DEFAULT_PROTECTED_ACTIONS = {
        "nsfw_prompts": True,
        "edit_blacklist": True,
        "edit_schedules": True,
        "edit_expansions": True,
        "edit_presets": True,
        "edit_concepts": True,
        "access_admin": True  # This window itself
    }
    
    def __init__(self, parent=None, toast_callback=None):
        super().__init__(parent, _("Password Administration"), width=500, height=600)
        
        self.toast_callback = toast_callback
        self.action_checkboxes = {}
        
        # Load protected actions
        PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        
        self.setup_ui()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Title
        title_label = QLabel(_("Password Protection Settings"), self)
        title_label.setStyleSheet("font-weight: bold; font-size: 14px; margin-bottom: 10px;")
        self.add_widget_to_content(title_label)
        
        # Description
        desc_label = QLabel(_("Select which actions require password authentication:"), self)
        desc_label.setWordWrap(True)
        self.add_widget_to_content(desc_label)
        
        # Action checkboxes
        action_descriptions = {
            "nsfw_prompts": _("NSFW/NSFL Prompt Modes"),
            "edit_blacklist": _("Edit Blacklist"),
            "edit_schedules": _("Edit Schedules"),
            "edit_expansions": _("Edit Expansions"),
            "edit_presets": _("Edit Presets"),
            "edit_concepts": _("Edit Concepts"),
            "access_admin": _("Access Password Administration")
        }
        
        for action, description in action_descriptions.items():
            if action in PasswordAdminWindow.protected_actions:
                checkbox = QCheckBox(description, self)
                checkbox.setChecked(PasswordAdminWindow.protected_actions[action])
                checkbox.toggled.connect(lambda checked, action=action: self.update_protected_action(action, checked))
                self.action_checkboxes[action] = checkbox
                self.add_widget_to_content(checkbox)
        
        # Override create_buttons to add our custom buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()
        
        self.add_button(_("Save Settings"), self.save_settings)
        self.add_button(_("Reset to Defaults"), self.reset_to_defaults)
        self.add_button(_("Close"), self.close)
    
    def update_protected_action(self, action, checked):
        """Update a specific protected action."""
        PasswordAdminWindow.protected_actions[action] = checked
    
    def save_settings(self):
        """Save the current settings."""
        PasswordAdminWindow.store_protected_actions()
        if self.toast_callback:
            self.toast_callback(_("Password protection settings saved."))
    
    def reset_to_defaults(self):
        """Reset all settings to their default values."""
        reply = QMessageBox.question(
            self,
            _("Reset to Defaults"),
            _("Are you sure you want to reset all password protection settings to their default values?"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS.copy()
            
            # Update checkboxes
            for action, checkbox in self.action_checkboxes.items():
                checkbox.setChecked(PasswordAdminWindow.protected_actions.get(action, False))
            
            if self.toast_callback:
                self.toast_callback(_("Settings reset to defaults."))
    
    @staticmethod
    def set_protected_actions():
        """Load protected actions from cache or use defaults."""
        if not app_info_cache.get("protected_actions"):
            app_info_cache.set("protected_actions", PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS)
        return app_info_cache.get("protected_actions", default_val=PasswordAdminWindow.DEFAULT_PROTECTED_ACTIONS)
    
    @staticmethod
    def store_protected_actions():
        """Store protected actions to cache."""
        app_info_cache.set("protected_actions", PasswordAdminWindow.protected_actions)
    
    @staticmethod
    def is_action_protected(action_name):
        """Check if a specific action requires password authentication."""
        if not hasattr(PasswordAdminWindow, 'protected_actions'):
            PasswordAdminWindow.protected_actions = PasswordAdminWindow.set_protected_actions()
        return PasswordAdminWindow.protected_actions.get(action_name, False)


# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.app_style import AppStyle
    
    def mock_toast(message):
        print(f"Toast: {message}")
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    window = PasswordAdminWindow(toast_callback=mock_toast)
    window.show()
    
    sys.exit(app.exec()) 