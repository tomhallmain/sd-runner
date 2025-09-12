import argparse
from copy import deepcopy
import time
import traceback
from typing import Optional

from utils.globals import Globals, PromptMode, ResolutionGroup, WorkflowType # must import first
from sd_runner.comfy_gen import ComfyGen
from sd_runner.control_nets import get_control_nets, redo_files, ControlNet
from sd_runner.gen_config import GenConfig, MultiGenProgressTracker
from sd_runner.ip_adapters import get_ip_adapters, IPAdapter
from sd_runner.prompter import PrompterConfiguration, GlobalPrompter
from sd_runner.models import Model
from sd_runner.resolution import Resolution
from sd_runner.run_config import RunConfig
from sd_runner.sdwebui_gen import SDWebuiGen
from sd_runner.workflow_prompt import WorkflowPrompt
from utils.config import config
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._

logger = get_logger("run")

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
        self.editing = False
        self.switching_params = False
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
        gen: ComfyGen | SDWebuiGen,
        original_positive: str,
        original_negative: str,
    ) -> None:
        gen_config = gen.gen_config
        prompter = GlobalPrompter.prompter_instance
        if not self.editing and not self.switching_params:
            gen_config.positive, gen_config.negative = prompter.generate_prompt(original_positive, original_negative)

        print(str(gen_config))
        if gen_config.is_redo_prompt():
            confirm_text = "\n\nRedo Prompt (y/n/[space to quit]): "
        else:
            confirm_text = f"\n\nPrompt: \"{gen_config.positive}\" (y/n/r/m/n/e/s/[space to quit]): "
        confirm = "y" if Globals.SKIP_CONFIRMATIONS else input(confirm_text)
        self.switching_params = False

        if confirm.lower() == " ": # go to next workflow / redo file
            return None
        elif confirm.lower() == "r":
            new_resolution = input("New resolution (p = portrait/l = landscape/s = square): ")
            if new_resolution.lower() == "p":
                config.resolutions[0].portrait(gen_config.architecture_type())
            if new_resolution.lower() == "l":
                config.resolutions[0].landscape(gen_config.architecture_type())
            if new_resolution.lower() == "s":
                config.resolutions[0].square(gen_config.architecture_type())
            self.switching_params = True
        elif confirm.lower() == "m":
            new_input_mode = input("New input mode (FIXED/SFW/NSFW/NSFL): ")
            prompter.set_prompt_mode(PromptMode[new_input_mode])
            self.switching_params = True
        elif confirm.lower() == "e":
            new_prompt = input("Prompt: ")
            self.editing = True
            gen_config.positive = new_prompt
        elif confirm.lower() == "s":
            new_seed = int(input(f"Enter a new seed (current seed {config.seed}): "))
            gen_config.seed = new_seed
            self.switching_params = True
        elif confirm.lower() != "y":
            return

        if self.last_config and gen_config == self.last_config:
            print("\n\nConfig matches last config. Please modify it or quit.")
            if Globals.SKIP_CONFIRMATIONS:
                raise Exception("Invalid state - must select an auto-modifiable config option if using auto run.")
            else:
                return

        if gen_config.prompts_match(self.last_config) or gen_config.validate():
            gen.run()

        if gen_config.maximum_gens() > 10:
            self.print(f"Large config with maximum gens {config.maximum_gens()} - skipping loop.")
            return

        self.last_config = deepcopy(gen.gen_config)

    def finalize_gen(
        self,
        gen: ComfyGen | SDWebuiGen,
        original_positive: str,
        original_negative: str,
    ) -> None:
        self.print("Filling expected number of generations due to skips.")
        gen.gen_config.set_countdown_mode()
        while gen.gen_config.countdown_value > 0:
            self.run(gen, original_positive, original_negative)
        gen.gen_config.reset_countdown_mode()

    def construct_gen(
        self,
        workflow: str | WorkflowType,
        positive_prompt: str,
        negative_prompt: str,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
    ) -> ComfyGen | SDWebuiGen:
        models = Model.get_models(self.args.model_tags,
                                  default_tag=Model.get_default_model_tag(workflow),
                                  inpainting=self.args.inpainting)
        loras = Model.get_models(self.args.lora_tags, is_lora=True,
                                 default_tag=models[0].get_default_lora(),
                                 inpainting=self.args.inpainting, is_xl=(2 if models[0].is_sd_15() else 1))
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
        if self.args.software_type == "ComfyUI":
            gen = ComfyGen(gen_config, self.ui_callbacks)
        elif self.args.software_type == "SDWebUI":
            gen = SDWebuiGen(gen_config, self.ui_callbacks)
        else:
            raise Exception(f"Unhandled software type: {self.args.software_type}")
        return gen

    def do_workflow(
        self,
        workflow: str | WorkflowType,
        positive_prompt: str,
        negative_prompt: str,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
    ) -> None:
        if self.is_cancelled:
            return
        gen = self.construct_gen(workflow, positive_prompt, negative_prompt, control_nets, ip_adapters)
        self.editing = False
        self.switching_params = False
        self.last_config = None
        count = 0

        try:
            while not self.is_cancelled:
                self.run(gen, positive_prompt, negative_prompt)
                if not gen.has_run_one_workflow:
                    continue
                # If some of the prompts are skipped, need to fill the gaps if we are not running infinitely
                if self.args.total > -1 and gen.gen_config is not None and gen.gen_config.has_skipped():
                    self.finalize_gen(gen, positive_prompt, negative_prompt)
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
                            self._sleep_for_delay(maximum_gens=gen.gen_config.maximum_gens() / 2) # NOTE halving the delay here
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
                self._sleep_for_delay(maximum_gens=gen.gen_config.maximum_gens())
        except KeyboardInterrupt:
            pass

    def _sleep_for_delay(self, maximum_gens: int = 1) -> None:
        if self.args.auto_run:
            # TODO websocket would be better here to ensure all have finished before starting new gen
            sleep_time = maximum_gens
            sleep_time *= Globals.GENERATION_DELAY_TIME_SECONDS
            self.print(f"Sleeping for {sleep_time} seconds.")
            while sleep_time > 0 and not self.is_cancelled:
                sleep_time -= 1
                time.sleep(1)

    def load_and_run(
        self,
        control_nets: list[ControlNet],
        ip_adapters: list[IPAdapter],
    ) -> None:
        if self.is_cancelled:
            return
        positive_prompt = self.args.positive_prompt if self.args.positive_prompt else Globals.DEFAULT_POSITIVE_PROMPT
        base_negative = "" if Globals.OVERRIDE_BASE_NEGATIVE else str(Globals.DEFAULT_NEGATIVE_PROMPT)
        negative_prompt = self.args.negative_prompt if self.args.negative_prompt else base_negative
        GlobalPrompter.set_prompter(self.prompter_config, Globals.PROMPTER_GET_SPECIFIC_LOCATIONS, prompt_list)

        if self.args.auto_run:
            self.print("Auto-run mode set.")

        self.print("Running prompt mode: " + str(self.args.prompter_config.prompt_mode))

        workflow_tags = self.args.redo_files.split(",") if self.args.redo_files else self.args.workflow_tag.split(",")
        for workflow_tag in workflow_tags:
            if self.is_cancelled:
                break
            workflow = WorkflowPrompt.setup_workflow(workflow_tag, control_nets, ip_adapters)
            try:
                self.do_workflow(workflow, positive_prompt, negative_prompt, control_nets, ip_adapters)
            except Exception as e:
                print(e)
                traceback.print_exc()

    def execute(self) -> None:
        logger.info("Executing run submitted by user at " + time.strftime("%Y-%m-%d %H:%M:%S", self.args.start_time))
        self.is_complete = False
        self.is_cancelled = False
        Model.load_all()
        Model.set_lora_strength(Globals.DEFAULT_LORA_STRENGTH)
        prompter_config = PrompterConfiguration(prompt_mode=PromptMode.FIXED) if self.args.prompter_override else self.args.prompter_config
        Model.set_model_presets(prompter_config.prompt_mode)
        Globals.SKIP_CONFIRMATIONS = self.args.auto_run

        control_nets, is_dir_controlnet = get_control_nets(Utils.split(self.args.control_nets, ",") if self.args.control_nets and self.args.control_nets != "" else None)
        ip_adapters, is_dir_ipadapter = get_ip_adapters(Utils.split(self.args.ip_adapters, ",") if self.args.ip_adapters and self.args.ip_adapters != "" else None)

        total_adapter_iterations = 1
        if is_dir_controlnet or is_dir_ipadapter:
            self.delay_after_last_run = True
            if self.args.total < 1:
                raise Exception("Infinite run not possible on directories")
            
            # Create progress tracker for directory processing
            if is_dir_controlnet:
                total_adapter_iterations *= len([c for c in control_nets if c.is_valid()])
            if is_dir_ipadapter:
                total_adapter_iterations *= len([i for i in ip_adapters if i.is_valid()])            

        self.progress_tracker = MultiGenProgressTracker(
            total_adapter_iterations=total_adapter_iterations,
            total_per_adapter=self.args.total,
            ui_callbacks=self.ui_callbacks,
            batch_limit=self.args.batch_limit
        )

        if is_dir_ipadapter and is_dir_controlnet:
            for i in range(len(control_nets)):
                if self.is_cancelled or not self.progress_tracker.should_continue():
                    if not self.progress_tracker.should_continue():
                        self.print(f"Batch limit reached: {self.progress_tracker.current_adapter_iteration}/{self.progress_tracker.batch_limit}")
                    break
                control_net = control_nets[i]
                if not control_net.is_valid():
                    continue
                for j in range(len(ip_adapters)):
                    if self.is_cancelled or not self.progress_tracker.should_continue():
                        if not self.progress_tracker.should_continue():
                            self.print(f"Batch limit reached: {self.progress_tracker.current_adapter_iteration}/{self.progress_tracker.batch_limit}")
                        break
                    ip_adapter = ip_adapters[j]
                    if not ip_adapter.is_valid():
                        continue
                    self.print(f"Running control net {i} - {control_net}")
                    self.print(f"Running ip adapter {j} - {ip_adapter}")
                    self.load_and_run([control_net], [ip_adapter])
                    self.progress_tracker.next_adapter()
        elif is_dir_controlnet:
            for i in range(len(control_nets)):
                if self.is_cancelled or not self.progress_tracker.should_continue():
                    if not self.progress_tracker.should_continue():
                        self.print(f"Batch limit reached: {self.progress_tracker.current_adapter_iteration}/{self.progress_tracker.batch_limit}")
                    break
                control_net = control_nets[i]
                if not control_net.is_valid():
                    continue
                self.print(f"Running control net {i} - {control_net}")
                self.load_and_run([control_net], ip_adapters)
                self.progress_tracker.next_adapter()
        elif is_dir_ipadapter:
            for i in range(len(ip_adapters)):
                if self.is_cancelled or not self.progress_tracker.should_continue():
                    if not self.progress_tracker.should_continue():
                        self.print(f"Batch limit reached: {self.progress_tracker.current_adapter_iteration}/{self.progress_tracker.batch_limit}")
                    break
                ip_adapter = ip_adapters[i]
                if not ip_adapter.is_valid():
                    continue
                self.print(f"Running ip adapter {i} - {ip_adapter}")
                self.load_and_run(control_nets, [ip_adapter])
                self.progress_tracker.next_adapter()
        else:
            self.load_and_run(control_nets, ip_adapters)

        self.is_complete = True

    def cancel(self, reason: Optional[str] = None) -> None:
        cancel_message = "Canceling..."
        if reason is not None:
            cancel_message += f" {reason}"
        self.print(cancel_message)
        self.is_cancelled = True
        # TODO send cancel/delete call to ComfyUI for all previously started prompts

def main(args: RunConfig) -> None:
    run = Run(args)
    run.execute()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-w", "--workflow-tag", type=str, default=Globals.DEFAULT_WORKFLOW)
    parser.add_argument("-r", "--res-tags", type=str, default=None)
    parser.add_argument("-m", "--model_tags", type=str, default=Globals.DEFAULT_MODEL)
    parser.add_argument("-l", "--lora_tags", type=str, default=None)
    parser.add_argument("-i", "--inpainting", type=bool, default=False)
    parser.add_argument("-n", "--n-latents", type=int, default=Globals.DEFAULT_N_LATENTS)
    parser.add_argument("-s", "--seed", type=int, default=-1)
    parser.add_argument("-u", "--steps", type=int, default=None)
    parser.add_argument("-g", "--cfg", type=int, default=None)
    parser.add_argument("-y", "--sampler-name", type=str, default=None)
    parser.add_argument("-e", "--scheduler", type=str, default=None)
    parser.add_argument("-d", "--denoise", type=float, default=None)
    parser.add_argument("-o", "--prompter-override", action="store_true")
    parser.add_argument("-f", "--redo-files", type=str, default=None)
    parser.add_argument("-p", "--prompt-mode", type=PromptMode, choices=list(PromptMode), default=PromptMode.FIXED)
    parser.add_argument("-c", "--control-nets", type=str, default=None)
    parser.add_argument("-k", "--ip-adapters", type=str, default=None)
    parser.add_argument("-0", "--positive-prompt", type=str, default=None)
    parser.add_argument("-1", "--negative-prompt", type=str, default=None)
    parser.add_argument("-a", "--auto-run", action="store_true")
    parser.add_argument("-t", "--total", type=int, default=100)
    args = parser.parse_args()
    main(RunConfig(args))
