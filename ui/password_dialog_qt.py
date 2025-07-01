from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QLineEdit, QMessageBox)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

from ui.app_style import AppStyle
from utils.translations import I18N

_ = I18N._


class PasswordDialog(QDialog):
    """Simple password dialog for authentication."""
    
    password_accepted = pyqtSignal()
    password_rejected = pyqtSignal()
    
    def __init__(self, parent=None, action_name="", callback=None):
        super().__init__(parent)
        self.action_name = action_name
        self.callback = callback
        self.result = False
        
        # Set up dialog properties
        self.setWindowTitle(_("Password Required"))
        self.setFixedSize(400, 200)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.Dialog)
        
        # Connect signals
        self.password_accepted.connect(self.on_password_accepted)
        self.password_rejected.connect(self.on_password_rejected)
        
        self.setup_ui()
        self.apply_style()
        
        # Focus on password entry
        self.password_entry.setFocus()
    
    def setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        
        # Title
        title_label = QLabel(_("Password Required"), self)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)
        
        # Action description
        action_label = QLabel(_("Password required for: {0}").format(self.action_name), self)
        action_label.setWordWrap(True)
        layout.addWidget(action_label)
        
        # Password entry
        password_label = QLabel(_("Password:"), self)
        layout.addWidget(password_label)
        
        self.password_entry = QLineEdit(self)
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_entry.returnPressed.connect(self.verify_password)
        layout.addWidget(self.password_entry)
        
        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        cancel_button = QPushButton(_("Cancel"), self)
        cancel_button.clicked.connect(self.cancel)
        button_layout.addWidget(cancel_button)
        
        ok_button = QPushButton(_("OK"), self)
        ok_button.clicked.connect(self.verify_password)
        button_layout.addWidget(ok_button)
        
        layout.addLayout(button_layout)
    
    def apply_style(self):
        """Apply styling to the dialog."""
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
            }}
            QLabel {{
                color: {AppStyle.FG_COLOR};
            }}
            QPushButton {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.FG_COLOR};
                padding: 5px;
                border-radius: 3px;
                min-width: 60px;
            }}
            QPushButton:hover {{
                background-color: {AppStyle.FG_COLOR};
                color: {AppStyle.BG_COLOR};
            }}
            QLineEdit {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.FG_COLOR};
                padding: 5px;
                border-radius: 3px;
            }}
        """)
    
    def verify_password(self):
        """Verify the entered password."""
        password = self.password_entry.text()
        
        # TODO: Implement actual password verification using the encryptor
        # For now, we'll use a simple check against a stored password
        # This should be replaced with proper password verification from the encryptor
        
        # Check if password is correct (placeholder implementation)
        if self.check_password(password):
            self.result = True
            self.password_accepted.emit()
            self.accept()
        else:
            QMessageBox.critical(self, _("Error"), _("Incorrect password"))
            self.password_entry.clear()
            self.password_entry.setFocus()
    
    def check_password(self, password):
        """Check if the password is correct."""
        # TODO: Implement proper password verification using the encryptor
        # This is a placeholder that should be replaced with actual verification
        # from the encryptor module
        
        # For now, return True to allow access (remove this in production)
        return True
    
    def cancel(self):
        """Cancel the password dialog."""
        self.result = False
        self.password_rejected.emit()
        self.reject()
    
    def on_password_accepted(self):
        """Handle password acceptance."""
        if self.callback:
            self.callback(True)
    
    def on_password_rejected(self):
        """Handle password rejection."""
        if self.callback:
            self.callback(False)
    
    @staticmethod
    def prompt_password(parent=None, action_name="", callback=None):
        """Static method to prompt for password."""
        dialog = PasswordDialog(parent, action_name, callback)
        result = dialog.exec()
        return result == QDialog.DialogCode.Accepted


# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    def password_callback(result):
        if result:
            print("Password accepted!")
        else:
            print("Password cancelled or incorrect.")
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    result = PasswordDialog.prompt_password(action_name="Edit Blacklist", callback=password_callback)
    print(f"Dialog result: {result}")
    
    sys.exit(app.exec()) 