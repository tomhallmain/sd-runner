"""
Debounce helper for Qt: coalesce rapid calls into a single invocation after a quiet period.

Uses QTimer so the callback runs on the Qt event loop (main thread).
Trailing-edge: the last scheduled args/kwargs win when the timer fires.
"""

from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer


class QtDebouncer(QObject):
    """
    Schedules a callback to run after a delay. Each schedule() cancels any
    pending run and resets the timer with the new arguments (trailing-edge).
    """

    def __init__(
        self,
        parent: QObject,
        delay_seconds: float,
        callback: Callable[..., None],
    ) -> None:
        """
        Args:
            parent: QObject parent (e.g. main window); used for timer and thread affinity.
            delay_seconds: Quiet period before the callback is invoked.
            callback: Called with the last scheduled (*args, **kwargs) when the timer fires.
        """
        super().__init__(parent)
        self._delay_ms = int(delay_seconds * 1000)
        self._callback = callback
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._pending_args: tuple = ()
        self._pending_kwargs: dict = {}

    def schedule(self, *args: Any, **kwargs: Any) -> None:
        """Schedule the callback to run after the delay with these args. Cancels any pending run."""
        self.cancel()
        self._pending_args = args
        self._pending_kwargs = kwargs
        self._timer.start(self._delay_ms)

    def cancel(self) -> None:
        """Cancel any pending invocation."""
        self._timer.stop()

    def _fire(self) -> None:
        args = self._pending_args
        kwargs = self._pending_kwargs
        self._pending_args = ()
        self._pending_kwargs = {}
        self._callback(*args, **kwargs)
