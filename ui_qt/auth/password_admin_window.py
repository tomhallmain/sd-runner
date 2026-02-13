"""
Password administration window (PySide6).
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QFrame,
    QWidget,
    QMessageBox,
    QScrollArea,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from lib.multi_display_qt import SmartWindow, display_manager
from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager, get_security_config
from ui.auth.password_utils import require_password
from utils.constants import ProtectedActions
from utils.translations import I18N

_ = I18N._


class PasswordChangeDialog(QDialog):
    """Dialog for changing password (current, new, confirm)."""

    def __init__(self, parent, app_actions):
        super().__init__(parent)
        self.app_actions = app_actions
        self.setWindowTitle(_("Change Password"))
        self.setFixedSize(400, 320)
        self.setModal(True)
        if parent:
            try:
                display_manager.position_window_on_same_display(
                    parent, self, offset_x=50, offset_y=50, geometry="400x320"
                )
            except Exception:
                pass
        self.setStyleSheet(AppStyle.get_stylesheet())

        layout = QVBoxLayout(self)
        layout.setSpacing(15)

        title_label = QLabel(_("Change Password"))
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        current_label = QLabel(_("Current Password:"))
        layout.addWidget(current_label)
        self.current_entry = QLineEdit(self)
        self.current_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.current_entry.setMinimumWidth(250)
        layout.addWidget(self.current_entry)

        new_label = QLabel(_("New Password:"))
        layout.addWidget(new_label)
        self.new_entry = QLineEdit(self)
        self.new_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.new_entry.setMinimumWidth(250)
        layout.addWidget(self.new_entry)

        confirm_label = QLabel(_("Confirm New Password:"))
        layout.addWidget(confirm_label)
        self.confirm_entry = QLineEdit(self)
        self.confirm_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_entry.setMinimumWidth(250)
        layout.addWidget(self.confirm_entry)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self.reject)
        button_layout.addWidget(cancel_btn)
        ok_btn = QPushButton(_("Change Password"))
        ok_btn.clicked.connect(self.change_password)
        button_layout.addWidget(ok_btn)
        layout.addLayout(button_layout)

        self.current_entry.setFocus()

    def change_password(self):
        current_pwd = self.current_entry.text()
        new_pwd = self.new_entry.text()
        confirm_pwd = self.confirm_entry.text()

        if not PasswordManager.verify_password(current_pwd):
            self._show_error(_("Current password is incorrect."))
            return

        if new_pwd != confirm_pwd:
            self._show_error(_("New passwords do not match."))
            return

        if len(new_pwd) < 6:
            self._show_error(_("Password must be at least 6 characters long."))
            return

        if PasswordManager.set_password(new_pwd):
            from ui.auth.password_session_manager import PasswordSessionManager

            PasswordSessionManager.clear_all_sessions()
            if hasattr(self.app_actions, "toast"):
                self.app_actions.toast(_("Password changed successfully."))
            else:
                QMessageBox.information(
                    self, _("Info"), _("Password changed successfully.")
                )
            self.accept()
        else:
            self._show_error(_("Failed to change password."))

    def _show_error(self, message):
        if hasattr(self.app_actions, "alert"):
            self.app_actions.alert(
                _("Administration Error"), message, kind="error"
            )
        else:
            QMessageBox.critical(self, _("Error"), message)


class PasswordAdminWindow(SmartWindow):
    top_level = None

    def __init__(self, master, app_actions):
        # Match Tk: position at top of same display (new_y=0), offset horizontally from parent
        new_x = master.geometry().x() + 50 if master and hasattr(master, "geometry") else 50
        new_y = 0
        positioned_geometry = f"{PasswordAdminWindow.get_geometry()}+{new_x}+{new_y}"

        super().__init__(
            persistent_parent=master,
            title=_("Password Administration"),
            geometry=positioned_geometry,
            auto_position=False,
        )
        self._parent = master
        self.app_actions = app_actions
        self.setMinimumSize(400, 400)

        PasswordAdminWindow.top_level = self
        self.master = self

        self.config = get_security_config()

        self.action_vars = {}
        for action in self.config.protected_actions.keys():
            self.action_vars[action] = self.config.protected_actions[action]

        for action_enum in ProtectedActions:
            if action_enum == ProtectedActions.OPEN_APPLICATION:
                continue
            action = action_enum.value
            if action not in self.action_vars:
                self.action_vars[action] = True

        self.session_timeout_enabled = self.config.session_timeout_enabled
        self.session_timeout_minutes = str(self.config.session_timeout_minutes)
        self.show_security_advice = self.config.is_security_advice_enabled()
        self.new_password = ""
        self.confirm_password = ""

        self.setStyleSheet(AppStyle.get_stylesheet())
        self.setup_ui()
        self.show()

    @staticmethod
    def get_geometry(is_gui=True):
        width = 900
        height = 700
        return f"{width}x{height}"

    def setup_ui(self):
        """Set up the UI components in a two-column layout."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(15, 15, 15, 15)

        title_label = QLabel(_("Password Protection Settings"))
        title_font = QFont()
        title_font.setPointSize(12)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        content = QWidget(self)
        content_layout = QGridLayout(content)

        left_frame = QFrame(content)
        left_layout = QVBoxLayout(left_frame)
        left_title = QLabel(_("Protected Actions"))
        left_title_font = QFont()
        left_title_font.setPointSize(11)
        left_title_font.setBold(True)
        left_title.setFont(left_title_font)
        left_layout.addWidget(left_title)

        left_desc = QLabel(
            _("Select which actions require password authentication:")
        )
        left_desc.setWordWrap(True)
        left_desc.setMaximumWidth(350)
        left_layout.addWidget(left_desc)

        self.action_checkboxes = {}
        for action_enum in ProtectedActions:
            if action_enum == ProtectedActions.OPEN_APPLICATION:
                continue
            action = action_enum.value
            if action not in self.action_vars:
                continue
            is_admin_action = action == ProtectedActions.ACCESS_ADMIN.value
            text = action_enum.get_description()
            if is_admin_action:
                text = text + " " + _("(Always protected if a password is set)")

            cb = QCheckBox(text)
            cb.setChecked(self.action_vars[action])
            cb.stateChanged.connect(self.update_protected_actions)
            if is_admin_action:
                cb.setEnabled(False)
            left_layout.addWidget(cb)
            self.action_checkboxes[action] = cb

        left_layout.addStretch()
        content_layout.addWidget(left_frame, 0, 0)

        right_frame = QFrame(content)
        right_layout = QVBoxLayout(right_frame)

        session_title = QLabel(_("Session Timeout Settings"))
        session_title_font = QFont()
        session_title_font.setPointSize(11)
        session_title_font.setBold(True)
        session_title.setFont(session_title_font)
        right_layout.addWidget(session_title)

        self.session_timeout_check = QCheckBox(
            _("Enable session timeout (remember password for a period)")
        )
        self.session_timeout_check.setChecked(self.config.session_timeout_enabled)
        self.session_timeout_check.stateChanged.connect(self.update_session_settings)
        right_layout.addWidget(self.session_timeout_check)

        timeout_row = QWidget()
        timeout_layout = QHBoxLayout(timeout_row)
        timeout_layout.setContentsMargins(20, 0, 0, 0)
        timeout_label = QLabel(_("Session timeout duration (minutes):"))
        timeout_layout.addWidget(timeout_label)
        self.timeout_entry = QLineEdit(timeout_row)
        self.timeout_entry.setMaximumWidth(80)
        self.timeout_entry.setText(str(self.config.session_timeout_minutes))
        self.timeout_entry.textChanged.connect(self.update_session_settings)
        timeout_layout.addWidget(self.timeout_entry)
        timeout_layout.addStretch()
        right_layout.addWidget(timeout_row)

        advice_title = QLabel(_("Security Advice Settings"))
        advice_title.setFont(session_title_font)
        right_layout.addWidget(advice_title)

        self.show_advice_check = QCheckBox(
            _("Show security advice when no password is configured")
        )
        self.show_advice_check.setChecked(self.config.is_security_advice_enabled())
        self.show_advice_check.stateChanged.connect(self.update_security_advice_settings)
        right_layout.addWidget(self.show_advice_check)

        password_title = QLabel(_("Password Setup"))
        password_title.setFont(session_title_font)
        right_layout.addWidget(password_title)

        password_configured = PasswordManager.is_security_configured()

        if password_configured:
            status_label = QLabel(_("Password is configured"))
            status_label.setStyleSheet("color: green;")
            right_layout.addWidget(status_label)

            change_btn = QPushButton(_("Change Password"))
            change_btn.clicked.connect(self.show_change_password_dialog)
            right_layout.addWidget(change_btn)

            remove_btn = QPushButton(_("Remove Password"))
            remove_btn.clicked.connect(self.remove_password)
            right_layout.addWidget(remove_btn)
        else:
            setup_label = QLabel(_("Set up a password to enable protection:"))
            setup_label.setWordWrap(True)
            setup_label.setMaximumWidth(350)
            right_layout.addWidget(setup_label)

            new_pwd_row = QWidget()
            new_pwd_layout = QHBoxLayout(new_pwd_row)
            new_pwd_layout.setContentsMargins(20, 0, 0, 0)
            new_pwd_label = QLabel(_("New Password:"))
            new_pwd_layout.addWidget(new_pwd_label)
            self.new_pwd_entry = QLineEdit(new_pwd_row)
            self.new_pwd_entry.setEchoMode(QLineEdit.EchoMode.Password)
            self.new_pwd_entry.setMaximumWidth(200)
            new_pwd_layout.addWidget(self.new_pwd_entry)
            right_layout.addWidget(new_pwd_row)

            confirm_pwd_row = QWidget()
            confirm_pwd_layout = QHBoxLayout(confirm_pwd_row)
            confirm_pwd_layout.setContentsMargins(20, 0, 0, 0)
            confirm_pwd_label = QLabel(_("Confirm Password:"))
            confirm_pwd_layout.addWidget(confirm_pwd_label)
            self.confirm_pwd_entry = QLineEdit(confirm_pwd_row)
            self.confirm_pwd_entry.setEchoMode(QLineEdit.EchoMode.Password)
            self.confirm_pwd_entry.setMaximumWidth(200)
            confirm_pwd_layout.addWidget(self.confirm_pwd_entry)
            right_layout.addWidget(confirm_pwd_row)

            set_pwd_btn = QPushButton(_("Set Password"))
            set_pwd_btn.clicked.connect(self.set_password)
            right_layout.addWidget(set_pwd_btn)

        right_layout.addStretch()
        content_layout.addWidget(right_frame, 0, 1)

        layout.addWidget(content)

        button_frame = QWidget(self)
        button_layout = QHBoxLayout(button_frame)
        button_layout.addStretch()

        reset_btn = QPushButton(_("Reset to Defaults"))
        reset_btn.clicked.connect(self.reset_to_defaults)
        button_layout.addWidget(reset_btn)

        current_btn = QPushButton(_("Set to Current"))
        current_btn.clicked.connect(self.set_to_current)
        button_layout.addWidget(current_btn)

        save_json_btn = QPushButton(_("Export Cache as JSON"))
        save_json_btn.clicked.connect(self.export_cache_as_json)
        button_layout.addWidget(save_json_btn)

        save_btn = QPushButton(_("Save Settings"))
        save_btn.clicked.connect(self.save_settings)
        button_layout.addWidget(save_btn)

        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close_window)
        button_layout.addWidget(close_btn)

        layout.addWidget(button_frame)

    def update_protected_actions(self):
        """Update the protected actions dictionary when checkboxes change."""
        for action, cb in self.action_checkboxes.items():
            self.config.set_action_protected(action, cb.isChecked())

    def update_session_settings(self, event=None):
        """Update the session timeout settings when UI elements change."""
        try:
            self.config.set_session_timeout_enabled(
                self.session_timeout_check.isChecked()
            )
            timeout_minutes = int(self.timeout_entry.text())
            self.config.set_session_timeout_minutes(timeout_minutes)
        except ValueError:
            self.timeout_entry.setText(str(self.config.session_timeout_minutes))

    def update_security_advice_settings(self):
        """Update security advice settings."""
        self.config.set_security_advice_enabled(self.show_advice_check.isChecked())

    def clear_sessions(self):
        """Clear all sessions when settings change."""
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
        from lib.qt_alert import qt_alert
        if not qt_alert(
            self,
            _("Reset to Defaults"),
            _("Are you sure you want to reset all password protection settings to their default values?"),
            kind="askyesno",
        ):
            return

        self.config.reset_to_defaults()

        for action, cb in self.action_checkboxes.items():
            cb.setChecked(self.config.protected_actions.get(action, False))

        self.session_timeout_check.setChecked(self.config.session_timeout_enabled)
        self.timeout_entry.setText(str(self.config.session_timeout_minutes))
        self.show_advice_check.setChecked(
            self.config.is_security_advice_enabled()
        )

        self.clear_sessions()

        self._show_toast_or_messagebox(_("Settings reset to defaults."))

    def set_to_current(self):
        """Restore settings to their current saved state."""
        from lib.qt_alert import qt_alert
        if not qt_alert(
            self,
            _("Set to Current"),
            _("Are you sure you want to restore all settings to their current saved state? This will discard any unsaved changes."),
            kind="askyesno",
        ):
            return

        self.config._load_settings()

        for action, cb in self.action_checkboxes.items():
            cb.setChecked(self.config.protected_actions.get(action, False))

        self.session_timeout_check.setChecked(self.config.session_timeout_enabled)
        self.timeout_entry.setText(str(self.config.session_timeout_minutes))
        self.show_advice_check.setChecked(
            self.config.is_security_advice_enabled()
        )

        self._show_toast_or_messagebox(
            _("Settings restored to current saved state.")
        )

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def set_password(self):
        """Set a new password."""
        new_password = self.new_pwd_entry.text()
        confirm_password = self.confirm_pwd_entry.text()

        if not new_password:
            self._show_toast_or_messagebox(
                _("Please enter a password."), error=True
            )
            return

        if new_password != confirm_password:
            self._show_toast_or_messagebox(
                _("Passwords do not match."), error=True
            )
            return

        if len(new_password) < 6:
            self._show_toast_or_messagebox(
                _("Password must be at least 6 characters long."), error=True
            )
            return

        if PasswordManager.set_password(new_password):
            self.clear_sessions()
            self._show_toast_or_messagebox(_("Password set successfully."))
            self.new_pwd_entry.clear()
            self.confirm_pwd_entry.clear()
            self.refresh_ui()
        else:
            self._show_toast_or_messagebox(
                _("Failed to set password."), error=True
            )

    def show_change_password_dialog(self):
        """Show dialog to change password."""
        dialog = PasswordChangeDialog(self, self.app_actions)
        dialog.exec()

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def remove_password(self):
        """Remove the current password."""
        from lib.qt_alert import qt_alert
        if not qt_alert(
            self,
            _("Remove Password"),
            _("Are you sure you want to remove password protection? This will disable all password requirements."),
            kind="askyesno",
        ):
            return

        if PasswordManager.clear_password():
            self.clear_sessions()
            self._show_toast_or_messagebox(_("Password removed successfully."))
            self.refresh_ui()
        else:
            self._show_toast_or_messagebox(
                _("Failed to remove password."), error=True
            )

    def refresh_ui(self):
        """Refresh the UI to reflect current state."""
        if PasswordAdminWindow.top_level is self:
            PasswordAdminWindow.top_level = None
        self.close()
        new_win = PasswordAdminWindow(self._parent, self.app_actions)
        new_win.show()

    def close_window(self, event=None):
        """Close the window."""
        if PasswordAdminWindow.top_level is self:
            PasswordAdminWindow.top_level = None
        self.close()

    def _show_toast_or_messagebox(self, message, error=False):
        """Show a toast if available, otherwise use a messagebox."""
        if hasattr(self, "app_actions") and hasattr(self.app_actions, "toast"):
            if error:
                self.app_actions.alert(
                    _("Administration Error"), message, kind="error"
                )
            else:
                self.app_actions.toast(message)
        else:
            if error:
                QMessageBox.critical(self, _("Error"), message)
            else:
                QMessageBox.information(self, _("Info"), message)

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def export_cache_as_json(self):
        """Export the app_info_cache as a JSON file (not encoded)."""
        from utils.app_info_cache import app_info_cache

        try:
            json_path = app_info_cache.export_as_json()
            self._show_toast_or_messagebox(
                _("Cache exported as JSON to:") + "\n" + json_path
            )
        except Exception as e:
            self._show_toast_or_messagebox(
                _("Failed to export cache as JSON:") + "\n" + str(e), error=True
            )

    def closeEvent(self, event):
        if PasswordAdminWindow.top_level is self:
            PasswordAdminWindow.top_level = None
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close_window()
            return
        super().keyPressEvent(event)
