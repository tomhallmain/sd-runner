import os
import time
import traceback

import tkinter as tk
from tkinter import messagebox, HORIZONTAL, Label, Checkbutton
from tkinter.constants import W
import tkinter.font as fnt
from tkinter.ttk import Button, Entry, Frame, OptionMenu, Progressbar
from lib.autocomplete_entry import AutocompleteEntry, matches
from ttkthemes import ThemedTk

from run import main, RunConfig
from globals import Globals, WorkflowType, Sampler, Scheduler

from comfy_gen import ComfyGen
from concepts import PromptMode
from gen_config import GenConfig
from models import IPAdapter, Model
from prompter import PROMPTER_CONFIG, Prompter
from utils import open_file_location, periodic, start_thread


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

class Sidebar(tk.Frame):
    def __init__(self, master=None, cnf={}, **kw):
        tk.Frame.__init__(self, master=master, cnf=cnf, **kw)


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
    DARK_BG = "#26242f"

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
            fg_color = "white"
        App.IS_DEFAULT_THEME = not App.IS_DEFAULT_THEME
        self.master.config(bg=bg_color)
        self.sidebar.config(bg=bg_color)
        self.prompter_config.config(bg=bg_color)
        for name, attr in self.__dict__.items():
            if isinstance(attr, Label):
                attr.config(bg=bg_color, fg=fg_color)
            elif isinstance(attr, Checkbutton):
                attr.config(bg=bg_color, fg=fg_color, selectcolor=bg_color)
        self.master.update()
        self.toast("Theme switched to dark." if App.IS_DEFAULT_THEME else "Theme switched to light.")

    def __init__(self, master):
        self.master = master
        self.progress_bar = None
        self.job_queue = JobQueue()
        Model.load_all()

        # Sidebar
        self.sidebar = Sidebar(self.master)
        self.sidebar.columnconfigure(0, weight=1)
        self.row_counter0 = 0
        self.sidebar.grid(column=0, row=self.row_counter0)
        self.label_title = Label(self.sidebar)
        self.add_label(self.label_title, "Run ComfyUI Workflows", sticky=None)

        # self.toggle_theme_btn = None
        # self.add_button("toggle_theme_btn", "Toggle theme", self.toggle_theme)

        # TODO multiselect
        self.label_workflows = Label(self.sidebar)
        self.add_label(self.label_workflows, "Workflow")
        self.workflow = tk.StringVar(master)
        self.workflows_choice = OptionMenu(self.sidebar, self.workflow, WorkflowType.SIMPLE_IMAGE_GEN_LORA.name,
                                           *WorkflowType.__members__.keys(), command=self.set_workflow_type)
        self.apply_to_grid(self.workflows_choice, sticky=W)

        self.label_resolutions = Label(self.sidebar)
        self.add_label(self.label_resolutions, "Resolutions")
        self.resolutions = tk.StringVar()
        self.resolutions_box = self.new_entry(self.resolutions)
        self.resolutions_box.insert(0, "landscape3,portrait3")
        self.apply_to_grid(self.resolutions_box, sticky=W)

        self.label_seed = Label(self.sidebar)
        self.add_label(self.label_seed, "Seed")
        self.seed = tk.StringVar()
        self.seed_box = self.new_entry(self.seed)
        self.seed_box.insert(0, "-1") # if less than zero, randomize
        self.apply_to_grid(self.seed_box, sticky=W)

        self.label_steps = Label(self.sidebar)
        self.add_label(self.label_steps, "Steps")
        self.steps = tk.StringVar()
        self.steps_box = self.new_entry(self.steps)
        self.steps_box.insert(0, "-1") # if not int / less than zero, take workflow's value
        self.apply_to_grid(self.steps_box, sticky=W)

        self.label_cfg = Label(self.sidebar)
        self.add_label(self.label_cfg, "CFG")
        self.cfg = tk.StringVar()
        self.cfg_box = self.new_entry(self.cfg)
        self.cfg_box.insert(0, "-1") # if not int / less than zero, take workflow's value
        self.apply_to_grid(self.cfg_box, sticky=W)

        self.label_denoise = Label(self.sidebar)
        self.add_label(self.label_denoise, "Denoise")
        self.denoise = tk.StringVar()
        self.denoise_box = self.new_entry(self.denoise)
        self.denoise_box.insert(0, "-1") # if not int / less than zero, take workflow's value
        self.apply_to_grid(self.denoise_box, sticky=W)

        self.label_model_tags = Label(self.sidebar)
        self.add_label(self.label_model_tags, "Model Tags")
        self.model_tags = tk.StringVar()
        model_names = list(map(lambda l: str(l).split('.')[0], Model.CHECKPOINTS))
        self.model_tags_box = AutocompleteEntry(model_names,
                                               self.sidebar,
                                               listboxLength=6,
                                               textvariable=self.model_tags,
                                               matchesFunction=matches_tag,
                                               setFunction=set_tag,
                                               width=40, font=fnt.Font(size=8))
        self.model_tags_box.bind("<Return>", self.set_prompt_massage_tags_box_from_model_tags)
        self.model_tags_box.insert(0, "realvisxlV40_v40Bakedvae")
        self.apply_to_grid(self.model_tags_box, sticky=W)

        self.label_lora_tags = Label(self.sidebar)
        self.add_label(self.label_lora_tags, "LoRA Tags")
        self.lora_tags = tk.StringVar()
        lora_names = list(map(lambda l: str(l).split('.')[0], Model.LORAS))

        self.lora_tags_box = AutocompleteEntry(lora_names,
                                               self.sidebar,
                                               listboxLength=6,
                                               textvariable=self.lora_tags,
                                               matchesFunction=matches_tag,
                                               setFunction=set_tag,
                                               width=40, font=fnt.Font(size=8))
        self.apply_to_grid(self.lora_tags_box, sticky=W)

        self.label_prompt_tags = Label(self.sidebar)
        self.add_label(self.label_prompt_tags, "Prompt Tags (Universal)")
        self.prompt_massage_tags = tk.StringVar()
        self.prompt_massage_tags_box = self.new_entry(self.prompt_massage_tags)
        self.apply_to_grid(self.prompt_massage_tags_box, sticky=W)
        self.prompt_massage_tags_box.bind("<Return>", self.set_prompt_massage_tags)
#        self.positive_tags = tk.StringVar()
        self.positive_tags_box = tk.Text(self.sidebar, height=3, width=40, font=fnt.Font(size=8))
        self.apply_to_grid(self.positive_tags_box, sticky=W)
        self.positive_tags_box.bind("<Return>", self.set_positive_tags)
        self.negative_tags = tk.StringVar()
        self.negative_tags_box = self.new_entry(self.negative_tags)
        self.apply_to_grid(self.negative_tags_box, sticky=W)
        self.negative_tags_box.bind("<Return>", self.set_negative_tags)

        self.label_bw_colorization = Label(self.sidebar)
        self.add_label(self.label_bw_colorization, "B/W Colorization Tags")
        self.bw_colorization = tk.StringVar()
        self.bw_colorization_box = self.new_entry(self.bw_colorization)
#        self.bw_colorization_box.insert(0, Globals.DEFAULT_B_W_COLORIZATION)
        self.apply_to_grid(self.bw_colorization_box, sticky=W)
        self.bw_colorization_box.bind("<Return>", self.set_bw_colorization)

        self.label_lora_strength = Label(self.sidebar)
        self.add_label(self.label_lora_strength, "Default LoRA Strength")
        self.lora_strength = tk.StringVar()
        self.lora_strength_box = self.new_entry(self.lora_strength)
        self.lora_strength_box.insert(0, str(Globals.DEFAULT_LORA_STRENGTH))
        self.apply_to_grid(self.lora_strength_box, sticky=W)
        self.lora_strength_box.bind("<Return>", self.set_lora_strength)

        self.label_controlnet_file = Label(self.sidebar)
        self.add_label(self.label_controlnet_file, "Control Net or Redo files")
        self.controlnet_file = tk.StringVar()
        self.controlnet_file_box = self.new_entry(self.controlnet_file)
        self.apply_to_grid(self.controlnet_file_box, sticky=W)

        self.label_controlnet_strength = Label(self.sidebar)
        self.add_label(self.label_controlnet_strength, "Default Control Net Strength")
        self.controlnet_strength = tk.StringVar()
        self.controlnet_strength_box = self.new_entry(self.controlnet_strength)
        self.controlnet_strength_box.insert(0, str(Globals.DEFAULT_CONTROL_NET_STRENGTH))
        self.apply_to_grid(self.controlnet_strength_box, sticky=W)
        self.controlnet_strength_box.bind("<Return>", self.set_controlnet_strength)

        self.label_ipadapter_file = Label(self.sidebar)
        self.add_label(self.label_ipadapter_file, "IPAdapter files")
        self.ipadapter_file = tk.StringVar()
        self.ipadapter_file_box = self.new_entry(self.ipadapter_file)
        self.apply_to_grid(self.ipadapter_file_box, sticky=W)

        self.label_ipadapter_strength = Label(self.sidebar)
        self.add_label(self.label_ipadapter_strength, "Default IPAdapter Strength")
        self.ipadapter_strength = tk.StringVar()
        self.ipadapter_strength_box = self.new_entry(self.ipadapter_strength)
        self.ipadapter_strength_box.insert(0, str(Globals.DEFAULT_IPADAPTER_STRENGTH))
        self.apply_to_grid(self.ipadapter_strength_box, sticky=W)
        self.ipadapter_strength_box.bind("<Return>", self.set_ipadapter_strength)

        self.label_redo_params = Label(self.sidebar)
        self.add_label(self.label_redo_params, "Redo Parameters")
        self.redo_params = tk.StringVar()
        self.redo_params_box = self.new_entry(self.redo_params)
        self.redo_params_box.insert(0, "models,resolutions,seed,n_latents")
        self.apply_to_grid(self.redo_params_box, sticky=W)
        self.redo_params_box.bind("<Return>", self.set_redo_params)

        self.label_random_skip = Label(self.sidebar)
        self.add_label(self.label_random_skip, "Random Skip Chance")
        self.random_skip = tk.StringVar()
        self.random_skip_box = self.new_entry(self.random_skip)
        self.random_skip_box.insert(0, str(ComfyGen.RANDOM_SKIP_CHANCE))
        self.apply_to_grid(self.random_skip_box, sticky=W)
        self.random_skip_box.bind("<Return>", self.set_random_skip)

        # Run context-aware UI elements
        self.run_btn = None
        self.add_button("run_btn", "Run Workflows", self.run)
        self.master.bind("<Shift-R>", self.run)

        # Prompter Config
        self.row_counter1 = 0
        self.prompter_config = Sidebar(self.master)
        self.prompter_config.columnconfigure(0, weight=1)
        self.prompter_config.columnconfigure(1, weight=1)
        self.prompter_config.columnconfigure(2, weight=1)
        self.prompter_config.grid(column=1, row=self.row_counter1)

        self.label_title_config = Label(self.prompter_config)
        self.add_label(self.label_title_config, "Prompts Configuration", column=1, columnspan=3, sticky=tk.W+tk.E)

        self.label_prompt_mode = Label(self.prompter_config)
        self.add_label(self.label_prompt_mode, "Prompt Mode", column=1)
        self.prompt_mode = tk.StringVar(master)
        self.prompt_mode_choice = OptionMenu(self.prompter_config, self.prompt_mode, str(PromptMode.SFW), *PromptMode.__members__.keys())
        self.apply_to_grid(self.prompt_mode_choice, sticky=W, column=1)

        self.label_sampler = Label(self.prompter_config)
        self.add_label(self.label_sampler, "Sampler", column=1)
        self.sampler = tk.StringVar(master)
        self.sampler_choice = OptionMenu(self.prompter_config, self.sampler, str(Sampler.ACCEPT_ANY), *Sampler.__members__.keys())
        self.apply_to_grid(self.sampler_choice, sticky=W, column=1)

        self.label_scheduler = Label(self.prompter_config)
        self.add_label(self.label_scheduler, "Scheduler", column=1)
        self.scheduler = tk.StringVar(master)
        self.scheduler_choice = OptionMenu(self.prompter_config, self.scheduler, str(Scheduler.ACCEPT_ANY), *Scheduler.__members__.keys())
        self.apply_to_grid(self.scheduler_choice, sticky=W, column=1)

        self.label_n_latents = Label(self.prompter_config)
        self.add_label(self.label_n_latents, "Set N Latents", column=1)
        self.n_latents = tk.StringVar(master)
        self.n_latents_choice = OptionMenu(self.prompter_config, self.n_latents, "1", *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.n_latents_choice, sticky=W, column=1)

        self.label_total = Label(self.prompter_config)
        self.add_label(self.label_total, "Set Total", column=1)
        self.total = tk.StringVar(master)
        self.total_choice = OptionMenu(self.prompter_config, self.total, "2", *[str(i) for i in list(range(101))])
        self.apply_to_grid(self.total_choice, sticky=W, column=1)

        self.label_concepts = Label(self.prompter_config)
        self.add_label(self.label_concepts, "Concepts", column=1)
        self.concepts0 = tk.StringVar(master)
        self.concepts1 = tk.StringVar(master)
        self.concepts0_choice = OptionMenu(self.prompter_config, self.concepts0, str(PROMPTER_CONFIG.concepts[0]), *[str(i) for i in list(range(51))])
        self.concepts1_choice = OptionMenu(self.prompter_config, self.concepts1, str(PROMPTER_CONFIG.concepts[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.concepts0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.concepts1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_positions = Label(self.prompter_config)
        self.add_label(self.label_positions, "Positions", column=1)
        self.positions0 = tk.StringVar(master)
        self.positions1 = tk.StringVar(master)
        self.positions0_choice = OptionMenu(self.prompter_config, self.positions0, str(PROMPTER_CONFIG.positions[0]), *[str(i) for i in list(range(51))])
        self.positions1_choice = OptionMenu(self.prompter_config, self.positions1, str(PROMPTER_CONFIG.positions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.positions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.positions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_locations = Label(self.prompter_config)
        self.add_label(self.label_locations, "Locations", column=1)
        self.locations0 = tk.StringVar(master)
        self.locations1 = tk.StringVar(master)
        self.locations0_choice = OptionMenu(self.prompter_config, self.locations0, str(PROMPTER_CONFIG.locations[0]), *[str(i) for i in list(range(51))])
        self.locations1_choice = OptionMenu(self.prompter_config, self.locations1, str(PROMPTER_CONFIG.locations[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.locations0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.locations1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_animals = Label(self.prompter_config)
        self.add_label(self.label_animals, "Animals", column=1)
        self.animals0 = tk.StringVar(master)
        self.animals1 = tk.StringVar(master)
        self.animals0_choice = OptionMenu(self.prompter_config, self.animals0, str(PROMPTER_CONFIG.animals[0]), *[str(i) for i in list(range(51))])
        self.animals1_choice = OptionMenu(self.prompter_config, self.animals1, str(PROMPTER_CONFIG.animals[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.animals0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.animals1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_colors = Label(self.prompter_config)
        self.add_label(self.label_colors, "Colors", column=1)
        self.colors0 = tk.StringVar(master)
        self.colors1 = tk.StringVar(master)
        self.colors0_choice = OptionMenu(self.prompter_config, self.colors0, str(PROMPTER_CONFIG.colors[0]), *[str(i) for i in list(range(51))])
        self.colors1_choice = OptionMenu(self.prompter_config, self.colors1, str(PROMPTER_CONFIG.colors[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.colors0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.colors1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_times = Label(self.prompter_config)
        self.add_label(self.label_times, "Times", column=1)
        self.times0 = tk.StringVar(master)
        self.times1 = tk.StringVar(master)
        self.times0_choice = OptionMenu(self.prompter_config, self.times0, str(PROMPTER_CONFIG.times[0]), *[str(i) for i in list(range(51))])
        self.times1_choice = OptionMenu(self.prompter_config, self.times1, str(PROMPTER_CONFIG.times[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.times0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.times1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_dress = Label(self.prompter_config)
        self.add_label(self.label_dress, "Dress", column=1)
        self.dress0 = tk.StringVar(master)
        self.dress1 = tk.StringVar(master)
        self.dress_chance = tk.StringVar()
        self.dress0_choice = OptionMenu(self.prompter_config, self.dress0, str(PROMPTER_CONFIG.dress[0]), *[str(i) for i in list(range(51))])
        self.dress1_choice = OptionMenu(self.prompter_config, self.dress1, str(PROMPTER_CONFIG.dress[1]), *[str(i) for i in list(range(51))])
        self.dress_chance_box = self.new_entry(self.dress_chance)
        self.apply_to_grid(self.dress0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.dress1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)
#        self.apply_to_grid(self.dress_chance_box, sticky=tk.E, interior_column=2, column=1, increment_row_counter=True)

        self.expressions_var = tk.BooleanVar(value=PROMPTER_CONFIG.expressions)
        self.expressions_choice = Checkbutton(self.prompter_config, text="Expressions", variable=self.expressions_var)
        self.apply_to_grid(self.expressions_choice, sticky=W, interior_column=0, column=1, increment_row_counter=True)

        self.label_actions = Label(self.prompter_config)
        self.add_label(self.label_actions, "Actions", column=1)
        self.actions0 = tk.StringVar(master)
        self.actions1 = tk.StringVar(master)
        self.actions0_choice = OptionMenu(self.prompter_config, self.actions0, str(PROMPTER_CONFIG.actions[0]), *[str(i) for i in list(range(51))])
        self.actions1_choice = OptionMenu(self.prompter_config, self.actions1, str(PROMPTER_CONFIG.actions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.actions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.actions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_descriptions = Label(self.prompter_config)
        self.add_label(self.label_descriptions, "Descriptions", column=1)
        self.descriptions0 = tk.StringVar(master)
        self.descriptions1 = tk.StringVar(master)
        self.descriptions0_choice = OptionMenu(self.prompter_config, self.descriptions0, str(PROMPTER_CONFIG.descriptions[0]), *[str(i) for i in list(range(51))])
        self.descriptions1_choice = OptionMenu(self.prompter_config, self.descriptions1, str(PROMPTER_CONFIG.descriptions[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.descriptions0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.descriptions1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.label_random_words = Label(self.prompter_config)
        self.add_label(self.label_random_words, "Random Words", column=1)
        self.random_words0 = tk.StringVar(master)
        self.random_words1 = tk.StringVar(master)
        self.random_words0_choice = OptionMenu(self.prompter_config, self.random_words0, str(PROMPTER_CONFIG.random_words[0]), *[str(i) for i in list(range(51))])
        self.random_words1_choice = OptionMenu(self.prompter_config, self.random_words1, str(PROMPTER_CONFIG.random_words[1]), *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.random_words0_choice, sticky=W, interior_column=0, column=1, increment_row_counter=False)
        self.apply_to_grid(self.random_words1_choice, sticky=W, interior_column=1, column=1, increment_row_counter=True)

        self.auto_run_var = tk.BooleanVar(value=True)
        self.auto_run_choice = Checkbutton(self.prompter_config, text='Auto Run', variable=self.auto_run_var)
        self.apply_to_grid(self.auto_run_choice, sticky=W, column=1)

        self.inpainting_var = tk.BooleanVar(value=False)
        self.inpainting_choice = Checkbutton(self.prompter_config, text='Inpainting', variable=self.inpainting_var)
        self.apply_to_grid(self.inpainting_choice, sticky=W, column=1)

        self.random_skip_var = tk.BooleanVar(value=False)
        self.random_skip_choice = Checkbutton(self.prompter_config, text="Randomly Skip Combinations", variable=self.random_skip_var,
                command=lambda: setattr(ComfyGen, "RANDOM_SKIP_CHANCE", 0.97 if self.random_skip_var.get() else 0))
        self.apply_to_grid(self.random_skip_choice, sticky=W, column=1, columnspan=3)

        self.override_negative_var = tk.BooleanVar(value=False)
        self.override_negative_choice = Checkbutton(self.prompter_config, text="Override Base Negative", variable=self.override_negative_var,
                command=lambda: setattr(Globals, "OVERRIDE_BASE_NEGATIVE", self.override_negative_var.get()))
        self.apply_to_grid(self.override_negative_choice, sticky=W, column=1, columnspan=3)

        self.master.bind("<Control-Return>", self.run)
        self.toggle_theme()
        self.master.update()
        self.model_tags_box.closeListbox()

    def set_workflow_type(self, event=None):
        workflow_tag = self.workflow.get()
        if workflow_tag == WorkflowType.INPAINT_CLIPSEG.name:
            self.inpainting_var.set(True)
            self.resolutions_box["text"] = "landscape3" # Technically not needed
            self.total.set("1")


    def destroy_progress_bar(self):
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.grid_forget()
            self.destroy_grid_element("progress_bar")
            self.progress_bar = None

    def run(self, event=None):
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
        args.prompt_mode = PromptMode[self.prompt_mode.get()]
#        self.set_prompt_massage_tags_box_from_model_tags(args.model_tags, args.inpainting)
        self.set_prompt_massage_tags()
        self.set_positive_tags()
        self.set_negative_tags()
        self.set_bw_colorization()
        self.set_lora_strength()
        controlnet_file = clear_quotes(self.controlnet_file_box.get())

        if args.workflow_tag == WorkflowType.REDO_PROMPT.name:
            args.workflow_tag = controlnet_file
            self.set_redo_params()
        else:
            args.control_nets = controlnet_file

        self.set_controlnet_strength()
        args.ip_adapters = clear_quotes(self.ipadapter_file_box.get())
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
            self.apply_to_grid(self.progress_bar)
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
            start_thread(run_async, use_asyncio=False, args=[args])


    def set_prompter_config(self):
        PROMPTER_CONFIG.concepts = (int(self.concepts0.get()), int(self.concepts1.get()))
        PROMPTER_CONFIG.positions = (int(self.positions0.get()), int(self.positions1.get()))
        PROMPTER_CONFIG.locations = (int(self.locations0.get()), int(self.locations1.get()))
        PROMPTER_CONFIG.animals = (int(self.animals0.get()), int(self.animals1.get()))
        PROMPTER_CONFIG.colors = (int(self.colors0.get()), int(self.colors1.get()))
        PROMPTER_CONFIG.times = (int(self.times0.get()), int(self.times1.get()))
        PROMPTER_CONFIG.dress = (int(self.dress0.get()), int(self.dress1.get()), 0.7)
        PROMPTER_CONFIG.expressions = self.expressions_var.get()
        PROMPTER_CONFIG.actions = (int(self.actions0.get()), int(self.actions1.get()))
        PROMPTER_CONFIG.descriptions = (int(self.descriptions0.get()), int(self.descriptions1.get()))
        PROMPTER_CONFIG.random_words = (int(self.random_words0.get()), int(self.random_words1.get()))

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
        Globals.set_prompt_massage_tags(self.prompt_massage_tags.get())

    def set_positive_tags(self, event=None):
        text = self.positive_tags_box.get("1.0", tk.END)
        if text.endswith("\n"):
            text = text[:-1]
        Prompter.set_positive_tags(text)

    def set_negative_tags(self, event=None):
        Prompter.set_negative_tags(self.negative_tags.get())

    def set_bw_colorization(self, event=None):
        IPAdapter.set_bw_coloration(self.bw_colorization.get())

    def set_lora_strength(self, event=None):
        Globals.set_lora_strength(float(self.lora_strength.get()))

    def set_ipadapter_strength(self, event=None):
        Globals.set_ipadapter_strength(float(self.ipadapter_strength.get()))

    def set_controlnet_strength(self, event=None):
        Globals.set_controlnet_strength(float(self.controlnet_strength.get()))

    def set_redo_params(self, event=None):
        GenConfig.set_redo_params(self.redo_params_box.get())

    def set_random_skip(self, event=None):
        ComfyGen.RANDOM_SKIP_CHANCE = float(self.random_skip.get()) if self.random_skip_var.get() else 0

    @classmethod
    def toggle_fill_canvas(cls):
        cls.fill_canvas = not cls.fill_canvas

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
        toast = tk.Toplevel(self.master, bg=App.DARK_BG)
        toast.geometry(f'{width}x{height}+{int(x)}+{int(y)}')
        self.container = tk.Frame(toast, bg=App.DARK_BG)
        self.container.pack(fill=tk.BOTH, expand=tk.YES)
        label = tk.Label(
            self.container,
            text=message,
            anchor=tk.NW,
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

    def add_label(self, label_ref, text, sticky=W, pady=0, column=0, columnspan=None):
        label_ref['text'] = text
        self.apply_to_grid(label_ref, sticky=sticky, pady=pady, column=column, columnspan=columnspan)

    def add_button(self, button_ref_name, text, command):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.sidebar, text=text, command=command)
            setattr(self, button_ref_name, button)
            button
            self.apply_to_grid(button)

    def new_entry(self, text_variable, text="", **kw):
        return Entry(self.sidebar, text=text, textvariable=text_variable, width=40, font=fnt.Font(size=8), **kw)

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
        app = App(root)
        root.mainloop()
        exit()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
