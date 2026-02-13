"""
Simple tooltip implementation for PySide6 widgets.

Port of lib/tooltip.py. Uses QToolTip for lightweight, native-feeling tooltips
with a configurable show delay. The tooltip appears after a delay when the mouse
enters the widget and hides when the mouse leaves or a button is pressed.
"""

from PySide6.QtCore import QEvent, QObject, QPoint, QTimer
from PySide6.QtWidgets import QToolTip, QWidget


class _ToolTipEventFilter(QObject):
    """Event filter that triggers tooltip show/hide on enter/leave."""

    def __init__(self, tooltip: "ToolTip"):
        super().__init__(tooltip.widget)
        self._tooltip = tooltip

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype == QEvent.Type.Enter:
            self._tooltip._schedule()
        elif etype in (QEvent.Type.Leave, QEvent.Type.MouseButtonPress):
            self._tooltip._cancel()
        return False


class ToolTip:
    """
    Create a tooltip for a given PySide6 widget.

    Uses QToolTip.showText() which integrates with the platform style.
    The tooltip appears after a configurable delay (default 500 ms) and
    hides automatically when the mouse leaves the widget.
    """

    def __init__(self, widget: QWidget, text: str = "widget info", delay_ms: int = 500):
        self.widget = widget
        self.text = text
        self.delay_ms = delay_ms

        self._timer = QTimer()
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._show)

        self._filter = _ToolTipEventFilter(self)
        self.widget.installEventFilter(self._filter)

    def set_text(self, text: str):
        """Update the tooltip text."""
        self.text = text

    def _schedule(self):
        """Schedule the tooltip to appear after the delay."""
        self._timer.start(self.delay_ms)

    def _cancel(self):
        """Cancel any pending tooltip and hide the current one."""
        self._timer.stop()
        QToolTip.hideText()

    def _show(self):
        """Display the tooltip at the widget's current position."""
        if self.widget.isVisible():
            global_pos = self.widget.mapToGlobal(
                QPoint(self.widget.width() // 2, self.widget.height())
            )
            QToolTip.showText(global_pos, self.text, self.widget)


def create_tooltip(widget: QWidget, text: str, delay_ms: int = 500) -> ToolTip:
    """Create a tooltip for the given widget. Drop-in replacement for the tkinter version."""
    return ToolTip(widget, text, delay_ms)
