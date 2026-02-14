"""
SchedulesWindow + ScheduleModifyWindow -- manage preset schedules (PySide6 port).

Ported from ``ui/schedules_windows.py``.  Static / class-level data
(``recent_schedules``, ``current_schedule``, etc.) lives on the *original*
``ui.schedules_windows.SchedulesWindow`` and is imported from there so
that persistence via ``CacheController`` continues to work.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QScrollArea, QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui.presets_window import PresetsWindow as _PresetsBackend
from ui.schedule import PresetTask, Schedule
from ui.schedules_windows import SchedulesWindow as _SchedulesBackend
from ui_qt.presets.presets_window import PresetsWindow
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ======================================================================
# ScheduleModifyWindow
# ======================================================================

class ScheduleModifyWindow(SmartDialog):
    """Edit a single schedule: add/remove/reorder preset tasks."""

    def __init__(
        self,
        parent: QWidget,
        refresh_callback,
        schedule: Schedule | None,
    ):
        self._schedule = schedule if schedule is not None else Schedule()
        super().__init__(
            parent=parent,
            title=_("Modify Preset Schedule: {0}").format(self._schedule.name),
            geometry="600x600",
        )
        self._refresh_callback = refresh_callback

        # --- Top bar -------------------------------------------------------
        top_bar = QHBoxLayout()
        top_bar.addWidget(QLabel(_("Modify Schedule")))
        self._name_entry = QLineEdit(self._schedule.name)
        self._name_entry.setMinimumWidth(200)
        top_bar.addWidget(self._name_entry)
        save_btn = QPushButton(_("Save schedule"))
        save_btn.clicked.connect(self._finalize_schedule)
        top_bar.addWidget(save_btn)
        add_task_btn = QPushButton(_("Add Preset Task"))
        add_task_btn.clicked.connect(self._add_preset_task)
        top_bar.addWidget(add_task_btn)
        top_bar.addStretch()

        # --- Scroll area for task rows -------------------------------------
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll_content = QWidget()
        self._rows_layout = QVBoxLayout(self._scroll_content)
        self._rows_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._scroll.setWidget(self._scroll_content)

        root = QVBoxLayout(self)
        root.addLayout(top_bar)
        root.addWidget(self._scroll)

        self._rebuild_rows()
        self.show()

    # ------------------------------------------------------------------
    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        preset_names = PresetsWindow.get_preset_names()

        for idx, task in enumerate(self._schedule.schedule):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)

            # Preset name combo
            combo = QComboBox()
            combo.addItems(preset_names)
            combo.setCurrentText(task.name)
            combo.currentTextChanged.connect(
                lambda text, _idx=idx: self._update_task_name(_idx, text)
            )
            h.addWidget(combo, stretch=1)

            # Count combo
            count_combo = QComboBox()
            count_items = ["-1"] + [str(i) for i in range(101)]
            count_combo.addItems(count_items)
            count_combo.setCurrentText(str(task.count_runs))
            count_combo.currentTextChanged.connect(
                lambda text, _idx=idx: self._update_task_count(_idx, text)
            )
            count_combo.setFixedWidth(80)
            h.addWidget(count_combo)

            # Move down
            move_btn = QPushButton(_("Move Down"))
            move_btn.setFixedWidth(90)
            move_btn.clicked.connect(lambda _=False, _idx=idx: self._move_task_down(_idx))
            h.addWidget(move_btn)

            # Delete
            del_btn = QPushButton(_("Delete"))
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(lambda _=False, _idx=idx: self._delete_task(_idx))
            h.addWidget(del_btn)

            self._rows_layout.addWidget(row)

    # ------------------------------------------------------------------
    def _update_task_name(self, idx: int, name: str) -> None:
        if idx < len(self._schedule.schedule):
            self._schedule.schedule[idx].name = name

    def _update_task_count(self, idx: int, count_text: str) -> None:
        if idx < len(self._schedule.schedule):
            try:
                self._schedule.schedule[idx].count_runs = int(count_text)
            except ValueError:
                pass

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _add_preset_task(self) -> None:
        self._schedule.add_preset_task(
            PresetTask(_PresetsBackend.get_most_recent_preset_name(), 1)
        )
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _delete_task(self, idx: int) -> None:
        self._schedule.delete_index(idx)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _move_task_down(self, idx: int) -> None:
        self._schedule.move_index(idx, 1)
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _finalize_schedule(self) -> None:
        self._schedule.name = self._name_entry.text()
        self.close()
        self._refresh_callback(self._schedule)


# ======================================================================
# SchedulesWindow
# ======================================================================

class SchedulesWindow(SmartDialog):
    """PySide6 schedule management window.

    Shows all saved schedules in a scrollable list with Set / Modify /
    Delete buttons per row, plus top-level Add / Clear buttons.
    """

    current_schedule = None  # Will be set from Schedule() during set_schedules
    recent_schedules = []
    schedule_history = []
    MAX_SCHEDULES = 50

    @staticmethod
    def set_schedules():
        from utils.app_info_cache import app_info_cache
        from ui.schedule import Schedule
        for schedule_dict in list(app_info_cache.get("recent_schedules", default_val=[])):
            SchedulesWindow.recent_schedules.append(Schedule.from_dict(schedule_dict))
        current_schedule_dict = app_info_cache.get("current_schedule", default_val=None)
        if current_schedule_dict is not None:
            SchedulesWindow.current_schedule = Schedule.from_dict(current_schedule_dict)
        else:
            SchedulesWindow.current_schedule = Schedule()

    @staticmethod
    def store_schedules():
        from utils.app_info_cache import app_info_cache
        schedule_dicts = []
        for schedule in SchedulesWindow.recent_schedules:
            schedule_dicts.append(schedule.to_dict())
        app_info_cache.set("recent_schedules", schedule_dicts)
        if SchedulesWindow.current_schedule is not None:
            app_info_cache.set("current_schedule", SchedulesWindow.current_schedule.to_dict())

    @staticmethod
    def update_history(schedule):
        if len(SchedulesWindow.schedule_history) > 0 and schedule == SchedulesWindow.schedule_history[0]:
            return
        SchedulesWindow.schedule_history.insert(0, schedule)
        if len(SchedulesWindow.schedule_history) > SchedulesWindow.MAX_SCHEDULES:
            del SchedulesWindow.schedule_history[-1]

    _modify_window: Optional[ScheduleModifyWindow] = None

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(
            parent=parent,
            title=_("Preset Schedules"),
            geometry="700x400",
        )
        self._app_actions = app_actions

        # --- Top bar -------------------------------------------------------
        top_bar = QHBoxLayout()
        self._info_label = QLabel(self._current_schedule_text())
        top_bar.addWidget(self._info_label, stretch=1)
        add_btn = QPushButton(_("Add schedule"))
        add_btn.clicked.connect(self._open_modify_window)
        top_bar.addWidget(add_btn)
        clear_btn = QPushButton(_("Clear schedules"))
        clear_btn.clicked.connect(self._clear_recent_schedules)
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
    @staticmethod
    def _current_schedule_text() -> str:
        return _("Current schedule: {0}").format(SchedulesWindow.current_schedule)

    def _rebuild_rows(self) -> None:
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        for schedule in SchedulesWindow.recent_schedules:
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(2, 2, 2, 2)
            label = QLabel(str(schedule))
            label.setWordWrap(True)
            label.setMinimumWidth(350)
            h.addWidget(label, stretch=1)

            set_btn = QPushButton(_("Set"))
            set_btn.setFixedWidth(60)
            set_btn.clicked.connect(lambda _=False, s=schedule: self._set_schedule(s))
            h.addWidget(set_btn)

            mod_btn = QPushButton(_("Modify"))
            mod_btn.setFixedWidth(70)
            mod_btn.clicked.connect(lambda _=False, s=schedule: self._open_modify_window(schedule=s))
            h.addWidget(mod_btn)

            del_btn = QPushButton(_("Delete"))
            del_btn.setFixedWidth(60)
            del_btn.clicked.connect(lambda _=False, s=schedule: self._delete_schedule(s))
            h.addWidget(del_btn)

            self._rows_layout.addWidget(row)

    # ------------------------------------------------------------------
    def _set_schedule(self, schedule: Schedule) -> None:
        SchedulesWindow.current_schedule = schedule
        self._info_label.setText(self._current_schedule_text())
        self._app_actions.toast(_("Set schedule: {0}").format(schedule))
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _open_modify_window(self, schedule: Schedule | None = None) -> None:
        if SchedulesWindow._modify_window is not None:
            try:
                SchedulesWindow._modify_window.close()
            except RuntimeError:
                pass
        SchedulesWindow._modify_window = ScheduleModifyWindow(
            self, self._on_schedule_modified, schedule,
        )

    def _on_schedule_modified(self, schedule: Schedule) -> None:
        """Callback from ScheduleModifyWindow after save."""
        SchedulesWindow.update_history(schedule)
        if schedule in SchedulesWindow.recent_schedules:
            SchedulesWindow.recent_schedules.remove(schedule)
        SchedulesWindow.recent_schedules.insert(0, schedule)
        self._set_schedule(schedule)

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _delete_schedule(self, schedule: Schedule | None = None) -> None:
        if schedule is not None and schedule in SchedulesWindow.recent_schedules:
            SchedulesWindow.recent_schedules.remove(schedule)
            self._app_actions.toast(_("Deleted schedule: {0}").format(schedule))
        self._rebuild_rows()

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def _clear_recent_schedules(self) -> None:
        SchedulesWindow.recent_schedules.clear()
        self._rebuild_rows()
        self._app_actions.toast(_("Cleared schedules"))
