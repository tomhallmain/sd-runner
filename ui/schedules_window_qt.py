from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QLineEdit, QListWidget,
                                 QDialog, QSpinBox)
from PyQt6.QtCore import Qt

from ui.dialog_base import DialogBase
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class PresetTask:
    def __init__(self, name, count_runs=1):
        self.name = name
        self.count_runs = count_runs

    def to_dict(self):
        return {
            "name": self.name,
            "count_runs": self.count_runs
        }

    @staticmethod
    def from_dict(data):
        return PresetTask(data["name"], data["count_runs"])

class PresetSchedule:
    def __init__(self, name, tasks=None):
        self.name = name
        self.tasks = tasks or []

    def to_dict(self):
        return {
            "name": self.name,
            "tasks": [task.to_dict() for task in self.tasks]
        }

    @staticmethod
    def from_dict(data):
        tasks = [PresetTask.from_dict(task) for task in data["tasks"]]
        return PresetSchedule(data["name"], tasks)

    def get_tasks(self):
        return self.tasks

    def __str__(self):
        return self.name

class ScheduleModifyWindow(DialogBase):
    def __init__(self, parent=None, refresh_callback=None, schedule=None):
        super().__init__(parent, _("Modify Schedule"), width=600, height=400)
        
        self.refresh_callback = refresh_callback
        self.schedule = schedule or PresetSchedule(_("New Schedule"))
        
        self.setup_ui()
        self.load_tasks()

    def setup_ui(self):
        # Schedule name
        name_layout = QHBoxLayout()
        self.name_label = QLabel(_("Schedule Name:"))
        self.name_edit = QLineEdit(self.schedule.name)
        name_layout.addWidget(self.name_label)
        name_layout.addWidget(self.name_edit)
        self.add_layout_to_content(name_layout)

        # Tasks list
        self.tasks_list = QListWidget()
        self.add_widget_to_content(self.tasks_list)

        # Task controls
        task_controls = QHBoxLayout()
        
        self.task_name_edit = QLineEdit()
        self.task_name_edit.setPlaceholderText(_("Task name"))
        
        self.task_count_spin = QSpinBox()
        self.task_count_spin.setRange(-1, 100)
        self.task_count_spin.setValue(1)
        
        self.add_task_btn = QPushButton(_("Add Task"))
        self.add_task_btn.clicked.connect(self.add_task)
        
        task_controls.addWidget(self.task_name_edit)
        task_controls.addWidget(self.task_count_spin)
        task_controls.addWidget(self.add_task_btn)
        
        self.add_layout_to_content(task_controls)

        # Override default buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()
        
        self.save_btn = self.add_button(_("Save"), self.save_schedule)
        self.delete_task_btn = self.add_button(_("Delete Selected Task"), self.delete_selected_task)
        self.close_btn = self.add_button(_("Close"), self.close)

    def load_tasks(self):
        self.tasks_list.clear()
        for task in self.schedule.tasks:
            self.tasks_list.addItem(f"{task.name} ({task.count_runs} runs)")

    def add_task(self):
        name = self.task_name_edit.text()
        if not name:
            return
            
        count = self.task_count_spin.value()
        task = PresetTask(name, count)
        self.schedule.tasks.append(task)
        
        self.task_name_edit.clear()
        self.task_count_spin.setValue(1)
        self.load_tasks()

    def delete_selected_task(self):
        current_row = self.tasks_list.currentRow()
        if current_row >= 0:
            del self.schedule.tasks[current_row]
            self.load_tasks()

    def save_schedule(self):
        self.schedule.name = self.name_edit.text()
        if self.refresh_callback:
            self.refresh_callback(self.schedule)
        self.close()

class SchedulesWindow(DialogBase):
    recent_schedules = []
    current_schedule = None
    schedule_modify_window = None
    
    def __init__(self, parent=None, toast_callback=None):
        super().__init__(parent, _("Schedules Window"), width=600, height=800)
        
        self.toast_callback = toast_callback
        self.filtered_schedules = SchedulesWindow.recent_schedules[:]
        
        self.setup_ui()
        self.load_schedules()

    def setup_ui(self):
        # Search box
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_("Search schedules..."))
        self.search_edit.textChanged.connect(self.filter_schedules)
        search_layout.addWidget(self.search_edit)
        self.add_layout_to_content(search_layout)

        # Current schedule label
        self.current_schedule_label = QLabel(self.get_current_schedule_label_text())
        self.add_widget_to_content(self.current_schedule_label)

        # Schedules list
        self.schedules_list = QListWidget()
        self.schedules_list.itemDoubleClicked.connect(self.set_selected_schedule)
        self.add_widget_to_content(self.schedules_list)

        # Override default buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()

        self.new_btn = self.add_button(_("New Schedule"), self.create_new_schedule)
        self.modify_btn = self.add_button(_("Modify Selected"), self.modify_selected_schedule)
        self.set_btn = self.add_button(_("Set Selected"), self.set_selected_schedule)
        self.delete_btn = self.add_button(_("Delete Selected"), self.delete_selected_schedule)
        self.close_btn = self.add_button(_("Close"), self.close)

    @staticmethod
    def set_schedules():
        SchedulesWindow.recent_schedules = []
        for schedule_dict in app_info_cache.get("recent_schedules", default_val=[]):
            SchedulesWindow.recent_schedules.append(PresetSchedule.from_dict(schedule_dict))

    @staticmethod
    def store_schedules():
        schedule_dicts = []
        for schedule in SchedulesWindow.recent_schedules:
            schedule_dicts.append(schedule.to_dict())
        app_info_cache.set("recent_schedules", schedule_dicts)

    def load_schedules(self):
        self.refresh()

    def filter_schedules(self, text):
        self.filtered_schedules = [
            schedule for schedule in SchedulesWindow.recent_schedules
            if text.lower() in schedule.name.lower()
        ]
        self.refresh_list()

    def refresh_list(self):
        self.schedules_list.clear()
        for schedule in self.filtered_schedules:
            self.schedules_list.addItem(schedule.name)

    def refresh(self):
        self.filtered_schedules = SchedulesWindow.recent_schedules[:]
        self.refresh_list()
        self.current_schedule_label.setText(self.get_current_schedule_label_text())

    def get_current_schedule_label_text(self):
        return _("Current schedule: {0}").format(
            SchedulesWindow.current_schedule.name if SchedulesWindow.current_schedule else "None"
        )

    def create_new_schedule(self):
        self.open_schedule_modify_window()

    def modify_selected_schedule(self):
        if not self.schedules_list.currentItem():
            return
            
        schedule_name = self.schedules_list.currentItem().text()
        schedule = self.get_schedule_by_name(schedule_name)
        if schedule:
            self.open_schedule_modify_window(schedule=schedule)

    def set_selected_schedule(self):
        if not self.schedules_list.currentItem():
            return
            
        schedule_name = self.schedules_list.currentItem().text()
        schedule = self.get_schedule_by_name(schedule_name)
        if schedule:
            SchedulesWindow.current_schedule = schedule
            self.current_schedule_label.setText(self.get_current_schedule_label_text())
            if self.toast_callback:
                self.toast_callback(_("Set schedule: {0}").format(schedule.name))

    def delete_selected_schedule(self):
        if not self.schedules_list.currentItem():
            return
            
        schedule_name = self.schedules_list.currentItem().text()
        schedule = self.get_schedule_by_name(schedule_name)
        if schedule:
            SchedulesWindow.recent_schedules.remove(schedule)
            if schedule == SchedulesWindow.current_schedule:
                SchedulesWindow.current_schedule = None
            self.store_schedules()
            self.refresh()
            if self.toast_callback:
                self.toast_callback(_("Deleted schedule: {0}").format(schedule.name))

    def open_schedule_modify_window(self, schedule=None):
        if SchedulesWindow.schedule_modify_window is not None:
            SchedulesWindow.schedule_modify_window.close()
        SchedulesWindow.schedule_modify_window = ScheduleModifyWindow(
            self,
            self.refresh_schedules,
            schedule
        )
        SchedulesWindow.schedule_modify_window.show()

    def refresh_schedules(self, schedule):
        if schedule in SchedulesWindow.recent_schedules:
            SchedulesWindow.recent_schedules.remove(schedule)
        SchedulesWindow.recent_schedules.insert(0, schedule)
        self.store_schedules()
        self.refresh()
        if self.toast_callback:
            self.toast_callback(_("Saved schedule: {0}").format(schedule.name))

    def get_schedule_by_name(self, name):
        for schedule in SchedulesWindow.recent_schedules:
            if schedule.name == name:
                return schedule
        return None

# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.app_style import AppStyle
    
    def mock_toast(message):
        print(f"Toast: {message}")
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    window = SchedulesWindow(toast_callback=mock_toast)
    window.show()
    
    sys.exit(app.exec()) 