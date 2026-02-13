"""
TimedSchedulesWindow + TimedScheduleModifyWindow -- day/time-based schedules (PySide6 port).

Ported from ``ui/timed_schedules_window.py``.  Backend data lives on the
``timed_schedules_manager`` singleton which is imported unchanged.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from sd_runner.timed_schedule import TimedSchedule
from sd_runner.timed_schedules_manager import timed_schedules_manager
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ======================================================================
# TimedScheduleModifyWindow
# ======================================================================

class TimedScheduleModifyWindow(SmartDialog):
    """Edit a single timed schedule: name, weekdays, start/end/shutdown times."""

    def __init__(
        self,
        parent: QWidget,
        refresh_callback,
        schedule: TimedSchedule | None,
        app_actions: AppActions | None = None,
    ):
        self._schedule = schedule if schedule is not None else TimedSchedule()
        super().__init__(
            parent=parent,
            title=_("Modify Timed Schedule: {0}").format(self._schedule.name),
            geometry="500x500",
        )
        self._refresh_callback = refresh_callback
        self._app_actions = app_actions

        root = QVBoxLayout(self)

        # --- Name row ------------------------------------------------------
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel(_("Schedule Name")))
        self._name_entry = QLineEdit(self._schedule.name)
        self._name_entry.setMinimumWidth(200)
        name_row.addWidget(self._name_entry, stretch=1)
        save_btn = QPushButton(_("Save schedule"))
        save_btn.clicked.connect(self._finalize_schedule)
        name_row.addWidget(save_btn)
        root.addLayout(name_row)

        # --- Days of the week ----------------------------------------------
        root.addSpacing(10)
        self._all_days_check = QCheckBox(_("Every day"))
        self._all_days_check.stateChanged.connect(self._toggle_all_days)
        root.addWidget(self._all_days_check)

        self._day_checks: list[QCheckBox] = []
        for i in range(7):
            cb = QCheckBox(I18N.day_of_the_week(i))
            self._day_checks.append(cb)
            root.addWidget(cb)

        # Pre-select days from existing schedule
        if hasattr(self._schedule, "weekday_options"):
            for idx in self._schedule.weekday_options:
                if 0 <= idx < 7:
                    self._day_checks[idx].setChecked(True)

        # --- Time rows (start, end, shutdown) ------------------------------
        root.addSpacing(10)
        hours = [str(h) for h in range(24)]
        minutes = [str(m) for m in range(0, 61, 15)]

        # Start time
        start_row = QHBoxLayout()
        start_row.addWidget(QLabel(_("Start Time")))
        self._start_hour = QComboBox()
        self._start_hour.addItems(hours)
        start_row.addWidget(self._start_hour)
        self._start_min = QComboBox()
        self._start_min.addItems(minutes)
        start_row.addWidget(self._start_min)
        start_row.addStretch()
        root.addLayout(start_row)

        # End time
        end_row = QHBoxLayout()
        end_row.addWidget(QLabel(_("End Time")))
        self._end_hour = QComboBox()
        self._end_hour.addItems(hours)
        end_row.addWidget(self._end_hour)
        self._end_min = QComboBox()
        self._end_min.addItems(minutes)
        end_row.addWidget(self._end_min)
        end_row.addStretch()
        root.addLayout(end_row)

        # Shutdown time
        shutdown_row = QHBoxLayout()
        shutdown_row.addWidget(QLabel(_("Shutdown Time")))
        self._shutdown_hour = QComboBox()
        self._shutdown_hour.addItems([""] + hours)
        shutdown_row.addWidget(self._shutdown_hour)
        self._shutdown_min = QComboBox()
        self._shutdown_min.addItems([""] + minutes)
        shutdown_row.addWidget(self._shutdown_min)
        shutdown_row.addStretch()
        root.addLayout(shutdown_row)

        root.addStretch()
        self.show()

    # ------------------------------------------------------------------
    def _toggle_all_days(self, state: int) -> None:
        checked = state == Qt.CheckState.Checked.value
        for cb in self._day_checks:
            cb.setChecked(checked)

    def _get_active_weekday_indices(self) -> list[int]:
        return [i for i, cb in enumerate(self._day_checks) if cb.isChecked()]

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def _finalize_schedule(self) -> None:
        self._schedule.name = self._name_entry.text()
        self._schedule.weekday_options = self._get_active_weekday_indices()
        if len(self._schedule.weekday_options) == 0:
            if self._app_actions:
                self._app_actions.alert(_("Validation Error"), _("No days selected"), kind="error", master=self)
            else:
                from lib.qt_alert import qt_alert
                qt_alert(self, _("Validation Error"), _("No days selected"), kind="error")
            return

        start_h = self._start_hour.currentText()
        start_m = self._start_min.currentText()
        if start_h:
            self._schedule.set_start_time(int(start_h), int(start_m or "0"))

        end_h = self._end_hour.currentText()
        end_m = self._end_min.currentText()
        if end_h:
            self._schedule.set_end_time(int(end_h), int(end_m or "0"))

        shutdown_h = self._shutdown_hour.currentText()
        shutdown_m = self._shutdown_min.currentText()
        if shutdown_h:
            self._schedule.set_shutdown_time(int(shutdown_h), int(shutdown_m or "0"))

        self.close()
        self._refresh_callback(self._schedule)


# ======================================================================
# TimedSchedulesWindow
# ======================================================================

class TimedSchedulesWindow(SmartDialog):
    """PySide6 timed-schedule management window.

    Shows all saved timed schedules with Modify / Delete / Enabled
    controls per row.
    """

    _modify_window: Optional[TimedScheduleModifyWindow] = None

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(
            parent=parent,
            title=_("Timed Schedules"),
            geometry="900x400",
        )
        self._app_actions = app_actions

        # --- Top bar -------------------------------------------------------
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel(_("Create and modify timed schedules")), stretch=1)
        add_btn = QPushButton(_("Add schedule"))
        add_btn.clicked.connect(self._open_modify_window)
        top_bar.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear schedules"))
        clear_btn.clicked.connect(self._clear_schedules)
        top_bar.addWidget(clear_btn)

        # --- Scroll area ---------------------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._rows_layout = QVBoxLayout(self._scroll_content)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)

        root = QVBoxLayout(self)
        root.addLayout(top_bar)
        root.addWidget(self._scroll)

        QShortcut(QKeySequence("Escape"), self, self.close)

        self._rebuild_rows()
        self.show()

    # ------------------------------------------------------------------
    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for schedule in timed_schedules_manager.recent_timed_schedules:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)

            label = QLabel(str(schedule))
            label.setWordWrap(True)
            label.setMinimumWidth(450)
            h.addWidget(label, stretch=1)

            mod_btn = QPushButton(_("Modify"))
            mod_btn.setFixedWidth(70)
            mod_btn.clicked.connect(
                lambda _=False, s=schedule: self._open_modify_window(schedule=s)
            )
            h.addWidget(mod_btn)

            del_btn = QPushButton(_("Delete"))
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(
                lambda _=False, s=schedule: self._delete_schedule(s)
            )
            h.addWidget(del_btn)

            enabled_cb = QCheckBox(_("Enabled"))
            enabled_cb.setChecked(getattr(schedule, "enabled", True))
            enabled_cb.stateChanged.connect(
                lambda state, s=schedule: self._toggle_enabled(s, state)
            )
            h.addWidget(enabled_cb)

            self._rows_layout.addWidget(row)

    # ------------------------------------------------------------------
    def _toggle_enabled(self, schedule: TimedSchedule, state: int) -> None:
        schedule.enabled = state == Qt.CheckState.Checked.value
        timed_schedules_manager.store_schedules()

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def _open_modify_window(self, schedule: TimedSchedule | None = None) -> None:
        if TimedSchedulesWindow._modify_window is not None:
            try:
                TimedSchedulesWindow._modify_window.close()
            except RuntimeError:
                pass
        TimedSchedulesWindow._modify_window = TimedScheduleModifyWindow(
            self, self._on_schedule_modified, schedule,
            app_actions=self._app_actions,
        )

    def _on_schedule_modified(self, schedule: TimedSchedule) -> None:
        timed_schedules_manager.refresh_schedule(schedule)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def _delete_schedule(self, schedule: TimedSchedule | None = None) -> None:
        timed_schedules_manager.delete_schedule(schedule)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def _clear_schedules(self) -> None:
        timed_schedules_manager.clear_all_schedules()
        self._rebuild_rows()
