import datetime
from copy import deepcopy
import time
import traceback
from typing import Optional

from utils.globals import Globals, PromptMode, ResolutionGroup, WorkflowType, ArchitectureType, SoftwareType # must import first
from sd_runner.generators.base import BaseImageGenerator
from sd_runner.generators.comfy import ComfyGen
from sd_runner.models.control_nets import get_control_nets, redo_files, ControlNet
from sd_runner.runs.gen_config import GenConfig, MultiGenProgressTracker
from sd_runner.models.ip_adapters import get_ip_adapters, IPAdapter
from sd_runner.prompts.prompter_configuration import PrompterConfiguration
from sd_runner.prompts.prompter import GlobalPrompter, Prompter
from sd_runner.models.source_prompts import SourcePrompt, get_source_prompts
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from sd_runner.runs.run_config import RunConfig
from sd_runner.generators.sdwebui import SDWebuiGen
from sd_runner.presets.timed_schedules_manager import timed_schedules_manager, ScheduledShutdownException
from sd_runner.workflow_prompts.base import WorkflowPrompt
from utils.config import config
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._

logger = get_logger("runs.run")

prompt_list = [
]


class Run:
    def __init__(
        self,
        args: RunConfig,
        ui_callbacks = None,
        delay_after_last_run: bool = True,
    ):
        self.id = str(time.time())
        self.is_complete = False
        self.is_cancelled = False
        self.delay_after_last_run = delay_after_last_run
        self.args = args
        self.prompter_config = args.prompter_config
        self.last_config = None
        self.ui_callbacks = ui_callbacks
        self.progress_tracker = None  # Will be set upon execution

    def print(self, *args):
        if config.debug:
            print(*args)

    def is_infinite(self):
        return self.args.total == -1

    def run(
        self,
        gen: BaseImageGenerator,
        original_positive: str,
        original_negative: str,
        prompt_image_path: str = "",
    ) -> None:
        gen_config = gen.gen_config
        gen_config.prompt_image_path = prompt_image_path or ""
        prompter = GlobalPrompter.prompter_instance
        gen_config.positive, gen_config.negative = prompter.generate_prompt(
            original_positive,
            original_negative,
            related_image_path=prompt_image_path,
        )

        self.print(str(gen_config))

        # An identical config would regenerate the same image. Nothing can vary
        # it from here, so this is a caller error rather than something to retry.
        if self.last_config and gen_config == self.last_config:
            raise Exception(
                "Invalid state - config matches the last one, so the run cannot vary."
            )

        if gen_config.prompts_match(self.last_config) or gen_config.validate():
            gen.run()

        if gen_config.maximum_gens() > 10:
            self.print(f"Large config with maximum gens {config.maximum_gens()} - skipping loop.")
            return

        self.last_config = deepcopy(gen.gen_config)

    def finalize_gen(
        self,
        gen: BaseImageGenerator,
        original_positive: str,
        original_negative: str,
        prompt_image_path: str = "",
    ) -> None:
        self.print("Filling expected number of generations due to skips.")
        gen.gen_config.set_countdown_mode()
        while gen.gen_config.countdown_value > 0:
            self.run(gen, original_positive, original_negative, prompt_image_path=prompt_image_path)
        gen.gen_config.reset_countdown_mode()

    def construct_gen(
        self,
        workflow: str | WorkflowType,
        positive_prompt: str,
        negative_prompt: str,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
    ) -> ComfyGen | SDWebuiGen:
        if SoftwareType[self.args.software_type].is_cloud():
            return self._construct_cloud_gen(workflow, positive_prompt, negative_prompt)

        models = Model.get_models(self.args.model_tags,
                                  default_tag=Model.get_default_model_tag(workflow),
                                  inpainting=self.args.inpainting)
        loras = Model.get_models(self.args.lora_tags, is_lora=True,
                                 default_tag=models[0].get_default_lora(),
                                 inpainting=self.args.inpainting,
                                 architecture_type=models[0].architecture_type)
        resolution_group = ResolutionGroup.get(self.args.resolution_group)
        resolutions = Resolution.get_resolutions(self.args.res_tags,
                                                 architecture_type=models[0].architecture_type,
                                                 resolution_group=resolution_group)
        gen_config = GenConfig(
            workflow_id=workflow, models=models, loras=loras, n_latents=self.args.n_latents,
            control_nets=control_nets, ip_adapters=ip_adapters,
            positive=positive_prompt, negative=negative_prompt, resolutions=resolutions,
            run_config=self.args,
        )
        sw = SoftwareType[self.args.software_type]
        if sw == SoftwareType.ComfyUI:
            gen = ComfyGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.SDWebUI:
            gen = SDWebuiGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.Forge:
            from sd_runner.generators.forge import ForgeGen
            gen = ForgeGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.SDNext:
            from sd_runner.generators.sdnext import SDNextGen
            gen = SDNextGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.SwarmUI:
            from sd_runner.generators.swarmui import SwarmUIGen
            gen = SwarmUIGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.InvokeAI:
            from sd_runner.generators.invokeai import InvokeAIGen
            gen = InvokeAIGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.Fooocus:
            from sd_runner.generators.fooocus import FooocusGen
            gen = FooocusGen(gen_config, self.ui_callbacks)
        else:
            raise Exception(f"Unhandled software type: {self.args.software_type}")
        return gen

    def _construct_cloud_gen(
        self,
        workflow: str | WorkflowType,
        positive_prompt: str,
        negative_prompt: str,
    ):
        model_tag = (self.args.model_tags or "").split(",")[0].strip()
        model = Model(id=model_tag) if model_tag else Model(id="default")
        resolution_group = ResolutionGroup.get(self.args.resolution_group)
        resolutions = Resolution.get_resolutions(
            self.args.res_tags,
            architecture_type=ArchitectureType.UNKNOWN,
            resolution_group=resolution_group,
        )
        gen_config = GenConfig(
            workflow_id=workflow,
            models=[model],
            n_latents=self.args.n_latents,
            positive=positive_prompt,
            negative=negative_prompt,
            resolutions=resolutions,
            run_config=self.args,
        )
        sw = SoftwareType[self.args.software_type]
        if sw == SoftwareType.StabilityAI:
            from sd_runner.generators.stability_ai import StabilityAIGen
            return StabilityAIGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.BFLFlux:
            from sd_runner.generators.bfl import BFLGen
            return BFLGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.FalAI:
            from sd_runner.generators.fal_ai import FalAIGen
            return FalAIGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.HuggingFace:
            from sd_runner.generators.huggingface import HuggingFaceGen
            return HuggingFaceGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.Replicate:
            from sd_runner.generators.replicate import ReplicateGen
            return ReplicateGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.OpenAI:
            from sd_runner.generators.openai_gen import OpenAIGen
            return OpenAIGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.Grok:
            from sd_runner.generators.grok import GrokGen
            return GrokGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.GoogleImagen:
            from sd_runner.generators.google_imagen import GoogleImagenGen
            return GoogleImagenGen(gen_config, self.ui_callbacks)
        elif sw == SoftwareType.Ideogram:
            from sd_runner.generators.ideogram import IdeogramGen
            return IdeogramGen(gen_config, self.ui_callbacks)
        else:
            raise Exception(f"Unknown cloud software type: {sw}")

    def do_workflow(
        self,
        workflow: str | WorkflowType,
        positive_prompt: str,
        negative_prompt: str,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
        prompt_image_path: str = "",
    ) -> None:  # gen type is BaseImageGenerator; local variable only
        if self.is_cancelled:
            return
        gen = self.construct_gen(workflow, positive_prompt, negative_prompt, control_nets, ip_adapters)
        self.last_config = None
        count = 0

        try:
            while not self.is_cancelled:
                self.run(gen, positive_prompt, negative_prompt, prompt_image_path=prompt_image_path)
                if not gen.has_run_one_workflow:
                    continue
                # If some of the prompts are skipped, need to fill the gaps if we are not running infinitely
                if self.args.total > -1 and gen.gen_config is not None and gen.gen_config.has_skipped():
                    self.finalize_gen(gen, positive_prompt, negative_prompt, prompt_image_path=prompt_image_path)
                if self.last_config is None:
                    return
                count += 1
                if self.args.total:
                    if self.args.total > -1 and count == self.args.total:
                        self.print(f"Reached maximum requested iterations: {self.args.total}")
                        if self.progress_tracker:
                            self.progress_tracker.update_progress(count, self.args.total, workflow, gen.gen_config)
                        elif self.ui_callbacks is not None:
                            self.ui_callbacks.update_progress(count, self.args.total, batch_limit=self.args.batch_limit)
                            remaining = self.args.total - count + 1 if self.args.total > 0 else 0
                            self.ui_callbacks.update_time_estimation(workflow, gen.gen_config, remaining)
                        if self.delay_after_last_run:
                            # print(Utils.format_red("WILL SLEEP AFTER LAST RUN."))
                            self._sleep_for_delay(maximum_gens=gen.gen_config.maximum_gens() / 2, gen=gen) # NOTE halving the delay here
                        return
                    else:
                        if self.args.total == -1:
                            self.print("Running until cancelled or total iterations reached")
                        else:
                            self.print(f"On iteration {count} of {self.args.total} - continuing.")
                        if self.progress_tracker:
                            self.progress_tracker.update_progress(count, self.args.total, workflow, gen.gen_config)
                        elif self.ui_callbacks is not None:
                            self.ui_callbacks.update_progress(count, self.args.total, batch_limit=self.args.batch_limit)
                            remaining = self.args.total - count + 1 if self.args.total > 0 else 0
                            self.ui_callbacks.update_time_estimation(workflow, gen.gen_config, remaining)
                self._sleep_for_delay(maximum_gens=gen.gen_config.maximum_gens(), gen=gen)
        except KeyboardInterrupt:
            pass

    def _sleep_for_delay(self, maximum_gens: int = 1, gen=None) -> None:
        """Hold the loop between iterations until the backend is idle again.

        The computed delay is a ceiling rather than a fixed cost. Given a live
        count of in-flight generations the loop can continue as soon as the
        work it dispatched has finished, instead of always waiting an interval
        guessed from the image count -- which over-sleeps on fast models and
        under-sleeps on slow ones.

        The ceiling stays: a backend that dies without releasing its count
        would otherwise stall the loop for good. Without *gen* there is nothing
        to observe, so the full interval is waited as before.
        """
        if not self.args.auto_run:
            return
        ceiling = maximum_gens * Globals.GENERATION_DELAY_TIME_SECONDS
        if gen is None:
            self.print(f"Sleeping for {ceiling} seconds.")
        else:
            self.print(f"Waiting up to {ceiling} seconds for generations to finish.")
        waited = 0
        while waited < ceiling and not self.is_cancelled:
            time.sleep(1)
            waited += 1
            if (gen is not None
                    and waited >= Globals.MINIMUM_PACING_SECONDS
                    and gen.pending_counter <= 0):
                self.print(f"Generations finished after {waited}s; continuing.")
                return

    def load_and_run(
        self,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
        source_prompt: SourcePrompt | None = None,
    ) -> None:
        if self.is_cancelled:
            return
        positive_prompt = self.args.positive_prompt if self.args.positive_prompt else Globals.DEFAULT_POSITIVE_PROMPT
        base_negative = "" if Globals.OVERRIDE_BASE_NEGATIVE else str(Globals.DEFAULT_NEGATIVE_PROMPT)
        negative_prompt = self.args.negative_prompt if self.args.negative_prompt else base_negative
        prompt_image_path = ""
        prompter_config = self.prompter_config
        restore_user_tags = False
        prior_positive_tags = ""
        prior_negative_tags = ""
        prior_tags_apply_to_start = Prompter.TAGS_APPLY_TO_START
        if source_prompt is not None:
            prompt_image_path = source_prompt.image_path
            add_user_prompt = bool(getattr(self.args, "source_prompts_add_user_prompt", False))
            # Source-prompt runs should be generated by TAKE mode.
            prompter_config = deepcopy(self.prompter_config)
            prompter_config.prompt_mode = PromptMode.TAKE
            if not add_user_prompt:
                restore_user_tags = True
                prior_positive_tags = Prompter.POSITIVE_TAGS
                prior_negative_tags = Prompter.NEGATIVE_TAGS
                Prompter.set_positive_tags("")
                Prompter.set_negative_tags("")
                positive_prompt = ""
                negative_prompt = ""

        try:
            GlobalPrompter.set_prompter(prompter_config, Globals.PROMPTER_GET_SPECIFIC_LOCATIONS, Globals.PROMPTER_GET_SPECIFIC_TIMES, prompt_list)

            if self.args.auto_run:
                self.print("Auto-run mode set.")

            self.print("Running prompt mode: " + str(prompter_config.prompt_mode))

            workflow_tags = self.args.redo_files.split(",") if self.args.redo_files else self.args.workflow_tag.split(",")
            for workflow_tag in workflow_tags:
                if self.is_cancelled:
                    break
                workflow = WorkflowPrompt.setup_workflow(workflow_tag, control_nets, ip_adapters)
                try:
                    self.do_workflow(
                        workflow,
                        positive_prompt,
                        negative_prompt,
                        control_nets,
                        ip_adapters,
                        prompt_image_path=prompt_image_path,
                    )
                except Exception as e:
                    from sd_runner.image_converter import ImageHandlingError
                    if not isinstance(e, ImageHandlingError):
                        print(e)
                        traceback.print_exc()
        finally:
            if restore_user_tags:
                Prompter.set_positive_tags(prior_positive_tags)
                Prompter.set_negative_tags(prior_negative_tags)
                Prompter.set_tags_apply_to_start(prior_tags_apply_to_start)

    @staticmethod
    def _group_for_iteration(items: list, should_iterate: bool, is_valid, skip_validation: bool = False) -> list[list]:
        """Group adapters into the units a single generation consumes.

        *skip_validation* is for directory mode: those paths came from a glob, so
        existence is already guaranteed, and running is_valid() over them would
        construct every adapter object up front -- defeating the lazy list. Each
        group is then built by index, so only the adapters actually reached get
        constructed. Manually entered paths keep the filter, since those may not
        exist.
        """
        if skip_validation:
            if should_iterate:
                return [[items[i]] for i in range(len(items))]
            return [items]
        valid_items = [item for item in items if is_valid(item)]
        if should_iterate:
            return [[item] for item in valid_items]
        return [valid_items]

    @staticmethod
    def _source_prompt_group(source_prompts: list[SourcePrompt], should_iterate: bool) -> list[SourcePrompt | None]:
        valid_prompts = [sp for sp in source_prompts if sp.has_valid_path()]
        if should_iterate:
            return valid_prompts
        if len(valid_prompts) > 1:
            logger.warning("Multiple source prompt files provided without directory mode; using the first file only.")
        return [valid_prompts[0]] if len(valid_prompts) > 0 else [None]

    def _iter_generation_combinations(
        self,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
        source_prompts: list[SourcePrompt],
        iterate_control_nets: bool,
        iterate_ip_adapters: bool,
        iterate_source_prompts: bool,
    ):
        control_groups = self._group_for_iteration(
            control_nets, iterate_control_nets, lambda c: c.is_valid(),
            skip_validation=iterate_control_nets,
        )
        ip_groups = self._group_for_iteration(
            ip_adapters, iterate_ip_adapters, lambda i: i.is_valid(),
            skip_validation=iterate_ip_adapters,
        )
        source_groups = self._source_prompt_group(source_prompts, iterate_source_prompts)
        for control_group in control_groups:
            for ip_group in ip_groups:
                for source_prompt in source_groups:
                    yield control_group, ip_group, source_prompt

    def execute(self) -> None:
        logger.info("Executing run submitted by user at " + time.strftime("%Y-%m-%d %H:%M:%S", self.args.start_time))
        
        # Check for scheduled shutdown before starting execution
        try:
            timed_schedules_manager.check_for_shutdown_request(datetime.datetime.now())
        except ScheduledShutdownException as e:
            logger.error(f"Scheduled shutdown requested: {e}")
            raise e
        
        self.is_complete = False
        self.is_cancelled = False
        Model.load_all()
        Model.set_lora_strength(Globals.DEFAULT_LORA_STRENGTH)
        prompter_config = PrompterConfiguration(prompt_mode=PromptMode.FIXED) if self.args.prompter_override else self.args.prompter_config
        Model.set_model_presets(prompter_config.prompt_mode)
        Globals.SKIP_CONFIRMATIONS = self.args.auto_run

        control_nets, is_dir_controlnet = get_control_nets(Utils.split(self.args.control_nets, ",") if self.args.control_nets and self.args.control_nets != "" else None, app_actions=self.ui_callbacks)
        ip_adapters, is_dir_ipadapter = get_ip_adapters(Utils.split(self.args.ip_adapters, ",") if self.args.ip_adapters and self.args.ip_adapters != "" else None, app_actions=self.ui_callbacks)
        source_prompt_files = Utils.split(self.args.source_prompts, ",") if self.args.source_prompts and self.args.source_prompts != "" else None
        source_prompts, is_dir_source_prompt = get_source_prompts(source_prompt_files, app_actions=self.ui_callbacks)

        iterate_source_prompts = is_dir_source_prompt or (source_prompt_files is not None and len(source_prompt_files) > 1)
        iterate_any_dimension = is_dir_controlnet or is_dir_ipadapter or iterate_source_prompts

        total_adapter_iterations = 1
        if iterate_any_dimension:
            self.delay_after_last_run = True
            if self.args.total < 1:
                raise Exception("Infinite run not possible when iterating adapter/prompt source files")
            
            # Create progress tracker for directory processing.
            # Directory paths come from glob so existence is guaranteed -- filtering
            # on is_valid() here would construct every adapter object just to count
            # them, which is what the lazy list exists to avoid.
            if is_dir_controlnet:
                total_adapter_iterations *= len(control_nets)
            if is_dir_ipadapter:
                total_adapter_iterations *= len(ip_adapters)
            if iterate_source_prompts:
                source_count = len([sp for sp in source_prompts if sp.has_valid_path()])
                total_adapter_iterations *= source_count

        self.progress_tracker = MultiGenProgressTracker(
            total_adapter_iterations=total_adapter_iterations,
            total_per_adapter=self.args.total,
            ui_callbacks=self.ui_callbacks,
            batch_limit=self.args.batch_limit
        )

        for control_group, ip_group, source_prompt in self._iter_generation_combinations(
            control_nets=control_nets,
            ip_adapters=ip_adapters,
            source_prompts=source_prompts,
            iterate_control_nets=is_dir_controlnet,
            iterate_ip_adapters=is_dir_ipadapter,
            iterate_source_prompts=iterate_source_prompts,
        ):
            if self.is_cancelled or not self.progress_tracker.should_continue():
                if not self.progress_tracker.should_continue():
                    self.print(
                        f"Batch limit reached: "
                        f"{self.progress_tracker.current_adapter_iteration}/{self.progress_tracker.batch_limit}"
                    )
                break

            if is_dir_controlnet and len(control_group) == 1:
                self.print(f"Running control net - {control_group[0]}")
            if is_dir_ipadapter and len(ip_group) == 1:
                self.print(f"Running ip adapter - {ip_group[0]}")
            if source_prompt is not None:
                self.print(f"Running source prompt from image - {source_prompt.image_path}")

            self.load_and_run(control_group, ip_group, source_prompt=source_prompt)
            if iterate_any_dimension:
                self.progress_tracker.next_adapter()

        self.is_complete = True

    def cancel(self, reason: Optional[str] = None) -> None:
        cancel_message = "Canceling..."
        if reason is not None:
            cancel_message += f" {reason}"
        self.print(cancel_message)
        self.is_cancelled = True
        # TODO send cancel/delete call to ComfyUI for all previously started prompts
