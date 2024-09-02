import argparse
from copy import deepcopy
import time
import traceback

from utils.globals import Globals # must import first
from sd_runner.concepts import PromptMode
from sd_runner.comfy_gen import ComfyGen
from sd_runner.control_nets import get_control_nets, redo_files
from sd_runner.gen_config import GenConfig
from sd_runner.ip_adapters import get_ip_adapters
from sd_runner.prompter import PrompterConfiguration, Prompter
from sd_runner.models import Model, Resolution
from sd_runner.sdwebui_gen import SDWebuiGen
from sd_runner.workflow_prompt import WorkflowPrompt
from utils.translations import I18N
from utils.utils import split

_ = I18N._

prompt_list = [
]


class Run:
    def __init__(self, args, progress_callback=None):
        self.id = str(time.time())
        self.is_complete = False
        self.is_cancelled = False
        self.args = args
        self.prompter_config = args.prompter_config
        self.editing = False
        self.switching_params = False
        self.last_config = None
        self.progress_callback = progress_callback

    def is_infinite(self):
        return self.args.total == -1

    def run(self, config, gen, original_positive, original_negative):
        prompter = Globals.PROMPTER
        if not self.editing and not self.switching_params:
            config.positive, config.negative = prompter.generate_prompt(original_positive, original_negative)

        print(config)
        if config.is_redo_prompt():
            confirm_text = "\n\nRedo Prompt (y/n/[space to quit]): "
        else:
            confirm_text = f"\n\nPrompt: \"{config.positive}\" (y/n/r/m/n/e/s/[space to quit]): "
        confirm = "y" if Globals.SKIP_CONFIRMATIONS else input(confirm_text)
        self.switching_params = False

        if confirm.lower() == " ": # go to next workflow / redo file
            return None
        elif confirm.lower() == "r":
            new_resolution = input("New resolution (p = portrait/l = landscape/s = square): ")
            if new_resolution.lower() == "p":
                config.resolutions[0].portrait(config.is_xl())
            if new_resolution.lower() == "l":
                config.resolutions[0].landscape(config.is_xl())
            if new_resolution.lower() == "s":
                config.resolutions[0].square(config.is_xl())
            self.switching_params = True
        elif confirm.lower() == "m":
            new_input_mode = input("New input mode (FIXED/SFW/NSFW/NSFL): ")
            prompter.set_prompt_mode(PromptMode[new_input_mode])
            self.switching_params = True
        elif confirm.lower() == "e":
            new_prompt = input("Prompt: ")
            self.editing = True
            config.positive = new_prompt
        elif confirm.lower() == "s":
            new_seed = int(input(f"Enter a new seed (current seed {config.seed}): "))
            config.seed = new_seed
            self.switching_params = True
        elif confirm.lower() != "y":
            return

        if self.last_config and config == self.last_config:
            print("\n\nConfig matches last config. Please modify it or quit.")
            if Globals.SKIP_CONFIRMATIONS:
                raise Exception("Invalid state - must select an auto-modifiable config option if using auto run.")
            else:
                return

        if config.prompts_match(self.last_config) or config.validate():
            gen.run()

        if config.maximum_gens() > 10:
            print(f"Large config with maximum gens {config.maximum_gens()} - skipping loop.")
            exit()

        self.last_config = deepcopy(gen.gen_config)


    def do_workflow(self, workflow, positive_prompt, negative_prompt, control_nets, ip_adapters):
        models = Model.get_models(self.args.model_tags,
                                  default_tag=Model.get_default_model_tag(workflow),
                                  inpainting=self.args.inpainting)
        loras = Model.get_models(self.args.lora_tags, is_lora=True,
                                 default_tag=models[0].get_default_lora(),
                                 inpainting=self.args.inpainting, is_xl=(2 if models[0].is_sd_15() else 1))
        resolutions = Resolution.get_resolutions(self.args.res_tags, is_xl=models[0].is_xl)
        config = GenConfig(
            workflow_id=workflow, models=models, loras=loras, n_latents=self.args.n_latents,
            control_nets=control_nets, ip_adapters=ip_adapters,
            positive=positive_prompt, negative=negative_prompt, resolutions=resolutions,
            run_config=self.args,
        )
        gen = ComfyGen(config) if self.args.software_type == "ComfyUI" else SDWebuiGen(config)
        self.editing = False
        self.switching_params = False
        self.last_config = None
        count = 0

        try:
            while not self.is_cancelled:
                self.run(config, gen, positive_prompt, negative_prompt)
                if self.last_config is None:
                    return
                count += 1
                if self.args.total:
                    if self.args.total > -1 and count == self.args.total:
                        print(f"Reached maximum requested iterations: {self.args.total}")
                        if self.progress_callback is not None:
                            self.progress_callback(count, self.args.total)
                        return
                    else:
                        if self.args.total == -1:
                            print("Running until cancelled or total iterations reached")
                        else:
                            print(f"On iteration {count} of {self.args.total} - continuing.")
                        if self.progress_callback is not None:
                            self.progress_callback(count, self.args.total)
                if self.args.auto_run:
                    # TODO websocket would be better here to ensure all have finished before starting new gen
                    sleep_time = config.maximum_gens()
                    sleep_time *= Globals.GENERATION_DELAY_TIME_SECONDS
                    print(f"Sleeping for {sleep_time} seconds.")
                    while sleep_time > 0 and not self.is_cancelled:
                        sleep_time -= 1
                        time.sleep(1)
        except KeyboardInterrupt:
            pass


    def load_and_run(self, control_nets):
        ip_adapters = get_ip_adapters(self.args.ip_adapters.split(",") if self.args.ip_adapters and self.args.ip_adapters != "" else None)
        positive_prompt = self.args.positive_prompt if self.args.positive_prompt else Globals.DEFAULT_POSITIVE_PROMPT
        base_negative = "" if Globals.OVERRIDE_BASE_NEGATIVE else str(Globals.DEFAULT_NEGATIVE_PROMPT)
        negative_prompt = self.args.negative_prompt if self.args.negative_prompt else base_negative
        Globals.set_prompter(Prompter(prompter_config=self.prompter_config, get_specific_locations=Globals.PROMPTER_GET_SPECIFIC_LOCATIONS, prompt_list=prompt_list))

        if self.args.auto_run:
            print("Auto-run mode set.")

        print("Running prompt mode: " + str(self.args.prompter_config.prompt_mode))

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

    def execute(self):
        self.is_complete = False
        self.is_cancelled = False
        Model.load_all()
        Model.set_lora_strength(Globals.DEFAULT_LORA_STRENGTH)
        prompter_config = PrompterConfiguration(prompt_mode=PromptMode.FIXED) if self.args.prompter_override else self.args.prompter_config
        Model.set_model_presets(prompter_config.prompt_mode)
        Globals.SKIP_CONFIRMATIONS = self.args.auto_run
        control_nets, is_dir = get_control_nets(split(self.args.control_nets, ",") if self.args.control_nets and self.args.control_nets != "" else None)
        if is_dir:
            for i in range(len(control_nets)):
                if self.is_cancelled:
                    break
                control_net = control_nets[i]
                print(f"Running control net {i} - {control_net}")
                self.load_and_run([control_net])
        else:
            self.load_and_run(control_nets)
        self.is_complete = True

    def cancel(self):
        print("Canceling...")
        self.is_cancelled = True
        # TODO send cancel/delete call to ComfyUI for all previously started prompts

def main(args):
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
