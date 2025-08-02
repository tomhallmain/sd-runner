from copy import deepcopy
import json
import datetime

from utils.globals import Globals, WorkflowType, Sampler, Scheduler, SoftwareType, ResolutionGroup

from sd_runner.comfy_gen import ComfyGen
from sd_runner.prompter import PrompterConfiguration


class RunnerAppConfig:
    def __init__(self):
        self.software_type = SoftwareType.ComfyUI.name
        self.workflow_type = WorkflowType.SIMPLE_IMAGE_GEN_LORA.name
        self.resolutions = "landscape3,portrait3"
        self.resolution_group = ResolutionGroup.FIVE_ONE_TWO.name
        self.seed = "-1"  # if less than zero, randomize
        self.steps = "-1"  # if not int / less than zero, take workflow's value
        self.cfg = "-1"  # if not int / less than zero, take workflow's value
        self.denoise = "-1"  # if not int / less than zero, take workflow's value
        self.model_tags = "realvisxlV40_v40Bakedvae"
        self.lora_tags = ""
        self.prompt_massage_tags = ""
        self.positive_tags = ""
        self.negative_tags = ""
        self.b_w_colorization = ""  # Globals.DEFAULT_B_W_COLORIZATION
        self.lora_strength = str(Globals.DEFAULT_LORA_STRENGTH)
        self.control_net_file = ""
        self.control_net_strength = str(Globals.DEFAULT_CONTROL_NET_STRENGTH)
        self.ip_adapter_file = ""
        self.ip_adapter_strength = str(Globals.DEFAULT_IPADAPTER_STRENGTH)
        self.redo_params = "models,resolutions,seed,n_latents"
        self.random_skip_chance = str(ComfyGen.RANDOM_SKIP_CHANCE)
        self.delay_time_seconds = str(Globals.GENERATION_DELAY_TIME_SECONDS)
        self.timestamp = datetime.datetime.now().isoformat()  # Add timestamp field
        self.continuous_seed_variation = False  # Whether to vary seed between every generation

        self.sampler = Sampler.ACCEPT_ANY.name
        self.scheduler = Scheduler.ACCEPT_ANY.name
        self.n_latents = 1
        self.total = 2
        self.prompter_config = PrompterConfiguration()

        self.auto_run = True
        self.override_resolution = False
        self.inpainting = False
        self.override_negative = False
        self.tags_apply_to_start = True

    def set_from_run_config(self, args):
        self.workflow_type = args.workflow_tag
        self.resolutions = args.res_tags
        self.seed = args.seed
        self.steps = args.steps
        self.cfg = args.cfg
        self.denoise = args.denoise
        self.model_tags = args.model_tags
        self.lora_tags = args.lora_tags
        #self.positive_tags = args.positive_prompt
        #self.negative_tags = args.negative_prompt
        self.control_net_file = args.control_nets if args.control_nets is not None else ""
        self.ip_adapter_file = args.ip_adapters if args.ip_adapters is not None else ""
        self.sampler = args.sampler.name
        self.scheduler = args.scheduler.name
        self.n_latents = args.n_latents
        self.total = args.total
        self.auto_run = args.auto_run
        self.override_resolution = args.override_resolution
        self.inpainting = args.inpainting
        self.continuous_seed_variation = getattr(args, 'continuous_seed_variation', False)

    @staticmethod
    def from_dict(_dict):
        app_config = RunnerAppConfig()
        app_config.__dict__ = deepcopy(_dict)
        if not hasattr(app_config, 'software_type'):
            app_config.software_type = SoftwareType.ComfyUI.name
        if not hasattr(app_config, 'tags_apply_to_start'):
            app_config.tags_apply_to_start = True
        if not hasattr(app_config, 'delay_time_seconds'):
            app_config.delay_time_seconds = 10
        if not hasattr(app_config,'override_resolution'):
            app_config.override_resolution = False
        if not hasattr(app_config, 'resolution_group'):
            app_config.resolution_group = ResolutionGroup.TEN_TWENTY_FOUR.name
        if not hasattr(app_config, 'timestamp'):
            app_config.timestamp = datetime.datetime.now().isoformat()  # Add timestamp for old entries
        if not hasattr(app_config, 'continuous_seed_variation'):
            app_config.continuous_seed_variation = False  # Default to False for backward compatibility
        if not isinstance(app_config.prompter_config, dict):
            raise Exception("Prompter config is not a dict")
        prompter_config_dict = deepcopy(app_config.prompter_config)
        app_config.prompter_config = PrompterConfiguration()
        app_config.prompter_config.set_from_dict(prompter_config_dict)
        return app_config

    def to_dict(self):
        _dict = deepcopy(self.__dict__)
        if not isinstance(self.software_type, str):
            _dict["software_type"] = self.software_type.name
        if not isinstance(self.workflow_type, str):
            _dict["workflow_type"] = self.workflow_type.name
        if not isinstance(self.sampler, str):
            _dict["sampler"] = self.sampler.name
        if not isinstance(self.scheduler, str):
            _dict["scheduler"] = self.scheduler.name
        if not isinstance(self.prompter_config, dict):
            _dict["prompter_config"] = self.prompter_config.to_dict()
        return _dict

    def __eq__(self, other):
        if not isinstance(other, RunnerAppConfig):
            return False
        # Create copies of both dicts without timestamp
        self_dict = {k: v for k, v in self.__dict__.items() if k != 'timestamp'}
        other_dict = {k: v for k, v in other.__dict__.items() if k != 'timestamp'}
        return self_dict == other_dict

    def __hash__(self):
        class EnumsEncoder(json.JSONEncoder):
            def default(self, z):
                if isinstance(z, SoftwareType) or isinstance(z, WorkflowType) or isinstance(z, Sampler) or isinstance(z, Scheduler):
                    return (str(z.name))
                else:
                    return super().default(z)
        # Create a copy of the dict without timestamp
        dict_without_timestamp = {k: v for k, v in self.__dict__.items() if k != 'timestamp'}
        return hash(json.dumps(dict_without_timestamp, cls=EnumsEncoder, sort_keys=True))
