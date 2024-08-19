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
from sd_runner.workflow_prompt import WorkflowPrompt
from utils.translations import I18N
from utils.utils import split

_ = I18N._

prompt_list = [
]


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



def run(editing, switching_params, last_config, config, comfy_gen, original_positive, original_negative):
    prompter = Globals.PROMPTER
    if not editing and not switching_params:
        config.positive, config.negative = prompter.generate_prompt(original_positive, original_negative)

    print(config)
    if config.is_redo_prompt():
        confirm_text = "\n\nRedo Prompt (y/n/[space to quit]): "
    else:
        confirm_text = f"\n\nPrompt: \"{config.positive}\" (y/n/r/m/n/e/s/[space to quit]): "
    confirm = "y" if Globals.SKIP_CONFIRMATIONS else input(confirm_text)
    switching_params = False

    if confirm.lower() == " ": # go to next workflow / redo file
        return (editing, switching_params, None)
    elif confirm.lower() == "r":
        new_resolution = input("New resolution (p = portrait/l = landscape/s = square): ")
        if new_resolution.lower() == "p":
            config.resolutions[0].portrait(config.is_xl())
        if new_resolution.lower() == "l":
            config.resolutions[0].landscape(config.is_xl())
        if new_resolution.lower() == "s":
            config.resolutions[0].square(config.is_xl())
        switching_params = True
        return (editing, switching_params, last_config)
    elif confirm.lower() == "m":
        new_input_mode = input("New input mode (FIXED/SFW/NSFW/NSFL): ")
        prompter.set_prompt_mode(PromptMode[new_input_mode])
        switching_params = True
        return (editing, switching_params, last_config)
    elif confirm.lower() == "e":
        new_prompt = input("Prompt: ")
        editing = True
        config.positive = new_prompt
    elif confirm.lower() == "s":
        new_seed = int(input(f"Enter a new seed (current seed {config.seed}): "))
        config.seed = new_seed
        switching_params = True
        return (editing, switching_params, last_config)
    elif confirm.lower() != "y":
        return (editing, switching_params, last_config)

    if last_config and config == last_config:
        print("\n\nConfig matches last config. Please modify it or quit.")
        if Globals.SKIP_CONFIRMATIONS:
            raise Exception("Invalid state - must select an auto-modifiable config option if using auto run.")
        else:
            return (editing, switching_params, last_config)

    if config.prompts_match(last_config) or config.validate():
        comfy_gen.run()

    if config.maximum_gens() > 10:
        print(f"Large config with maximum gens {config.maximum_gens()} - skipping loop.")
        exit()

    last_config = deepcopy(comfy_gen.gen_config)
    return (editing, switching_params, last_config)



def do_workflow(args, workflow, positive_prompt, negative_prompt, control_nets, ip_adapters):
    models = Model.get_models(args.model_tags, default_tag=Model.get_default_model_tag(workflow), inpainting=args.inpainting)
    loras = Model.get_models(args.lora_tags, is_lora=True, default_tag=("add-detail" if models[0].is_sd_15() else "add-detail-xl"), inpainting=args.inpainting, is_xl=(2 if models[0].is_sd_15() else 1))
    resolutions = Resolution.get_resolutions(args.res_tags, is_xl=models[0].is_xl)
    config = GenConfig(
        workflow_id=workflow, models=models, loras=loras, n_latents=args.n_latents,
        control_nets=control_nets, ip_adapters=ip_adapters,
        positive=positive_prompt, negative=negative_prompt, resolutions=resolutions,
        seed=args.seed, steps=args.steps, cfg=args.cfg, sampler=args.sampler, scheduler=args.scheduler, denoise=args.denoise
    )
    comfy_gen = ComfyGen(config)
    editing = False
    switching_params = False
    last_config = None
    count = 0

    try:
        while True:
            editing, switching_params, last_config = run(
                editing, switching_params, last_config,
                config, comfy_gen, positive_prompt, negative_prompt
            )
            if last_config is None:
                return
            count += 1
            if args.total:
                if count == args.total:
                    print(f"Reached maximum requested iterations: {args.total}")
                    return
                else:
                    print(f"On iteration {count} of {args.total} - continuing.")
            if args.auto_run:
                # TODO websocket would be better here to ensure all have finished before starting new gen
                sleep_time = config.maximum_gens()
                sleep_time *= Globals.GENERATION_DELAY_TIME_SECONDS
                print(f"Sleeping for {sleep_time} seconds.")
                time.sleep(sleep_time)
    except KeyboardInterrupt:
        pass


def load_and_run(args, prompter_config, control_nets):
    ip_adapters = get_ip_adapters(args.ip_adapters.split(",") if args.ip_adapters and args.ip_adapters != "" else None)
    positive_prompt = args.positive_prompt if args.positive_prompt else Globals.DEFAULT_POSITIVE_PROMPT
    base_negative = "" if Globals.OVERRIDE_BASE_NEGATIVE else str(Globals.DEFAULT_NEGATIVE_PROMPT)
    negative_prompt = args.negative_prompt if args.negative_prompt else base_negative
    Globals.set_prompter(Prompter(prompter_config=prompter_config, get_specific_locations=Globals.PROMPTER_GET_SPECIFIC_LOCATIONS, prompt_list=prompt_list))

    if args.auto_run:
        print("Auto-run mode set.")

    print(args.prompter_config.prompt_mode)

    workflow_tags = args.redo_files.split(",") if args.redo_files else args.workflow_tag.split(",")
    for workflow_tag in workflow_tags:
        workflow = WorkflowPrompt.setup_workflow(workflow_tag, control_nets, ip_adapters)
        try:
            do_workflow(args, workflow, positive_prompt, negative_prompt, control_nets, ip_adapters)
        except Exception as e:
            print(e)
            traceback.print_exc()


def main(args):
    Model.load_all()
    Model.set_lora_strength(Globals.DEFAULT_LORA_STRENGTH)
    prompter_config = PrompterConfiguration(prompt_mode=PromptMode.FIXED) if args.prompter_override else args.prompter_config
    Model.set_model_presets(prompter_config.prompt_mode)
    Globals.SKIP_CONFIRMATIONS = args.auto_run
    control_nets, is_dir = get_control_nets(split(args.control_nets, ",") if args.control_nets and args.control_nets != "" else None)
    if is_dir:
        for i in range(len(control_nets)):
            control_net = control_nets[i]
            print(f"Running control net {i} - {control_net}")
            load_and_run(args, prompter_config, [control_net])
    else:
        load_and_run(args, prompter_config, control_nets)



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
