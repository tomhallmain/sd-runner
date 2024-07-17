from copy import deepcopy
import json

from utils.globals import Globals, WorkflowType, Sampler, Scheduler

from sd_runner.comfy_gen import ComfyGen
from sd_runner.prompter import PrompterConfiguration

class RunnerAppConfig:
    def __init__(self):
        self.workflow_type = WorkflowType.SIMPLE_IMAGE_GEN_LORA.name
        self.resolutions = "landscape3,portrait3"
        self.seed = "-1" # if less than zero, randomize
        self.steps = "-1" # if not int / less than zero, take workflow's value
        self.cfg = "-1" # if not int / less than zero, take workflow's value
        self.denoise = "-1" # if not int / less than zero, take workflow's value
        self.model_tags = "realvisxlV40_v40Bakedvae"
        self.lora_tags = ""
        self.prompt_massage_tags = ""
        self.positive_tags = ""
        self.negative_tags = ""
        self.b_w_colorization = "" # Globals.DEFAULT_B_W_COLORIZATION
        self.lora_strength = str(Globals.DEFAULT_LORA_STRENGTH)
        self.control_net_file = ""
        self.control_net_strength = str(Globals.DEFAULT_CONTROL_NET_STRENGTH)
        self.ip_adapter_file = ""
        self.ip_adapter_strength = str(Globals.DEFAULT_IPADAPTER_STRENGTH)
        self.redo_params = "models,resolutions,seed,n_latents"
        self.random_skip_chance = str(ComfyGen.RANDOM_SKIP_CHANCE)

        self.sampler = Sampler.ACCEPT_ANY.name
        self.scheduler = Scheduler.ACCEPT_ANY.name
        self.n_latents = 1
        self.total = 2
        self.prompter_config = PrompterConfiguration()

        self.auto_run = True
        self.inpainting = False
        self.override_negative = False

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
        self.inpainting = args.inpainting

    @staticmethod
    def from_dict(_dict):
        app_config = RunnerAppConfig()
        app_config.__dict__ = deepcopy(_dict)
        if not isinstance(app_config.prompter_config, dict):
            raise Exception("Prompter config is not a dict")
        prompter_config_dict = deepcopy(app_config.prompter_config)
        app_config.prompter_config = PrompterConfiguration()
        app_config.prompter_config.set_from_dict(prompter_config_dict)
        return app_config
    
    def to_dict(self):
        _dict = deepcopy(self.__dict__)
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
        return self.__dict__ == other.__dict__

    def __hash__(self):
        class EnumsEncoder(json.JSONEncoder):
            def default(self, z):
                if isinstance(z, WorkflowType) or isinstance(z, Sampler) or isinstance(z, Scheduler):
                    return (str(z.name))
                else:
                    return super().default(z)
        return hash(json.dumps(self, cls=EnumsEncoder, sort_keys=True))