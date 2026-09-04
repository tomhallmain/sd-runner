"""Qt implementation of the UI-responsiveness port.

Counterpart to utils.ui_responsiveness.NullResponsiveness. Lives under ui_qt/
so the packages that use the port stay free of PySide6.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QEventLoop, QThread
from PySide6.QtWidgets import QApplication

from utils.logging_setup import get_logger

logger = get_logger("qt_responsiveness")


class _CallableWorker(QThread):
    """Runs one callable and stores its result.

    A failure leaves the result unset rather than reaching the caller, because
    an exception raised here would only unwind the worker thread. It is logged
    so the failure is not silent.
    """

    def __init__(self, func: Callable[[], Any]) -> None:
        super().__init__()
        self._func = func
        self.result: Any = None

    def run(self) -> None:
        try:
            self.result = self._func()
        except Exception:
            logger.exception("Background work failed.")


class QtResponsiveness:
    def yield_to_ui(self) -> None:
        """Process pending events so the display reflects work done so far."""
        QApplication.processEvents()

    def run_off_thread(self, func: Callable[[], Any]) -> Any:
        """Run *func* on a worker thread, blocking here until it returns.

        The nested event loop is the point: it keeps the main thread delivering
        events -- repaints, timers -- while this call blocks. Anything the
        callable invokes must therefore be safe to call from a worker thread.
        """
        worker = _CallableWorker(func)
        loop = QEventLoop()
        worker.finished.connect(loop.quit)
        worker.start()
        loop.exec()
        result = worker.result
        worker.deleteLater()
        return result
