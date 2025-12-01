from copy import deepcopy
import datetime
import os
import signal
import time
import traceback
from typing import Optional

from tkinter import messagebox, Frame, Label, Checkbutton, Text, StringVar, BooleanVar, END, HORIZONTAL, NW, BOTH, YES, N, E, W
from tkinter.constants import W
import tkinter.font as fnt
from tkinter.ttk import Button, OptionMenu, Progressbar, Scale
from lib.autocomplete_entry import AutocompleteEntry, matches
from lib.multi_display import SmartToplevel
from ttkthemes import ThemedTk

from run import Run
from utils.globals import (
    Globals, PromptMode, WorkflowType, Sampler, Scheduler, SoftwareType,
    ResolutionGroup, ProtectedActions, BlacklistMode, BlacklistPromptMode
)

from extensions.sd_runner_server import SDRunnerServer

from lib.aware_entry import AwareEntry, AwareText
from sd_runner.blacklist import Blacklist, BlacklistException
from sd_runner.comfy_gen import ComfyGen
from sd_runner.gen_config import GenConfig
from sd_runner.model_adapters import IPAdapter
from sd_runner.models import Model
from sd_runner.prompter import Prompter
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from sd_runner.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
from utils.time_estimator import TimeEstimator
from ui.app_actions import AppActions
from ui.app_style import AppStyle
from ui.concept_editor_window import ConceptEditorWindow
from ui.expansions_window import ExpansionsWindow
from ui.auth.password_admin_window import PasswordAdminWindow
from ui.auth.password_utils import check_password_required, require_password
from ui.auth.password_core import get_security_config
from ui.models_window import ModelsWindow
from ui.recent_adapters_window import RecentAdaptersWindow
from ui.preset import Preset
from ui.presets_window import PresetsWindow
from ui.schedules_windows import SchedulesWindow
from ui.timed_schedules_window import TimedSchedulesWindow
from ui.tags_blacklist_window import BlacklistWindow
from ui.prompt_config_window import PromptConfigWindow
from ui.scheduled_shutdown_dialog import ScheduledShutdownDialog
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.job_queue import SDRunsQueue, PresetSchedulesQueue
from utils.logging_setup import get_logger, set_logger_level
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._

logger = get_logger("app")

def set_attr_if_not_empty(text_box):
    current_value = text_box.get()
    if not current_value or current_value == "":
        return None
    return 

def matches_tag(fieldValue, acListEntry):
    if fieldValue and "+" in fieldValue:
        pattern_base = fieldValue.split("+")[-1]
    elif fieldValue and "," in fieldValue:
        pattern_base = fieldValue.split(",")[-1]
    else:
        pattern_base = fieldValue
    return matches(pattern_base, acListEntry)

def set_tag(current_value, new_value):
    if current_value and (current_value.endswith("+") or current_value.endswith(",")):
        return current_value + new_value
    else:
        return new_value
    
def clear_quotes(s):
    if len(s) > 0:
        if s.startswith('"'):
            s = s[1:]
        if s.endswith('"'):
            s = s[:-1]
        if s.startswith("'"):
            s = s[1:]
        if s.endswith("'"):
            s = s[:-1]
    return s


class Sidebar(Frame):
    def __init__(self, master=None, cnf={}, **kw):
        Frame.__init__(self, master=master, cnf=cnf, **kw)


class App():
    '''
    UI for Stable Diffusion workflow management.
    '''

    def __init__(self, master):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.progress_bar = None
        self.job_queue = SDRunsQueue()
        self.job_queue_preset_schedules = PresetSchedulesQueue(
            get_run_config_callback=self.get_basic_run_config,
            get_current_schedule_callback=lambda: SchedulesWindow.current_schedule
        )
        self.server = self.setup_server()
        self.runner_app_config = self.load_info_cache()
        self.config_history_index = 0
        self.current_run = Run(RunConfig())
        Model.load_all()

        self.app_actions = AppActions({"update_progress": self.update_progress,
                                      "update_pending": self.update_pending,
                                      "update_time_estimation": self.update_time_estimation,
                                      "construct_preset": self.construct_preset,
                                      "set_widgets_from_preset": self.set_widgets_from_preset,
                                      "open_password_admin_window": self.open_password_admin_window,
                                      "set_model_from_models_window": self.set_model_from_models_window,
                                      "set_adapter_from_adapters_window": self.set_adapter_from_adapters_window,
                                      "add_recent_adapter_file": RecentAdaptersWindow.add_recent_adapter_file,
                                      "contains_recent_adapter_file": RecentAdaptersWindow.contains_recent_adapter_file,
                                      "toast": self.toast,
                                      "_alert": self.alert,}, master=self.master)

        # Set UI callbacks for Blacklist filtering notifications
        Blacklist.set_ui_callbacks(self.app_actions)

        # Sidebar
        self.sidebar = Sidebar(self.master)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.columnconfigure(0, weight=1)
        self.row_counter0 = 0
        self.sidebar.grid(column=0, row=self.row_counter0)
        self.label_title = Label(self.sidebar)
        self.add_label(self.label_title, _("Run SD Workflows"), sticky=None, columnspan=2)
        ## TODO change above label to be software-agnostic (i18n)

        self.run_btn = None
        self.add_button("run_btn", _("Run Workflows"), self.run)

        self.cancel_btn = Button(self.sidebar, text=_("Cancel Run"), command=self.cancel)
        self.label_progress = Label(self.sidebar)
        self.add_label(self.label_progress, "", sticky=None)
        
        self.label_pending = Label(self.sidebar)
        self.add_label(self.label_pending, "", sticky=None, increment_row_counter=False)
        self.label_time_est = Label(self.sidebar)
        self.add_label(self.label_time_est, "", sticky=None, interior_column=1)

        # Additional progress information row
        self.label_pending_adapters = Label(self.sidebar)
        self.add_label(self.label_pending_adapters, "", sticky=None, increment_row_counter=False)
        self.label_pending_preset_schedules = Label(self.sidebar)
        self.add_label(self.label_pending_preset_schedules, "", sticky=None, interior_column=1)

        self.label_software = Label(self.sidebar)
        self.add_label(self.label_software, _("Software"), increment_row_counter=False)
        self.software = StringVar(master)
        self.software_choice = OptionMenu(self.sidebar, self.software, self.runner_app_config.software_type,
                                          *SoftwareType.__members__.keys(), command=self.set_software_type)
        self.apply_to_grid(self.software_choice, interior_column=1, sticky=W)

        # TODO multiselect
        self.label_workflows = Label(self.sidebar)
        self.add_label(self.label_workflows, _("Workflow"), increment_row_counter=False)
        self.workflow = StringVar(master)
        self.workflows_choice = OptionMenu(self.sidebar, self.workflow, WorkflowType.get(self.runner_app_config.workflow_type).get_translation(),
                                           *[wf.get_translation() for wf in WorkflowType], command=self.set_workflow_type)
        self.apply_to_grid(self.workflows_choice, interior_column=1, sticky=W)

        self.label_n_latents = Label(self.sidebar)
        self.add_label(self.label_n_latents, _("Set N Latents"), increment_row_counter=False)
        self.n_latents = StringVar(master)
        self.n_latents_choice = OptionMenu(self.sidebar, self.n_latents, str(self.runner_app_config.n_latents), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.n_latents_choice, interior_column=1, sticky=W)

        self.label_total = Label(self.sidebar)
        self.add_label(self.label_total, _("Set Total"), increment_row_counter=False)
        self.total = StringVar(master)
        total_options = [str(i) for i in list(range(-1, 101))]
        total_options.remove('0')
        self.total_choice = OptionMenu(self.sidebar, self.total, str(self.runner_app_config.total), *total_options)
        self.apply_to_grid(self.total_choice, interior_column=1, sticky=W)

        self.label_batch_limit = Label(self.sidebar)
        self.add_label(self.label_batch_limit, _("Batch Limit"), increment_row_counter=False)
        self.batch_limit = StringVar(master)
        batch_limit_options = ['-1', '1', '2', '5', '10', '20', '50', '100', '200', '500', '1000', '2000', '5000', '10000']
        self.batch_limit_choice = OptionMenu(self.sidebar, self.batch_limit, str(self.runner_app_config.batch_limit), *batch_limit_options)
        self.apply_to_grid(self.batch_limit_choice, interior_column=1, sticky=W)

        self.label_delay = Label(self.sidebar)
        self.add_label(self.label_delay, _("Delay Seconds"), increment_row_counter=False)
        self.delay = StringVar(master)
        self.delay_choice = OptionMenu(self.sidebar, self.delay, str(self.runner_app_config.delay_time_seconds), *[str(i) for i in list(range(101))], command=self.set_delay)
        self.apply_to_grid(self.delay_choice, interior_column=1, sticky=W)

        self.label_resolutions = Label(self.sidebar)
        self.add_label(self.label_resolutions, _("Resolutions"), increment_row_counter=False)
        self.resolutions = StringVar()
        self.resolutions_box = self.new_entry(self.resolutions, width=20)
        self.resolutions_box.insert(0, self.runner_app_config.resolutions)
        self.apply_to_grid(self.resolutions_box, interior_column=1, sticky=W)

        self.label_resolution_group = Label(self.sidebar)
        self.add_label(self.label_resolution_group, _("Resolution Group"), increment_row_counter=False)
        self.resolution_group = StringVar(master)
        self.resolution_group_choice = OptionMenu(self.sidebar, self.resolution_group, str(self.runner_app_config.resolution_group), *ResolutionGroup.display_values())
        self.apply_to_grid(self.resolution_group_choice, interior_column=1, sticky=W)

        self.label_model_tags = Label(self.sidebar)
        self.add_label(self.label_model_tags, _("Model Tags"), increment_row_counter=False)
        self.models_window_btn = None
        self.add_button("models_window_btn", text=_("Models"), command=self.open_models_window, sidebar=True, interior_column=1)
        self.model_tags = StringVar()
        model_names = list(map(lambda l: str(l).split('.')[0], Model.CHECKPOINTS))
        self.model_tags_box = AutocompleteEntry(model_names,
                                               self.sidebar,
                                               listboxLength=6,
                                               textvariable=self.model_tags,
                                               matchesFunction=matches_tag,
                                               setFunction=set_tag,
                                               width=55, font=fnt.Font(size=8))
        self.model_tags_box.bind("<Return>", self.set_model_dependent_fields)
        self.model_tags_box.insert(0, self.runner_app_config.model_tags)
        self.apply_to_grid(self.model_tags_box, sticky=W, columnspan=2)

        self.label_lora_tags = Label(self.sidebar)
        self.add_label(self.label_lora_tags, _("LoRA Tags"), increment_row_counter=False)
        self.lora_models_window_btn = None
        self.add_button("lora_models_window_btn", text=_("Models"), command=self.open_lora_models_window, sidebar=True, interior_column=1)
        self.lora_tags = StringVar()
        lora_names = list(map(lambda l: str(l).split('.')[0], Model.LORAS))

        self.lora_tags_box = AutocompleteEntry(lora_names,
                                               self.sidebar,
                                               listboxLength=6,
                                               textvariable=self.lora_tags,
                                               matchesFunction=matches_tag,
                                               setFunction=set_tag,
                                               width=55, font=fnt.Font(size=8))
        if self.runner_app_config.lora_tags is not None and self.runner_app_config.lora_tags!= "":
            self.lora_tags.set(self.runner_app_config.lora_tags)
        self.apply_to_grid(self.lora_tags_box, sticky=W, columnspan=2)

        self.label_lora_strength = Label(self.sidebar)
        self.add_label(self.label_lora_strength, _("Default LoRA Strength"), increment_row_counter=False)
        self.lora_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_lora_strength)
        self.set_widget_value(self.lora_strength_slider, self.runner_app_config.lora_strength)
        self.apply_to_grid(self.lora_strength_slider, interior_column=1, sticky=W)

        self.label_bw_colorization = Label(self.sidebar)
        self.add_label(self.label_bw_colorization, _("B/W Colorization Tags"), increment_row_counter=False)
        self.bw_colorization = StringVar()
        self.bw_colorization_box = self.new_entry(self.bw_colorization, width=20)
        self.bw_colorization_box.insert(0, self.runner_app_config.b_w_colorization)
        self.apply_to_grid(self.bw_colorization_box, interior_column=1, sticky=W)
        self.bw_colorization_box.bind("<Return>", self.set_bw_colorization)

        self.label_controlnet_file = Label(self.sidebar)
        self.add_label(self.label_controlnet_file, _("Control Net or Redo files"), increment_row_counter=False)
        self.controlnet_adapters_window_btn = None
        self.add_button("controlnet_adapters_window_btn", text=_("Recent"), command=self.open_controlnet_adapters_window, sidebar=True, interior_column=1)
        self.controlnet_file = StringVar()
        self.controlnet_file_box = self.new_entry(self.controlnet_file)
        self.controlnet_file_box.insert(0, self.runner_app_config.control_net_file)
        self.apply_to_grid(self.controlnet_file_box, sticky=W, columnspan=2)

        self.label_controlnet_strength = Label(self.sidebar)
        self.add_label(self.label_controlnet_strength, _("Default Control Net Strength"), increment_row_counter=False)
        self.controlnet_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_controlnet_strength)
        self.set_widget_value(self.controlnet_strength_slider, self.runner_app_config.control_net_strength)
        self.apply_to_grid(self.controlnet_strength_slider, interior_column=1, sticky=W)

        self.label_ipadapter_file = Label(self.sidebar)
        self.add_label(self.label_ipadapter_file, _("IPAdapter files"), increment_row_counter=False)
        self.ipadapter_adapters_window_btn = None
        self.add_button("ipadapter_adapters_window_btn", text=_("Recent"), command=self.open_ipadapter_adapters_window, sidebar=True, interior_column=1)
        self.ipadapter_file = StringVar()
        self.ipadapter_file_box = self.new_entry(self.ipadapter_file)
        self.ipadapter_file_box.insert(0, self.runner_app_config.ip_adapter_file)
        self.apply_to_grid(self.ipadapter_file_box, sticky=W, columnspan=2)

        self.label_ipadapter_strength = Label(self.sidebar)
        self.add_label(self.label_ipadapter_strength, _("Default IPAdapter Strength"), increment_row_counter=False)
        self.ipadapter_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_ipadapter_strength)
        self.set_widget_value(self.ipadapter_strength_slider, self.runner_app_config.ip_adapter_strength)
        self.apply_to_grid(self.ipadapter_strength_slider, interior_column=1, sticky=W)

        self.label_redo_params = Label(self.sidebar)
        self.add_label(self.label_redo_params, _("Redo Parameters"), increment_row_counter=False)
        self.redo_params = StringVar()
        self.redo_params_box = self.new_entry(self.redo_params, width=20)
        self.redo_params_box.insert(0, self.runner_app_config.redo_params)
        self.apply_to_grid(self.redo_params_box, interior_column=1, sticky=W)
        self.redo_params_box.bind("<Return>", self.set_redo_params)

        # Second Column
        self.row_counter1 = 0
        self.second_column = Sidebar(self.master)
        self.second_column.columnconfigure(0, weight=1)
        self.second_column.columnconfigure(1, weight=1)
        self.second_column.columnconfigure(2, weight=1)
        self.second_column.grid(column=1, row=self.row_counter1)
        
        self.label_title_config = Label(self.second_column)
        self.add_label(self.label_title_config, _("Prompts Configuration"), column=1, columnspan=3, sticky=W+E)

        self.preset_schedules_window_btn = None
        self.presets_window_btn = None
        self.timed_schedules_window_btn = None
        self.add_button("preset_schedules_window_btn", text=_("Preset Schedule Window"), command=self.open_preset_schedules_window, sidebar=False, increment_row_counter=False)
        self.add_button("presets_window_btn", text=_("Presets Window"), command=self.open_presets_window, sidebar=False, interior_column=1, increment_row_counter=False)
        self.add_button("timed_schedules_window_btn", text=_("Timed Schedules Window"), command=self.open_timed_schedules_window, sidebar=False, interior_column=2)

        self.tag_blacklist_btn = None
        self.expansions_window_btn = None
        # self.password_admin_btn = None
        self.add_button("tag_blacklist_btn", text=_("Tag Blacklist"), command=self.show_tag_blacklist, sidebar=False, increment_row_counter=False)
        self.add_button("expansions_window_btn", text=_("Expansions Window"), command=self.open_expansions_window, sidebar=False, interior_column=1)
        # self.add_button("password_admin_btn", text=_("Password Administration"), command=self.open_password_admin_window, sidebar=False, increment_row_counter=True)

        self.prompt_config_window_btn = None
        self.add_button("prompt_config_window_btn", text=_("Prompts Configuration"), command=self.open_prompt_config_window, sidebar=False, increment_row_counter=False, interior_column=2)

        self.label_prompt_mode = Label(self.second_column)
        self.add_label(self.label_prompt_mode, _("Prompt Mode"), column=1, increment_row_counter=False)
        self.prompt_mode = StringVar(master)
        starting_prompt_mode = self.runner_app_config.prompter_config.prompt_mode.display()
        self.prompt_mode_choice = OptionMenu(self.second_column, self.prompt_mode, starting_prompt_mode, *PromptMode.display_values(), command=self.check_prompt_mode_password)
        self.apply_to_grid(self.prompt_mode_choice, interior_column=1, sticky=W, column=1)

        self.concept_editor_window_btn = None
        self.add_button("concept_editor_window_btn", text=_("Edit Concepts"), command=self.open_concept_editor_window, sidebar=False, increment_row_counter=False, interior_column=2)

        self.label_concepts_dir = Label(self.second_column)
        self.add_label(self.label_concepts_dir, _("Concepts Dir"), column=1, increment_row_counter=False)
        self.concepts_dir = StringVar(master)
        self.concepts_dir_choice = OptionMenu(self.second_column, self.concepts_dir, config.default_concepts_dir,
                                              *config.concepts_dirs.keys(), command=self.set_concepts_dir)
        self.apply_to_grid(self.concepts_dir_choice, interior_column=1, sticky=W, column=1)

        # self.auto_run_var = BooleanVar(value=True) TODO at some point add in a way to approve prompts before running in the UI.
        # self.auto_run_choice = Checkbutton(self.second_column, text=_('Auto Run'), variable=self.auto_run_var)
        # self.apply_to_grid(self.auto_run_choice, sticky=W, column=1)

        self.override_resolution_var = BooleanVar(value=self.runner_app_config.override_resolution)
        self.override_resolution_choice = Checkbutton(self.second_column, text=_('Override Resolution'), variable=self.override_resolution_var)
        self.apply_to_grid(self.override_resolution_choice, sticky=W, column=1)

        self.inpainting_var = BooleanVar(value=False)
        self.inpainting_choice = Checkbutton(self.second_column, text=_('Inpainting'), variable=self.inpainting_var)
        self.apply_to_grid(self.inpainting_choice, sticky=W, column=1)

        self.override_negative_var = BooleanVar(value=False)
        self.override_negative_choice = Checkbutton(self.second_column, text=_("Override Base Negative"), variable=self.override_negative_var, command=self.set_override_negative)
        self.apply_to_grid(self.override_negative_choice, sticky=W, column=1, columnspan=3)

        self.run_preset_schedule_var = BooleanVar(value=False)
        self.run_preset_schedule_choice = Checkbutton(self.second_column, text=_("Run Preset Schedule"), variable=self.run_preset_schedule_var)
        self.apply_to_grid(self.run_preset_schedule_choice, sticky=W, column=1, columnspan=3)

        self.continuous_seed_variation_var = BooleanVar(value=self.runner_app_config.continuous_seed_variation)
        self.continuous_seed_variation_choice = Checkbutton(self.second_column, text=_("Continuous Seed Variation"), variable=self.continuous_seed_variation_var)
        self.apply_to_grid(self.continuous_seed_variation_choice, sticky=W, column=1, columnspan=3)

        self.label_prompt_tags = Label(self.second_column)
        self.add_label(self.label_prompt_tags, _("Prompt Massage Tags"), column=1, columnspan=2)
        self.prompt_massage_tags_box = AwareText(self.second_column, height=4, width=70, font=fnt.Font(size=8))
        self.prompt_massage_tags_box.insert("0.0", self.runner_app_config.prompt_massage_tags)
        self.apply_to_grid(self.prompt_massage_tags_box, column=1, columnspan=3)
        self.prompt_massage_tags_box.bind("<Return>", self.set_prompt_massage_tags)

        self.label_positive_tags = Label(self.second_column)
        self.add_label(self.label_positive_tags, _("Positive Tags"), columnspan=3)
        self.positive_tags_box = AwareText(self.second_column, height=11, width=70, font=fnt.Font(size=8))
        self.positive_tags_box.insert("0.0", self.runner_app_config.positive_tags)
        self.apply_to_grid(self.positive_tags_box, columnspan=3)
        self.positive_tags_box.bind("<Return>", self.set_positive_tags)

        self.label_negative_tags = Label(self.second_column)
        self.add_label(self.label_negative_tags, _("Negative Tags"), columnspan=3)
        self.negative_tags = StringVar()
        self.negative_tags_box = AwareText(self.second_column, height=4, width=70, font=fnt.Font(size=8))
        self.negative_tags_box.insert("0.0", self.runner_app_config.negative_tags)
        self.apply_to_grid(self.negative_tags_box, columnspan=3)
        self.negative_tags_box.bind("<Return>", self.set_negative_tags)

        self.master.bind("<Control-Return>", self.run)
        self.master.bind("<Shift-R>", lambda event: self.check_focus(event, self.run))
        self.master.bind("<Shift-N>", lambda event: self.check_focus(event, self.next_preset))
        self.master.bind("<Prior>", lambda event: self.one_config_away(change=1))
        self.master.bind("<Next>", lambda event: self.one_config_away(change=-1))
        self.master.bind("<Home>", lambda event: self.first_config())
        self.master.bind("<End>", lambda event: self.first_config(end=True))
        self.master.bind("<Control-b>", lambda event: self.check_focus(event, self.show_tag_blacklist))
        self.master.bind("<Control-q>", self.quit)
        self.master.bind("<Control-p>", lambda event: self.check_focus(event, self.open_password_admin_window))  # Password Administration
        self.master.bind("<Control-d>", lambda event: self.toggle_debug())
        self.toggle_theme()
        self.master.update()
        self.close_autocomplete_popups()

    def toggle_debug(self):
        config.debug = not config.debug
        set_logger_level(config.debug)
        self.master.title(_(" ComfyGen ") + (" (Debug)" if config.debug else ""))
        self.toast(_("Debug mode toggled.") + (" (Enabled)" if config.debug else " (Disabled)"))

    def toggle_theme(self, to_theme=None, do_toast=True):
        if (to_theme is None and AppStyle.IS_DEFAULT_THEME) or to_theme == AppStyle.LIGHT_THEME:
            if to_theme is None:
                self.master.set_theme("breeze", themebg="black")  # Changes the window to light theme
            AppStyle.BG_COLOR = "gray"
            AppStyle.FG_COLOR = "black"
        else:
            if to_theme is None:
                self.master.set_theme("black", themebg="black")  # Changes the window to dark theme
            AppStyle.BG_COLOR = config.background_color if config.background_color and config.background_color != "" else "#053E10"
            AppStyle.FG_COLOR = config.foreground_color if config.foreground_color and config.foreground_color != "" else "white"
        AppStyle.IS_DEFAULT_THEME = (not AppStyle.IS_DEFAULT_THEME or to_theme
                                     == AppStyle.DARK_THEME) and to_theme != AppStyle.LIGHT_THEME
        self.master.config(bg=AppStyle.BG_COLOR)
        self.sidebar.config(bg=AppStyle.BG_COLOR)
        self.second_column.config(bg=AppStyle.BG_COLOR)
        for name, attr in self.__dict__.items():
            if isinstance(attr, Label):
                attr.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
                            # font=fnt.Font(size=config.font_size))
            elif isinstance(attr, Checkbutton):
                attr.config(bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                            selectcolor=AppStyle.BG_COLOR)#, font=fnt.Font(size=config.font_size))
        self.master.update()
        if do_toast:
            self.toast(f"Theme switched to {AppStyle.get_theme_name()}.")

    def close_autocomplete_popups(self):
        self.model_tags_box.closeListbox()
        self.lora_tags_box.closeListbox()
        self.run_btn.focus_force()

    def on_closing(self):
        Utils.prevent_sleep(False)
        ComfyGen.close_all_connections()
        # Store display position and virtual screen info before storing cache
        try:
            app_info_cache.set_display_position(self.master)
            app_info_cache.set_virtual_screen_info(self.master)
        except Exception as e:
            logger.warning(f"Failed to store display position info: {e}")
        self.store_info_cache()
        app_info_cache.wipe_instance()
        if hasattr(self, 'server') and self.server is not None:
            try:
                self.server.stop()
            except Exception as e:
                logger.error(f"Error stopping server: {e}")
        if hasattr(self, 'current_run') and self.current_run is not None:
            self.current_run.cancel("Application shutdown")
        if hasattr(self, 'job_queue') and self.job_queue is not None:
            self.job_queue.cancel()
        if hasattr(self, 'job_queue_preset_schedules') and self.job_queue_preset_schedules is not None:
            self.job_queue_preset_schedules.cancel()
        
        from sd_runner.base_image_generator import BaseImageGenerator
        # Shutdown the thread pool executor to stop all background threads
        BaseImageGenerator.shutdown_executor(wait=False)
        # Clean up image converter temporary files on shutdown
        BaseImageGenerator.cleanup_image_converter()
        
        self.master.destroy()
        os._exit(0)


    def quit(self, event=None):
        res = self.alert(_("Confirm Quit"), _("Would you like to quit the application?"), kind="askokcancel")
        if self.is_alert_confirmed(res):
            logger.info("Exiting application")
            self.on_closing()


    def setup_server(self):
        server = SDRunnerServer(self.server_run_callback, self.cancel, self.revert_to_simple_gen)
        try:
            Utils.start_thread(server.start)
            return server
        except Exception as e:
            logger.error(f"Failed to start server: {e}")

    def store_info_cache(self):
        try:
            if self.runner_app_config is not None:
                if app_info_cache.set_history(self.runner_app_config):
                    if self.config_history_index > 0:
                        self.config_history_index -= 1
            app_info_cache.set("config_history_index", self.config_history_index)
            self.update_progress(override_text=_("Storing caches..."))
            BlacklistWindow.store_blacklist()
            PresetsWindow.store_recent_presets()
            SchedulesWindow.store_schedules()
            ExpansionsWindow.store_expansions()
            timed_schedules_manager.store_schedules()
            RecentAdaptersWindow.save_recent_adapters()
            get_security_config().save_settings()
            app_info_cache.store()
        except Exception as e:
            logger.error(f"Failed to store info cache: {e}")

    def load_info_cache(self):
        try:
            self.config_history_index = app_info_cache.get("config_history_index", default_val=0)
            BlacklistWindow.set_blacklist()
            PresetsWindow.set_recent_presets()
            SchedulesWindow.set_schedules()
            ExpansionsWindow.set_expansions()
            timed_schedules_manager.set_schedules()
            RecentAdaptersWindow.load_recent_adapters()
            # Security config is loaded automatically when first accessed
            get_security_config()
            config = RunnerAppConfig.from_dict(app_info_cache.get_history(0))
            
            # Set the runner_app_config reference on PromptConfigWindow for any existing instances
            PromptConfigWindow.set_runner_app_config(config)
            
            return config
        except Exception as e:
            logger.error(e)
            return RunnerAppConfig()

    def one_config_away(self, change=1):
        assert type(self.config_history_index) == int, "History index must be an integer"
        self.config_history_index += change
        try:
            self.runner_app_config = RunnerAppConfig.from_dict(app_info_cache.get_history(self.config_history_index))
            self.set_widgets_from_config()
            self.close_autocomplete_popups()
        except Exception as e:
            self.config_history_index -= change

    def first_config(self, end=False):
        self.config_history_index = app_info_cache.get_last_history_index() if end else 0
        try:
            self.runner_app_config = RunnerAppConfig.from_dict(app_info_cache.get_history(self.config_history_index))
            self.set_widgets_from_config()
            self.close_autocomplete_popups()
        except Exception as e:
            self.config_history_index = 0

    def set_default_config(self, event=None):
        self.runner_app_config = RunnerAppConfig()
        self.set_widgets_from_config()
        self.close_autocomplete_popups()

    def set_widget_value(self, widget, value):
        if isinstance(widget, Scale):
            widget.set(float(value) * 100)
        elif isinstance(widget, Text):
            widget.delete("0.0", "end")
            widget.insert("0.0", str(value))
        else:
            widget.delete(0, "end")
            widget.insert(0, value)

    def get_widget_value(self, widget):
        if isinstance(widget, Text):
            text = widget.get("1.0", END)
            if text.endswith("\n"):
                text = text[:-1]
            return text
        else:
            return widget.get()

    def set_widgets_from_config(self):
        if self.runner_app_config is None:
            raise Exception("No config to set widgets from")
        self.software.set(self.runner_app_config.software_type)
        self.set_workflow_type(self.runner_app_config.workflow_type)
        self.n_latents.set(str(self.runner_app_config.n_latents))
        self.total.set(str(self.runner_app_config.total))
        self.batch_limit.set(str(self.runner_app_config.batch_limit))
        self.delay.set(str(self.runner_app_config.delay_time_seconds))
        self.set_widget_value(self.resolutions_box, self.runner_app_config.resolutions)
        self.set_widget_value(self.model_tags_box, self.runner_app_config.model_tags)
        if self.runner_app_config.lora_tags is not None and self.runner_app_config.lora_tags!= "":
            self.set_widget_value(self.lora_tags_box, self.runner_app_config.lora_tags)
        self.set_widget_value(self.prompt_massage_tags_box, self.runner_app_config.prompt_massage_tags)
        self.set_widget_value(self.positive_tags_box, self.runner_app_config.positive_tags)
        self.set_widget_value(self.negative_tags_box, self.runner_app_config.negative_tags)
        self.set_widget_value(self.bw_colorization_box, self.runner_app_config.b_w_colorization)
        self.set_widget_value(self.lora_strength_slider, self.runner_app_config.lora_strength)
        self.set_widget_value(self.controlnet_file_box, self.runner_app_config.control_net_file)
        self.set_widget_value(self.controlnet_strength_slider, self.runner_app_config.control_net_strength)
        self.set_widget_value(self.ipadapter_file_box, self.runner_app_config.ip_adapter_file)
        self.set_widget_value(self.ipadapter_strength_slider, self.runner_app_config.ip_adapter_strength)
        self.set_widget_value(self.redo_params_box, self.runner_app_config.redo_params)

        # Prompter Config
        prompter_config = self.runner_app_config.prompter_config
        self.prompt_mode.set(str(prompter_config.prompt_mode))
        self.override_resolution_var.set(self.runner_app_config.override_resolution)
        self.inpainting_var.set(self.runner_app_config.inpainting)
        self.override_negative_var.set(self.runner_app_config.override_negative)
        self.continuous_seed_variation_var.set(self.runner_app_config.continuous_seed_variation)
        
        # Update the PromptConfigWindow class reference to keep it synchronized
        PromptConfigWindow.set_runner_app_config(self.runner_app_config)

    def set_widgets_from_preset(self, preset, manual=True):
        self.prompt_mode.set(preset.prompt_mode)
        self.set_widget_value(self.positive_tags_box, preset.positive_tags)
        self.set_widget_value(self.negative_tags_box, preset.negative_tags)
        if manual:
            self.run_preset_schedule_var.set(False)
        self.master.update()

    def construct_preset(self, name):
        args, args_copy = self.get_args()
        self.runner_app_config.set_from_run_config(args)
        # Store the configuration to cache when creating presets
        self.store_info_cache()
        return Preset.from_runner_app_config(name, self.runner_app_config)

    def run_preset_schedule(self, override_args={}):
        def run_preset_async():
            # Check for scheduled shutdown before starting preset schedule
            try:
                timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
            except ScheduledShutdownException as e:
                self._handle_scheduled_shutdown(e)
            
            self.job_queue_preset_schedules.job_running = True
            if "control_net" in override_args:
                self.controlnet_file.set(override_args["control_net"])
                if config.debug:
                    print(f"Updated Control Net for next preset schedule: " + str(override_args["control_net"]))
            if "ip_adapter" in override_args:
                self.ipadapter_file.set(override_args["ip_adapter"])
                if config.debug:
                    print(f"Updated IP Adapater for next preset schedule: " + str(override_args["ip_adapter"]))
            starting_total = int(self.total.get())
            schedule = SchedulesWindow.current_schedule
            if schedule is None:
                raise Exception("No Schedule Selected")
            if config.debug:
                print(f"Running Preset Schedule: {schedule}")
            else:
                logger.info(f"Running preset schedule")
            for preset_task in schedule.get_tasks():
                if not self.job_queue_preset_schedules.has_pending() or not self.run_preset_schedule_var.get() or \
                        (self.current_run is not None and not self.current_run.is_infinite() and self.current_run.is_cancelled):
                    self.job_queue_preset_schedules.cancel()
                    return
                try:
                    preset = PresetsWindow.get_preset_by_name(preset_task.name)
                    if config.debug:
                        print(f"Running Preset Schedule: {preset}")
                    else:
                        logger.info(f"Running preset schedule")
                except Exception as e:
                    self.handle_error(e, "Preset Schedule Error")
                    raise e
                self.set_widgets_from_preset(preset, manual=False)
                self.total.set(str(preset_task.count_runs if preset_task.count_runs > 0 else starting_total))
                self.run()
                # NOTE have to do some special handling here because the runs are still not self-contained,
                # and overwriting widget values may cause the current run to have its settings changed mid-run
                time.sleep(0.1)
                started_run_id = self.current_run.id
                while (self.current_run is not None and started_run_id == self.current_run.id
                        and not self.current_run.is_cancelled and not self.current_run.is_complete):
                    if not self.job_queue_preset_schedules.has_pending() or not self.run_preset_schedule_var.get():
                        self.job_queue_preset_schedules.cancel()
                        return
                    time.sleep(1)
            self.total.set(str(starting_total))
            self.job_queue_preset_schedules.job_running = False
            next_preset_schedule_args = self.job_queue_preset_schedules.take()
            if next_preset_schedule_args is None:
                self.job_queue_preset_schedules.cancel()
            else:
                self.run_preset_schedule(override_args=next_preset_schedule_args)

        Utils.start_thread(run_preset_async, use_asyncio=False, args=[])

    def single_resolution(self):
        current_res = self.resolutions_box.get()
        if "," in current_res:
            current_res = current_res[:current_res.index(",")]
            self.resolutions_box.delete(0, "end")
            self.resolutions_box.insert(0, current_res) # Technically not needed

    def set_software_type(self, event=None):
        self.runner_app_config.software_type = self.software.get()

    def set_workflow_type(self, event=None, workflow_tag=None):
        if workflow_tag is None:
            workflow_tag = WorkflowType.get(self.workflow.get())
        if isinstance(workflow_tag, WorkflowType):
            workflow_tag = workflow_tag.name
        if workflow_tag == WorkflowType.INPAINT_CLIPSEG.name:
            self.inpainting_var.set(True)
            self.single_resolution()
            self.total.set("1")
        if workflow_tag == WorkflowType.CONTROLNET.name:
            # self.single_resolution()
            pass

    def destroy_progress_bar(self):
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.grid_forget()
            self.destroy_grid_element("progress_bar")
            self.progress_bar = None

    def has_runs_pending(self):
        return self.job_queue.has_pending() or self.job_queue_preset_schedules.has_pending()

    def run(self, event=None):
        if self.current_run.is_infinite():
            self.current_run.cancel("Infinite run switch")

        # Check for scheduled shutdown before validating arguments
        try:
            timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
        except ScheduledShutdownException as e:
            self.handle_error(e, "Scheduled Shutdown")
            self.on_closing()

        if event is not None and self.job_queue_preset_schedules.has_pending():
            res = self.alert(_("Confirm Run"),
                _("Starting a new run will cancel the current preset schedule. Are you sure you want to proceed?"),
                kind="warning")
            if not self.is_alert_confirmed(res):
                return
            self.job_queue_preset_schedules.cancel()
        if self.run_preset_schedule_var.get():
            if not self.job_queue_preset_schedules.has_pending():
                self.run_preset_schedule()
                return None
        else:
            self.job_queue_preset_schedules.cancel()
        args, args_copy = self.get_args()

        try:
            args.validate()
        except BlacklistException as e:
            self.handle_error(e, "Blacklist Validation Error")
            return None
        except Exception as e:
            res = self.alert(_("Confirm Run"),
                str(e) + "\n\n" + _("Are you sure you want to proceed?"),
                kind="askokcancel")
            if not self.is_alert_confirmed(res):
                logger.info("User did not confirm run, returning")
                return None
            logger.info("User confirmed run, continuing")

        # Store the configuration to cache after validation
        self.store_info_cache()
        self.update_progress(override_text=_("Setting up run..."))  # will be cleared during run execution

        # Check if estimated time exceeds threshold and show confirmation dialog
        # Create a temporary GenConfig for time estimation (similar to Run.construct_gen)
        # TODO: Handle adapter complications - this only estimates time for a single gen config,
        # but runs can have multiple gen configs due to control nets, IP adapters, and other variations
        # that create different combinations. The actual run time could be much longer.
        
        # Get basic configuration for time estimation
        workflow_type = args.workflow_tag
        models = Model.get_models(args.model_tags, default_tag=Model.get_default_model_tag(workflow_type), inpainting=args.inpainting)
        resolution_group = ResolutionGroup.get(args.resolution_group)
        resolutions = Resolution.get_resolutions(args.res_tags, architecture_type=models[0].architecture_type, resolution_group=resolution_group)
        
        # Create a minimal GenConfig for time estimation
        gen_config = GenConfig(
            workflow_id=workflow_type,
            models=models,
            n_latents=args.n_latents,
            resolutions=resolutions,
            run_config=args
        )
        
        estimated_seconds = self.calculate_current_run_estimated_time(workflow_type, gen_config)
        
        if estimated_seconds > Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS:
            formatted_time = TimeEstimator.format_time(estimated_seconds)
            threshold_formatted = TimeEstimator.format_time(Globals.TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS)
            
            res = self.alert(_("Long Running Job Confirmation"),
                _("The estimated time for this run is {0}, which exceeds the threshold of {1}.\n\n"
                  "This run will generate {2} images.\n\n"
                  "Note: This estimate is for a single generation configuration. "
                  "If you have multiple control nets, IP adapters, or other variations, "
                  "the actual run time could be significantly longer.\n\n"
                  "Are you sure you want to proceed?").format(
                    formatted_time,
                    threshold_formatted,
                    gen_config.maximum_gens_per_latent()
                ),
                kind="warning")
            if not self.is_alert_confirmed(res):
                return None

        def run_async(args) -> None:
            Utils.prevent_sleep(True)
            self.job_queue.job_running = True
            self.destroy_progress_bar()
            self.progress_bar = Progressbar(self.sidebar, orient=HORIZONTAL, length=100, mode='indeterminate')
            self.progress_bar.grid(row=1, column=1)
            self.progress_bar.start()
            self.cancel_btn.grid(row=2, column=1)
            self.current_run = Run(args, ui_callbacks=self.app_actions, delay_after_last_run=self.has_runs_pending())
            try:
                self.current_run.execute()
            except ScheduledShutdownException as e:
                self._handle_scheduled_shutdown(e)
            except Exception:
                traceback.print_exc()
                self.current_run.cancel("Run failure")
            self.cancel_btn.grid_forget()
            self.destroy_progress_bar()
            self.job_queue.job_running = False
            next_job_args = self.job_queue.take()
            if next_job_args:
                self.current_run.delay_after_last_run = True
                Utils.start_thread(run_async, use_asyncio=False, args=[next_job_args])
            else:
                Utils.prevent_sleep(False)
                # Clear time estimation when all runs are complete
                self.label_time_est["text"] = ""

        if self.job_queue.has_pending():
            self.job_queue.add(args)
        else:
            self.runner_app_config.set_from_run_config(args_copy)
            Utils.start_thread(run_async, use_asyncio=False, args=[args])

    def cancel(self, event=None, reason=None):
        self.current_run.cancel(reason=reason)
        # Clear time estimation when run is cancelled
        self.label_time_est["text"] = ""

    def revert_to_simple_gen(self, event=None):
        self.cancel(reason="Revert to simple generation")
        self.workflow.set(WorkflowType.SIMPLE_IMAGE_GEN_LORA.get_translation())
        self.set_workflow_type(WorkflowType.SIMPLE_IMAGE_GEN_LORA)
        self.run()

    def get_basic_run_config(self):
        self.set_delay()
        args = RunConfig()
        args.software_type = self.software.get()
        args.workflow_tag = WorkflowType.get(self.workflow.get()).name
        args.auto_run = True
        args.resolution_group = self.resolution_group.get()
        args.override_resolution = self.override_resolution_var.get()
        args.inpainting = self.inpainting_var.get()
        args.lora_tags = self.lora_tags_box.get()
        args.model_tags = self.model_tags_box.get()
        args.res_tags = self.resolutions.get()
        args.n_latents = int(self.n_latents.get())

        args.total = int(self.total.get())
        args.batch_limit = int(self.batch_limit.get())
        self.runner_app_config.prompt_massage_tags = self.get_widget_value(self.prompt_massage_tags_box)
        self.runner_app_config.prompter_config.prompt_mode = PromptMode.get(self.prompt_mode.get())

        # Use the PromptConfigWindow class method to set values from prompter config
        PromptConfigWindow.set_args_from_prompter_config(args)
        args.prompter_config = self.runner_app_config.get_prompter_config_copy()
        
        # Store original prompt decomposition in prompter config before any processing
        args.prompter_config.original_positive_tags = self.runner_app_config.positive_tags
        args.prompter_config.original_negative_tags = self.runner_app_config.negative_tags
        
        return args

    def get_args(self):
        self.set_concepts_dir()
        args = self.get_basic_run_config()
#        self.set_prompt_massage_tags_box_from_model_tags(args.model_tags, args.inpainting)
        self.set_prompt_massage_tags()
        self.set_positive_tags()  # Blacklist is checked here for user defined positive tags
        self.set_negative_tags()
        self.set_bw_colorization()
        self.set_lora_strength()
        controlnet_file = clear_quotes(self.controlnet_file.get())
        self.runner_app_config.control_net_file = str(controlnet_file)
        RecentAdaptersWindow.add_recent_controlnet(controlnet_file)

        if args.workflow_tag == WorkflowType.REDO_PROMPT.name:
            args.workflow_tag = controlnet_file
            self.set_redo_params()
        else:
            if config.debug:
                print("Control Net file: " + controlnet_file)
            args.control_nets = controlnet_file

        self.set_controlnet_strength()
        ipadapter_file = clear_quotes(self.ipadapter_file.get())
        self.runner_app_config.ip_adapter_file = str(ipadapter_file)
        args.ip_adapters = ipadapter_file
        RecentAdaptersWindow.add_recent_ipadapter(ipadapter_file)
        self.set_ipadapter_strength()

        args_copy = deepcopy(args)
        return args, args_copy

    def update_progress(self, current_index: int = -1, total: int = -1, pending_adapters: int = 0,
            prepend_text: str = None, batch_limit: int = None, override_text: Optional[str] = None):

        # If override_text is provided and a run is currently executing, return immediately
        if override_text is not None:
            text = override_text
        else:
            if total == -1:
                text = str(current_index) + _(" (unlimited)")
            else:
                # If batch limit is set and is lower than total, show both effective total and actual total
                if batch_limit is not None and batch_limit > 0 and batch_limit < total:
                    text = str(current_index) + "/" + str(batch_limit) + f" (of {total})"
                else:
                    text = str(current_index) + "/" + str(total)

        if prepend_text is not None:
            self.label_progress["text"] = prepend_text + text
        else:
            self.label_progress["text"] = text

        if override_text is None:            
            # Update adapters info label if provided
            if pending_adapters is not None:
                if isinstance(pending_adapters, int) and pending_adapters > 0:
                    self.label_pending_adapters["text"] = _("{0} remaining adapters").format(pending_adapters)
                else:
                    self.label_pending_adapters["text"] = ""

            preset_text = self.job_queue_preset_schedules.pending_text()
            self.label_pending_preset_schedules["text"] = preset_text if preset_text is not None else ""

        self.master.update()
    
    def update_pending(self, count_pending):
        # NOTE this is the number of pending generations expected receivable
        # from the external software after being created in separate threads
        # by the gen classes.
        if count_pending <= 0:
            self.label_pending["text"] = ""
            if not self.job_queue_preset_schedules.has_pending() and self.current_run.is_complete:
                Utils.play_sound()
                # Clear adapters info when runs complete
                self.label_pending_adapters["text"] = ""
        else:
            self.label_pending["text"] = _("{0} pending generations").format(count_pending)
        self.master.update()

    def server_run_callback(self, workflow_type, args):
        if workflow_type is not None:
            self.workflow.set(workflow_type.get_translation())
            self.set_workflow_type(workflow_type)
        elif config.debug:
            print("Rerunning from server request with last settings.")
        if len(args) > 0:
            if "image" in args:
                image_path = args["image"].replace(",", "\\,")
                if config.debug:
                    print("Image path received from client: " + image_path)
                if workflow_type in [WorkflowType.CONTROLNET, WorkflowType.RENOISER, WorkflowType.REDO_PROMPT]:
                    if self.run_preset_schedule_var.get() and self.job_queue_preset_schedules.has_pending():
                        self.job_queue_preset_schedules.add({"control_net": image_path})
                        return {}
                    elif "append" in args and args["append"] and self.controlnet_file.get().strip() != "":
                        self.controlnet_file.set(self.controlnet_file.get() + "," + image_path)
                    else:
                        self.controlnet_file.set(image_path)
                elif workflow_type in [WorkflowType.IP_ADAPTER, WorkflowType.IMG2IMG]:
                    if self.run_preset_schedule_var.get() and self.job_queue_preset_schedules.has_pending():
                        self.job_queue_preset_schedules.add({"ip_adapter": image_path})
                        return {}
                    if "append" in args and args["append"] and self.ipadapter_file.get().strip() != "":
                        self.ipadapter_file.set(self.ipadapter_file.get() + "," + image_path)
                    else:
                        self.ipadapter_file.set(image_path)
                else:
                    logger.warning(f"Unhandled workflow type for server connection: {workflow_type}")
                
            self.master.update()
        self.run()
        return {} # Empty error object for confirmation

    def set_model_dependent_fields(self, event=None, model_tags=None, inpainting=None):
        Model.set_model_presets(PromptMode.get(self.prompt_mode.get()))
        if model_tags is None:
            model_tags = self.model_tags.get()
        if inpainting is None:
            inpainting = self.inpainting_var.get()
        prompt_massage_tags, models = Model.get_first_model_prompt_massage_tags(
            model_tags,
            prompt_mode=PromptMode.get(self.prompt_mode.get()),
            inpainting=inpainting
        )
        self.set_widget_value(self.prompt_massage_tags_box, prompt_massage_tags)
        self.set_prompt_massage_tags()
        if len(models) > 0:
            model: Model = models[0]
            self.resolution_group.set(model.get_standard_resolution_group().get_description())
        # TODO
        #    self.lora_tags = Model.get_first_model_lora_tags(self.model_tags, self.lora_tags)
        self.master.update()

    def set_prompt_massage_tags(self, event=None):
        text = self.get_widget_value(self.prompt_massage_tags_box)
        self.runner_app_config.prompt_massage_tags = text
        Globals.set_prompt_massage_tags(self.runner_app_config.prompt_massage_tags)

    def validate_blacklist(self, text):
        """Validate text against blacklist before processing.
        Returns True if validation passes, False if blacklisted items are found."""
        if not config.blacklist_prevent_execution:
            return True
        
        prompt_mode = PromptMode.get(self.prompt_mode.get())
        if prompt_mode.is_nsfw() and Blacklist.get_blacklist_prompt_mode() == BlacklistPromptMode.ALLOW_IN_NSFW:
            return True

        # Step 1: Standard blacklist check
        filtered = Blacklist.find_blacklisted_items(text)
        
        # Step 2: Detailed check for user-provided positive tags (only if standard check passed)
        if not filtered:
            filtered = Blacklist.check_user_prompt_detailed(text)
        
        if filtered:
            if not Blacklist.get_blacklist_silent_removal():
                alert_text = _("Blacklisted items found in prompt: {0}").format(filtered)
                self.alert(_("Invalid Prompt Tags"), alert_text, kind="error")
            if Blacklist.get_blacklist_mode() == BlacklistMode.FAIL_PROMPT:
                if Blacklist.get_blacklist_silent_removal():
                    self.alert(_("Invalid Prompt Tags"), _("Blacklist validation failed!"), kind="error")
                raise BlacklistException("Blacklist validation failed", [], filtered)
            return False
        return True

    def set_positive_tags(self, event=None):
        text = self.get_widget_value(self.positive_tags_box)
        if not self.validate_blacklist(text):
            return
        text = self.apply_expansions(text, positive=True)
        self.runner_app_config.positive_tags = text
        Prompter.set_positive_tags(text)

    def set_negative_tags(self, event=None):
        text = self.get_widget_value(self.negative_tags_box)
        text = self.apply_expansions(text, positive=False)
        self.runner_app_config.negative_tags = text
        Prompter.set_negative_tags(text)

    def set_bw_colorization(self, event=None):
        self.runner_app_config.b_w_colorization = self.bw_colorization.get()
        IPAdapter.set_bw_coloration(self.runner_app_config.b_w_colorization)

    def set_lora_strength(self, event=None):
        value = self.lora_strength_slider.get() / 100
        self.runner_app_config.lora_strength = str(value)
        Globals.set_lora_strength(value)

    def set_ipadapter_strength(self, event=None):
        value = self.ipadapter_strength_slider.get() / 100
        self.runner_app_config.ip_adapter_strength = str(value)
        Globals.set_ipadapter_strength(value)

    def set_controlnet_strength(self, event=None):
        value = self.controlnet_strength_slider.get() / 100
        self.runner_app_config.control_net_strength = str(value)
        Globals.set_controlnet_strength(value)

    def set_redo_params(self, event=None):
        self.runner_app_config.redo_params = self.redo_params_box.get()
        GenConfig.set_redo_params(self.runner_app_config.redo_params)

    def set_delay(self, event=None):
        self.runner_app_config.delay_time_seconds = self.delay.get()
        Globals.set_delay(int(self.runner_app_config.delay_time_seconds))

    def set_concepts_dir(self, event=None):
        self.runner_app_config.prompter_config.concepts_dir = config.concepts_dirs[self.concepts_dir.get()]

    def set_override_negative(self, event=None):
        self.runner_app_config.override_negative = self.override_negative_var.get()
        Globals.set_override_base_negative(self.runner_app_config.override_negative)

    def apply_expansions(self, text, positive=False):
        if Prompter.contains_expansion_var(text, from_ui=True):
            text = Prompter.apply_expansions(text, from_ui=True)
            if positive:
                self.set_widget_value(self.positive_tags_box, text)
            else:
                self.negative_tags.set(text)
            self.master.update()
        return text

    def open_window(self, window_class, error_title):
        """Open a window with standard constructor arguments.
        ### TODO: Add support for dynamic constructor arguments if needed in the future
        """
        try:
            window = window_class(self.master, self.app_actions)
        except Exception as e:
            self.handle_error(e, title=error_title)

    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def show_tag_blacklist(self):
        self.open_window(BlacklistWindow, "Blacklist Window Error")

    @require_password(ProtectedActions.EDIT_PRESETS)
    def open_presets_window(self):
        self.open_window(PresetsWindow, "Presets Window Error")

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def open_preset_schedules_window(self):
        self.open_window(SchedulesWindow, "Preset Schedules Window Error")

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def open_timed_schedules_window(self, event=None):
        self.open_window(TimedSchedulesWindow, "Timed Schedules Window Error")

    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def open_concept_editor_window(self, event=None):
        self.open_window(ConceptEditorWindow, "Concept Editor Window Error")

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def open_expansions_window(self, event=None):
        self.open_window(ExpansionsWindow, "Expansions Window Error")

    def open_prompt_config_window(self, event=None):
        """Open the detailed prompt configuration window."""
        try:
            PromptConfigWindow(self.master, self.app_actions, self.runner_app_config)
        except Exception as e:
            self.handle_error(e, title="Prompt Configuration Window Error")

    def open_models_window(self, event=None):
        # Wrapper to use the common open_window pattern
        self.open_window(ModelsWindow, "Models Window Error")

    def open_lora_models_window(self, event=None):
        """Open the models window directly to the LoRAs/Adapters tab."""
        try:
            window = ModelsWindow(self.master, self.app_actions)
            # Switch to the adapters tab (index 1)
            window.notebook.select(1)
        except Exception as e:
            self.handle_error(e, title="LoRA Models Window Error")

    def open_controlnet_adapters_window(self, event=None):
        """Open the recent adapters window directly to the ControlNets tab."""
        try:
            window = RecentAdaptersWindow(self.master, self.app_actions)
            # Switch to the controlnet tab (index 0)
            window.notebook.select(0)
        except Exception as e:
            self.handle_error(e, title="ControlNet Adapters Window Error")

    def open_ipadapter_adapters_window(self, event=None):
        """Open the recent adapters window directly to the IP Adapters tab."""
        try:
            window = RecentAdaptersWindow(self.master, self.app_actions)
            # Switch to the ipadapter tab (index 1)
            window.notebook.select(1)
        except Exception as e:
            self.handle_error(e, title="IP Adapter Adapters Window Error")

    def set_model_from_models_window(self, value: str, is_lora: bool, replace: bool):
        box = self.lora_tags_box if is_lora else self.model_tags_box
        current = box.get().strip()
        if is_lora:
            if replace or current == "":
                new_val = value
            else:
                sep = "+" if current.endswith("+") or "+" in current else ","
                if not current.endswith(sep):
                    new_val = current + sep + value
                else:
                    new_val = current + value
        else:
            if replace or current.strip() == "":
                new_val = value
            else:
                # Append with comma for models to keep multiple model tags if desired
                sep = ","
                if not current.endswith(sep):
                    new_val = current + sep + value
                else:
                    new_val = current + value
        box.delete(0, "end")
        box.insert(0, new_val)
        if not is_lora:
            self.set_model_dependent_fields()
        self.master.update()

    def set_adapter_from_adapters_window(self, value: str, is_controlnet: bool, replace: bool = True) -> None:
        """Set adapter file from recent adapters window selection.
        
        Args:
            value: The file path to set
            is_controlnet: True for control net, False for IP adapter
            replace: Whether to replace current value or append
        """
        if is_controlnet:
            current = self.controlnet_file.get().strip()
            widget = self.controlnet_file
        else:
            current = self.ipadapter_file.get().strip()
            widget = self.ipadapter_file
            
        if replace or current == "":
            new_val = value
        else:
            # Append with comma for multiple files
            sep = ","
            if not current.endswith(sep):
                new_val = current + sep + value
            else:
                new_val = current + value
        widget.set(new_val)
        self.master.update()

    @require_password(ProtectedActions.ACCESS_ADMIN)
    def open_password_admin_window(self, event=None):
        self.open_window(PasswordAdminWindow, "Password Administration Window Error")

    def check_prompt_mode_password(self, prompt_mode):
        """Check if password is required for the selected prompt mode."""
        if PromptMode.get(prompt_mode).is_nsfw():
            def password_callback(result):
                if not result:
                    self.alert(_("Password Cancelled"), _("Password cancelled or incorrect, revert to previous mode"))
                    self.prompt_mode.set(self.runner_app_config.prompter_config.prompt_mode.display())
            check_password_required(list(ProtectedActions.NSFW_PROMPTS), self.master, password_callback)

    def next_preset(self, event=None):
        self.set_widgets_from_preset(PresetsWindow.next_preset(self.alert))

    def alert(self, title: str, message: str, kind: str = "info", severity: str = "normal", master: Optional[object] = None) -> None:
        if kind not in ("error", "warning", "info", "askokcancel", "askyesno", "askyesnocancel"):
            raise ValueError("Unsupported alert kind.")

        logger.warning(f"Alert - Title: \"{title}\" Message: {message}")
        
        # Use provided master or fall back to self.master
        parent_window = master if master is not None else self.master
        
        # Use standard messagebox for normal cases
        if kind in ["askokcancel", "askyesno", "askyesnocancel"]:
            alert_method = getattr(messagebox, kind)
        else:
            alert_method = getattr(messagebox, f"show{kind}")
        return alert_method(title=title, message=message, parent=parent_window)
    
    def is_alert_confirmed(self, alert_result) -> bool:
        """
        Check if an alert result indicates a positive/confirmed response.
        Handles all possible return values from tkinter messagebox functions.
        
        Args:
            alert_result: The return value from a messagebox function
            
        Returns:
            True if the result indicates confirmation/OK/Yes, False otherwise
        """
        # Check all possible positive return values
        # messagebox functions can return "ok"/"yes" (strings), messagebox.OK/YES constants,
        # True (boolean), or 1 (integer) depending on platform and messagebox type
        return alert_result in (messagebox.OK, messagebox.YES, True, "ok", "yes", 1)

    def handle_error(self, error, title=None, kind="error"):
        traceback.print_exc()
        error_text = str(error)
        if title is None:
            title = _("Error")
        self.alert(title, error_text, kind=kind)

    def _handle_scheduled_shutdown(self, e):
        """Handle a scheduled shutdown exception by showing a countdown dialog."""
        # Extract schedule name from the exception
        schedule_name = e.schedule.name if e.schedule else "Unknown Schedule"
        
        # Show countdown dialog instead of immediate shutdown
        logger.info(f"Scheduled shutdown requested: {e}")
        shutdown_dialog = ScheduledShutdownDialog(self.master, schedule_name, countdown_seconds=6)
        cancelled = shutdown_dialog.show()
        
        if not cancelled:
            # User didn't cancel, proceed with shutdown
            self.on_closing()

    def toast(self, message):
        print("Toast message: " + message)

        # Set the position of the toast on the screen (top right)
        width = 300
        height = 100
        x = self.master.winfo_screenwidth() - width
        y = 0

        # Create the toast on the top level
        toast = SmartToplevel(persistent_parent=self.master, geometry=f'{width}x{height}+{int(x)}+{int(y)}', auto_position=False)
        self.container = Frame(toast, bg=AppStyle.BG_COLOR)
        self.container.pack(fill=BOTH, expand=YES)
        label = Label(
            self.container,
            text=message,
            anchor=NW,
            bg=AppStyle.BG_COLOR,
            fg=AppStyle.FG_COLOR,
            font=('Helvetica', 12)
        )
        label.grid(row=1, column=1, sticky="NSEW", padx=10, pady=(0, 5))
        
        # Make the window invisible and bring it to front
        toast.attributes('-topmost', True)
#        toast.withdraw()

        # Start a new thread that will destroy the window after a few seconds
        def self_destruct_after(time_in_seconds):
            time.sleep(time_in_seconds)
            label.destroy()
            toast.destroy()
        Utils.start_thread(self_destruct_after, use_asyncio=False, args=[2])

    def apply_to_grid(self, component, sticky=None, pady=0, interior_column=0, column=0, increment_row_counter=True, columnspan=None):
        row = self.row_counter0 if column == 0 else self.row_counter1
        if sticky is None:
            if columnspan is None:
                component.grid(column=interior_column, row=row, pady=pady)
            else:
                component.grid(column=interior_column, row=row, pady=pady, columnspan=columnspan)
        else:
            if columnspan is None:
                component.grid(column=interior_column, row=row, sticky=sticky, pady=pady)
            else:
                component.grid(column=interior_column, row=row, sticky=sticky, pady=pady, columnspan=columnspan)
        if increment_row_counter:
            if column == 0:
                self.row_counter0 += 1
            else:
                self.row_counter1 += 1

    def add_label(self, label_ref, text, sticky=W, pady=0, column=0, columnspan=None, increment_row_counter=True, interior_column=0):
        label_ref['text'] = text
        self.apply_to_grid(label_ref, sticky=sticky, pady=pady, column=column, columnspan=columnspan, increment_row_counter=increment_row_counter, interior_column=interior_column)

    def add_button(self, button_ref_name, text, command, sidebar=True, interior_column=0, increment_row_counter=True):
        if getattr(self, button_ref_name) is None:
            master = self.sidebar if sidebar else self.second_column
            button = Button(master=master, text=text, command=command)
            setattr(self, button_ref_name, button)
            button
            self.apply_to_grid(button, column=(0 if sidebar else 1), interior_column=interior_column, increment_row_counter=increment_row_counter)

    def new_entry(self, text_variable, text="", width=55, sidebar=True, **kw):
        master = self.sidebar if sidebar else self.second_column
        return AwareEntry(master, text=text, textvariable=text_variable, width=width, font=fnt.Font(size=8), **kw)

    def destroy_grid_element(self, element_ref_name):
        element = getattr(self, element_ref_name)
        if element is not None:
            element.destroy()
            setattr(self, element_ref_name, None)
            self.row_counter0 -= 1

    def check_focus(self, event, func):
        # Skip key binding that might be triggered by a text entry
        if event is not None and (AwareEntry.an_entry_has_focus or AwareText.an_entry_has_focus):
            return
        if func:
            func()

    def calculate_current_run_estimated_time(self, workflow_type: str, gen_config: GenConfig) -> int:
        """
        Calculate the estimated time in seconds for the current run only.
        
        Args:
            workflow_type: The type of workflow being run
            gen_config: The current generation configuration
            
        Returns:
            Estimated time in seconds for current run
        """
        # Calculate time for current job only
        total_jobs = gen_config.maximum_gens_per_latent()
        current_job_time = TimeEstimator.estimate_queue_time(total_jobs, gen_config.n_latents)
        logger.debug(f"App.calculate_current_run_estimated_time - current job: {total_jobs} jobs, time: {current_job_time}s")
        return current_job_time

    def update_time_estimation(self, workflow_type: str, gen_config: GenConfig, remaining_count: int = 1):
        """
        Update the time estimation label with estimated time for current and queued jobs.
        
        Args:
            workflow_type: The type of workflow being run
            gen_config: The current generation configuration
            remaining_count: Number of remaining generations in current job
        """
        total_seconds = 0
        
        # Calculate time for current job
        total_jobs = gen_config.maximum_gens_per_latent()
        current_job_time = TimeEstimator.estimate_queue_time(total_jobs * remaining_count, gen_config.n_latents)
        total_seconds += current_job_time
        logger.debug(f"App.update_time_estimation - current job: {total_jobs} jobs, {remaining_count} remaining, time: {current_job_time}s")
        
        # Add time for jobs in standard run queue
        if self.job_queue.has_pending():
            queue_time = self.job_queue.estimate_time(gen_config)
            total_seconds += queue_time
            logger.debug(f"App.update_time_estimation - standard queue time: {queue_time}s")
                
        # Add time for jobs in preset schedule queue
        if self.job_queue_preset_schedules.has_pending():
            preset_time = self.job_queue_preset_schedules.estimate_time(gen_config)
            total_seconds += preset_time
            logger.debug(f"App.update_time_estimation - preset queue time: {preset_time}s")
            
        current_estimate = TimeEstimator.format_time(total_seconds)
        logger.debug(f"App.update_time_estimation - total time: {total_seconds}s, formatted: {current_estimate}")
        self.label_time_est["text"] = current_estimate            
        self.master.update()



if __name__ == "__main__":
    try:
        def create_root():
            # assets = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")
            root = ThemedTk(theme="black", themebg="black")
            root.title(_(" ComfyGen ") + (" (Debug)" if config.debug else ""))
            #root.iconbitmap(bitmap=r"icon.ico")
            # icon = PhotoImage(file=os.path.join(assets, "icon.png"))
            # root.iconphoto(False, icon)
            
            # Try to restore saved window position
            try:
                position_data = app_info_cache.get_display_position()
                virtual_screen_info = app_info_cache.get_virtual_screen_info()
                
                if position_data and position_data.is_valid():
                    # Update window to ensure it's ready for visibility check
                    root.update_idletasks()
                    
                    # Check if the saved position is still visible on current display setup
                    if virtual_screen_info:
                        is_visible = position_data.is_visible_on_display(root, virtual_screen_info)
                    else:
                        is_visible = position_data.is_visible_on_display(root)
                    
                    if is_visible:
                        root.geometry(position_data.get_geometry())
                        logger.debug(f"Restored window position: {position_data}")
                    else:
                        # Position not visible, use default
                        root.geometry("900x600")
                        logger.debug(f"Saved position not visible on current display, using default")
                else:
                    # No saved position or invalid, use default
                    root.geometry("900x600")
            except Exception as e:
                logger.warning(f"Failed to restore window position: {e}")
                # Fallback to default geometry
                root.geometry("900x600")
            
            # root.attributes('-fullscreen', True)
            root.resizable(1, 1)
            root.columnconfigure(0, weight=1)
            root.columnconfigure(1, weight=1)
            root.rowconfigure(0, weight=1)
            return root

        app = None

        # Graceful shutdown handler
        def graceful_shutdown(signum, frame):
            logger.info("Caught signal, shutting down gracefully...")
            if app is not None:
                app.on_closing()
            else:
                os._exit(0)

        # Register the signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, graceful_shutdown)
        signal.signal(signal.SIGTERM, graceful_shutdown)

        def startup_callback(result):
            if result:
                # Password verified or not required, create the application
                global app
                
                # Clean up any old image converter temporary files on startup
                from sd_runner.base_image_generator import BaseImageGenerator
                BaseImageGenerator.cleanup_image_converter()
                
                root = create_root()
                app = App(root)
                try:
                    root.mainloop()
                except KeyboardInterrupt:
                    pass
                except Exception:
                    traceback.print_exc()
            else:
                # User cancelled the password dialog, exit
                logger.info("Startup cancelled, exiting...")
                os._exit(0)
        
        # Check if startup password is required
        # This will either call the callback immediately (if no password required)
        # or show a password dialog and call the callback when done
        from ui.auth.app_startup_auth import check_startup_password_required
        check_startup_password_required(startup_callback)
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
