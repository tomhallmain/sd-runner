from typing import Optional

from tkinter import Frame, Label, StringVar, BooleanVar, Checkbutton, Toplevel, W, E, HORIZONTAL, END
from tkinter.ttk import Button, OptionMenu, Scale
from tkinter.font import Font

from lib.aware_entry import AwareEntry
from sd_runner.base_image_generator import BaseImageGenerator
from sd_runner.prompter import PrompterConfiguration, Prompter
from sd_runner.run_config import RunConfig
from ui.app_style import AppStyle
from utils.globals import Sampler, Scheduler
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

_ = I18N._


class PromptConfigWindow:
    """
    Window for detailed prompt configuration settings.
    Contains the detailed prompt configuration widgets that were previously
    in the main application window's prompter_config_bar frame.
    """
    
    _runner_app_config: RunnerAppConfig = RunnerAppConfig()
    
    _prompt_config_window_instance: Optional['PromptConfigWindow'] = None
    
    @classmethod
    def set_runner_app_config(cls, runner_app_config: RunnerAppConfig):
        """Set the runner_app_config reference for the class."""
        cls._runner_app_config = runner_app_config
    
    @classmethod
    def get_runner_app_config(cls) -> RunnerAppConfig:
        """Get the runner_app_config reference for the class."""
        return cls._runner_app_config
    
    @classmethod
    def set_prompt_config_window_instance(cls, instance):
        """Set the prompt_config_window instance reference."""
        cls._prompt_config_window_instance = instance
    
    @classmethod
    def get_prompt_config_window_instance(cls):
        """Get the prompt_config_window instance reference."""
        return cls._prompt_config_window_instance
    
    @classmethod
    def set_args_from_prompter_config(cls, args: RunConfig):
        """Set appropriate values from the prompter config to the args object."""
        # Update prompter config from the detailed configuration window if it exists
        if cls._prompt_config_window_instance is not None:
            cls._prompt_config_window_instance.set_prompter_config()
        
        # Set values from runner_app_config to args
        args.seed = int(cls._runner_app_config.seed)
        args.steps = int(cls._runner_app_config.steps)
        args.cfg = float(cls._runner_app_config.cfg)
        args.sampler = Sampler.get(cls._runner_app_config.sampler)
        args.scheduler = Scheduler.get(cls._runner_app_config.scheduler)
        args.denoise = float(cls._runner_app_config.denoise)
        BaseImageGenerator.RANDOM_SKIP_CHANCE = float(cls._runner_app_config.random_skip_chance)
        Prompter.set_tags_apply_to_start(cls._runner_app_config.tags_apply_to_start)
        args.continuous_seed_variation = cls._runner_app_config.continuous_seed_variation
        cls._runner_app_config.prompter_config.sparse_mixed_tags = cls._runner_app_config.sparse_mixed_tags
    
    def __init__(self, master, app_actions, runner_app_config: RunnerAppConfig):
        self.master = master
        self.app_actions = app_actions
        self.runner_app_config = runner_app_config
        
        # Set the class reference to the runner_app_config
        self.__class__.set_runner_app_config(runner_app_config)
        
        # Set the class instance reference
        self.__class__.set_prompt_config_window_instance(self)
        
        # Create the top-level window
        self.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        self.top_level.title(_("Prompt Configuration"))
        self.top_level.geometry("800x900")
        self.top_level.protocol("WM_DELETE_WINDOW", self.close_window)
        
        # Setup main frame
        self.main_frame = Frame(self.top_level, bg=AppStyle.BG_COLOR)
        self.main_frame.grid(column=0, row=0, sticky="nsew", padx=10, pady=10)
        self.main_frame.columnconfigure(0, weight=1)
        self.main_frame.columnconfigure(1, weight=1)
        self.main_frame.columnconfigure(2, weight=1)
        
        # Row counter for grid layout
        self.row_counter = 0
        
        # Create the UI
        self.setup_ui()
        
        # Apply theme colors
        self.apply_theme()
        
        # Bind widget change events to update the configuration
        self.bind_widget_events()
    
    def bind_widget_events(self):
        """Bind widget change events to update the configuration."""
        # Bind text entry widgets
        self.seed_box.bind("<KeyRelease>", self.update_config_from_widgets)
        self.steps_box.bind("<KeyRelease>", self.update_config_from_widgets)
        self.cfg_box.bind("<KeyRelease>", self.update_config_from_widgets)
        self.denoise_box.bind("<KeyRelease>", self.update_config_from_widgets)
        self.random_skip_box.bind("<KeyRelease>", self.update_config_from_widgets)
        
        # Bind dropdown widgets
        self.sampler.trace_add('write', self.update_config_from_widgets)
        self.scheduler.trace_add('write', self.update_config_from_widgets)
        
        # Bind concept count widgets
        self.concepts0.trace_add('write', self.update_config_from_widgets)
        self.concepts1.trace_add('write', self.update_config_from_widgets)
        self.positions0.trace_add('write', self.update_config_from_widgets)
        self.positions1.trace_add('write', self.update_config_from_widgets)
        self.locations0.trace_add('write', self.update_config_from_widgets)
        self.locations1.trace_add('write', self.update_config_from_widgets)
        self.animals0.trace_add('write', self.update_config_from_widgets)
        self.animals1.trace_add('write', self.update_config_from_widgets)
        self.colors0.trace_add('write', self.update_config_from_widgets)
        self.colors1.trace_add('write', self.update_config_from_widgets)
        self.times0.trace_add('write', self.update_config_from_widgets)
        self.times1.trace_add('write', self.update_config_from_widgets)
        self.dress0.trace_add('write', self.update_config_from_widgets)
        self.dress1.trace_add('write', self.update_config_from_widgets)
        self.expressions0.trace_add('write', self.update_config_from_widgets)
        self.expressions1.trace_add('write', self.update_config_from_widgets)
        self.actions0.trace_add('write', self.update_config_from_widgets)
        self.actions1.trace_add('write', self.update_config_from_widgets)
        self.descriptions0.trace_add('write', self.update_config_from_widgets)
        self.descriptions1.trace_add('write', self.update_config_from_widgets)
        self.characters0.trace_add('write', self.update_config_from_widgets)
        self.characters1.trace_add('write', self.update_config_from_widgets)
        self.random_words0.trace_add('write', self.update_config_from_widgets)
        self.random_words1.trace_add('write', self.update_config_from_widgets)
        self.nonsense0.trace_add('write', self.update_config_from_widgets)
        self.nonsense1.trace_add('write', self.update_config_from_widgets)
        self.jargon0.trace_add('write', self.update_config_from_widgets)
        self.jargon1.trace_add('write', self.update_config_from_widgets)
        self.sayings0.trace_add('write', self.update_config_from_widgets)
        self.sayings1.trace_add('write', self.update_config_from_widgets)
        
        # Bind other widgets
        self.multiplier.trace_add('write', self.update_config_from_widgets)
        self.override_negative_var.trace_add('write', self.update_config_from_widgets)
        self.tags_at_start_var.trace_add('write', self.update_config_from_widgets)
        self.tags_sparse_mix_var.trace_add('write', self.update_config_from_widgets)
        self.continuous_seed_variation_var.trace_add('write', self.update_config_from_widgets)
        
    def update_config_from_widgets(self, *args):
        """Update the configuration from the current widget values."""
        try:
            prompter_config = self.runner_app_config.prompter_config
            
            # Update concept counts
            prompter_config.concepts = (int(self.concepts0.get()), int(self.concepts1.get()))
            prompter_config.positions = (int(self.positions0.get()), int(self.positions1.get()))
            prompter_config.locations = (int(self.locations0.get()), int(self.locations1.get()))
            prompter_config.animals = (int(self.animals0.get()), int(self.animals1.get()))
            prompter_config.colors = (int(self.colors0.get()), int(self.colors1.get()))
            prompter_config.times = (int(self.times0.get()), int(self.times1.get()))
            prompter_config.dress = (int(self.dress0.get()), int(self.dress1.get()), 0.7)
            prompter_config.expressions = (int(self.expressions0.get()), int(self.expressions1.get()))
            prompter_config.actions = (int(self.actions0.get()), int(self.actions1.get()))
            prompter_config.descriptions = (int(self.descriptions0.get()), int(self.descriptions1.get()))
            prompter_config.characters = (int(self.characters0.get()), int(self.characters1.get()))
            prompter_config.random_words = (int(self.random_words0.get()), int(self.random_words1.get()))
            prompter_config.nonsense = (int(self.nonsense0.get()), int(self.nonsense1.get()))
            prompter_config.jargon = (int(self.jargon0.get()), int(self.jargon1.get()))
            prompter_config.sayings = (int(self.sayings0.get()), int(self.sayings1.get()))
            
            # Update other prompter config values
            prompter_config.multiplier = float(self.multiplier.get())
            prompter_config.specific_locations_chance = float(self.specific_locations_slider.get()) / 100
            prompter_config.specify_humans_chance = float(self.specify_humans_chance_slider.get()) / 100
            prompter_config.art_styles_chance = float(self.art_style_chance_slider.get()) / 100
            prompter_config.emphasis_chance = float(self.emphasis_chance_slider.get()) / 100
            prompter_config.sparse_mixed_tags = self.tags_sparse_mix_var.get()
            
            # Update other settings
            self.runner_app_config.sampler = Sampler.get(self.sampler.get())
            self.runner_app_config.scheduler = Scheduler.get(self.scheduler.get())
            self.runner_app_config.seed = int(self.seed.get())
            self.runner_app_config.steps = int(self.steps.get())
            self.runner_app_config.cfg = float(self.cfg.get())
            self.runner_app_config.denoise = float(self.denoise.get())
            self.runner_app_config.random_skip_chance = self.random_skip.get().strip()
            self.runner_app_config.override_negative = self.override_negative_var.get()
            self.runner_app_config.tags_apply_to_start = self.tags_at_start_var.get()
            self.runner_app_config.continuous_seed_variation = self.continuous_seed_variation_var.get()
            self.runner_app_config.sparse_mixed_tags = self.tags_sparse_mix_var.get()
            
        except (ValueError, AttributeError) as e:
            # Ignore errors during widget updates (e.g., empty fields)
            pass
    
    def setup_ui(self):
        """Setup the user interface with all the prompt configuration widgets."""
        
        # Title
        self.label_title = Label(self.main_frame, text=_("Detailed Prompt Configuration"), 
                                font=Font(size=14, weight="bold"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_title, columnspan=3, sticky=W+E)
        
        # Basic Generation Settings Section
        self.add_section_header(_("Basic Generation Settings"))
        
        # Sampler
        self.label_sampler = Label(self.main_frame, text=_("Sampler"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_sampler, increment_row_counter=False)
        self.sampler = StringVar(self.master)
        self.sampler_choice = OptionMenu(self.main_frame, self.sampler, str(self.runner_app_config.sampler), 
                                        *Sampler.__members__.keys())
        self.apply_to_grid(self.sampler_choice, interior_column=1, sticky=W)
        
        # Scheduler
        self.label_scheduler = Label(self.main_frame, text=_("Scheduler"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_scheduler, increment_row_counter=False)
        self.scheduler = StringVar(self.master)
        self.scheduler_choice = OptionMenu(self.main_frame, self.scheduler, str(self.runner_app_config.scheduler), 
                                          *Scheduler.__members__.keys())
        self.apply_to_grid(self.scheduler_choice, interior_column=1, sticky=W)
        
        # Seed
        self.label_seed = Label(self.main_frame, text=_("Seed"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_seed, increment_row_counter=False)
        self.seed = StringVar()
        self.seed_box = AwareEntry(self.main_frame, textvariable=self.seed, width=10, font=Font(size=8))
        self.apply_to_grid(self.seed_box, interior_column=1, sticky=W)
        self.set_widget_value(self.seed_box, self.runner_app_config.seed)
        
        # Steps
        self.label_steps = Label(self.main_frame, text=_("Steps"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_steps, increment_row_counter=False)
        self.steps = StringVar()
        self.steps_box = AwareEntry(self.main_frame, textvariable=self.steps, width=10, font=Font(size=8))
        self.apply_to_grid(self.steps_box, interior_column=1, sticky=W)
        self.set_widget_value(self.steps_box, self.runner_app_config.steps)
        
        # CFG
        self.label_cfg = Label(self.main_frame, text=_("CFG"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_cfg, increment_row_counter=False)
        self.cfg = StringVar()
        self.cfg_box = AwareEntry(self.main_frame, textvariable=self.cfg, width=10, font=Font(size=8))
        self.apply_to_grid(self.cfg_box, interior_column=1, sticky=W)
        self.set_widget_value(self.cfg_box, self.runner_app_config.cfg)
        
        # Denoise
        self.label_denoise = Label(self.main_frame, text=_("Denoise"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_denoise, increment_row_counter=False)
        self.denoise = StringVar()
        self.denoise_box = AwareEntry(self.main_frame, textvariable=self.denoise, width=10, font=Font(size=8))
        self.apply_to_grid(self.denoise_box, interior_column=1, sticky=W)
        self.set_widget_value(self.denoise_box, self.runner_app_config.denoise)
        
        # Random Skip Chance
        self.label_random_skip = Label(self.main_frame, text=_("Random Skip Chance"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_random_skip, increment_row_counter=False)
        self.random_skip = StringVar()
        self.random_skip_box = AwareEntry(self.main_frame, textvariable=self.random_skip, width=10, font=Font(size=8))
        self.apply_to_grid(self.random_skip_box, interior_column=1, sticky=W)
        self.set_widget_value(self.random_skip_box, self.runner_app_config.random_skip_chance)
        self.random_skip_box.bind("<Return>", self.set_random_skip)
        
        # Prompts Configuration Section
        self.add_section_header(_("Prompts Configuration"), columnspan=3)
        
        # Concept Counts
        self.setup_concept_counts()
        
        # Position Counts
        self.setup_position_counts()
        
        # Location Counts
        self.setup_location_counts()
        
        # Animal Counts
        self.setup_animal_counts()
        
        # Color Counts
        self.setup_color_counts()
        
        # Time Counts
        self.setup_time_counts()
        
        # Dress Counts
        self.setup_dress_counts()
        
        # Expression Counts
        self.setup_expression_counts()
        
        # Action Counts
        self.setup_action_counts()
        
        # Description Counts
        self.setup_description_counts()
        
        # Character Counts
        self.setup_character_counts()
        
        # Random Word Counts
        self.setup_random_word_counts()
        
        # Nonsense Counts
        self.setup_nonsense_counts()
        
        # Jargon Counts
        self.setup_jargon_counts()
        
        # Sayings Counts
        self.setup_sayings_counts()
        
        # Multiplier
        self.label_multiplier = Label(self.main_frame, text=_("Multiplier"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_multiplier, increment_row_counter=False)
        multiplier_options = [str(i) for i in list(range(8))]
        multiplier_options.insert(2, "1.5")
        multiplier_options.insert(1, "0.75")
        multiplier_options.insert(1, "0.5")
        multiplier_options.insert(1, "0.25")
        self.multiplier = StringVar(self.master)
        self.multiplier_choice = OptionMenu(self.main_frame, self.multiplier, 
                                           str(self.runner_app_config.prompter_config.multiplier), 
                                           *multiplier_options, command=self.set_multiplier)
        self.apply_to_grid(self.multiplier_choice, interior_column=1, sticky=W)
        
        # Chance Sliders
        self.setup_chance_sliders()
        
        # Checkboxes
        self.setup_checkboxes()
        
        # Close Button
        self.close_btn = Button(self.main_frame, text=_("Close"), command=self.close_window)
        self.apply_to_grid(self.close_btn, columnspan=3, pady=20)
        
    def setup_concept_counts(self):
        """Setup concept count widgets."""
        self.label_concepts = Label(self.main_frame, text=_("Concepts"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_concepts, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.concepts0 = StringVar(self.master)
        self.concepts1 = StringVar(self.master)
        self.concepts0_choice = OptionMenu(self.main_frame, self.concepts0, str(prompter_config.concepts[0]), 
                                          *[str(i) for i in list(range(51))])
        self.concepts1_choice = OptionMenu(self.main_frame, self.concepts1, str(prompter_config.concepts[1]), 
                                          *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.concepts0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.concepts1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_position_counts(self):
        """Setup position count widgets."""
        self.label_positions = Label(self.main_frame, text=_("Positions"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_positions, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.positions0 = StringVar(self.master)
        self.positions1 = StringVar(self.master)
        self.positions0_choice = OptionMenu(self.main_frame, self.positions0, str(prompter_config.positions[0]), 
                                           *[str(i) for i in list(range(51))])
        self.positions1_choice = OptionMenu(self.main_frame, self.positions1, str(prompter_config.positions[1]), 
                                           *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.positions0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.positions1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_location_counts(self):
        """Setup location count widgets."""
        self.label_locations = Label(self.main_frame, text=_("Locations"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_locations, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.locations0 = StringVar(self.master)
        self.locations1 = StringVar(self.master)
        self.locations0_choice = OptionMenu(self.main_frame, self.locations0, str(prompter_config.locations[0]), 
                                           *[str(i) for i in list(range(51))])
        self.locations1_choice = OptionMenu(self.main_frame, self.locations1, str(prompter_config.locations[1]), 
                                           *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.locations0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.locations1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_animal_counts(self):
        """Setup animal count widgets."""
        self.label_animals = Label(self.main_frame, text=_("Animals"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_animals, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.animals0 = StringVar(self.master)
        self.animals1 = StringVar(self.master)
        self.animals0_choice = OptionMenu(self.main_frame, self.animals0, str(prompter_config.animals[0]), 
                                         *[str(i) for i in list(range(51))])
        self.animals1_choice = OptionMenu(self.main_frame, self.animals1, str(prompter_config.animals[1]), 
                                         *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.animals0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.animals1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_color_counts(self):
        """Setup color count widgets."""
        self.label_colors = Label(self.main_frame, text=_("Colors"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_colors, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.colors0 = StringVar(self.master)
        self.colors1 = StringVar(self.master)
        self.colors0_choice = OptionMenu(self.main_frame, self.colors0, str(prompter_config.colors[0]), 
                                        *[str(i) for i in list(range(51))])
        self.colors1_choice = OptionMenu(self.main_frame, self.colors1, str(prompter_config.colors[1]), 
                                        *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.colors0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.colors1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_time_counts(self):
        """Setup time count widgets."""
        self.label_times = Label(self.main_frame, text=_("Times"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_times, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.times0 = StringVar(self.master)
        self.times1 = StringVar(self.master)
        self.times0_choice = OptionMenu(self.main_frame, self.times0, str(prompter_config.times[0]), 
                                       *[str(i) for i in list(range(51))])
        self.times1_choice = OptionMenu(self.main_frame, self.times1, str(prompter_config.times[1]), 
                                       *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.times0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.times1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_dress_counts(self):
        """Setup dress count widgets."""
        self.label_dress = Label(self.main_frame, text=_("Dress"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_dress, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.dress0 = StringVar(self.master)
        self.dress1 = StringVar(self.master)
        self.dress0_choice = OptionMenu(self.main_frame, self.dress0, str(prompter_config.dress[0]), 
                                       *[str(i) for i in list(range(51))])
        self.dress1_choice = OptionMenu(self.main_frame, self.dress1, str(prompter_config.dress[1]), 
                                       *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.dress0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.dress1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_expression_counts(self):
        """Setup expression count widgets."""
        self.label_expressions = Label(self.main_frame, text=_("Expressions"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_expressions, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.expressions0 = StringVar(self.master)
        self.expressions1 = StringVar(self.master)
        self.expressions0_choice = OptionMenu(self.main_frame, self.expressions0, str(prompter_config.expressions[0]), 
                                             *[str(i) for i in list(range(51))])
        self.expressions1_choice = OptionMenu(self.main_frame, self.expressions1, str(prompter_config.expressions[1]), 
                                             *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.expressions0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.expressions1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_action_counts(self):
        """Setup action count widgets."""
        self.label_actions = Label(self.main_frame, text=_("Actions"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_actions, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.actions0 = StringVar(self.master)
        self.actions1 = StringVar(self.master)
        self.actions0_choice = OptionMenu(self.main_frame, self.actions0, str(prompter_config.actions[0]), 
                                         *[str(i) for i in list(range(51))])
        self.actions1_choice = OptionMenu(self.main_frame, self.actions1, str(prompter_config.actions[1]), 
                                         *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.actions0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.actions1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_description_counts(self):
        """Setup description count widgets."""
        self.label_descriptions = Label(self.main_frame, text=_("Descriptions"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_descriptions, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.descriptions0 = StringVar(self.master)
        self.descriptions1 = StringVar(self.master)
        self.descriptions0_choice = OptionMenu(self.main_frame, self.descriptions0, str(prompter_config.descriptions[0]), 
                                              *[str(i) for i in list(range(51))])
        self.descriptions1_choice = OptionMenu(self.main_frame, self.descriptions1, str(prompter_config.descriptions[1]), 
                                              *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.descriptions0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.descriptions1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_character_counts(self):
        """Setup character count widgets."""
        self.label_characters = Label(self.main_frame, text=_("Characters"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_characters, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.characters0 = StringVar(self.master)
        self.characters1 = StringVar(self.master)
        self.characters0_choice = OptionMenu(self.main_frame, self.characters0, str(prompter_config.characters[0]), 
                                            *[str(i) for i in list(range(51))])
        self.characters1_choice = OptionMenu(self.main_frame, self.characters1, str(prompter_config.characters[1]), 
                                            *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.characters0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.characters1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_random_word_counts(self):
        """Setup random word count widgets."""
        self.label_random_words = Label(self.main_frame, text=_("Random Words"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_random_words, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.random_words0 = StringVar(self.master)
        self.random_words1 = StringVar(self.master)
        self.random_words0_choice = OptionMenu(self.main_frame, self.random_words0, str(prompter_config.random_words[0]), 
                                              *[str(i) for i in list(range(51))])
        self.random_words1_choice = OptionMenu(self.main_frame, self.random_words1, str(prompter_config.random_words[1]), 
                                              *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.random_words0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.random_words1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_nonsense_counts(self):
        """Setup nonsense count widgets."""
        self.label_nonsense = Label(self.main_frame, text=_("Nonsense"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_nonsense, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.nonsense0 = StringVar(self.master)
        self.nonsense1 = StringVar(self.master)
        self.nonsense0_choice = OptionMenu(self.main_frame, self.nonsense0, str(prompter_config.nonsense[0]), 
                                          *[str(i) for i in list(range(51))])
        self.nonsense1_choice = OptionMenu(self.main_frame, self.nonsense1, str(prompter_config.nonsense[1]), 
                                          *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.nonsense0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.nonsense1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_jargon_counts(self):
        """Setup jargon count widgets."""
        self.label_jargon = Label(self.main_frame, text=_("Jargon"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_jargon, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.jargon0 = StringVar(self.master)
        self.jargon1 = StringVar(self.master)
        self.jargon0_choice = OptionMenu(self.main_frame, self.jargon0, str(prompter_config.jargon[0]), 
                                        *[str(i) for i in list(range(51))])
        self.jargon1_choice = OptionMenu(self.main_frame, self.jargon1, str(prompter_config.jargon[1]), 
                                        *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.jargon0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.jargon1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_sayings_counts(self):
        """Setup sayings count widgets."""
        self.label_sayings = Label(self.main_frame, text=_("Sayings"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_sayings, increment_row_counter=False)
        
        prompter_config = self.runner_app_config.prompter_config
        self.sayings0 = StringVar(self.master)
        self.sayings1 = StringVar(self.master)
        self.sayings0_choice = OptionMenu(self.main_frame, self.sayings0, str(prompter_config.sayings[0]), 
                                         *[str(i) for i in list(range(51))])
        self.sayings1_choice = OptionMenu(self.main_frame, self.sayings1, str(prompter_config.sayings[1]), 
                                         *[str(i) for i in list(range(51))])
        self.apply_to_grid(self.sayings0_choice, sticky=W, interior_column=1, increment_row_counter=False)
        self.apply_to_grid(self.sayings1_choice, sticky=W, interior_column=2, increment_row_counter=True)
        
    def setup_chance_sliders(self):
        """Setup chance slider widgets."""
        # Specific Locations Chance
        self.label_specific_locations = Label(self.main_frame, text=_("Specific Locations Chance"), 
                                             bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_specific_locations, increment_row_counter=False, columnspan=2)
        self.specific_locations_slider = Scale(self.main_frame, from_=0, to=100, orient=HORIZONTAL, 
                                              command=self.set_specific_locations)
        self.set_widget_value(self.specific_locations_slider, self.runner_app_config.prompter_config.specific_locations_chance)
        self.apply_to_grid(self.specific_locations_slider, interior_column=2, sticky=W)
        
        # Specify Humans Chance
        self.label_specify_humans_chance = Label(self.main_frame, text=_("Specify Humans Chance"), 
                                                bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_specify_humans_chance, increment_row_counter=False, columnspan=2)
        self.specify_humans_chance_slider = Scale(self.main_frame, from_=0, to=100, orient=HORIZONTAL, 
                                                  command=self.set_specify_humans_chance)
        self.set_widget_value(self.specify_humans_chance_slider, self.runner_app_config.prompter_config.specify_humans_chance)
        self.apply_to_grid(self.specify_humans_chance_slider, interior_column=2, sticky=W)
        
        # Art Style Chance
        self.label_art_style_chance = Label(self.main_frame, text=_("Art Styles Chance"), 
                                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_art_style_chance, increment_row_counter=False, columnspan=2)
        self.art_style_chance_slider = Scale(self.main_frame, from_=0, to=100, orient=HORIZONTAL, 
                                             command=self.set_art_style_chance)
        self.set_widget_value(self.art_style_chance_slider, self.runner_app_config.prompter_config.art_styles_chance)
        self.apply_to_grid(self.art_style_chance_slider, interior_column=2, sticky=W)
        
        # Emphasis Chance
        self.label_emphasis_chance = Label(self.main_frame, text=_("Emphasis Chance"), 
                                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(self.label_emphasis_chance, increment_row_counter=False, columnspan=2)
        self.emphasis_chance_slider = Scale(self.main_frame, from_=0, to=100, orient=HORIZONTAL, 
                                            command=self.set_emphasis_chance)
        self.set_widget_value(self.emphasis_chance_slider, self.runner_app_config.prompter_config.emphasis_chance)
        self.apply_to_grid(self.emphasis_chance_slider, interior_column=2, sticky=W)
        
    def setup_checkboxes(self):
        """Setup checkbox widgets."""
        # Override Negative
        self.override_negative_var = BooleanVar(value=self.runner_app_config.override_negative)
        self.override_negative_choice = Checkbutton(self.main_frame, text=_("Override Base Negative"), 
                                                   variable=self.override_negative_var, command=self.set_override_negative, 
                                                   bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectcolor=AppStyle.BG_COLOR)
        self.apply_to_grid(self.override_negative_choice, sticky=W, columnspan=3)
        
        # Tags Applied to Prompt Start
        self.tags_at_start_var = BooleanVar(value=self.runner_app_config.tags_apply_to_start)
        self.tags_at_start_choice = Checkbutton(self.main_frame, text=_("Tags Applied to Prompt Start"), 
                                               variable=self.tags_at_start_var, command=self.set_tags_apply_to_start, 
                                               bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectcolor=AppStyle.BG_COLOR)
        self.apply_to_grid(self.tags_at_start_choice, sticky=W, columnspan=3)
        
        # Sparse Mixed Tags
        self.tags_sparse_mix_var = BooleanVar(value=self.runner_app_config.prompter_config.sparse_mixed_tags)
        self.tags_sparse_mix_choice = Checkbutton(self.main_frame, text=_("Sparse Mixed Tags"), 
                                                  variable=self.tags_sparse_mix_var, command=self.set_tags_sparse_mix, 
                                                  bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectcolor=AppStyle.BG_COLOR)
        self.apply_to_grid(self.tags_sparse_mix_choice, sticky=W, columnspan=3)
         
        # Continuous Seed Variation
        self.continuous_seed_variation_var = BooleanVar(value=self.runner_app_config.continuous_seed_variation)
        self.continuous_seed_variation_choice = Checkbutton(self.main_frame, text=_("Continuous Seed Variation"), 
                                                            variable=self.continuous_seed_variation_var, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, selectcolor=AppStyle.BG_COLOR)
        self.apply_to_grid(self.continuous_seed_variation_choice, sticky=W, columnspan=3)
        
    def add_section_header(self, text, columnspan=1, sticky=W):
        """Add a section header label."""
        label = Label(self.main_frame, text=text, font=Font(size=12, weight="bold"), 
                      bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.add_label(label, columnspan=columnspan, sticky=sticky, pady=(20, 10))
        
    def add_label(self, label_ref, sticky=W, pady=0, columnspan=None, increment_row_counter=True, interior_column=0):
        """Add a label to the grid."""
        if columnspan is None:
            label_ref.grid(column=interior_column, row=self.row_counter, sticky=sticky, pady=pady)
        else:
            label_ref.grid(column=interior_column, row=self.row_counter, sticky=sticky, pady=pady, columnspan=columnspan)
        if increment_row_counter:
            self.row_counter += 1
            
    def apply_to_grid(self, component, sticky=None, pady=0, interior_column=0, columnspan=None, increment_row_counter=True):
        """Apply a component to the grid."""
        row = self.row_counter
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
            self.row_counter += 1
            
    def set_widget_value(self, widget, value):
        """Set the value of a widget."""
        if hasattr(widget, 'set'):
            # For sliders, convert from 0.0-1.0 to 0-100
            widget.set(float(value) * 100)
        else:
            # For text widgets, just set the value directly
            widget.delete(0, "end")
            widget.insert(0, value)
            
    def apply_theme(self):
        """Apply the current theme colors to all widgets."""
        self.top_level.config(bg=AppStyle.BG_COLOR)
        self.main_frame.config(bg=AppStyle.BG_COLOR)
        # Refresh selectcolor for all Checkbutton widgets
        for widget in self.main_frame.winfo_children():
            if isinstance(widget, Checkbutton):
                widget.config(selectcolor=AppStyle.BG_COLOR)
        
    # Implemented setter methods that update the runner_app_config directly
    def set_random_skip(self, event=None):
        """Set random skip chance."""
        value = self.random_skip.get().strip()
        self.runner_app_config.random_skip_chance = value
        BaseImageGenerator.RANDOM_SKIP_CHANCE = float(value)
        
    def set_multiplier(self, event=None):
        """Set multiplier value."""
        value = float(self.multiplier.get())
        self.runner_app_config.prompter_config.multiplier = value
        
    def set_specific_locations(self, event=None):
        """Set specific locations chance."""
        value = float(self.specific_locations_slider.get()) / 100
        self.runner_app_config.prompter_config.specific_locations_chance = value
        
    def set_specify_humans_chance(self, event=None):
        """Set specify humans chance."""
        value = float(self.specify_humans_chance_slider.get()) / 100
        self.runner_app_config.prompter_config.specify_humans_chance = value
        
    def set_art_style_chance(self, event=None):
        """Set art style chance."""
        value = float(self.art_style_chance_slider.get()) / 100
        self.runner_app_config.prompter_config.art_styles_chance = value
        
    def set_emphasis_chance(self, event=None):
        """Set emphasis chance."""
        value = float(self.emphasis_chance_slider.get()) / 100
        self.runner_app_config.prompter_config.emphasis_chance = value
        
    def set_override_negative(self, event=None):
        """Set override negative."""
        value = self.override_negative_var.get()
        self.runner_app_config.override_negative = value
        
    def set_tags_apply_to_start(self, event=None):
        """Set tags apply to start."""
        value = self.tags_at_start_var.get()
        self.runner_app_config.tags_apply_to_start = value
        
    def set_tags_sparse_mix(self, event=None):
        """Set tags sparse mix."""
        value = self.tags_sparse_mix_var.get()
        self.runner_app_config.sparse_mixed_tags = value
        
    def set_continuous_seed_variation(self, event=None):
        """Set continuous seed variation."""
        value = self.continuous_seed_variation_var.get()
        self.runner_app_config.continuous_seed_variation = value
        
    def set_prompter_config(self):
        """Update the prompter configuration from the widget values."""
        prompter_config: PrompterConfiguration = self.runner_app_config.prompter_config
        
        # Update concept counts from widgets
        prompter_config.concepts = (int(self.concepts0.get()), int(self.concepts1.get()))
        prompter_config.positions = (int(self.positions0.get()), int(self.positions1.get()))
        prompter_config.locations = (int(self.locations0.get()), int(self.locations1.get()))
        prompter_config.animals = (int(self.animals0.get()), int(self.animals1.get()))
        prompter_config.colors = (int(self.colors0.get()), int(self.colors1.get()))
        prompter_config.times = (int(self.times0.get()), int(self.times1.get()))
        prompter_config.dress = (int(self.dress0.get()), int(self.dress1.get()), 0.7)
        prompter_config.expressions = (int(self.expressions0.get()), int(self.expressions1.get()))
        prompter_config.actions = (int(self.actions0.get()), int(self.actions1.get()))
        prompter_config.descriptions = (int(self.descriptions0.get()), int(self.descriptions1.get()))
        prompter_config.characters = (int(self.characters0.get()), int(self.characters1.get()))
        prompter_config.random_words = (int(self.random_words0.get()), int(self.random_words1.get()))
        prompter_config.nonsense = (int(self.nonsense0.get()), int(self.nonsense1.get()))
        prompter_config.jargon = (int(self.jargon0.get()), int(self.jargon1.get()))
        prompter_config.sayings = (int(self.sayings0.get()), int(self.sayings1.get()))
        
    def close_window(self):
        """Close the prompt configuration window."""
        self.top_level.destroy()
        self.__class__.set_prompt_config_window_instance(None)
