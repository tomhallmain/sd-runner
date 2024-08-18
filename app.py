from copy import deepcopy
import os
import signal
import time
import traceback

from tkinter import messagebox, Toplevel, Frame, Label, Checkbutton, Text, StringVar, BooleanVar, END, HORIZONTAL, NW, BOTH, YES, N, E, W
from tkinter.constants import W
import tkinter.font as fnt
from tkinter.ttk import Button, Entry, OptionMenu, Progressbar, Scale
from lib.autocomplete_entry import AutocompleteEntry, matches
from ttkthemes import ThemedTk

from run import main, RunConfig
from utils.globals import Globals, WorkflowType, Sampler, Scheduler

from extensions.sd_runner_server import SDRunnerServer

from sd_runner.comfy_gen import ComfyGen
from sd_runner.concepts import PromptMode
from sd_runner.gen_config import GenConfig
from sd_runner.models import IPAdapter, Model
from sd_runner.prompter import Prompter
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.runner_app_config import RunnerAppConfig
from utils.utils import open_file_location, periodic, start_thread


# TODO enable "madlibs" style prompting variables (requires labelling parts of speech in english_words.txt)
# TODO enable "profile" prompting with cycles between them, possibly interfacing with the madlib prompting in previous TODO comment


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


class ProgressListener:
    def __init__(self, update_func):
        self.update_func = update_func

    def update(self, context, percent_complete):
        self.update_func(context, percent_complete)

class JobQueue:
    def __init__(self, max_size=20):
        self.max_size = max_size
        self.pending_jobs = []
        self.job_running = False

    def has_pending(self):
        return self.job_running or len(self.pending_jobs) > 0

    def take(self):
        if len(self.pending_jobs) == 0:
            return None
        run_config = self.pending_jobs[0]
        del self.pending_jobs[0]
        return run_config

    def add(self, run_config):
        if len(self.pending_jobs) > self.max_size:
            raise Exception(f"Reached limit of pending runs: {self.max_size} - wait until current run has completed.")
        self.pending_jobs.append(run_config)
        print(f"Added pending job: {run_config}")



class App():
    '''
    UI for overlay of ComfyUI workflow management.
    '''

    IS_DEFAULT_THEME = False
    GRAY = "gray"
    DARK_BG = config.background_color if config.background_color and config.background_color != "" else "#053E10"
    DARK_FG = config.foreground_color if config.foreground_color and config.foreground_color != "" else "white"

    def configure_style(self, theme):
        self.master.set_theme(theme, themebg="black")

    def toggle_theme(self):
        if App.IS_DEFAULT_THEME:
            self.configure_style("breeze") # Changes the window to light theme
            bg_color = App.GRAY
            fg_color = "black"
        else:
            self.configure_style("black") # Changes the window to dark theme
            bg_color = App.DARK_BG
            fg_color = App.DARK_FG
        App.IS_DEFAULT_THEME = not App.IS_DEFAULT_THEME
        self.master.config(bg=bg_color)
        self.sidebar.config(bg=bg_color)
        self.prompter_config_bar.config(bg=bg_color)
        for name, attr in self.__dict__.items():
            if isinstance(attr, Label):
                attr.config(bg=bg_color, fg=fg_color)
            elif isinstance(attr, Checkbutton):
                attr.config(bg=bg_color, fg=fg_color, selectcolor=bg_color)
        self.master.update()
        self.toast("Theme switched to dark." if App.IS_DEFAULT_THEME else "Theme switched to light.")

    def __init__(self, master):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.progress_bar = None
        self.job_queue = JobQueue()
        self.server = self.setup_server()
        self.runner_app_config = self.load_info_cache()
        self.config_history_index = 0
        Model.load_all()

        # Sidebar
        self.sidebar = Sidebar(self.master)
        self.sidebar.columnconfigure(0, weight=1)
        self.sidebar.columnconfigure(0, weight=1)
        self.row_counter0 = 0
        self.sidebar.grid(column=0, row=self.row_counter0)
        self.label_title = Label(self.sidebar)
        self.add_label(self.label_title, "Run ComfyUI Workflows", sticky=None, columnspan=2)

        self.run_btn = None
        self.add_button("run_btn", "Run Workflows", self.run)
        self.master.bind("<Shift-R>", self.run)

        # self.toggle_theme_btn = None
        # self.add_button("toggle_theme_btn", "Toggle theme", self.toggle_theme)

        # TODO multiselect
        self.label_workflows = Label(self.sidebar)
        self.add_label(self.label_workflows, "Workflow", increment_row_counter=False)
        self.workflow = StringVar(master)
        self.workflows_choice = OptionMenu(self.sidebar, self.workflow, self.runner_app_config.workflow_type,
                                           *WorkflowType.__members__.keys(), command=self.set_workflow_type)
        self.apply_to_grid(self.workflows_choice, interior_column=1, sticky=W)

        self.label_sampler = Label(self.sidebar)
        self.add_label(self.label_sampler, "Sampler", increment_row_counter=False)
        self.sampler = StringVar(master)
        self.sampler_choice = OptionMenu(self.sidebar, self.sampler, str(self.runner_app_config.sampler), *Sampler.__members__.keys())
        self.apply_to_grid(self.sampler_choice, interior_column=1, sticky=W)

        self.label_scheduler = Label(self.sidebar)
        self.add_label(self.label_scheduler, "Scheduler", increment_row_counter=False)
        self.scheduler = StringVar(master)
        self.scheduler_choice = OptionMenu(self.sidebar, self.scheduler, str(self.runner_app_config.scheduler), *Scheduler.__members__.keys())
        self.apply_to_grid(self.scheduler_choice, interior_column=1, sticky=W)

        self.label_n_latents = Label(self.sidebar)
        self.add_label(self.label_n_latents, "Set N Latents", increment_row_counter=False)
        self.n_latents = StringVar(master)
        self.n_latents_choice = OptionMenu(self.sidebar, self.n_latents, str(self.runner_app_config.n_latents), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.n_latents_choice, interior_column=1, sticky=W)

        self.label_total = Label(self.sidebar)
        self.add_label(self.label_total, "Set Total", increment_row_counter=False)
        self.total = StringVar(master)
        self.total_choice = OptionMenu(self.sidebar, self.total, str(self.runner_app_config.total), *[str(i) for i in list(range(101))])
        self.apply_to_grid(self.total_choice, interior_column=1, sticky=W)

        self.label_delay = Label(self.sidebar)
        self.add_label(self.label_delay, "Delay Seconds", increment_row_counter=False)
        self.delay = StringVar(master)
        self.delay_choice = OptionMenu(self.sidebar, self.delay, str(Globals.GENERATION_DELAY_TIME_SECONDS), *[str(i) for i in list(range(101))], command=self.set_delay)
        self.apply_to_grid(self.delay_choice, interior_column=1, sticky=W)
        self.delay_choice.bind("<Return>", self.set_random_skip)

        self.label_resolutions = Label(self.sidebar)
        self.add_label(self.label_resolutions, "Resolutions", increment_row_counter=False)
        self.resolutions = StringVar()
        self.resolutions_box = self.new_entry(self.resolutions, width=20)
        self.resolutions_box.insert(0, self.runner_app_config.resolutions)
        self.apply_to_grid(self.resolutions_box, interior_column=1, sticky=W)

        self.label_model_tags = Label(self.sidebar)
        self.add_label(self.label_model_tags, "Model Tags")
        self.model_tags = StringVar()
        model_names = list(map(lambda l: str(l).split('.')[0], Model.CHECKPOINTS))
        self.model_tags_box = AutocompleteEntry(model_names,
                                               self.sidebar,
                                               listboxLength=6,
                                               textvariable=self.model_tags,
                                               matchesFunction=matches_tag,
                                               setFunction=set_tag,
                                               width=55, font=fnt.Font(size=8))
        self.model_tags_box.bind("<Return>", self.set_prompt_massage_tags_box_from_model_tags)
        self.model_tags_box.insert(0, self.runner_app_config.model_tags)
        self.apply_to_grid(self.model_tags_box, sticky=W, columnspan=2)

        self.label_lora_tags = Label(self.sidebar)
        self.add_label(self.label_lora_tags, "LoRA Tags")
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
        self.add_label(self.label_lora_strength, "Default LoRA Strength", increment_row_counter=False)
        self.lora_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_lora_strength)
        self.set_widget_value(self.lora_strength_slider, self.runner_app_config.lora_strength)
        self.apply_to_grid(self.lora_strength_slider, interior_column=1, sticky=W)

        self.label_prompt_tags = Label(self.sidebar)
        self.add_label(self.label_prompt_tags, "Prompt Massage Tags")
        self.prompt_massage_tags = StringVar()
        self.prompt_massage_tags_box = self.new_entry(self.prompt_massage_tags)
        self.prompt_massage_tags_box.insert(0, self.runner_app_config.prompt_massage_tags)
        self.apply_to_grid(self.prompt_massage_tags_box, sticky=W, columnspan=2)
        self.prompt_massage_tags_box.bind("<Return>", self.set_prompt_massage_tags)

        self.label_positive_tags = Label(self.sidebar)
        self.add_label(self.label_positive_tags, "Positive Tags")
        self.positive_tags_box = Text(self.sidebar, height=6, width=55, font=fnt.Font(size=8))
        self.positive_tags_box.insert("0.0", self.runner_app_config.positive_tags)
        self.apply_to_grid(self.positive_tags_box, sticky=W, columnspan=2)
        self.positive_tags_box.bind("<Return>", self.set_positive_tags)

        self.label_negative_tags = Label(self.sidebar)
        self.add_label(self.label_negative_tags, "Negative Tags")
        self.negative_tags = StringVar()
        self.negative_tags_box = Text(self.sidebar, height=3, width=55, font=fnt.Font(size=8))
        self.negative_tags_box.insert("0.0", self.runner_app_config.negative_tags)
        self.apply_to_grid(self.negative_tags_box, sticky=W, columnspan=2)
        self.negative_tags_box.bind("<Return>", self.set_negative_tags)

        self.label_bw_colorization = Label(self.sidebar)
        self.add_label(self.label_bw_colorization, "B/W Colorization Tags", increment_row_counter=False)
        self.bw_colorization = StringVar()
        self.bw_colorization_box = self.new_entry(self.bw_colorization, width=20)
        self.bw_colorization_box.insert(0, self.runner_app_config.b_w_colorization)
        self.apply_to_grid(self.bw_colorization_box, interior_column=1, sticky=W)
        self.bw_colorization_box.bind("<Return>", self.set_bw_colorization)

        self.label_controlnet_file = Label(self.sidebar)
        self.add_label(self.label_controlnet_file, "Control Net or Redo files")
        self.controlnet_file = StringVar()
        self.controlnet_file_box = self.new_entry(self.controlnet_file)
        self.controlnet_file_box.insert(0, self.runner_app_config.control_net_file)
        self.apply_to_grid(self.controlnet_file_box, sticky=W, columnspan=2)

        self.label_controlnet_strength = Label(self.sidebar)
        self.add_label(self.label_controlnet_strength, "Default Control Net Strength", increment_row_counter=False)
        self.controlnet_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_controlnet_strength)
        self.set_widget_value(self.controlnet_strength_slider, self.runner_app_config.control_net_strength)
        self.apply_to_grid(self.controlnet_strength_slider, interior_column=1, sticky=W)

        self.label_ipadapter_file = Label(self.sidebar)
        self.add_label(self.label_ipadapter_file, "IPAdapter files")
        self.ipadapter_file = StringVar()
        self.ipadapter_file_box = self.new_entry(self.ipadapter_file)
        self.ipadapter_file_box.insert(0, self.runner_app_config.ip_adapter_file)
        self.apply_to_grid(self.ipadapter_file_box, sticky=W, columnspan=2)

        self.label_ipadapter_strength = Label(self.sidebar)
        self.add_label(self.label_ipadapter_strength, "Default IPAdapter Strength", increment_row_counter=False)
        self.ipadapter_strength_slider = Scale(self.sidebar, from_=0, to=100, orient=HORIZONTAL, command=self.set_ipadapter_strength)
        self.set_widget_value(self.ipadapter_strength_slider, self.runner_app_config.ip_adapter_strength)
        self.apply_to_grid(self.ipadapter_strength_slider, interior_column=1, sticky=W)

        self.label_redo_params = Label(self.sidebar)
        self.add_label(self.label_redo_params, "Redo Parameters", increment_row_counter=False)
        self.redo_params = StringVar()
        self.redo_params_box = self.new_entry(self.redo_params, width=20)
        self.redo_params_box.insert(0, self.runner_app_config.redo_params)
        self.apply_to_grid(self.redo_params_box, interior_column=1, sticky=W)
        self.redo_params_box.bind("<Return>", self.set_redo_params)

        self.label_seed = Label(self.sidebar)
        self.add_label(self.label_seed, "Seed", increment_row_counter=False)
        self.seed = StringVar()
        self.seed_box = self.new_entry(self.seed, width=10)
        self.seed_box.insert(0, self.runner_app_config.seed)
        self.apply_to_grid(self.seed_box, interior_column=1, sticky=W)

        self.label_steps = Label(self.sidebar)
        self.add_label(self.label_steps, "Steps", increment_row_counter=False)
        self.steps = StringVar()
        self.steps_box = self.new_entry(self.steps, width=10)
        self.steps_box.insert(0, self.runner_app_config.steps) 
        self.apply_to_grid(self.steps_box, interior_column=1, sticky=W)

        self.label_cfg = Label(self.sidebar)
        self.add_label(self.label_cfg, "CFG", increment_row_counter=False)
        self.cfg = StringVar()
        self.cfg_box = self.new_entry(self.cfg, width=10)
        self.cfg_box.insert(0, self.runner_app_config.cfg)
        self.apply_to_grid(self.cfg_box, interior_column=1, sticky=W)

        self.label_denoise = Label(self.sidebar)
        self.add_label(self.label_denoise, "Denoise", increment_row_counter=False)
        self.denoise = StringVar()
        self.denoise_box = self.new_entry(self.denoise, width=10)
        self.denoise_box.insert(0, self.runner_app_config.denoise)
        self.apply_to_grid(self.denoise_box, interior_column=1, sticky=W)

        self.label_random_skip = Label(self.sidebar)
        self.add_label(self.label_random_skip, "Random Skip Chance", increment_row_counter=False)
        self.random_skip = StringVar()
        self.random_skip_box = self.new_entry(self.random_skip, width=10)
        self.random_skip_box.insert(0, self.runner_app_config.random_skip_chance)
        self.apply_to_grid(self.random_skip_box, interior_column=1, sticky=W)
        self.random_skip_box.bind("<Return>", self.set_random_skip)

        # Prompter Config
        self.row_counter1 = 0
        self.prompter_config_bar = Sidebar(self.master)
        self.prompter_config_bar.columnconfigure(0, weight=1)
        self.prompter_config_bar.columnconfigure(1, weight=1)
        self.prompter_config_bar.columnconfigure(2, weight=1)
        self.prompter_config_bar.grid(column=1, row=self.row_counter1)

        self.label_title_config = Label(self.prompter_config_bar)
        self.add_label(self.label_title_config, "Prompts Configuration", column=1, columnspan=3, sticky=W+E)

        self.label_prompt_mode = Label(self.prompter_config_bar)
        self.add_label(self.label_prompt_mode, "Prompt Mode", column=1, increment_row_counter=False)
        self.prompt_mode = StringVar(master)
        starting_prompt_mode = self.runner_app_config.prompter_config.prompt_mode.name
        self.prompt_mode_choice = OptionMenu(self.prompter_config_bar, self.prompt_mode, starting_prompt_mode, *PromptMode.__members__.keys())
        self.apply_to_grid(self.prompt_mode_choice, interior_column=1, sticky=W, column=1)

        prompter_config = self.runner_app_config.prompter_config

        self.label_concepts = Label(self.prompter_config_bar)
        self.add_label(self.label_concepts, "Concepts", column=1)
        self.concepts0 = StringVar(master)
        self.concepts1 = StringVar(master)
        self.concepts0_choice = OptionMenu(self.prompter_config_bar, self.concepts0, str(prompter_config.concepts[0]), *[str(i) for i in list(range(51))])
        self.concepts1_choice = OptionMenu(self.prompter_config_bar, self.concepts1, str(prompter_config.concepts[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.concepts0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.concepts1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_positions = Label(self.prompter_config_bar)
        self.add_label(self.label_positions, "Positions", column=1)
        self.positions0 = StringVar(master)
        self.positions1 = StringVar(master)
        self.positions0_choice = OptionMenu(self.prompter_config_bar, self.positions0, str(prompter_config.positions[0]), *[str(i) for i in list(range(51))])
        self.positions1_choice = OptionMenu(self.prompter_config_bar, self.positions1, str(prompter_config.positions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.positions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.positions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_locations = Label(self.prompter_config_bar)
        self.add_label(self.label_locations, "Locations", column=1)
        self.locations0 = StringVar(master)
        self.locations1 = StringVar(master)
        self.locations0_choice = OptionMenu(self.prompter_config_bar, self.locations0, str(prompter_config.locations[0]), *[str(i) for i in list(range(51))])
        self.locations1_choice = OptionMenu(self.prompter_config_bar, self.locations1, str(prompter_config.locations[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.locations0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.locations1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.specific_locations_var = BooleanVar(value=self.runner_app_config.prompter_config.specific_locations)
        self.specific_locations_choice = Checkbutton(self.prompter_config_bar, text="Allow Specific Locations", variable=self.specific_locations_var, command=self.set_specific_locations)
        self.apply_to_grid(self.specific_locations_choice, sticky=W, column=1, columnspan=3)

        self.label_animals = Label(self.prompter_config_bar)
        self.add_label(self.label_animals, "Animals", column=1)
        self.animals0 = StringVar(master)
        self.animals1 = StringVar(master)
        self.animals0_choice = OptionMenu(self.prompter_config_bar, self.animals0, str(prompter_config.animals[0]), *[str(i) for i in list(range(51))])
        self.animals1_choice = OptionMenu(self.prompter_config_bar, self.animals1, str(prompter_config.animals[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.animals0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.animals1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_colors = Label(self.prompter_config_bar)
        self.add_label(self.label_colors, "Colors", column=1)
        self.colors0 = StringVar(master)
        self.colors1 = StringVar(master)
        self.colors0_choice = OptionMenu(self.prompter_config_bar, self.colors0, str(prompter_config.colors[0]), *[str(i) for i in list(range(51))])
        self.colors1_choice = OptionMenu(self.prompter_config_bar, self.colors1, str(prompter_config.colors[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.colors0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.colors1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_times = Label(self.prompter_config_bar)
        self.add_label(self.label_times, "Times", column=1)
        self.times0 = StringVar(master)
        self.times1 = StringVar(master)
        self.times0_choice = OptionMenu(self.prompter_config_bar, self.times0, str(prompter_config.times[0]), *[str(i) for i in list(range(51))])
        self.times1_choice = OptionMenu(self.prompter_config_bar, self.times1, str(prompter_config.times[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.times0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.times1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_dress = Label(self.prompter_config_bar)
        self.add_label(self.label_dress, "Dress", column=1)
        self.dress0 = StringVar(master)
        self.dress1 = StringVar(master)
        self.dress0_choice = OptionMenu(self.prompter_config_bar, self.dress0, str(prompter_config.dress[0]), *[str(i) for i in list(range(51))])
        self.dress1_choice = OptionMenu(self.prompter_config_bar, self.dress1, str(prompter_config.dress[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.dress0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.dress1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_expressions = Label(self.prompter_config_bar)
        self.add_label(self.label_expressions, "Expressions", column=1)
        self.expressions0 = StringVar(master)
        self.expressions1 = StringVar(master)
        self.expressions0_choice = OptionMenu(self.prompter_config_bar, self.expressions0, str(prompter_config.expressions[0]), *[str(i) for i in list(range(51))])
        self.expressions1_choice = OptionMenu(self.prompter_config_bar, self.expressions1, str(prompter_config.expressions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.expressions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.expressions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_actions = Label(self.prompter_config_bar)
        self.add_label(self.label_actions, "Actions", column=1)
        self.actions0 = StringVar(master)
        self.actions1 = StringVar(master)
        self.actions0_choice = OptionMenu(self.prompter_config_bar, self.actions0, str(prompter_config.actions[0]), *[str(i) for i in list(range(51))])
        self.actions1_choice = OptionMenu(self.prompter_config_bar, self.actions1, str(prompter_config.actions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.actions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.actions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_descriptions = Label(self.prompter_config_bar)
        self.add_label(self.label_descriptions, "Descriptions", column=1)
        self.descriptions0 = StringVar(master)
        self.descriptions1 = StringVar(master)
        self.descriptions0_choice = OptionMenu(self.prompter_config_bar, self.descriptions0, str(prompter_config.descriptions[0]), *[str(i) for i in list(range(51))])
        self.descriptions1_choice = OptionMenu(self.prompter_config_bar, self.descriptions1, str(prompter_config.descriptions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.descriptions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.descriptions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_random_words = Label(self.prompter_config_bar)
        self.add_label(self.label_random_words, "Random Words", column=1)
        self.random_words0 = StringVar(master)
        self.random_words1 = StringVar(master)
        self.random_words0_choice = OptionMenu(self.prompter_config_bar, self.random_words0, str(prompter_config.random_words[0]), *[str(i) for i in list(range(51))])
        self.random_words1_choice = OptionMenu(self.prompter_config_bar, self.random_words1, str(prompter_config.random_words[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.random_words0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.random_words1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_specify_humans_chance = Label(self.prompter_config_bar)
        self.add_label(self.label_specify_humans_chance, "Specify Humans Chance", column=1, increment_row_counter=False)
        self.specify_humans_chance_slider = Scale(self.prompter_config_bar, from_=0, to=100, orient=HORIZONTAL, command=self.set_specify_humans_chance)
        self.set_widget_value(self.specify_humans_chance_slider, self.runner_app_config.prompter_config.specify_humans_chance)
        self.apply_to_grid(self.specify_humans_chance_slider, interior_column=1, sticky=W, column=1)

        self.label_art_style_chance = Label(self.prompter_config_bar)
        self.add_label(self.label_art_style_chance, "Art Styles Chance", column=1, increment_row_counter=False)
        self.art_style_chance_slider = Scale(self.prompter_config_bar, from_=0, to=100, orient=HORIZONTAL, command=self.set_art_style_chance)
        self.set_widget_value(self.art_style_chance_slider, self.runner_app_config.prompter_config.art_styles_chance)
        self.apply_to_grid(self.art_style_chance_slider, interior_column=1, sticky=W, column=1)

        self.auto_run_var = BooleanVar(value=True)
        self.auto_run_choice = Checkbutton(self.prompter_config_bar, text='Auto Run', variable=self.auto_run_var)
        self.apply_to_grid(self.auto_run_choice, sticky=W, column=1)

        self.inpainting_var = BooleanVar(value=False)
        self.inpainting_choice = Checkbutton(self.prompter_config_bar, text='Inpainting', variable=self.inpainting_var)
        self.apply_to_grid(self.inpainting_choice, sticky=W, column=1)

        self.override_negative_var = BooleanVar(value=False)
        self.override_negative_choice = Checkbutton(self.prompter_config_bar, text="Override Base Negative", variable=self.override_negative_var, command=self.set_override_negative)
        self.apply_to_grid(self.override_negative_choice, sticky=W, column=1, columnspan=3)

        self.tags_at_start_var = BooleanVar(value=self.runner_app_config.tags_apply_to_start)
        self.tags_at_start_choice = Checkbutton(self.prompter_config_bar, text="Tags Applied to Prompt Start", variable=self.tags_at_start_var, command=self.set_tags_apply_to_start)
        self.apply_to_grid(self.tags_at_start_choice, sticky=W, column=1, columnspan=3)

        self.master.bind("<Control-Return>", self.run)
        self.master.bind("<Prior>", lambda event: self.one_config_away(change=1))
        self.master.bind("<Next>", lambda event: self.one_config_away(change=-1))
        self.master.bind("<Control-q>", self.quit)
        self.toggle_theme()
        self.master.update()
        self.close_autocomplete_popups()


    def close_autocomplete_popups(self):
        self.model_tags_box.closeListbox()
        self.lora_tags_box.closeListbox()


    def on_closing(self):
        self.store_info_cache()
        if self.server is not None:
            try:
                self.server.stop()
            except Exception as e:
                print(f"Error stopping server: {e}")
        self.master.destroy()


    def quit(self, event=None):
        res = self.alert("Confirm Quit", "Would you like to quit the application?", kind="askokcancel")
        if res == messagebox.OK or res == True:
            print("Exiting application")
            self.on_closing()


    def setup_server(self):
        server = SDRunnerServer(self.server_run_callback)
        try:
            start_thread(server.start)
            return server
        except Exception as e:
            print(f"Failed to start server: {e}")

    def store_info_cache(self):
        if self.runner_app_config is not None:
            app_info_cache.set_history(self.runner_app_config)
        app_info_cache.set("config_history_index", self.config_history_index)
        app_info_cache.store()

    def load_info_cache(self):
        try:
            self.config_history_index = app_info_cache.get("config_history_index", default_val=0)
            return RunnerAppConfig.from_dict(app_info_cache.get_history(0))
        except Exception as e:
            print(e)
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

    def set_default_config(self, event=None):
        self.runner_app_config = RunnerAppConfig()
        self.set_widgets_from_config()
        self.close_autocomplete_popups()

    def set_widget_value(self, widget, value):
        if isinstance(widget, Scale):
            widget.set(float(value) * 100)
        else:
            widget.delete(0, "end")
            widget.insert(0, value)

    def set_widgets_from_config(self):
        if self.runner_app_config is None:
            raise Exception("No config to set widgets from")
        self.set_workflow_type(self.runner_app_config.workflow_type)
        self.set_widget_value(self.resolutions_box, self.runner_app_config.resolutions)
        self.set_widget_value(self.seed_box, self.runner_app_config.seed)
        self.set_widget_value(self.steps_box, self.runner_app_config.steps)
        self.set_widget_value(self.cfg_box, self.runner_app_config.cfg)
        self.set_widget_value(self.denoise_box, self.runner_app_config.denoise)
        self.set_widget_value(self.model_tags_box, self.runner_app_config.model_tags)
        if self.runner_app_config.lora_tags is not None and self.runner_app_config.lora_tags!= "":
            self.set_widget_value(self.lora_tags_box, self.runner_app_config.lora_tags)
        self.set_widget_value(self.prompt_massage_tags_box, self.runner_app_config.prompt_massage_tags)
        self.positive_tags_box.delete("0.0", "end")
        self.positive_tags_box.insert("0.0", self.runner_app_config.positive_tags)
        self.negative_tags_box.delete("0.0", "end")
        self.negative_tags_box.insert("0.0", self.runner_app_config.negative_tags)
        self.set_widget_value(self.bw_colorization_box, self.runner_app_config.b_w_colorization)
        self.set_widget_value(self.lora_strength_slider, self.runner_app_config.lora_strength)
        self.set_widget_value(self.controlnet_file_box, self.runner_app_config.control_net_file)
        self.set_widget_value(self.controlnet_strength_slider, self.runner_app_config.control_net_strength)
        self.set_widget_value(self.ipadapter_file_box, self.runner_app_config.ip_adapter_file)
        self.set_widget_value(self.ipadapter_strength_slider, self.runner_app_config.ip_adapter_strength)
        self.set_widget_value(self.redo_params_box, self.runner_app_config.redo_params)
        self.set_widget_value(self.random_skip_box, self.runner_app_config.random_skip_chance)
        self.random_skip_box.insert(0, self.runner_app_config.random_skip_chance)

        # Prompter Config
        prompter_config = self.runner_app_config.prompter_config
        self.prompt_mode.set(str(prompter_config.prompt_mode))
        self.sampler.set(str(self.runner_app_config.sampler))
        self.scheduler.set(str(self.runner_app_config.scheduler))
        self.n_latents.set(str(self.runner_app_config.n_latents))
        self.total.set(str(self.runner_app_config.total))
        self.concepts0.set(str(prompter_config.concepts[0]))
        self.concepts1.set(str(prompter_config.concepts[1]))
        self.positions0.set(str(prompter_config.positions[0]))
        self.positions1.set(str(prompter_config.positions[1]))
        self.locations0.set(str(prompter_config.positions[0]))
        self.locations1.set(str(prompter_config.positions[1]))
        self.animals0.set(str(prompter_config.animals[0]))
        self.animals1.set(str(prompter_config.animals[1]))
        self.colors0.set(str(prompter_config.colors[0]))
        self.colors1.set(str(prompter_config.colors[1]))
        self.times0.set(str(prompter_config.times[0]))
        self.times1.set(str(prompter_config.times[1]))
        self.dress0.set(str(prompter_config.dress[0]))
        self.dress1.set(str(prompter_config.dress[1]))
        self.expressions0.set(str(prompter_config.expressions[0]))
        self.expressions1.set(str(prompter_config.expressions[1]))
        self.actions0.set(str(prompter_config.actions[0]))
        self.actions1.set(str(prompter_config.actions[1]))
        self.descriptions0.set(str(prompter_config.descriptions[0]))
        self.descriptions1.set(str(prompter_config.descriptions[1]))
        self.random_words0.set(str(prompter_config.random_words[0]))
        self.random_words1.set(str(prompter_config.random_words[1]))

        self.auto_run_var.set(self.runner_app_config.auto_run)
        self.inpainting_var.set(self.runner_app_config.inpainting)
        self.override_negative_var.set(self.runner_app_config.override_negative)


    def single_resolution(self):
        # TODO make a setting to ignore resolutions for controlnet optionally (would require updating workflows)
        current_res = self.resolutions_box.get()
        if "," in current_res:
            current_res = current_res[:current_res.index(",")]
            self.resolutions_box.delete(0, "end")
            self.resolutions_box.insert(0, current_res) # Technically not needed

    def set_workflow_type(self, event=None, workflow_tag=None):
        if workflow_tag is None:
            workflow_tag = self.workflow.get()
        if workflow_tag == WorkflowType.INPAINT_CLIPSEG.name:
            self.inpainting_var.set(True)
            self.single_resolution()
            self.total.set("1")
        if workflow_tag == WorkflowType.CONTROLNET.name:
            self.single_resolution()

    def destroy_progress_bar(self):
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.grid_forget()
            self.destroy_grid_element("progress_bar")
            self.progress_bar = None

    def run(self, event=None):
        self.store_info_cache()
        args = RunConfig()
        args.auto_run = self.auto_run_var.get()
        args.inpainting = self.inpainting_var.get()
        args.lora_tags = self.lora_tags_box.get()
        args.workflow_tag = self.workflow.get()
        args.model_tags = self.model_tags_box.get()
        args.res_tags = self.resolutions.get()
        args.n_latents = int(self.n_latents.get())
        args.seed = int(self.seed.get())
        args.steps = int(self.steps.get())
        args.cfg = float(self.cfg.get())
        args.sampler = Sampler[self.sampler.get()]
        args.scheduler = Scheduler[self.scheduler.get()]
        args.denoise = float(self.denoise.get())
        args.total = int(self.total.get())
        self.runner_app_config.prompt_massage_tags = self.prompt_massage_tags.get()
        self.runner_app_config.prompter_config.prompt_mode = PromptMode[self.prompt_mode.get()]
        args.prompter_config = deepcopy(self.runner_app_config.prompter_config)
#        self.set_prompt_massage_tags_box_from_model_tags(args.model_tags, args.inpainting)
        self.set_prompt_massage_tags()
        self.set_positive_tags()
        self.set_negative_tags()
        self.set_bw_colorization()
        self.set_lora_strength()
        controlnet_file = clear_quotes(self.controlnet_file.get())
        self.runner_app_config.control_net_file = controlnet_file
        args_copy = deepcopy(args)

        if args.workflow_tag == WorkflowType.REDO_PROMPT.name:
            args.workflow_tag = controlnet_file
            self.set_redo_params()
        else:
            print(controlnet_file)
            args.control_nets = controlnet_file

        self.set_controlnet_strength()
        args.ip_adapters = clear_quotes(self.ipadapter_file.get())
        self.set_ipadapter_strength()
        self.set_random_skip()

        self.set_prompter_config()

        try:
            args.validate()
        except Exception as e:
            res = self.alert("Confirm Run",
                str(e) + "\n\nAre you sure you want to proceed?",
                kind="warning")
            if res != messagebox.OK:
                return

        def run_async(args) -> None:
            self.job_queue.job_running = True
            self.destroy_progress_bar()
            self.progress_bar = Progressbar(self.sidebar, orient=HORIZONTAL, length=100, mode='indeterminate')
            self.progress_bar.grid(row=1, column=1)
            self.progress_bar.start()
            main(args)
            self.destroy_progress_bar()
            self.job_queue.job_running = False
            next_job_args = self.job_queue.take()
            if next_job_args:
                start_thread(run_async, use_asyncio=False, args=[next_job_args])

        if self.job_queue.has_pending():
            self.job_queue.add(args)
        else:
            self.runner_app_config.set_from_run_config(args_copy)
            start_thread(run_async, use_asyncio=False, args=[args])


    def server_run_callback(self, workflow_type, args):
        if workflow_type is not None:
            self.workflow.set(workflow_type.name)
            self.set_workflow_type(workflow_type.name)
        else:
            print("Rerunning from server request with last settings.")
        if len(args) > 0:
            file = args[0].replace(",", "\\,")
            print(file)
            if workflow_type in [WorkflowType.CONTROLNET, WorkflowType.RENOISER, WorkflowType.REDO_PROMPT]:
                self.controlnet_file.set(file)
            elif workflow_type == WorkflowType.IP_ADAPTER:
                self.ipadapter_file.set(file)
            else:
                print(f"Unhandled workflow type for server connection: {workflow_type}")
            self.master.update()
        self.run()
        return {} # Empty error object for confirmation


    def set_prompter_config(self):
        self.runner_app_config.prompter_config.concepts = (int(self.concepts0.get()), int(self.concepts1.get()))
        self.runner_app_config.prompter_config.positions = (int(self.positions0.get()), int(self.positions1.get()))
        self.runner_app_config.prompter_config.locations = (int(self.locations0.get()), int(self.locations1.get()))
        self.runner_app_config.prompter_config.animals = (int(self.animals0.get()), int(self.animals1.get()))
        self.runner_app_config.prompter_config.colors = (int(self.colors0.get()), int(self.colors1.get()))
        self.runner_app_config.prompter_config.times = (int(self.times0.get()), int(self.times1.get()))
        self.runner_app_config.prompter_config.dress = (int(self.dress0.get()), int(self.dress1.get()), 0.7)
        self.runner_app_config.prompter_config.expressions = (int(self.expressions0.get()), int(self.expressions1.get()))
        self.runner_app_config.prompter_config.actions = (int(self.actions0.get()), int(self.actions1.get()))
        self.runner_app_config.prompter_config.descriptions = (int(self.descriptions0.get()), int(self.descriptions1.get()))
        self.runner_app_config.prompter_config.random_words = (int(self.random_words0.get()), int(self.random_words1.get()))

    def set_prompt_massage_tags_box_from_model_tags(self, event=None, model_tags=None, inpainting=None):
        Model.set_model_presets(PromptMode[self.prompt_mode.get()])
        if model_tags is None:
            model_tags = self.model_tags.get()
        if inpainting is None:
            inpainting = self.inpainting_var.get()
        prompt_massage_tags = Model.get_first_model_prompt_massage_tags(model_tags, prompt_mode=self.prompt_mode.get(), inpainting=inpainting)
        self.prompt_massage_tags_box.delete(0, 'end')
        self.prompt_massage_tags_box.insert(0, prompt_massage_tags)
        self.prompt_massage_tags.set(prompt_massage_tags)
        self.set_prompt_massage_tags()
        self.master.update()

    def set_prompt_massage_tags(self, event=None):
        self.runner_app_config.prompt_massage_tags = self.prompt_massage_tags.get()
        Globals.set_prompt_massage_tags(self.runner_app_config.prompt_massage_tags)

    def set_positive_tags(self, event=None):
        text = self.positive_tags_box.get("1.0", END)
        if text.endswith("\n"):
            text = text[:-1]
        text = self.apply_wildcards(text, positive=True)
        self.runner_app_config.positive_tags = text
        Prompter.set_positive_tags(text)

    def set_negative_tags(self, event=None):
        text = self.negative_tags_box.get("1.0", END)
        if text.endswith("\n"):
            text = text[:-1]
        text = self.apply_wildcards(text, positive=False)
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
        delay = int(self.delay.get())
        Globals.set_delay(delay)

    def set_specific_locations(self, event=None):
        self.runner_app_config.prompter_config.specific_locations = self.specific_locations_var.get()

    def set_random_skip(self, event=None):
        self.runner_app_config.random_skip_chance = self.random_skip.get().strip()
        ComfyGen.RANDOM_SKIP_CHANCE = float(self.runner_app_config.random_skip_chance)

    def set_specify_humans_chance(self, event=None):
        value = float(self.specify_humans_chance_slider.get()) / 100
        self.runner_app_config.prompter_config.specify_humans_chance = value

    def set_art_style_chance(self, event=None):
        value = float(self.art_style_chance_slider.get()) / 100
        self.runner_app_config.prompter_config.art_styles_chance = value

    def set_override_negative(self, event=None):
        self.runner_app_config.override_negative = self.override_negative_var.get()
        Globals.set_override_base_negative(self.runner_app_config.override_negative)

    def set_tags_apply_to_start(self, event=None):
        self.runner_app_config.tags_apply_to_start = self.tags_at_start_var.get()
        Prompter.set_tags_apply_to_start(self.runner_app_config.tags_apply_to_start)

    def apply_wildcards(self, text, positive=False):
        if Prompter.contains_wildcard(text):
            text = Prompter.apply_wildcards(text)
            if positive:
                self.positive_tags_box.delete("0.0", END)
                self.positive_tags_box.insert("0.0", text)
            else:
                self.negative_tags.set(text)
            self.master.update()
        return text

    def alert(self, title, message, kind="info", hidemain=True) -> None:
        if kind not in ("error", "warning", "info"):
            raise ValueError("Unsupported alert kind.")

        print(f"Alert - Title: \"{title}\" Message: {message}")
        show_method = getattr(messagebox, "show{}".format(kind))
        return show_method(title, message)

    def toast(self, message):
        print("Toast message: " + message)

        # Set the position of the toast on the screen (top right)
        width = 300
        height = 100
        x = self.master.winfo_screenwidth() - width
        y = 0

        # Create the toast on the top level
        toast = Toplevel(self.master, bg=App.DARK_BG)
        toast.geometry(f'{width}x{height}+{int(x)}+{int(y)}')
        self.container = Frame(toast, bg=App.DARK_BG)
        self.container.pack(fill=BOTH, expand=YES)
        label = Label(
            self.container,
            text=message,
            anchor=NW,
            bg=App.DARK_BG,
            fg='white',
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
        start_thread(self_destruct_after, use_asyncio=False, args=[2])

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

    def add_label(self, label_ref, text, sticky=W, pady=0, column=0, columnspan=None, increment_row_counter=True):
        label_ref['text'] = text
        self.apply_to_grid(label_ref, sticky=sticky, pady=pady, column=column, columnspan=columnspan, increment_row_counter=increment_row_counter)

    def add_button(self, button_ref_name, text, command):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.sidebar, text=text, command=command)
            setattr(self, button_ref_name, button)
            button
            self.apply_to_grid(button)

    def new_entry(self, text_variable, text="", width=55, **kw):
        return Entry(self.sidebar, text=text, textvariable=text_variable, width=width, font=fnt.Font(size=8), **kw)

    def destroy_grid_element(self, element_ref_name):
        element = getattr(self, element_ref_name)
        if element is not None:
            element.destroy()
            setattr(self, element_ref_name, None)
            self.row_counter0 -= 1


if __name__ == "__main__":
    try:
        assets = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")
        root = ThemedTk(theme="black", themebg="black")
        root.title(" ComfyGen ")
        #root.iconbitmap(bitmap=r"icon.ico")
        # icon = PhotoImage(file=os.path.join(assets, "icon.png"))
        # root.iconphoto(False, icon)
        root.geometry("600x950")
        # root.attributes('-fullscreen', True)
        root.resizable(1, 1)
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # Graceful shutdown handler
        def graceful_shutdown(signum, frame):
            print("Caught signal, shutting down gracefully...")
            app.on_closing()
            exit(0)

        # Register the signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, graceful_shutdown)
        signal.signal(signal.SIGTERM, graceful_shutdown)

        app = App(root)
        root.mainloop()
        exit()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
