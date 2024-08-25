
from utils.globals import Globals # must import first
from sd_runner.concepts import PromptMode


class RunConfig:
    previous_model_tags = None
    model_switch_detected = False
    has_warned_about_prompt_massage_text_mismatch = False

    def __init__(self, args=None):
        self.args = args
        self.workflow_tag = self.get("workflow_tag")
        self.res_tags = self.get("res_tags")
        self.model_tags = self.get("model_tags")
        self.lora_tags = self.get("lora_tags")
        self.inpainting = self.get("inpainting")
        self.n_latents = self.get("n_latents")
        self.seed = self.get("seed")
        self.steps = self.get("steps")
        self.cfg = self.get("cfg")
        self.sampler = self.get("sampler")
        self.scheduler = self.get("scheduler")
        self.denoise = self.get("denoise")
        self.prompter_override = self.get("prompter_override")
        self.redo_files = self.get("redo_files")
        self.prompter_config = self.get("prompter_config")
        self.control_nets = self.get("control_nets")
        self.ip_adapters = self.get("ip_adapters")
        self.positive_prompt = self.get("positive_prompt")
        self.negative_prompt = self.get("negative_prompt")
        self.auto_run = self.get("auto_run")
        self.total = self.get("total")

        if RunConfig.previous_model_tags != self.model_tags:
            RunConfig.model_switch_detected = True

        RunConfig.previous_model_tags = self.model_tags

    def get(self, name):
        if isinstance(self.args, dict):
            return self.args[name]
        elif not self.args:
            return None
        else:
            return getattr(self.args, name)

    def validate(self):
        if self.prompter_config is None:
            raise Exception(_("No prompter config found!"))
        # Check here if for example, using FIXED prompt mode and > 6 set total
        if self.prompter_config.prompt_mode == PromptMode.FIXED and self.total > 10:
            raise Exception(_("Ensure configuration is correct - do you really want to create more than 10 images using the same prompt?"))
        if RunConfig.model_switch_detected and not RunConfig.has_warned_about_prompt_massage_text_mismatch:
            prompt_massage_tags = Model.get_first_model_prompt_massage_tags(self.model_tags, prompt_mode=self.prompter_config.prompt_mode, inpainting=self.inpainting)
            if Globals.POSITIVE_PROMPT_MASSAGE_TAGS != prompt_massage_tags:
                RunConfig.has_warned_about_prompt_massage_text_mismatch = True
                raise Exception(_("A model switch was detected and the model massage tags don't match. This warning will only be shown once."))
        return True