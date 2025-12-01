import time

from utils.globals import Globals, PromptMode, WorkflowType # must import first

from sd_runner.models import Model
from utils.logging_setup import get_logger
from utils.time_estimator import TimeEstimator
from utils.translations import I18N

_ = I18N._

logger = get_logger("run_config")

class RunConfig:
    previous_model_tags = None
    model_switch_detected = False
    has_warned_about_prompt_massage_text_mismatch = False

    def __init__(self, args=None):
        self.args = args
        self.start_time = time.localtime()
        self.software_type = self.get("software_type")
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
        self.resolution_group = self.get("resolution_group")
        self.override_resolution = self.get("override_resolution")
        self.total = self.get("total")
        self.batch_limit = self.get("batch_limit")
        self.continuous_seed_variation = self.get("continuous_seed_variation")

        if RunConfig.previous_model_tags != self.model_tags:
            RunConfig.model_switch_detected = True

        RunConfig.previous_model_tags = self.model_tags

    def get(self, name: str):
        if isinstance(self.args, dict):
            return self.args[name]
        elif not self.args:
            return None
        else:
            return getattr(self.args, name)

    def validate(self) -> bool:
        if self.prompter_config is None:
            raise Exception(_("No prompter config found!"))

        # Check here if for example, using FIXED prompt mode and > 6 set total
        if self.prompter_config.prompt_mode == PromptMode.FIXED and self.total > 10:
            raise Exception(_("Ensure configuration is correct - do you really want to create more than 10 images using the same prompt?"))

        # Validate prompt massage tags
        prompt_massage_tags, models = Model.get_first_model_prompt_massage_tags(self.model_tags, prompt_mode=self.prompter_config.prompt_mode, inpainting=self.inpainting)
        if RunConfig.model_switch_detected and not RunConfig.has_warned_about_prompt_massage_text_mismatch:
            if Globals.POSITIVE_PROMPT_MASSAGE_TAGS != prompt_massage_tags:
                RunConfig.has_warned_about_prompt_massage_text_mismatch = True
                raise Exception(_("A model switch was detected and the model massage tags don't match. This warning will only be shown once."))

        # Validate models against blacklist
        Model.validate_model_blacklist(self.model_tags,
                prompt_mode=self.prompter_config.prompt_mode,
                inpainting=self.inpainting)

        # Validate loras against blacklist
        Model.validate_model_blacklist(self.lora_tags,
                prompt_mode=self.prompter_config.prompt_mode,
                default_tag=models[0].get_default_lora(),
                inpainting=self.inpainting,
                is_lora=True,
                architecture_type=models[0].architecture_type)

        # Validate workflow-specific requirements
        self._validate_workflow_requirements()

        return True

    def __str__(self) -> str:
        return str(self.__dict__)

    def estimate_time(self, gen_config = None) -> int:
        """
        Estimate the total time in seconds for this run configuration.
        
        Args:
            gen_config: Optional GenConfig instance for calculating total jobs
            
        Returns:
            Estimated time in seconds
        """
        # Calculate total jobs using gen_config if available
        total_jobs = gen_config.maximum_gens_per_latent() if gen_config else 1
        logger.debug(f"RunConfig.estimate_time - total_jobs: {total_jobs}, total: {self.total}, n_latents: {self.n_latents}")
        
        # Get time for all jobs
        total_time = TimeEstimator.estimate_queue_time(total_jobs * self.total, self.n_latents)
        logger.debug(f"RunConfig.estimate_time - total_time: {total_time}s")
        return total_time

    def _get_workflow_type(self) -> WorkflowType:
        """Convert workflow_tag to WorkflowType for validation."""
        if not self.workflow_tag:
            return None
        
        try:
            return WorkflowType.get(self.workflow_tag)
        except Exception:
            return None

    def _is_ip_adapter_missing(self) -> bool:
        """Check if IP adapters are missing or empty."""
        return not self.ip_adapters or self.ip_adapters.strip() == ""

    def _is_control_net_missing(self) -> bool:
        """Check if control nets are missing or empty."""
        return not self.control_nets or self.control_nets.strip() == ""

    def _validate_workflow_requirements(self) -> None:
        """Validate workflow-specific requirements (IP adapters, control nets, etc.)"""
        workflow_type = self._get_workflow_type()
        if not workflow_type:
            return

        # Workflows that require IP adapters
        ip_adapter_required_workflows = [
            WorkflowType.INSTANT_LORA,
            WorkflowType.IP_ADAPTER,
            WorkflowType.IMG2IMG
        ]

        # Workflows that require control nets
        control_net_required_workflows = [
            WorkflowType.INSTANT_LORA,
            WorkflowType.CONTROLNET,
            WorkflowType.INPAINT_CLIPSEG,
            WorkflowType.RENOISER,
            WorkflowType.REDO_PROMPT
        ]

        # Validate IP adapter requirements
        if workflow_type in ip_adapter_required_workflows and self._is_ip_adapter_missing():
            raise Exception(_(f"Workflow '{workflow_type.get_translation()}' requires an IP adapter to be specified."))

        # Validate control net requirements
        if workflow_type in control_net_required_workflows and self._is_control_net_missing():
            raise Exception(_(f"Workflow '{workflow_type.get_translation()}' requires a control net to be specified."))
        
        # Validate renoiser workflow with multiple resolutions
        if workflow_type == WorkflowType.RENOISER and self.res_tags and "," in self.res_tags:
            raise Exception(_(
                "WARNING: Multiple resolutions in renoiser workflow will produce nearly identical results (duplicates)."
            ))
