"""
Password dialog (PySide6).
"""

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from lib.multi_display_qt import SmartDialog
from ui.app_style import AppStyle
from ui.auth.password_core import PasswordManager
from ui.auth.password_session_manager import PasswordSessionManager
from utils.translations import I18N

_ = I18N._


def _is_caps_lock_on() -> bool:
    """Detect caps lock state using native platform API."""
    import platform
    if platform.system() == "Windows":
        try:
            import ctypes
            # GetKeyState(VK_CAPITAL=0x14): low bit == 1 means toggled ON
            return bool(ctypes.windll.user32.GetKeyState(0x14) & 1)
        except Exception:
            pass
    elif platform.system() == "Darwin":
        try:
            import subprocess
            # ioreg reports the HIDCapsLockState
            out = subprocess.check_output(
                ["ioreg", "-n", "IOHIDKeyboard", "-r"],
                timeout=1, text=True,
            )
            return "CapsLockState" in out and '"CapsLockState" = Yes' in out
        except Exception:
            pass
    # Linux / fallback: not reliably detectable without X11/Wayland bindings
    return False


class PasswordLineEdit(QLineEdit):
    """QLineEdit that updates a caps lock warning label on key events."""

    def __init__(self, parent, caps_label):
        super().__init__(parent)
        self.caps_label = caps_label

    def _update_caps_indicator(self):
        if _is_caps_lock_on():
            self.caps_label.setText(_("⚠ Caps Lock is ON"))
        else:
            self.caps_label.setText("")

    def keyPressEvent(self, event):
        super().keyPressEvent(event)
        self._update_caps_indicator()

    def keyReleaseEvent(self, event):
        super().keyReleaseEvent(event)
        self._update_caps_indicator()


class PasswordDialog(SmartDialog):
    """Simple password dialog for authentication."""

    def __init__(
        self,
        master,
        config,
        action_name,
        callback=None,
        app_actions=None,
        action_enum=None,
        custom_text=None,
        allow_unauthenticated=False,
    ):
        password_configured = PasswordManager.is_security_configured()
        if custom_text and len(custom_text) > 100:
            width = 500 if password_configured else 550
            height = 400 if password_configured else 450
        else:
            width = 450 if password_configured else 500
            height = 300 if password_configured else 350

        title = (
            _("Password Required")
            if password_configured
            else _("Password Protection")
        )
        super().__init__(
            parent=master,
            title=title,
            geometry=f"{width}x{height}",
            center=True,
        )
        self.master = master
        self.config = config
        self.action_name = action_name
        self.callback = callback
        self.app_actions = app_actions
        self.action_enum = action_enum
        self.custom_text = custom_text
        self.allow_unauthenticated = allow_unauthenticated
        self.result = False
        self._cancel_called = False
        self.password_configured = password_configured

        self.setFixedSize(width, height)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.Dialog)
        self.setModal(True)

        self.setStyleSheet(AppStyle.get_stylesheet())
        self.setup_ui()

        if self.password_configured:
            self.password_entry.setFocus()

    def _is_password_configured(self):
        """Check if a password is configured for the application."""
        return PasswordManager.is_security_configured()

    def _should_show_security_advice(self):
        """Check if security advice should be shown."""
        return self.config.is_security_advice_enabled()

    def setup_ui(self):
        """Set up the UI components."""
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)

        if self.password_configured:
            self._setup_password_ui(layout)
        else:
            if self._should_show_security_advice():
                self._setup_advertisement_ui(layout)
            else:
                self.cancel(result=True)

    def _setup_password_ui(self, layout):
        """Set up UI for password entry."""
        title_label = QLabel(_("Password Required"))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        action_label = QLabel(
            _("Password required for: {0}").format(self.action_name)
        )
        action_label.setWordWrap(True)
        action_label.setMaximumWidth(400)
        layout.addWidget(action_label)

        if self.custom_text:
            custom_label = QLabel(self.custom_text)
            custom_label.setWordWrap(True)
            custom_label.setMaximumWidth(400)
            custom_font = QFont()
            custom_font.setPointSize(9)
            custom_label.setFont(custom_font)
            layout.addWidget(custom_label)
        else:
            spacer = QLabel("")
            layout.addWidget(spacer)

        password_label = QLabel(_("Password:"))
        layout.addWidget(password_label)

        self.caps_lock_label = QLabel("")
        caps_font = QFont()
        caps_font.setPointSize(9)
        caps_font.setItalic(True)
        self.caps_lock_label.setFont(caps_font)
        self.caps_lock_label.setStyleSheet("color: #FF6B6B;")

        self.password_entry = PasswordLineEdit(self, self.caps_lock_label)
        self.password_entry.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_entry.setMinimumWidth(200)
        self.password_entry.setMaxLength(256)
        layout.addWidget(self.password_entry)
        layout.addWidget(self.caps_lock_label)

        button_layout = QHBoxLayout()
        button_layout.addStretch()
        cancel_btn = QPushButton(_("Cancel"))
        cancel_btn.clicked.connect(lambda: self.cancel(result=False))
        button_layout.addWidget(cancel_btn)
        ok_btn = QPushButton(_("OK"))
        ok_btn.clicked.connect(self.verify_password)
        button_layout.addWidget(ok_btn)
        layout.addLayout(button_layout)

    def _setup_advertisement_ui(self, layout):
        """Set up UI for password protection advertisement."""
        title_label = QLabel(_("Password Protection Available"))
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        action_label = QLabel(
            _("This action requires password protection: {0}").format(
                self.action_name
            )
        )
        action_label.setWordWrap(True)
        action_label.setMaximumWidth(450)
        layout.addWidget(action_label)

        if self.custom_text:
            custom_label = QLabel(self.custom_text)
            custom_label.setWordWrap(True)
            custom_label.setMaximumWidth(450)
            custom_font = QFont()
            custom_font.setPointSize(9)
            custom_label.setFont(custom_font)
            layout.addWidget(custom_label)

        if self.allow_unauthenticated:
            info_text = _(
                "Password protection is not currently configured. You can:"
            )
            info_label = QLabel(info_text)
            info_label.setWordWrap(True)
            info_label.setMaximumWidth(450)
            layout.addWidget(info_label)

            option1 = QLabel(
                _(
                    "• Configure password protection for sensitive actions"
                )
            )
            option1.setWordWrap(True)
            option1.setMaximumWidth(400)
            layout.addWidget(option1)

            option2 = QLabel(
                _("• Continue without password protection (less secure)")
            )
            option2.setWordWrap(True)
            option2.setMaximumWidth(400)
            layout.addWidget(option2)

            self.dont_show_again_var = QCheckBox(
                _("Don't show this security advice again")
            )
            self.dont_show_again_var.setChecked(
                not self.config.is_security_advice_enabled()
            )
            layout.addWidget(self.dont_show_again_var)

            button_layout = QHBoxLayout()
            button_layout.addStretch()
            cancel_btn = QPushButton(_("Cancel"))
            cancel_btn.clicked.connect(lambda: self.cancel(result=False))
            button_layout.addWidget(cancel_btn)
            continue_btn = QPushButton(_("Continue Without Protection"))
            continue_btn.clicked.connect(self.continue_without_protection)
            button_layout.addWidget(continue_btn)
            configure_btn = QPushButton(_("Configure Protection"))
            configure_btn.clicked.connect(self.open_password_admin)
            button_layout.addWidget(configure_btn)
            layout.addLayout(button_layout)
        else:
            info_text = _(
                "Password protection is required for this action but is not currently configured."
            )
            info_label = QLabel(info_text)
            info_label.setWordWrap(True)
            info_label.setMaximumWidth(450)
            layout.addWidget(info_label)

            button_layout = QHBoxLayout()
            button_layout.addStretch()
            cancel_btn = QPushButton(_("Cancel"))
            cancel_btn.clicked.connect(lambda: self.cancel(result=False))
            button_layout.addWidget(cancel_btn)
            configure_btn = QPushButton(_("Configure Protection"))
            configure_btn.clicked.connect(self.open_password_admin)
            button_layout.addWidget(configure_btn)
            layout.addLayout(button_layout)

    def verify_password(self, event=None):
        """Verify the entered password."""
        password = self.password_entry.text()

        if self.check_password(password):
            self.cancel(result=True)
        else:
            QMessageBox.critical(
                self,
                _("Error"),
                _("Incorrect password"),
            )
            self.password_entry.clear()
            self.password_entry.setFocus()

    def check_password(self, password):
        """Check if the password is correct."""
        return PasswordManager.verify_password(password)

    def open_password_admin(self):
        """Open the password administration window."""
        self.cancel(result=False)

        if self.app_actions and getattr(
            self.app_actions, "open_password_admin_window", None
        ):
            self.app_actions.open_password_admin_window()
        else:
            raise Exception("AppActions failed to initialize")

    def continue_without_protection(self):
        """Continue without password protection."""
        if hasattr(self, "dont_show_again_var") and self.dont_show_again_var.isChecked():
            self.config.set_security_advice_enabled(False)
            self.config.save_settings()

        if self.action_enum:
            PasswordSessionManager.record_successful_verification(
                self.action_enum, is_authenticated=False
            )

        self.cancel(result=True)

    def cancel(self, event=None, result=False):
        """Cancel the password dialog."""
        self._cancel_called = True
        self.result = result
        if self.callback:
            self.callback(result)
        self.accept() if result else self.reject()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.cancel(result=False)
            return
        if (
            self.password_configured
            and event.key() == Qt.Key.Key_Return
            and event.modifiers() == Qt.KeyboardModifier.NoModifier
        ):
            self.verify_password()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event):
        if not getattr(self, "_cancel_called", False):
            self.result = False
            if self.callback:
                self.callback(False)
        event.accept()

    @staticmethod
    def prompt_password(
        master,
        config,
        action_name,
        callback=None,
        app_actions=None,
        action_enum=None,
        custom_text=None,
        allow_unauthenticated=False,
    ):
        """Static method to prompt for password."""
        dialog = PasswordDialog(
            master,
            config,
            action_name,
            callback,
            app_actions,
            action_enum,
            custom_text,
            allow_unauthenticated,
        )
        if dialog.result:
            return dialog.result
        dialog.exec()
        return dialog.result
