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
from sd_runner.ui.app_style import AppStyle
from lib.logging_setup import get_logger
from lib.translations import I18N

if TYPE_CHECKING:
    from sd_runner.ui.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("ui.notification_controller")


class _NotificationSignals(QObject):
    """Signals for cross-thread toast / title-notify delivery."""
    toast_requested = Signal(str, int, str)       # message, duration_ms, bg_color
    title_notify_requested = Signal(str, str, int)  # message, base_title, duration_ms
    status_open = Signal(int, str, str)   # token, message, bg_color
    status_update = Signal(int, str)      # token, message
    status_finish = Signal(int, str, int)  # token, message, linger_ms


class StatusToast:
    """A toast that stays up until the work it reports on is over.

    The plain toast is told its lifetime when it appears, which suits an event
    that has already happened. This one reports something still running, so it
    is told when to change and when to go. Every method is safe from a worker
    thread: each only emits.
    """

    def __init__(self, signals: _NotificationSignals, token: int):
        self._signals = signals
        self._token = token

    def update(self, message: str) -> None:
        """Replace the text, keeping it on screen."""
        self._signals.status_update.emit(self._token, message)

    def finish(self, message: str, linger_ms: int = 7000) -> None:
        """Show a last message, then close after *linger_ms*.

        The linger is what makes the outcome readable: closing the moment the
        work finishes would replace "starting" with nothing, and the reader
        would never learn how it ended.
        """
        self._signals.status_finish.emit(self._token, message, linger_ms)


class NotificationController:
    """
    Owns toast display, message-box alerts, error handling, and
    sidebar state / label updates.
    """

    def __init__(self, app_window: AppWindow):
        self._app = app_window
        self._signals = _NotificationSignals()
        self._signals.toast_requested.connect(self._do_toast)
        self._signals.title_notify_requested.connect(self._do_title_notify)
        self._signals.status_open.connect(self._do_status_open)
        self._signals.status_update.connect(self._do_status_update)
        self._signals.status_finish.connect(self._do_status_finish)
        #: token -> (widget, label). GUI thread only.
        self._status_toasts: dict[int, tuple] = {}
        self._next_status_token = 0

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

    #: Toast box size, and how far a status toast sits below a plain one so the
    #: two are both readable when a run toasts while a backend is coming up.
    _TOAST_WIDTH = 300
    _TOAST_HEIGHT = 100

    def _build_toast(self, message: str, bg_color: str, row: int = 0):
        """A frameless overlay at the top-right of the window, shown.

        No Qt parent, so it floats above everything. Returns the widget and its
        label; the caller decides what closes it.
        """
        parent_geo = self._app.geometry()
        x = parent_geo.x() + parent_geo.width() - self._TOAST_WIDTH
        y = parent_geo.y() + row * self._TOAST_HEIGHT

        toast_widget = QWidget(
            None,
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool,
        )
        toast_widget.setFixedSize(self._TOAST_WIDTH, self._TOAST_HEIGHT)
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
        return toast_widget, label

    def _do_toast(self, message: str, duration_ms: int, bg_color: str) -> None:
        """Main-thread implementation of toast display."""
        toast_widget, _label = self._build_toast(message, bg_color)
        QTimer.singleShot(
            duration_ms,
            lambda: toast_widget.close() if toast_widget else None,
        )

    # ------------------------------------------------------------------
    # Status toast -- a toast for work still in progress
    # ------------------------------------------------------------------
    def status_toast(self, message: str, bg_color: Optional[str] = None) -> StatusToast:
        """Open a toast that stays up until its handle is told to finish.

        Safe from any thread, and returns before the widget exists: the handle
        addresses it by token, so a caller on a worker thread never holds a
        widget reference.
        """
        logger.info("Status: " + message.replace("\n", " "))
        self._next_status_token += 1
        token = self._next_status_token
        self._signals.status_open.emit(
            token, message, bg_color or AppStyle.BG_COLOR
        )
        return StatusToast(self._signals, token)

    def _do_status_open(self, token: int, message: str, bg_color: str) -> None:
        # One row down from the plain toasts, which take the top slot.
        self._status_toasts[token] = self._build_toast(message, bg_color, row=1)

    def _do_status_update(self, token: int, message: str) -> None:
        entry = self._status_toasts.get(token)
        if entry is not None:
            entry[1].setText(message.strip())

    def _do_status_finish(self, token: int, message: str, linger_ms: int) -> None:
        entry = self._status_toasts.pop(token, None)
        if entry is None:
            return
        widget, label = entry
        label.setText(message.strip())
        QTimer.singleShot(linger_ms, lambda: widget.close() if widget else None)

    # ------------------------------------------------------------------
    # Title notifications
    # ------------------------------------------------------------------
    # TODO: Start using title_notify for key events:
    #   - Generation run complete / cancelled
    #   - Preset schedule finished
    #   - Server connection established / lost
    #   - Scheduled shutdown warnings
    # These calls should be added in RunController (run completion,
    # preset schedule completion) and AppWindow (server lifecycle).
    # ------------------------------------------------------------------
    def title_notify(
        self,
        message: str,
        base_message: str = "",
        time_in_seconds: int = 3,
    ) -> None:
        """
        Temporarily modify the window title to show a notification message.
        Thread-safe via signals.  After *time_in_seconds* the title reverts
        to *base_message* (or the current window title if empty).
        """
        duration_ms = time_in_seconds * 1000
        base = base_message or self._app.windowTitle()
        self._signals.title_notify_requested.emit(message, base, duration_ms)

    def _do_title_notify(self, message: str, base_title: str, duration_ms: int) -> None:
        """Main-thread implementation of title notification."""
        self._app.setWindowTitle(message)
        QTimer.singleShot(
            duration_ms,
            lambda: self._app.setWindowTitle(base_title),
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
