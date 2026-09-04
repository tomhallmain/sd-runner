import threading
import time

from copy import deepcopy
from enum import Enum

from utils.globals import Globals, PromptMode, Sampler, Scheduler, WorkflowType # must import first

from sd_runner.models.model import Model, NoModelsFound
from utils.logging_setup import get_logger
from utils.time_estimator import TimeEstimator
from utils.translations import I18N

_ = I18N._

logger = get_logger("runs.run_config")


def _arg(source, name: str):
    """Read *name* from a RunConfig constructor source.

    The source is a dict, an object carrying the same attribute names, or None.
    Reading through one accessor is what lets the three construction paths --
    the sidebar, a server request, and a restored run -- share __init__.
    """
    if isinstance(source, dict):
        return source.get(name)
    if not source:
        return None
    return getattr(source, name, None)


class RunConfig:
    # Class-level state tracking a one-shot advisory about a model switch.
    # Runs are built on more than one thread -- the GUI thread for the user's
    # own, a worker thread for a server request -- so the compare-and-set in
    # __init__ and the check-and-set in validate() are guarded, or the warning
    # can be attributed to the wrong run or lost entirely.
    _model_switch_lock = threading.Lock()
    previous_model_tags = None
    model_switch_detected = False
    has_warned_about_prompt_massage_text_mismatch = False

    #: Rebuilt by __init__ rather than carried across sessions, so to_dict()
    #: leaves it out and from_dict() never has to restore it.
    TRANSIENT_FIELDS = ("start_time",)

    def __init__(self, args=None):
        # args is constructor input, not state, and is deliberately not kept:
        # every value it carries is copied onto the instance here. The sidebar
        # path passes nothing and assigns the fields itself, a server request
        # passes a dict, and a restored run passes its stored dict -- so a
        # retained args would mean three different things and would not reflect
        # later edits to a queued run. The instance is the run.
        self.start_time = time.localtime()
        self.software_type = _arg(args, "software_type")
        self.workflow_tag = _arg(args, "workflow_tag")
        self.res_tags = _arg(args, "res_tags")
        self.model_tags = _arg(args, "model_tags")
        self.lora_tags = _arg(args, "lora_tags")
        self.inpainting = _arg(args, "inpainting")
        self.n_latents = _arg(args, "n_latents")
        self.seed = _arg(args, "seed")
        self.steps = _arg(args, "steps")
        self.cfg = _arg(args, "cfg")
        self.sampler = _arg(args, "sampler")
        self.scheduler = _arg(args, "scheduler")
        self.denoise = _arg(args, "denoise")
        # Carried rather than applied where the run is built: generation reads
        # these off BaseImageGenerator and Prompter, so apply_prompt_globals
        # sets them when the run starts. A queued run then generates with its
        # own values instead of whatever a later run pushed while it waited.
        self.random_skip_chance = _arg(args, "random_skip_chance")
        self.tags_apply_to_start = _arg(args, "tags_apply_to_start")
        self.prompter_override = _arg(args, "prompter_override")
        self.redo_files = _arg(args, "redo_files")
        self.prompter_config = _arg(args, "prompter_config")
        self.control_nets = _arg(args, "control_nets")
        self.ip_adapters = _arg(args, "ip_adapters")
        self.source_prompts = _arg(args, "source_prompts")
        self.source_prompts_add_user_prompt = _arg(args, "source_prompts_add_user_prompt")
        self.positive_prompt = _arg(args, "positive_prompt")
        self.negative_prompt = _arg(args, "negative_prompt")
        self.auto_run = _arg(args, "auto_run")
        self.resolution_group = _arg(args, "resolution_group")
        self.override_resolution = _arg(args, "override_resolution")
        self.total = _arg(args, "total")
        self.batch_limit = _arg(args, "batch_limit")
        self.continuous_seed_variation = _arg(args, "continuous_seed_variation")
        self.dimension_variation = _arg(args, "dimension_variation")
        self.second_derivative = _arg(args, "second_derivative")
        #: The pre-pass to run over the reference image, or None. A plain dict
        #: rather than the UI object that describes it, so that it survives
        #: to_dict/from_dict unchanged -- from_dict rebuilds only the types it
        #: knows, and a restored run carrying a half-restored object would drop
        #: its pre-pass silently.
        self.intermediate_prompt = _arg(args, "intermediate_prompt")
        self.target_dir = _arg(args, "target_dir")

        with RunConfig._model_switch_lock:
            if RunConfig.previous_model_tags != self.model_tags:
                RunConfig.model_switch_detected = True
            RunConfig.previous_model_tags = self.model_tags

    def to_dict(self) -> dict:
        """Serialize the run for cross-session persistence.

        Walks the instance rather than a fixed field list: both run paths set
        further attributes after construction (the tag and strength fields, and
        run_origin), from two different places, so a list here would drift
        out of step with them. A field that cannot be converted is left as-is
        and surfaces at the json encode naming its type, rather than being
        silently dropped.
        """
        _dict = {}
        for key, value in self.__dict__.items():
            if key in RunConfig.TRANSIENT_FIELDS:
                continue
            if isinstance(value, Enum):
                _dict[key] = value.name
            elif hasattr(value, "to_dict"):
                _dict[key] = value.to_dict()
            else:
                _dict[key] = value
        return _dict

    @classmethod
    def from_dict(cls, _dict: dict) -> "RunConfig":
        """Rebuild a run from to_dict() output, inverting its conversions.

        Raises ValueError if the dict is not in RunConfig's own vocabulary, so
        a stored entry in some other shape is reported rather than restored as
        a run with silently empty fields.
        """
        from sd_runner.prompter_configuration import PrompterConfiguration

        data = deepcopy(_dict) if _dict else {}
        if "workflow_tag" not in data:
            raise ValueError("not a RunConfig dict (no workflow_tag)")
        if data.get("sampler") is not None:
            data["sampler"] = Sampler.get(data["sampler"])
        if data.get("scheduler") is not None:
            data["scheduler"] = Scheduler.get(data["scheduler"])
        if isinstance(data.get("prompter_config"), dict):
            prompter_config = PrompterConfiguration()
            prompter_config.set_from_dict(data["prompter_config"])
            data["prompter_config"] = prompter_config

        run_config = cls(args=data)
        # Restore the attributes set after construction by whichever path built
        # the original run; __init__ does not read them.
        for key, value in data.items():
            if not hasattr(run_config, key):
                setattr(run_config, key, value)
        return run_config

    def validate(self) -> bool:
        if self.prompter_config is None:
            raise Exception(_("No prompter config found!"))

        # Check here if for example, using FIXED prompt mode and > 6 set total
        if self.prompter_config.prompt_mode == PromptMode.FIXED and self.total > 10:
            raise Exception(_("Ensure configuration is correct - do you really want to create more than 10 images using the same prompt?"))

        # Validate prompt massage tags
        prompt_massage_tags, models = Model.get_first_model_prompt_massage_tags(self.model_tags, prompt_mode=self.prompter_config.prompt_mode, inpainting=self.inpainting)
        # get_models() skips a tag it cannot resolve rather than raising, so an
        # unresolvable tag arrives here as an empty list. Everything below reads
        # models[0] for the default lora and the architecture.
        if not models:
            raise NoModelsFound(_("No models found matching '{0}'").format(self.model_tags))
        should_warn = False
        with RunConfig._model_switch_lock:
            if (RunConfig.model_switch_detected
                    and not RunConfig.has_warned_about_prompt_massage_text_mismatch
                    and Globals.POSITIVE_PROMPT_MASSAGE_TAGS != prompt_massage_tags):
                RunConfig.has_warned_about_prompt_massage_text_mismatch = True
                should_warn = True
        if should_warn:
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
        images = total_jobs * self.total * self.n_latents
        total_time = (TimeEstimator.estimate_run_seconds(gen_config, images) if gen_config
                      else TimeEstimator.estimate_queue_time(images))
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
            WorkflowType.IMG2IMG,
            WorkflowType.IMAGE_EDIT,
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
