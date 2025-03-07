from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                                 QHBoxLayout, QLabel, QPushButton, QComboBox, 
                                 QCheckBox, QLineEdit, QTextEdit, QProgressBar,
                                 QSlider, QFrame, QScrollArea)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont
import sys
import signal
import time
import traceback
from copy import deepcopy

from run import Run
from utils.globals import Globals, WorkflowType, Sampler, Scheduler, SoftwareType
from extensions.sd_runner_server import SDRunnerServer
from sd_runner.comfy_gen import ComfyGen
from sd_runner.concepts import PromptMode
from sd_runner.gen_config import GenConfig
from sd_runner.models import IPAdapter, Model
from sd_runner.prompter import Prompter
from sd_runner.run_config import RunConfig
from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.job_queue import JobQueue
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N
from utils.utils import Utils

from lib.autocomplete_line_edit import AutocompleteLineEdit
from lib.toast_widget import ToastWidget
from ui.presets_window_qt import PresetsWindow

_ = I18N._

class Sidebar(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.setLayout(self.layout)

class App(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(_(" ComfyGen "))
        self.resize(500, 800)
        
        # Initialize core components
        self.progress_bar = None
        self.job_queue = JobQueue(JobQueue.JOB_QUEUE_SD_RUNS_KEY)
        self.job_queue_preset_schedules = JobQueue(JobQueue.JOB_QUEUE_PRESETS_KEY)
        self.server = self.setup_server()
        self.runner_app_config = self.load_info_cache()
        self.config_history_index = 0
        self.current_run = Run(RunConfig())
        Model.load_all()

        # Create central widget and main layout
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(5, 5, 5, 5)
        self.main_layout.setSpacing(5)
        
        # Create sidebar with fixed width
        self.sidebar = Sidebar(self)
        self.sidebar.setFixedWidth(250)
        self.main_layout.addWidget(self.sidebar)
        
        # Create prompter config area
        self.prompter_config_area = QScrollArea(self)
        self.prompter_config_widget = QWidget()
        self.prompter_config_layout = QVBoxLayout(self.prompter_config_widget)
        self.prompter_config_layout.setContentsMargins(5, 5, 5, 5)
        self.prompter_config_layout.setSpacing(5)
        self.prompter_config_area.setWidget(self.prompter_config_widget)
        self.prompter_config_area.setWidgetResizable(True)
        self.main_layout.addWidget(self.prompter_config_area)
        
        self.setup_ui()
        self.apply_style()

    def create_combo_box(self, label_text, items, current_text=None, height=20, on_change=None, sidebar=True):
        layout = QHBoxLayout()
        label = QLabel(_(label_text))
        combo = QComboBox()
        combo.setFixedHeight(height)
        combo.addItems(items)
        if current_text:
            combo.setCurrentText(current_text)
        if on_change:
            combo.currentTextChanged.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(combo)
        if sidebar:
            self.sidebar.layout.addLayout(layout)
        return layout, combo

    def create_text_input(self, label_text, text="", height=20, on_change=None, sidebar=True):
        layout = QVBoxLayout()
        label = QLabel(_(label_text))
        text_edit = QTextEdit() if height else QLineEdit()
        if height:
            text_edit.setFixedHeight(height)
        text_edit.setText(text)
        if on_change:
            text_edit.textChanged.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(text_edit)
        if sidebar:
            self.sidebar.layout.addLayout(layout)
        return layout, text_edit

    def create_slider(self, label_text, value, height=20, on_change=None, sidebar=True):
        layout = QHBoxLayout()
        label = QLabel(_(label_text))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setFixedHeight(height)
        slider.setRange(0, 100)
        slider.setValue(int(float(value) * 100))
        if on_change:
            slider.valueChanged.connect(on_change)
        layout.addWidget(label)
        layout.addWidget(slider)
        if sidebar:
            self.sidebar.layout.addLayout(layout)
        return layout, slider

    def create_checkbox(self, text, checked=False, on_change=None, sidebar=True):
        checkbox = QCheckBox(_(text))
        checkbox.setChecked(checked)
        if on_change:
            checkbox.stateChanged.connect(on_change)
        if sidebar:
            self.sidebar.layout.addWidget(checkbox)
        return checkbox

    def setup_ui(self):
        # Title with smaller font
        self.label_title = QLabel(_("Run ComfyUI Workflows"))
        title_font = QFont()
        title_font.setPointSize(10)
        self.label_title.setFont(title_font)
        self.sidebar.layout.addWidget(self.label_title)

        # Run button with fixed height
        self.run_btn = QPushButton(_("Run Workflows"))
        self.run_btn.setFixedHeight(20)
        self.run_btn.clicked.connect(self.run)
        self.sidebar.layout.addWidget(self.run_btn)

        # Cancel button with fixed height
        self.cancel_btn = QPushButton(_("Cancel Run"))
        self.cancel_btn.setFixedHeight(20)
        self.cancel_btn.hide()
        self.cancel_btn.clicked.connect(self.cancel)
        self.sidebar.layout.addWidget(self.cancel_btn)

        # Progress bar with fixed height
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setFixedHeight(20)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.hide()
        self.sidebar.layout.addWidget(self.progress_bar)

        # Progress label with smaller font
        self.label_progress = QLabel("")
        progress_font = QFont()
        progress_font.setPointSize(8)
        self.label_progress.setFont(progress_font)
        self.sidebar.layout.addWidget(self.label_progress)

        # Add spacing between sections
        self.sidebar.layout.addSpacing(5)

        # Software selection
        software_layout, self.software_combo = self.create_combo_box(
            "Software", SoftwareType.__members__.keys(), self.runner_app_config.software_type, on_change=self.set_software_type)

        # Prompt mode
        prompt_mode_layout, self.prompt_mode_combo = self.create_combo_box(
            "Prompt Mode", PromptMode.__members__.keys(), str(Globals.DEFAULT_PROMPT_MODE))

        # Workflow type
        workflow_layout, self.workflow_combo = self.create_combo_box(
            "Workflow Type", WorkflowType.__members__.keys(), on_change=self.set_workflow_type)

        # N Latents
        n_latents_layout, self.n_latents_combo = self.create_combo_box(
            "Set N Latents", [str(i) for i in range(51)], str(self.runner_app_config.n_latents), on_change=lambda x: setattr(self.runner_app_config, 'n_latents', int(x)))

        # Total
        total_layout, self.total_combo = self.create_combo_box(
            "Set Total", [str(i) for i in range(-1, 101) if i != 0], str(self.runner_app_config.total), on_change=lambda x: setattr(self.runner_app_config, 'total', int(x)))

        # Delay
        delay_layout, self.delay_combo = self.create_combo_box(
            "Delay Seconds", [str(i) for i in range(101)], str(self.runner_app_config.delay_time_seconds), on_change=self.set_delay)

        # Resolutions
        resolutions_layout, self.resolutions_edit = self.create_text_input(
            "Resolutions", self.runner_app_config.resolutions, on_change=self.set_resolutions)

        # Model tags
        model_tags_layout, self.model_tags_edit = self.create_text_input(
            "Model Tags", self.runner_app_config.model_tags, on_change=self.set_model_tags)
        self.model_tags_edit = AutocompleteLineEdit(list(map(lambda l: str(l).split('.')[0], Model.CHECKPOINTS)))

        # LoRA tags
        lora_tags_layout, self.lora_tags_edit = self.create_text_input(
            "LoRA Tags", self.runner_app_config.lora_tags, on_change=lambda x: setattr(self.runner_app_config, 'lora_tags', x))
        self.lora_tags_edit = AutocompleteLineEdit(list(map(lambda l: str(l).split('.')[0], Model.LORAS)))

        # LoRA strength
        lora_strength_layout, self.lora_strength_slider = self.create_slider(
            "Default LoRA Strength", self.runner_app_config.lora_strength, on_change=self.set_lora_strength)

        # Prompt massage tags
        prompt_tags_layout, self.prompt_massage_tags_edit = self.create_text_input(
            "Prompt Massage Tags", self.runner_app_config.prompt_massage_tags, on_change=self.set_prompt_massage_tags)

        # Positive tags
        positive_tags_layout, self.positive_tags_edit = self.create_text_input(
            "Positive Tags", self.runner_app_config.positive_tags, height=100, on_change=self.set_positive_tags)

        # Negative tags
        negative_tags_layout, self.negative_tags_edit = self.create_text_input(
            "Negative Tags", self.runner_app_config.negative_tags, height=50, on_change=self.set_negative_tags)

        # B/W Colorization
        bw_layout, self.bw_colorization_edit = self.create_text_input(
            "B/W Colorization Tags", self.runner_app_config.b_w_colorization, on_change=self.set_bw_colorization)

        # Control Net files
        controlnet_layout, self.controlnet_file_edit = self.create_text_input(
            "Control Net or Redo files", self.runner_app_config.control_net_file, on_change=lambda x: setattr(self.runner_app_config, 'control_net_file', x))

        # Control Net strength
        controlnet_strength_layout, self.controlnet_strength_slider = self.create_slider(
            "Default Control Net Strength", self.runner_app_config.control_net_strength, on_change=self.set_controlnet_strength)

        # IP Adapter files
        ipadapter_layout, self.ipadapter_file_edit = self.create_text_input(
            "IPAdapter files", self.runner_app_config.ip_adapter_file, on_change=lambda x: setattr(self.runner_app_config, 'ip_adapter_file', x))

        # IP Adapter strength
        ipadapter_strength_layout, self.ipadapter_strength_slider = self.create_slider(
            "Default IPAdapter Strength", self.runner_app_config.ip_adapter_strength, on_change=self.set_ipadapter_strength)

        # Redo parameters
        redo_layout, self.redo_params_edit = self.create_text_input(
            "Redo Parameters", self.runner_app_config.redo_params, on_change=self.set_redo_params)

        # Checkboxes
        self.run_preset_schedule_var = self.create_checkbox("Run Preset Schedule")

        self.override_resolution_var = self.create_checkbox(
            "Override Resolution", self.runner_app_config.override_resolution, on_change=lambda x: setattr(self.runner_app_config, 'override_resolution', bool(x)))

        self.inpainting_var = self.create_checkbox(
            "Inpainting", on_change=lambda x: setattr(self.runner_app_config, 'inpainting', bool(x)))

        self.override_negative_var = self.create_checkbox(
            "Override Base Negative", on_change=self.set_override_negative)

        self.tags_at_start_var = self.create_checkbox(
            "Tags Applied to Prompt Start", self.runner_app_config.tags_apply_to_start, on_change=self.set_tags_apply_to_start)

        # Buttons
        buttons_layout = QHBoxLayout()
        self.presets_btn = QPushButton(_("Manage Presets"))
        self.schedules_btn = QPushButton(_("Preset Schedule Window"))
        self.blacklist_btn = QPushButton(_("Tag Blacklist"))
        self.expansions_btn = QPushButton(_("Expansions Window"))
        
        for btn, callback in [
            (self.presets_btn, self.open_presets_window),
            (self.schedules_btn, self.open_preset_schedules_window),
            (self.blacklist_btn, self.show_tag_blacklist),
            (self.expansions_btn, self.open_expansions_window)
        ]:
            btn.setFixedHeight(25)
            btn.clicked.connect(callback)
            buttons_layout.addWidget(btn)
        
        self.sidebar.layout.addLayout(buttons_layout)

        # Add spacer at the bottom
        self.sidebar.layout.addStretch()

    def apply_style(self):
        if AppStyle.IS_DEFAULT_THEME:
            self.setStyleSheet(f"""
                QMainWindow, QWidget {{
                    background-color: {AppStyle.BG_COLOR}; color: {AppStyle.FG_COLOR}; }}
                QPushButton {{
                    background-color: {AppStyle.BG_COLOR}; color: {AppStyle.FG_COLOR};
                    border: 1px solid {AppStyle.FG_COLOR}; padding: 5px; border-radius: 3px; }}
                QPushButton:hover {{
                    background-color: {AppStyle.FG_COLOR}; color: {AppStyle.BG_COLOR}; }}
                QComboBox, QLineEdit, QTextEdit {{
                    background-color: {AppStyle.BG_COLOR}; color: {AppStyle.FG_COLOR};
                    border: 1px solid {AppStyle.FG_COLOR}; padding: 5px; }}  """)

    def setup_server(self):
        server = SDRunnerServer(self.server_run_callback, self.cancel, self.revert_to_simple_gen)
        try:
            Utils.start_thread(server.start)
            return server
        except Exception as e:
            print(f"Failed to start server: {e}")
            return None

    def server_run_callback(self, workflow_type, args):
        """Handle server run requests."""
        if workflow_type is not None:
            self.workflow_combo.setCurrentText(workflow_type.name)
            self.set_workflow_type(workflow_type)
        elif config.debug:
            print("Rerunning from server request with last settings.")
            
        if len(args) > 0:
            if "image" in args:
                image_path = args["image"].replace(",", "\\,")
                print(image_path)
                if workflow_type in [WorkflowType.CONTROLNET, WorkflowType.RENOISER, WorkflowType.REDO_PROMPT]:
                    if self.run_preset_schedule_var.isChecked() and self.job_queue_preset_schedules.has_pending():
                        self.job_queue_preset_schedules.add({"control_net": image_path})
                        return {}
                    elif "append" in args and args["append"] and self.controlnet_file_edit.text().strip() != "":
                        self.controlnet_file_edit.setText(self.controlnet_file_edit.text() + "," + image_path)
                    else:
                        self.controlnet_file_edit.setText(image_path)
                elif workflow_type == WorkflowType.IP_ADAPTER:
                    if self.run_preset_schedule_var.isChecked() and self.job_queue_preset_schedules.has_pending():
                        self.job_queue_preset_schedules.add({"ip_adapter": image_path})
                        return {}
                    if "append" in args and args["append"] and self.ipadapter_file_edit.text().strip() != "":
                        self.ipadapter_file_edit.setText(self.ipadapter_file_edit.text() + "," + image_path)
                    else:
                        self.ipadapter_file_edit.setText(image_path)
                else:
                    print(f"Unhandled workflow type for server connection: {workflow_type}")
                
            self.update()
        self.run()
        return {}  # Empty error object for confirmation

    def revert_to_simple_gen(self, event=None):
        """Revert to simple generation workflow."""
        self.cancel(reason="Revert to simple generation")
        self.workflow_combo.setCurrentText(WorkflowType.SIMPLE_IMAGE_GEN_LORA.name)
        self.set_workflow_type(WorkflowType.SIMPLE_IMAGE_GEN_LORA)
        self.run()

    def run(self):
        """Execute the workflow run."""
        if self.current_run.is_infinite():
            self.current_run.cancel("Infinite run switch")

        if self.job_queue_preset_schedules.has_pending():
            # TODO: Implement QMessageBox for confirmation
            self.job_queue_preset_schedules.cancel()

        if hasattr(self, 'run_preset_schedule_var') and self.run_preset_schedule_var.isChecked():
            if not self.job_queue_preset_schedules.has_pending():
                self.run_preset_schedule()
                return None
        else:
            self.job_queue_preset_schedules.cancel()

        args, args_copy = self.get_args()

        try:
            args.validate()
        except Exception as e:
            # TODO: Implement QMessageBox for confirmation
            return None

        def run_async(args) -> None:
            Utils.prevent_sleep(True)
            self.job_queue.job_running = True
            
            # Update UI for run state
            self.progress_bar.setRange(0, 0)  # Indeterminate mode
            self.progress_bar.show()
            self.cancel_btn.show()
            
            self.current_run = Run(args, progress_callback=self.update_progress, 
                                 delay_after_last_run=self.has_runs_pending())
            try:
                self.current_run.execute()
            except Exception:
                traceback.print_exc()
                self.current_run.cancel("Run failure")
            
            # Reset UI after run
            self.cancel_btn.hide()
            self.progress_bar.hide()
            self.job_queue.job_running = False
            
            next_job_args = self.job_queue.take()
            if next_job_args:
                self.current_run.delay_after_last_run = True
                Utils.start_thread(run_async, use_asyncio=False, args=[next_job_args])
            else:
                Utils.prevent_sleep(False)
                if not self.job_queue_preset_schedules.has_pending() and not self.current_run.is_cancelled:
                    Utils.play_sound()

        if self.job_queue.has_pending():
            self.job_queue.add(args)
        else:
            self.runner_app_config.set_from_run_config(args_copy)
            Utils.start_thread(run_async, use_asyncio=False, args=[args])

    def cancel(self, reason=None):
        """Cancel the current run."""
        if self.current_run:
            self.current_run.cancel(reason=reason)
            self.update_progress("Run cancelled")

    def has_runs_pending(self):
        """Check if there are any pending runs."""
        return self.job_queue.has_pending() or self.job_queue_preset_schedules.has_pending()

    def update_progress(self, current_index, total):
        """Update the progress display."""
        if total == -1:
            self.label_progress.setText(str(current_index) + _(" (unlimited)"))
        else:
            pending_text = self.job_queue_preset_schedules.pending_text()
            if pending_text is None or pending_text == "":
                pending_text = self.job_queue.pending_text()
                if pending_text is None:
                    pending_text = ""
            self.label_progress.setText(str(current_index) + "/" + str(total) + pending_text)
        self.update()

    def get_args(self):
        """Get run configuration arguments."""
        # TODO: Implement full argument gathering from UI
        config = RunConfig()
        config.software_type = self.software_combo.currentText()
        config.workflow_type = self.workflow_combo.currentText()
        config.resolutions = self.resolutions_edit.text()
        config.model_tags = self.model_tags_edit.text()
        config.positive_tags = self.positive_tags_edit.toPlainText()
        config.negative_tags = self.negative_tags_edit.toPlainText()
        
        # Create a copy for the runner app config
        args_copy = deepcopy(config)
        
        return config, args_copy

    def open_presets_window(self):
        presets_window = PresetsWindow(self, toast_callback=self.show_toast,
            construct_preset_callback=self.construct_preset, apply_preset_callback=self.set_widgets_from_preset)
        presets_window.show()

    def open_preset_schedules_window(self):
        from ui.schedules_window_qt import SchedulesWindow
        SchedulesWindow(self, toast_callback=self.show_toast).show()

    def show_tag_blacklist(self):
        from ui.tags_blacklist_window_qt import TagsBlacklistWindow
        TagsBlacklistWindow(self, toast_callback=self.show_toast).show()
        
    def open_expansions_window(self):
        from ui.expansions_window_qt import ExpansionsWindow
        ExpansionsWindow(self, toast_callback=self.show_toast).show()

    def construct_preset(self):
        # Implementation for creating a new preset from current settings
        pass

    def set_widgets_from_preset(self, preset):
        # Implementation for applying a preset to the UI
        pass

    def show_toast(self, message, duration=2000):
        ToastWidget.show_message(self, message, duration)

    def handle_error(self, error_text, title="Error"):
        traceback.print_exc()
        # TODO: Implement error dialog

    def closeEvent(self, event):
        self.on_closing()
        event.accept()

    def on_closing(self):
        # Save settings
        self.store_info_cache()
        # Cleanup server
        if self.server:
            self.server.stop()

    def set_delay(self, value):
        """Set the delay time between runs."""
        self.runner_app_config.delay_time_seconds = value
        Globals.set_delay(int(value))

    def set_resolutions(self, text):
        self.runner_app_config.resolutions = text

    def set_positive_tags(self, text):
        self.runner_app_config.positive_tags = text

    def set_negative_tags(self, text):
        self.runner_app_config.negative_tags = text

    def set_prompt_massage_tags(self, text):
        self.runner_app_config.prompt_massage_tags = text
        Globals.set_prompt_massage_tags(text)

    def set_bw_colorization(self, text):
        self.runner_app_config.b_w_colorization = text
        IPAdapter.set_bw_coloration(text)

    def set_redo_params(self, text):
        self.runner_app_config.redo_params = text
        GenConfig.set_redo_params(text)

    def set_lora_strength(self, value):
        strength = value / 100.0
        self.runner_app_config.lora_strength = str(strength)
        Globals.set_lora_strength(strength)

    def set_controlnet_strength(self, value):
        strength = value / 100.0
        self.runner_app_config.control_net_strength = str(strength)
        Globals.set_controlnet_strength(strength)

    def set_ipadapter_strength(self, value):
        strength = value / 100.0
        self.runner_app_config.ip_adapter_strength = str(strength)
        Globals.set_ipadapter_strength(strength)

    def set_override_negative(self, state):
        self.runner_app_config.override_negative = bool(state)
        Globals.set_override_base_negative(bool(state))

    def set_tags_apply_to_start(self, state):
        self.runner_app_config.tags_apply_to_start = bool(state)
        Prompter.set_tags_apply_to_start(bool(state))

    def set_model_tags(self, text):
        self.runner_app_config.model_tags = text
        Model.set_model_presets(PromptMode[self.prompt_mode_combo.currentText()])
        
        prompt_massage_tags = Model.get_first_model_prompt_massage_tags(
            text,
            prompt_mode=self.prompt_mode_combo.currentText(),
            inpainting=self.inpainting_var.isChecked()
        )
        
        self.prompt_massage_tags_edit.setText(prompt_massage_tags)
        self.set_prompt_massage_tags(prompt_massage_tags)

    def set_software_type(self, software_type):
        self.runner_app_config.software_type = software_type
        Globals.set_software_type(SoftwareType[software_type])

    def set_workflow_type(self, workflow_type):
        if isinstance(workflow_type, str):
            workflow_type = WorkflowType[workflow_type]
        self.runner_app_config.workflow_type = workflow_type.name
        Globals.set_workflow_type(workflow_type)

    def run_preset_schedule(self, override_args=None):
        """Run a preset schedule."""
        def run_preset_async():
            self.job_queue_preset_schedules.job_running = True
            
            if override_args:
                if "control_net" in override_args:
                    self.controlnet_file_edit.setText(override_args["control_net"])
                    print(f"Updated Control Net for next preset schedule: {override_args['control_net']}")
                if "ip_adapter" in override_args:
                    self.ipadapter_file_edit.setText(override_args["ip_adapter"])
                    print(f"Updated IP Adapter for next preset schedule: {override_args['ip_adapter']}")
            
            starting_total = int(self.total_combo.currentText())
            schedule = SchedulesWindow.current_schedule
            
            if schedule is None:
                raise Exception("No Schedule Selected")
                
            print(f"Running Preset Schedule: {schedule}")
            
            for preset_task in schedule.get_tasks():
                if (not self.job_queue_preset_schedules.has_pending() or 
                    not self.run_preset_schedule_var.isChecked() or 
                    (self.current_run is not None and 
                     not self.current_run.is_infinite() and 
                     self.current_run.is_cancelled)):
                    self.job_queue_preset_schedules.cancel()
                    return
                    
                try:
                    preset = PresetsWindow.get_preset_by_name(preset_task.name)
                    print(f"Running Preset Schedule: {preset}")
                except Exception as e:
                    self.handle_error(str(e), "Preset Schedule Error")
                    raise e
                    
                self.set_widgets_from_preset(preset, manual=False)
                self.total_combo.setCurrentText(str(preset_task.count_runs if preset_task.count_runs > 0 else starting_total))
                self.run()
                
                # Wait for current run to complete
                time.sleep(0.1)
                started_run_id = self.current_run.id
                while (self.current_run is not None and 
                       started_run_id == self.current_run.id and 
                       not self.current_run.is_cancelled and 
                       not self.current_run.is_complete):
                    if not self.job_queue_preset_schedules.has_pending() or not self.run_preset_schedule_var.isChecked():
                        self.job_queue_preset_schedules.cancel()
                        return
                    time.sleep(1)
                    
            self.total_combo.setCurrentText(str(starting_total))
            self.job_queue_preset_schedules.job_running = False
            
            next_preset_schedule_args = self.job_queue_preset_schedules.take()
            if next_preset_schedule_args is None:
                self.job_queue_preset_schedules.cancel()
            else:
                self.run_preset_schedule(override_args=next_preset_schedule_args)

        Utils.start_thread(run_preset_async, use_asyncio=False)

    def load_info_cache(self):
        try:
            self.config_history_index = app_info_cache.get("config_history_index", default_val=0)
            BlacklistWindow.set_blacklist()
            PresetsWindow.set_recent_presets()
            SchedulesWindow.set_schedules()
            ExpansionsWindow.set_expansions()
            return RunnerAppConfig.from_dict(app_info_cache.get_history(0))
        except Exception as e:
            print(e)
            return RunnerAppConfig()

    def store_info_cache(self):
        if self.runner_app_config is not None:
            if app_info_cache.set_history(self.runner_app_config):
                if self.config_history_index > 0:
                    self.config_history_index -= 1
        app_info_cache.set("config_history_index", self.config_history_index)
        BlacklistWindow.store_blacklist()
        PresetsWindow.store_recent_presets()
        SchedulesWindow.store_schedules()
        ExpansionsWindow.store_expansions()
        app_info_cache.store()

def main():
    try:
        app = QApplication(sys.argv)
        
        # Register signal handlers for graceful shutdown
        def signal_handler(signum, frame):
            print("Caught signal, shutting down gracefully...")
            app.quit()
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
        # Set up dark theme
        AppStyle.IS_DEFAULT_THEME = True
        AppStyle.BG_COLOR = config.background_color or "#053E10"
        AppStyle.FG_COLOR = config.foreground_color or "white"
        
        window = App()
        window.show()
        sys.exit(app.exec())
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()

if __name__ == "__main__":
    main() 