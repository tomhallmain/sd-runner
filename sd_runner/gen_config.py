import re
import random

from sd_runner.concepts import HardConcepts
from utils.config import config
from utils.globals import Sampler, Scheduler
from sd_runner.models import Globals, IPAdapter, Model, Resolution

RESET = "\033[m"
GRAY = "\033[90m"
WHITE = "\033[37m"
DARK_RED = "\033[91m"
DARK_GREEN = "\033[92m"
CYAN = "\033[34m"

def format_red(s):
    return f"{DARK_RED}{s}{RESET}"

def format_green(s):
    return f"{DARK_GREEN}{s}{RESET}"

def format_white(s):
    return f"{WHITE}{s}{RESET}"

def format_cyan(s):
    return f"{CYAN}{s}{RESET}"

def print_list_str(ls):
    out = "[\n"
    for item in ls:
        out += f"\t{item}\n"
    out += "]"
    return out

class GenConfig:
    REDO_PARAMETERS = config.redo_parameters

    def __init__(self, workflow_id=Globals.DEFAULT_WORKFLOW, n_latents=Globals.DEFAULT_N_LATENTS, positive="",
                 negative=Globals.DEFAULT_NEGATIVE_PROMPT, models=[Model(Globals.DEFAULT_MODEL)], vaes=[],
                 control_nets=[], ip_adapters = [], loras = [], resolutions=[Resolution()], seed=None,
                 steps=-1, cfg=-1, sampler=Sampler.ACCEPT_ANY, scheduler=Scheduler.ACCEPT_ANY, denoise=-1):
        self.workflow_id = workflow_id
        self.n_latents = n_latents
        self.models = models
        self.vaes = vaes
        self.control_nets = control_nets
        self.ip_adapters = ip_adapters
        self.positive = positive
        self.negative = negative
        self.loras = loras
        self.resolutions = resolutions
        self.seed = seed
        self.steps = steps
        self.cfg = cfg
        self.sampler = sampler
        self.scheduler = scheduler
        self.denoise = denoise

    def is_xl(self):
        return self.models[0].is_xl

    def prepare(self):
        if len(self.vaes) == 0:
            self.vaes.append(None)
        if len(self.loras) == 0:
            self.loras.append(None)
        if len(self.control_nets) == 0:
            self.control_nets.append(None)
        if len(self.ip_adapters) == 0:
            self.ip_adapters.append(None)
        if self.positive and self.positive != "":
            self.positive = re.sub("\n  +", "\n", self.positive) # TODO fix this
            self.positive = re.sub("  {2,}", " ", self.positive)
        if self.is_redo_prompt():
            if "model" not in GenConfig.REDO_PARAMETERS and "models" not in GenConfig.REDO_PARAMETERS:
                self.models = self.models[0:1]
            if "vae" not in GenConfig.REDO_PARAMETERS and "vaes" not in GenConfig.REDO_PARAMETERS:
                self.vaes.clear()
                self.vaes.append(None)
            if "lora" not in GenConfig.REDO_PARAMETERS and "loras" not in GenConfig.REDO_PARAMETERS:
                self.loras.clear()
                self.loras.append(None)
            if "control_net" not in GenConfig.REDO_PARAMETERS and "control_nets" not in GenConfig.REDO_PARAMETERS:
                self.control_nets.clear()
                self.control_nets.append(None)
            if "ip_adapter" not in GenConfig.REDO_PARAMETERS and "ip_adapters" not in GenConfig.REDO_PARAMETERS:
                self.ip_adapters.clear()
                self.ip_adapters.append(None)
            if "resolution" not in GenConfig.REDO_PARAMETERS and "resolutions" not in GenConfig.REDO_PARAMETERS:
                self.resolutions.clear()
                self.resolutions.append(None)


    def prompts_match(self, prior_config):
        if prior_config:
            return prior_config.positive == self.positive and prior_config.negative == self.negative
        return False

    def validate(self):
        if Globals.SKIP_CONFIRMATIONS or self.is_redo_prompt():
            return True
        confirm_messages = []
        if self.positive and self.positive != "":
            for concept in HardConcepts.hard_concepts:
                if concept in self.positive:
                    confirm_messages.append(f"You are using HARD concept {concept} in prompt - this is hard for image generation models.")
            for concept in HardConcepts.exclusionary_concepts:
                if concept in self.positive:
                    confirm_messages.append(f"You are using EXCLUSIONARY concept {concept} in prompt.")
            for concept in HardConcepts.boring_concepts:
                if concept in self.positive:
                    confirm_messages.append(f"You are using BORING concept {concept} in prompt.")
        if self.workflow_id == "renoiser.json":
            if "dark" not in self.positive and "night" not in self.positive and "shadows" not in self.positive:
                confirm_messages.append("The renoiser workflow creates images that are fairly bright, but no dark keywords detected.")
        if len(confirm_messages) == 0:
            return True
        confirm_str = ""
        for message in confirm_messages:
            confirm_str += message + "\n"
        confirm_str += "Confirm (y/n): "
        return input(confirm_str).lower().startswith("y")
              

    def is_redo_prompt(self):
        return isinstance(self.workflow_id, str) and self.workflow_id.endswith(".png")

    def redo_param(self, override_key, value_if_not_set):
        if not self.is_redo_prompt() or override_key in GenConfig.REDO_PARAMETERS:
            return value_if_not_set
        return None

    @classmethod
    def set_redo_params(cls, redo_params_str):
        if redo_params_str.strip() == "":
            cls.REDO_PARAMETERS = []
        else:
            cls.REDO_PARAMETERS = [p.strip() for p in redo_params_str.split(",")]

    @staticmethod
    def random_seed():
        return int(random.random() * 9999999999999)
    
    def get_seed(self):
        return self.seed if (self.seed and self.seed > -1) else GenConfig.random_seed()
    
    def get_ip_adapter_models(self):
        if self.is_xl():
            return IPAdapter.DEFAULT_SDXL_MODEL, IPAdapter.DEFAULT_SDXL_CLIP_VISION_MODEL
        return IPAdapter.DEFAULT_SD15_MODEL, IPAdapter.DEFAULT_SD15_CLIP_VISION_MODEL

    def maximum_gens(self):
        n_resolutions = len(self.resolutions) if len(self.resolutions) > 0 else 1
        n_models = len(self.models) if len(self.models) > 0 else 1
        n_vaes = len(self.vaes) if len(self.vaes) > 0 else 1
        n_loras = len(self.loras) if len(self.loras) > 0 else 1
        if self.workflow_id in ["instant_lora.json", "ip_adapter.json"]:
            n_control_nets = len(self.control_nets) if len(self.control_nets) > 0 else 1
            n_ip_adapters = len(self.ip_adapters) if len(self.ip_adapters) > 0 else 1
            return n_resolutions * n_models * n_vaes * n_loras * n_control_nets * n_ip_adapters * self.n_latents
        else:
            return n_resolutions * n_models * n_vaes * n_loras * self.n_latents

    @staticmethod
    def is_set(ls_var):
        return len(ls_var) > 0 and ls_var[0] is not None

    def __str__(self):
        if self.is_redo_prompt():
            out = format_white(f"GenConfig: {self.workflow_id}") + "\n"
            out += f"Models: {print_list_str(self.models)}\n"
            out += "Overrides: " + print_list_str(GenConfig.REDO_PARAMETERS)
            return out
        else:
            vae_str = f"VAEs: {print_list_str(self.vaes)}\n" if GenConfig.is_set(self.vaes) else ""
            lora_str = f"LoRAs: {print_list_str(self.loras)}\n" if GenConfig.is_set(self.loras) else ""
            control_net_str = f"Control nets: {print_list_str(self.control_nets)}\n" if GenConfig.is_set(self.control_nets) else ""
            ip_adapter_str = f"IP Adapters: {print_list_str(self.ip_adapters)}\n" if GenConfig.is_set(self.ip_adapters) else ""
            negative_str = f"Negative: {format_red(self.negative)}\n" if Globals.PRINT_NEGATIVES else ""
            return f"""{format_white(f"GenConfig: {self.workflow_id}")}
Resolutions: {print_list_str(self.resolutions)}
Models: {print_list_str(self.models)}
{vae_str}{lora_str}Positive: {format_green(self.positive)}
{negative_str}{control_net_str}{ip_adapter_str}"""

    def __hash__(self):
        return hash((
            self.workflow_id,
            self.n_latents,
            self.models,
            self.vaes,
            self.control_nets,
            self.ip_adapters,
            self.positive,
            self.negative,
            self.loras,
            self.resolutions,
        ))
    
    def __eq__(self, other):
        if isinstance(other, GenConfig):
            if self.seed is None or other.seed is None:
                return False
            return (
                self.workflow_id,
                self.n_latents,
                self.models,
                self.vaes,
                self.control_nets,
                self.ip_adapters,
                self.positive,
                self.negative,
                self.loras,
                self.resolutions,
                self.seed,
            ) == (
                other.workflow_id,
                other.n_latents,
                other.models,
                other.vaes,
                other.control_nets,
                other.ip_adapters,
                other.positive,
                other.negative,
                other.loras,
                other.resolutions,
                other.seed,
            ) and (self.seed is not None and other.seed is not None
                   and self.seed >-1 and other.seed > -1) # Ensure random seed not set.
        return False  # To handle the case when other object is of different type
    
    def __ne__(self, other):
        return not self.__eq__(other)