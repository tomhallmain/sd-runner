"""
ScheduledShutdownDialog -- countdown dialog before scheduled shutdown (PySide6 port).

Ported from ``ui/scheduled_shutdown_dialog.py``.  Replaces the
background-thread countdown with a ``QTimer`` so no cross-thread widget
access occurs.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
)

from ui_qt.app_style import AppStyle
from utils.translations import I18N

_ = I18N._


class ScheduledShutdownDialog(QDialog):
    """Modal countdown dialog shown before a scheduled shutdown.

    The dialog starts a ``QTimer`` that decrements a label every second.
    When the countdown reaches zero the application's ``on_closing()``
    method is called.  The user may press **Shutdown Now** to skip the
    wait.
    """

    def __init__(
        self,
        parent,
        schedule_name: str,
        countdown_seconds: int = 6,
    ):
        super().__init__(parent)
        self._parent = parent
        self._remaining = countdown_seconds
        self._cancelled = False

        self.setWindowTitle(_("Scheduled Shutdown"))
        self.setFixedSize(400, 200)
        self.setWindowFlags(
            self.windowFlags()
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setModal(True)

        # --- Layout --------------------------------------------------------
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)

        title_label = QLabel(_("Scheduled Shutdown"))
        title_label.setStyleSheet("font-size: 14pt; font-weight: bold;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(title_label)

        schedule_label = QLabel(_("Schedule: {0}").format(schedule_name))
        schedule_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(schedule_label)

        self._countdown_label = QLabel(
            _("Shutting down in {0} seconds...").format(self._remaining)
        )
        self._countdown_label.setStyleSheet("font-size: 12pt; font-weight: bold; color: red;")
        self._countdown_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self._countdown_label)

        root.addSpacing(10)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        shutdown_now_btn = QPushButton(_("Shutdown Now"))
        shutdown_now_btn.clicked.connect(self._shutdown_now)
        btn_row.addWidget(shutdown_now_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        # --- Countdown timer (main-thread, no background thread needed) ----
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    @property
    def cancelled(self) -> bool:
        return self._cancelled

    # ------------------------------------------------------------------
    # Timer
    # ------------------------------------------------------------------
    def _tick(self) -> None:
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.accept()
            self._force_shutdown()
            return
        self._countdown_label.setText(
            _("Shutting down in {0} seconds...").format(self._remaining)
        )

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _shutdown_now(self) -> None:
        self._timer.stop()
        self._cancelled = False
        self.accept()
        self._force_shutdown()

    def _cancel_shutdown(self) -> None:
        self._timer.stop()
        self._cancelled = True
        self.reject()

    def _force_shutdown(self) -> None:
        if hasattr(self._parent, "on_closing"):
            self._parent.on_closing()
