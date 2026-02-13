"""
NotificationController -- toast display, title notifications, alerts, and errors.

Extracted from: toast, alert, handle_error.
Uses signals internally so it is safe to call from any thread.
"""

from __future__ import annotations

import traceback
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QObject, QTimer, Signal, Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from lib.qt_alert import qt_alert
from ui_qt.app_style import AppStyle
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("ui_qt.notification_controller")


class _NotificationSignals(QObject):
    """Signals for cross-thread toast delivery."""
    toast_requested = Signal(str, int, str)  # message, duration_ms, bg_color


class NotificationController:
    """
    Owns toast display, message-box alerts, error handling, and
    sidebar state / label updates.
    """

    def __init__(self, app_window: AppWindow):
        self._app = app_window
        self._signals = _NotificationSignals()
        self._signals.toast_requested.connect(self._do_toast)

    # ------------------------------------------------------------------
    # Toast
    # ------------------------------------------------------------------
    def toast(
        self,
        message: str,
        duration_ms: int = 2000,
        bg_color: Optional[str] = None,
    ) -> None:
        """
        Show a transient toast notification. Thread-safe: if called from
        a background thread the signal is queued to the main thread.
        """
        logger.info("Toast: " + message.replace("\n", " "))
        color = bg_color or AppStyle.BG_COLOR
        self._signals.toast_requested.emit(message, duration_ms, color)

    def _do_toast(self, message: str, duration_ms: int, bg_color: str) -> None:
        """
        Main-thread implementation of toast display.

        Creates a frameless overlay widget at the top-right of the parent
        window, which auto-destructs after *duration_ms*.
        """
        parent = self._app

        # Calculate position: top-right of parent window
        width = 300
        height = 100
        parent_geo = parent.geometry()
        x = parent_geo.x() + parent_geo.width() - width
        y = parent_geo.y()

        # Create frameless overlay (no Qt parent so it floats above everything)
        toast_widget = QWidget(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        toast_widget.setFixedSize(width, height)
        toast_widget.move(x, y)
        toast_widget.setStyleSheet(
            f"background-color: {bg_color}; border: 1px solid {AppStyle.FG_COLOR};"
        )

        layout = QVBoxLayout(toast_widget)
        layout.setContentsMargins(10, 5, 10, 5)
        label = QLabel(message.strip())
        label.setStyleSheet(
            f"color: {AppStyle.FG_COLOR}; font-size: 10pt; border: none;"
        )
        label.setWordWrap(True)
        layout.addWidget(label)

        toast_widget.show()

        # Auto-destruct after the specified time
        QTimer.singleShot(
            duration_ms,
            lambda: toast_widget.close() if toast_widget else None,
        )

    # ------------------------------------------------------------------
    # Alerts / errors
    # ------------------------------------------------------------------
    def alert(
        self,
        title: str,
        message: str,
        kind: str = "info",
        severity: str = "normal",
        master: Optional[QWidget] = None,
    ) -> bool:
        """
        Show a modal message box. Returns True for OK/Yes, False otherwise.

        ``kind`` can be ``"info"``, ``"warning"``, ``"error"``,
        ``"askokcancel"``, ``"askyesno"``, or ``"askyesnocancel"``.
        """
        logger.warning(f'Alert - Title: "{title}" Message: {message}')
        parent = master or self._app
        return qt_alert(parent, title, message, kind=kind)

    def handle_error(
        self, error_text: str, title: Optional[str] = None, kind: str = "error"
    ) -> None:
        """Display an error dialog and print the traceback."""
        traceback.print_exc()
        title = title or _("Error")
        self.alert(title, error_text, kind=kind)

    # ------------------------------------------------------------------
    # Sidebar label state
    # ------------------------------------------------------------------
    def set_label_state(self, text: str = "", **kwargs) -> None:
        """Update the progress/state label on the sidebar.

        This is a thin pass-through; the actual label lives on
        ``SidebarPanel`` and is updated here for convenience.
        """
        # TODO: wire to sidebar_panel.label_progress once progress labels
        # are fully hooked up in SidebarPanel.
        pass
