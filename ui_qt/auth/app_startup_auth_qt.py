"""
Application startup authentication (PySide6).

Port of auth/app_startup_auth.py.  Uses the existing Qt PasswordDialog
infrastructure rather than a custom Tkinter dialog.  The public entry
point is ``check_startup_password_required(callback)``.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QMessageBox
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager, get_security_config
from ui.auth.password_session_manager import PasswordSessionManager
from ui.auth.password_dialog import PasswordLineEdit
from utils.constants import ProtectedActions
from utils.translations import I18N

_ = I18N._


class StartupPasswordDialog(QDialog):
    """Simple modal password dialog shown before the main window is created."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle(_("Application Password Required"))
        self.setFixedSize(500, 260)
        self.setWindowFlags(
            self.windowFlags() | Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(True)
        self.setStyleSheet(AppStyle.get_stylesheet())
        self.result = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        # Title
        title_label = QLabel(_("Application Password Required"))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Description
        desc_label = QLabel(_("A password is required to open this application."))
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addSpacing(10)

        # Password entry
        password_label = QLabel(_("Password:"))
        layout.addWidget(password_label)

        self.caps_lock_label = QLabel("")
        caps_font = QFont()
        caps_font.setPointSize(9)
        caps_font.setItalic(True)
        self.caps_lock_label.setFont(caps_font)
        self.caps_lock_label.setStyleSheet("color: #FF6B6B;")

        self.password_entry = PasswordLineEdit(self, self.caps_lock_label)
        self.password_entry.setEchoMode(self.password_entry.EchoMode.Password)
        self.password_entry.setMinimumWidth(200)
        self.password_entry.setMaxLength(256)
        layout.addWidget(self.password_entry)
        layout.addWidget(self.caps_lock_label)

        # Buttons
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(self._cancel)
        button_layout.addWidget(cancel_btn)
        ok_btn = QPushButton(_("OK"))
        ok_btn.clicked.connect(self._verify_password)
        button_layout.addWidget(ok_btn)
        layout.addLayout(button_layout)

        self.password_entry.setFocus()
        self._position_dialog()

    # ------------------------------------------------------------------

    def _position_dialog(self):
        """Center the dialog on the same display where the main window was last shown."""
        try:
            from utils.app_info_cache_qt import app_info_cache
            from lib.position_data_qt import PositionData

            position_data = app_info_cache.get_display_position()
            if position_data and position_data.is_valid():
                dlg_w, dlg_h = self.width(), self.height()
                dlg_x = position_data.x + (position_data.width - dlg_w) // 2
                dlg_y = position_data.y + (position_data.height - dlg_h) // 2

                dlg_pos = PositionData(dlg_x, dlg_y, dlg_w, dlg_h)
                if dlg_pos.is_visible_on_display():
                    self.move(dlg_x, dlg_y)
                    return

            # Fallback: center on the primary screen
            from PySide6.QtWidgets import QApplication
            screen = QApplication.primaryScreen()
            if screen:
                geo = screen.availableGeometry()
                self.move(
                    geo.x() + (geo.width() - self.width()) // 2,
                    geo.y() + (geo.height() - self.height()) // 2,
                )
        except Exception:
            pass  # silently fall back to default Qt positioning

    def _verify_password(self):
        password = self.password_entry.text()
        if PasswordManager.verify_password(password):
            self.result = True
            self.accept()
        else:
            QMessageBox.critical(self, _("Error"), _("Incorrect password"))
            self.password_entry.clear()
            self.password_entry.setFocus()

    def _cancel(self):
        self.result = False
        self.reject()

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() == Qt.Key.Key_Escape:
            self._cancel()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._verify_password()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):  # noqa: N802
        if not self.result:
            self.result = False
        event.accept()


def check_startup_password_required(callback=None):
    """
    Check whether the application startup requires a password.

    If protection is disabled or no password is configured, ``callback(True)``
    is called immediately.  Otherwise a modal dialog is shown.

    Args:
        callback: ``callback(True)`` on success, ``callback(False)`` on cancel.
    """
    config = get_security_config()

    # Not protected
    if not config.is_action_protected(ProtectedActions.OPEN_APPLICATION.value):
        if callback:
            callback(True)
        return True

    # Protected but no password configured — invalid state, allow through
    if not PasswordManager.is_security_configured():
        if callback:
            callback(True)
        return True

    # Session still valid
    if config.is_session_timeout_enabled():
        timeout_minutes = config.get_session_timeout_minutes()
        if PasswordSessionManager.is_session_valid(
            ProtectedActions.OPEN_APPLICATION, timeout_minutes
        ):
            if callback:
                callback(True)
            return True

    # Show the password dialog
    dialog = StartupPasswordDialog()
    dialog.exec()

    if dialog.result:
        # Record session on success
        if config.is_session_timeout_enabled():
            PasswordSessionManager.record_successful_verification(
                ProtectedActions.OPEN_APPLICATION
            )

    if callback:
        callback(dialog.result)
    return dialog.result
