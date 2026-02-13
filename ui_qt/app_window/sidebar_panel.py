"""
SidebarPanel -- two-column run/prompts configuration panel.

Owns all sidebar widgets (labels, entries, buttons, checkboxes, dropdowns,
sliders, text boxes) and exposes references so that ``AppWindow`` and
controllers can read/write UI state.

Left column:  Run configuration (software, workflow, model tags, etc.)
Right column: Prompts configuration (prompt mode, positive/negative tags, etc.)
"""

import tkinter.font as fnt
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QComboBox, QCheckBox, QPushButton,
    QPlainTextEdit, QSlider, QProgressBar, QScrollArea, QFrame,
    QSplitter,
)
from PySide6.QtCore import Qt

from lib.autocomplete_entry_qt import AutocompleteEntry, default_matches
from lib.aware_entry_qt import AwareEntry
from ui_qt.app_style import AppStyle
from utils.globals import (
    PromptMode, WorkflowType, SoftwareType, ResolutionGroup,
    Sampler, Scheduler,
)
from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._
logger = get_logger("ui_qt.sidebar_panel")


# ---------------------------------------------------------------------------
# Tag-splitting helpers (ported from app.py module-level functions)
# ---------------------------------------------------------------------------

def matches_tag(field_value: str, ac_list_entry: str) -> bool:
    """Match against the rightmost segment after ``+`` or ``,``."""
    if field_value and "+" in field_value:
        pattern_base = field_value.split("+")[-1]
    elif field_value and "," in field_value:
        pattern_base = field_value.split(",")[-1]
    else:
        pattern_base = field_value
    return default_matches(pattern_base, ac_list_entry)


def set_tag(current_value: str, new_value: str) -> str:
    """Append *new_value* after the last separator, or replace entirely."""
    if current_value and (current_value.endswith("+") or current_value.endswith(",")):
        return current_value + new_value
    return new_value


class SidebarPanel(QWidget):
    """Two-column configuration panel for the main window.

    Parameters
    ----------
    parent : QWidget
        Visual parent (the splitter or main layout).
    app_window : AppWindow
        Back-reference for reading/writing application state.
    """

    def __init__(self, parent: QWidget, app_window):
        super().__init__(parent)
        self._app = app_window

        # Master layout: left column | right column
        master_layout = QHBoxLayout(self)
        master_layout.setContentsMargins(4, 4, 4, 4)
        master_layout.setSpacing(6)

        # Wrap each column in a scroll area
        self._left_column = self._build_left_column()
        self._right_column = self._build_right_column()

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(self._left_column)
        left_scroll.setFrameShape(QFrame.Shape.NoFrame)

        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setWidget(self._right_column)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)

        master_layout.addWidget(left_scroll, stretch=1)
        master_layout.addWidget(right_scroll, stretch=1)

    # ==================================================================
    # LEFT COLUMN -- Run Configuration
    # ==================================================================
    def _build_left_column(self) -> QWidget:
        from sd_runner.models import Model

        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        runner_cfg = self._app.runner_app_config

        # Title
        title = QLabel(_("Run SD Workflows"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Run / Cancel buttons
        self.run_btn = QPushButton(_("Run Workflows"))
        self.run_btn.clicked.connect(lambda: self._app.run_ctrl.run())
        layout.addWidget(self.run_btn)

        self.cancel_btn = QPushButton(_("Cancel Run"))
        self.cancel_btn.clicked.connect(lambda: self._app.run_ctrl.cancel())
        self.cancel_btn.setVisible(False)
        layout.addWidget(self.cancel_btn)

        # Progress labels
        self.label_progress = QLabel("")
        layout.addWidget(self.label_progress)

        row = QHBoxLayout()
        self.label_batch_info = QLabel("")
        self.label_adapter_progress = QLabel("")
        row.addWidget(self.label_batch_info)
        row.addWidget(self.label_adapter_progress)
        layout.addLayout(row)

        row2 = QHBoxLayout()
        self.label_pending = QLabel("")
        self.label_time_est = QLabel("")
        row2.addWidget(self.label_pending)
        row2.addWidget(self.label_time_est)
        layout.addLayout(row2)

        row3 = QHBoxLayout()
        self.label_pending_adapters = QLabel("")
        self.label_pending_preset_schedules = QLabel("")
        row3.addWidget(self.label_pending_adapters)
        row3.addWidget(self.label_pending_preset_schedules)
        layout.addLayout(row3)

        # Software / Workflow dropdowns
        self.software_combo = self._add_combo_row(
            layout, _("Software"),
            list(SoftwareType.__members__.keys()),
            runner_cfg.software_type,
        )
        self.workflow_combo = self._add_combo_row(
            layout, _("Workflow"),
            [wf.get_translation() for wf in WorkflowType],
            WorkflowType.get(runner_cfg.workflow_type).get_translation(),
        )

        # N Latents / Total / Batch Limit / Delay
        self.n_latents_combo = self._add_combo_row(
            layout, _("Set N Latents"),
            [str(i) for i in range(51)],
            str(runner_cfg.n_latents),
        )
        total_opts = [str(i) for i in range(-1, 101) if i != 0]
        self.total_combo = self._add_combo_row(
            layout, _("Set Total"), total_opts, str(runner_cfg.total),
        )
        batch_opts = ["-1", "1", "2", "5", "10", "20", "50", "100",
                      "200", "500", "1000", "2000", "5000", "10000"]
        self.batch_limit_combo = self._add_combo_row(
            layout, _("Batch Limit"), batch_opts, str(runner_cfg.batch_limit),
        )
        self.delay_combo = self._add_combo_row(
            layout, _("Delay Seconds"),
            [str(i) for i in range(101)],
            str(runner_cfg.delay_time_seconds),
        )

        # Resolutions / Resolution Group
        self.resolutions_entry = self._add_entry_row(
            layout, _("Resolutions"), runner_cfg.resolutions,
        )
        self.resolution_group_combo = self._add_combo_row(
            layout, _("Resolution Group"),
            ResolutionGroup.display_values(),
            str(runner_cfg.resolution_group),
        )

        # Model Tags (with autocomplete)
        model_names = [str(m).split(".")[0] for m in Model.CHECKPOINTS]
        row_m = QHBoxLayout()
        row_m.addWidget(QLabel(_("Model Tags")))
        self.models_window_btn = QPushButton(_("Models"))
        self.models_window_btn.clicked.connect(
            lambda: self._app.window_launcher.open_models_window()
        )
        row_m.addWidget(self.models_window_btn)
        layout.addLayout(row_m)

        self.model_tags_entry = AutocompleteEntry(
            model_names, parent=self,
            listbox_length=6,
            matches_function=matches_tag,
            set_function=set_tag,
        )
        self.model_tags_entry.setText(runner_cfg.model_tags)
        layout.addWidget(self.model_tags_entry)

        # LoRA Tags (with autocomplete)
        lora_names = [str(l).split(".")[0] for l in Model.LORAS]
        row_l = QHBoxLayout()
        row_l.addWidget(QLabel(_("LoRA Tags")))
        self.lora_models_btn = QPushButton(_("Models"))
        self.lora_models_btn.clicked.connect(
            lambda: self._app.window_launcher.open_lora_models_window()
        )
        row_l.addWidget(self.lora_models_btn)
        layout.addLayout(row_l)

        self.lora_tags_entry = AutocompleteEntry(
            lora_names, parent=self,
            listbox_length=6,
            matches_function=matches_tag,
            set_function=set_tag,
        )
        if runner_cfg.lora_tags:
            self.lora_tags_entry.setText(runner_cfg.lora_tags)
        layout.addWidget(self.lora_tags_entry)

        # LoRA Strength slider
        self.lora_strength_slider = self._add_slider_row(
            layout, _("Default LoRA Strength"),
            int(float(runner_cfg.lora_strength) * 100),
        )

        # B/W Colorization
        self.bw_colorization_entry = self._add_entry_row(
            layout, _("B/W Colorization Tags"), runner_cfg.b_w_colorization,
        )

        # Control Net
        row_cn = QHBoxLayout()
        row_cn.addWidget(QLabel(_("Control Net or Redo files")))
        self.controlnet_recent_btn = QPushButton(_("Recent"))
        self.controlnet_recent_btn.clicked.connect(
            lambda: self._app.window_launcher.open_controlnet_adapters_window()
        )
        row_cn.addWidget(self.controlnet_recent_btn)
        layout.addLayout(row_cn)

        self.controlnet_file_entry = AwareEntry(self)
        self.controlnet_file_entry.setText(runner_cfg.control_net_file)
        layout.addWidget(self.controlnet_file_entry)

        self.controlnet_strength_slider = self._add_slider_row(
            layout, _("Default Control Net Strength"),
            int(float(runner_cfg.control_net_strength) * 100),
        )

        # IPAdapter
        row_ip = QHBoxLayout()
        row_ip.addWidget(QLabel(_("IPAdapter files")))
        self.ipadapter_recent_btn = QPushButton(_("Recent"))
        self.ipadapter_recent_btn.clicked.connect(
            lambda: self._app.window_launcher.open_ipadapter_adapters_window()
        )
        row_ip.addWidget(self.ipadapter_recent_btn)
        layout.addLayout(row_ip)

        self.ipadapter_file_entry = AwareEntry(self)
        self.ipadapter_file_entry.setText(runner_cfg.ip_adapter_file)
        layout.addWidget(self.ipadapter_file_entry)

        self.ipadapter_strength_slider = self._add_slider_row(
            layout, _("Default IPAdapter Strength"),
            int(float(runner_cfg.ip_adapter_strength) * 100),
        )

        # Redo Parameters
        self.redo_params_entry = self._add_entry_row(
            layout, _("Redo Parameters"), runner_cfg.redo_params,
        )

        layout.addStretch()
        return widget

    # ==================================================================
    # RIGHT COLUMN -- Prompts Configuration
    # ==================================================================
    def _build_right_column(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        runner_cfg = self._app.runner_app_config

        title = QLabel(_("Prompts Configuration"))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Window launcher buttons (row 1)
        btn_row1 = QHBoxLayout()
        self.preset_schedules_btn = QPushButton(_("Preset Schedule"))
        self.preset_schedules_btn.clicked.connect(
            lambda: self._app.window_launcher.open_preset_schedules_window()
        )
        btn_row1.addWidget(self.preset_schedules_btn)

        self.presets_btn = QPushButton(_("Presets"))
        self.presets_btn.clicked.connect(
            lambda: self._app.window_launcher.open_presets_window()
        )
        btn_row1.addWidget(self.presets_btn)

        self.timed_schedules_btn = QPushButton(_("Timed Schedules"))
        self.timed_schedules_btn.clicked.connect(
            lambda: self._app.window_launcher.open_timed_schedules_window()
        )
        btn_row1.addWidget(self.timed_schedules_btn)
        layout.addLayout(btn_row1)

        # Window launcher buttons (row 2)
        btn_row2 = QHBoxLayout()
        self.blacklist_btn = QPushButton(_("Tag Blacklist"))
        self.blacklist_btn.clicked.connect(
            lambda: self._app.window_launcher.show_tag_blacklist()
        )
        btn_row2.addWidget(self.blacklist_btn)

        self.expansions_btn = QPushButton(_("Expansions"))
        self.expansions_btn.clicked.connect(
            lambda: self._app.window_launcher.open_expansions_window()
        )
        btn_row2.addWidget(self.expansions_btn)

        self.prompt_config_btn = QPushButton(_("Prompt Config"))
        self.prompt_config_btn.clicked.connect(
            lambda: self._app.window_launcher.open_prompt_config_window()
        )
        btn_row2.addWidget(self.prompt_config_btn)
        layout.addLayout(btn_row2)

        # Prompt Mode + Concept Editor
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel(_("Prompt Mode")))
        self.prompt_mode_combo = QComboBox()
        self.prompt_mode_combo.addItems(PromptMode.display_values())
        starting_mode = runner_cfg.prompter_config.prompt_mode.display()
        idx = self.prompt_mode_combo.findText(starting_mode)
        if idx >= 0:
            self.prompt_mode_combo.setCurrentIndex(idx)
        mode_row.addWidget(self.prompt_mode_combo)

        self.concept_editor_btn = QPushButton(_("Edit Concepts"))
        self.concept_editor_btn.clicked.connect(
            lambda: self._app.window_launcher.open_concept_editor_window()
        )
        mode_row.addWidget(self.concept_editor_btn)
        layout.addLayout(mode_row)

        # Concepts Dir
        concepts_row = QHBoxLayout()
        concepts_row.addWidget(QLabel(_("Concepts Dir")))
        from utils.config import config as app_config
        self.concepts_dir_combo = QComboBox()
        self.concepts_dir_combo.addItems(list(app_config.concepts_dirs.keys()))
        concepts_row.addWidget(self.concepts_dir_combo)
        layout.addLayout(concepts_row)

        # Checkboxes
        self.override_resolution_check = QCheckBox(_("Override Resolution"))
        self.override_resolution_check.setChecked(runner_cfg.override_resolution)
        layout.addWidget(self.override_resolution_check)

        self.inpainting_check = QCheckBox(_("Inpainting"))
        self.inpainting_check.setChecked(False)
        layout.addWidget(self.inpainting_check)

        self.override_negative_check = QCheckBox(_("Override Base Negative"))
        self.override_negative_check.setChecked(False)
        layout.addWidget(self.override_negative_check)

        self.run_preset_schedule_check = QCheckBox(_("Run Preset Schedule"))
        self.run_preset_schedule_check.setChecked(False)
        layout.addWidget(self.run_preset_schedule_check)

        self.continuous_seed_var_check = QCheckBox(_("Continuous Seed Variation"))
        self.continuous_seed_var_check.setChecked(runner_cfg.continuous_seed_variation)
        layout.addWidget(self.continuous_seed_var_check)

        # Prompt Massage Tags
        layout.addWidget(QLabel(_("Prompt Massage Tags")))
        self.prompt_massage_tags_box = QPlainTextEdit()
        self.prompt_massage_tags_box.setMaximumHeight(80)
        self.prompt_massage_tags_box.setPlainText(runner_cfg.prompt_massage_tags)
        layout.addWidget(self.prompt_massage_tags_box)

        # Positive Tags
        layout.addWidget(QLabel(_("Positive Tags")))
        self.positive_tags_box = QPlainTextEdit()
        self.positive_tags_box.setPlainText(runner_cfg.positive_tags)
        layout.addWidget(self.positive_tags_box)

        # Negative Tags
        layout.addWidget(QLabel(_("Negative Tags")))
        self.negative_tags_box = QPlainTextEdit()
        self.negative_tags_box.setMaximumHeight(80)
        self.negative_tags_box.setPlainText(runner_cfg.negative_tags)
        layout.addWidget(self.negative_tags_box)

        layout.addStretch()
        return widget

    # ==================================================================
    # Public helpers
    # ==================================================================
    def close_autocomplete_popups(self) -> None:
        """Dismiss any open autocomplete popups."""
        self.model_tags_entry.close_listbox()
        self.lora_tags_entry.close_listbox()

    def next_preset(self) -> None:
        """Advance to the next preset (placeholder)."""
        # TODO: wire to PresetSchedulesQueue or PresetsWindow
        pass

    def set_widgets_from_preset(self, preset, manual: bool = True) -> None:
        """Apply a preset to the UI widgets."""
        self.prompt_mode_combo.setCurrentText(preset.prompt_mode)
        self.positive_tags_box.setPlainText(preset.positive_tags)
        self.negative_tags_box.setPlainText(preset.negative_tags)
        if manual:
            self.run_preset_schedule_check.setChecked(False)

    def construct_preset(self, name: str):
        """Build a ``Preset`` from the current widget values."""
        from ui.preset import Preset
        args, _ = self._app.get_args()
        self._app.runner_app_config.set_from_run_config(args)
        self._app.cache_ctrl.store_info_cache()
        return Preset.from_runner_app_config(name, self._app.runner_app_config)

    # ==================================================================
    # Private widget-building helpers
    # ==================================================================
    @staticmethod
    def _add_combo_row(
        layout: QVBoxLayout, label_text: str,
        items: list[str], current: str,
    ) -> QComboBox:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        combo = QComboBox()
        combo.addItems(items)
        idx = combo.findText(current)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        row.addWidget(combo)
        layout.addLayout(row)
        return combo

    @staticmethod
    def _add_entry_row(
        layout: QVBoxLayout, label_text: str, initial: str = "",
    ) -> AwareEntry:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        entry = AwareEntry()
        entry.setText(initial)
        row.addWidget(entry)
        layout.addLayout(row)
        return entry

    @staticmethod
    def _add_slider_row(
        layout: QVBoxLayout, label_text: str, value: int = 50,
    ) -> QSlider:
        row = QHBoxLayout()
        row.addWidget(QLabel(label_text))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(0, 100)
        slider.setValue(value)
        row.addWidget(slider)
        layout.addLayout(row)
        return slider
