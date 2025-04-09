import json
import os

from utils.config import config
from utils.globals import Globals, WorkflowType, Sampler, Scheduler, ComfyNodeName, PromptTypeSDWebUI
from sd_runner.models import Model, LoraBundle
from sd_runner.resolution import Resolution


class TempRedoInputs:
    def __init__(self, model, ksampler_inputs, clip_last_layer, positive, negative, resolution, vae, lora, control_net, ip_adapter):
        self.model = model
        self.ksampler_inputs = ksampler_inputs
        self.clip_last_layer = clip_last_layer
        self.positive = positive
        self.negative = negative
        self.resolution = resolution
        self.vae = vae
        self.lora = lora
        self.control_net = control_net
        self.ip_adapter = ip_adapter


class KSamplerInputs:
    def __init__(self, ksampler_node_values, node_type=ComfyNodeName.KSAMPLER):
        if node_type == ComfyNodeName.KSAMPLER:
            self.seed = ksampler_node_values[0]
            self.steps = ksampler_node_values[2]
            self.cfg = ksampler_node_values[3]
            self.sampler_name = ksampler_node_values[4]
            self.scheduler = ksampler_node_values[5]
            self.denoise = ksampler_node_values[6]
        elif node_type == ComfyNodeName.KSAMPLER_ADVANCED:
            self.seed = ksampler_node_values[1]
            self.steps = ksampler_node_values[3]
            self.cfg = ksampler_node_values[4]
            self.sampler_name = ksampler_node_values[5]
            self.scheduler = ksampler_node_values[6]
            self.denoise = None
        else:
            raise Exception("Unhandled node type: " + node_type)


class WorkflowPrompt:
    PROMPTS_LOC = os.path.join(os.path.abspath(os.path.dirname(os.path.dirname(__file__))), "prompts")
    LAST_PROMPT_FILENAME = "test.json"
    LAST_PROMPT_FILE = os.path.join(PROMPTS_LOC, LAST_PROMPT_FILENAME)

    def __init__(self, workflow_filename):
        pass

    def get_json(self):
        raise NotImplementedError("WorkflowPrompt.get_json() must be implemented by subclasses")

    def set_from_workflow(self, workflow_filename):
        raise NotImplementedError("WorkflowPrompt.set_from_workflow() must be implemented by subclasses")

    @staticmethod
    def setup_workflow(workflow_tag, control_nets, ip_adapters):
        workflow = None
        workflow_tag = workflow_tag.lower()
        if workflow_tag.endswith(".png"):
            workflow = workflow_tag
            return workflow
        for wf in WorkflowType.__members__.values():
            if workflow_tag in wf.value:
                workflow = wf
                break
        if workflow is None:
            raise Exception("Invalid workflow tag: " + workflow_tag)
        if workflow not in [
                WorkflowType.INSTANT_LORA,
                WorkflowType.IP_ADAPTER]:
            if workflow != WorkflowType.ANIMATE_DIFF or len(ip_adapters) > 1:
                ip_adapters.clear()
                ip_adapters.append(None)
        if workflow not in [
                WorkflowType.CONTROLNET,
                WorkflowType.INSTANT_LORA,
                WorkflowType.RENOISER,
                WorkflowType.UPSCALE_SIMPLE,
                WorkflowType.UPSCALE_BETTER,
                WorkflowType.ANIMATE_DIFF]:
            control_nets.clear()
            control_nets.append(None)
        return workflow


class WorkflowPromptComfy(WorkflowPrompt):
    """
    Used for creating new prompts to serve to the Comfy API
    Can also be used for gathering information about prompts stored in images already created by Comfy
    """
    CLASS_TYPE = "class_type"
    ID = "id"
    INPUTS = "inputs"
    NON_API_INPUTS = "widgets_values"

    def __init__(self, workflow_filename):
        self.workflow_filename = workflow_filename
        if self.workflow_filename.endswith(".png"):
            self.full_path = workflow_filename
            self.json = Globals.get_image_data_extractor().extract_prompt(self.full_path)
        else:
            self.full_path = os.path.join(WorkflowPrompt.PROMPTS_LOC, workflow_filename)
            self.json = json.load(open(self.full_path, "r"))
        self.temp_redo_inputs = None
        self.is_xl = None

    def set_from_workflow(self, workflow_filename):
        self.workflow_filename = workflow_filename
        self.full_path = os.path.join(WorkflowPrompt.PROMPTS_LOC, workflow_filename)
        if self.workflow_filename.endswith(".png"):
            raise Exception("No preset workflow: " + self.workflow_filename)
        self.json = json.load(open(self.full_path, "r"))

    def get_json(self):
        self.handle_old_prompt_image_location() # Tries to find the original image location if it's not found
        with open(WorkflowPrompt.LAST_PROMPT_FILE, "w") as store:
            json.dump(self.json, store, indent=2)
        p = {"prompt": self.json}
        return json.dumps(p).encode('utf-8')

    def find_node_of_class_type(self, class_type, raise_exc=True, test=False, i=0):
        count = 0
        for node in self.json.items():
            if test:
                print(node[1][WorkflowPrompt.CLASS_TYPE])
            if WorkflowPrompt.CLASS_TYPE in node[1] and node[1][WorkflowPrompt.CLASS_TYPE] == class_type:
                if i == count:
                    return node[1]
                count += 1
        if raise_exc:
            raise Exception(f"No {class_type} node count {i} found for workflow: {self.workflow_filename}")
        return None

    def get_sampler_node(self):
        node = self.find_node_of_class_type(ComfyNodeName.KSAMPLER, raise_exc=False)
        if node is None:
            node = self.find_node_of_class_type(ComfyNodeName.KSAMPLER_ADVANCED, raise_exc=False)
            if node is None:
                node = self.find_node_of_class_type(ComfyNodeName.SAMPLER_CUSTOM)[WorkflowPrompt.INPUTS]
        return node

    def get_ksampler_node_inputs(self):
        return self.get_sampler_node()[WorkflowPrompt.INPUTS]

    def set_for_class_type(self, class_type, key, value):
        if not value:
            return
        node = self.find_node_of_class_type(class_type)
        node[WorkflowPrompt.INPUTS][key] = value

    def get_for_class_type(self, class_type, key):
        node = self.find_node_of_class_type(class_type)
        return node[WorkflowPrompt.INPUTS][key]

    def set_by_id(self, id_key, key, value):
        self.json[id_key][WorkflowPrompt.INPUTS][key] = value

    def find_linked_input_node(self, starting_class_type=ComfyNodeName.IP_ADAPTER_ADVANCED, class_type=ComfyNodeName.LOAD_IMAGE, vartype="image"):
        found_node = None
        counter = 0
        next_input = ()
        current_node = self.find_node_of_class_type(starting_class_type)
        while found_node is None and counter < 100:
            next_input = current_node[WorkflowPrompt.INPUTS][vartype]
            if len(next_input) < 2:
                raise Exception(f"Bad input connection on node when backtracing inputs: {current_node}")
            counter += 1
            current_node = self.json[next_input[0]]
            if current_node[WorkflowPrompt.CLASS_TYPE] == class_type:
                found_node = current_node
                break
        if found_node is None:
            raise Exception(f"Could not find input {class_type} of type {vartype} for {starting_class_type}")
        return found_node

    def set_linked_input_node(self, value, starting_class_type=ComfyNodeName.IP_ADAPTER_ADVANCED, class_type=ComfyNodeName.LOAD_IMAGE, vartype="image"):
        if not value:
            return
        node = self.find_linked_input_node(starting_class_type=starting_class_type, class_type=class_type, vartype=vartype)
        node[WorkflowPrompt.INPUTS][vartype] = value

    def set_model(self, model):
        if not model:
            return
        self.set_for_class_type(ComfyNodeName.LOAD_CHECKPOINT, "ckpt_name", model.path)

    def get_model(self):
        return self.get_for_class_type(ComfyNodeName.LOAD_CHECKPOINT, "ckpt_name")

    def set_vae(self, vae):
        if not vae:
            return
        self.set_for_class_type(ComfyNodeName.LOAD_VAE, "vae_name", vae)

    def get_vae(self):
        return self.get_for_class_type(ComfyNodeName.LOAD_VAE, "vae_name")

    def set_empty_latents(self, n_latents):
        if not n_latents:
            return
        return self.set_for_class_type(ComfyNodeName.EMPTY_LATENT, "batch_size", n_latents)
    
    def set_image_duplicator(self, n_latents):
        if not n_latents:
            return
        node = self.find_node_of_class_type(ComfyNodeName.IMAGE_DUPLICATOR)
        node[WorkflowPrompt.INPUTS]["dup_times"] = n_latents
        node[WorkflowPrompt.INPUTS]["images"][0] = n_latents

    def set_latent_dimensions(self, resolution):
        if not resolution:
            return
        node = self.find_node_of_class_type(ComfyNodeName.EMPTY_LATENT)
        node[WorkflowPrompt.INPUTS]["width"] = resolution.width
        node[WorkflowPrompt.INPUTS]["height"] = resolution.height

    def set_clip_text(self, text, model, positive=True):
        if not text:
            return
        if model:
            if positive:
                text, negative = model.get_model_text(text, "")
            else:
                _positive, text = model.get_model_text("", text)
            if model.clip_req:
                self.set_clip_last_layer(model.clip_req)
        try:
            sampler_inputs = self.get_ksampler_node_inputs()
            node = self.json[sampler_inputs["positive" if positive else "negative"][0]]
            node[WorkflowPrompt.INPUTS]["text"] = text
        except Exception as e:
            if positive:
                node = self.find_node_of_class_type(ComfyNodeName.IMPACT_WILDCARD_PROCESSOR)
                node[WorkflowPrompt.INPUTS]["wildcard_text"] = positive
                node[WorkflowPrompt.INPUTS]["populated_text"] = positive
            else:
                raise e

    # Have to use IDs because these nodes use the same class type CLIPTextEncode
    def set_clip_text_by_id(self, positive, negative, positive_id=None, negative_id=None, model=None):
        if not (positive or negative):
            return
        if model:
            positive, negative = model.get_model_text(positive, negative)
            if model.clip_req:
                self.set_clip_last_layer(model.clip_req)
        if positive:
            if positive_id:
                self.json[positive_id][WorkflowPrompt.INPUTS]["text"] = positive
            else:
                node = self.find_node_of_class_type(ComfyNodeName.IMPACT_WILDCARD_PROCESSOR)
                node[WorkflowPrompt.INPUTS]["wildcard_text"] = positive
                node[WorkflowPrompt.INPUTS]["populated_text"] = positive

        if negative:
            if negative_id:
                self.json[negative_id][WorkflowPrompt.INPUTS]["text"] = negative
            else:
                print("No negative prompt text added!!!")

    def set_clip_last_layer(self, clip_last_layer):
        if not clip_last_layer:
            return
        node = self.find_node_of_class_type("CLIPSetLastLayer")
        node[WorkflowPrompt.INPUTS]["stop_at_clip_layer"] = clip_last_layer

    def set_clip_seg(self, text):
        if not text:
            return
        self.set_for_class_type(ComfyNodeName.CLIP_SEG, ComfyNodeName.CLIP_SEG, text)

    def set_load_image(self, image_path):
        if not image_path:
            return
        self.set_for_class_type(ComfyNodeName.LOAD_IMAGE, "image", image_path)

    def set_load_image_mask(self, image_path):
        if not image_path:
            return
        self.set_for_class_type(ComfyNodeName.LOAD_IMAGE_MASK, "image", image_path)

    def set_seed(self, seed_val):
        if not seed_val:
            return
        node = self.get_sampler_node()
        if node[WorkflowPrompt.CLASS_TYPE] == ComfyNodeName.SAMPLER_CUSTOM:
            node[WorkflowPrompt.INPUTS]["noise_seed"] = seed_val
        else:
            node[WorkflowPrompt.INPUTS]["seed"] = seed_val

    def set_other_sampler_inputs(self, gen_config):
        if gen_config.steps and gen_config.steps > 0:
            self.set_sampler_steps(gen_config.steps)
        if gen_config.cfg and gen_config.cfg > 0:
            self.set_sampler_cfg(gen_config.cfg)
        if gen_config.sampler and gen_config.sampler != Sampler.ACCEPT_ANY:
            self.set_sampler(gen_config.sampler)
        if gen_config.scheduler and gen_config.scheduler != Scheduler.ACCEPT_ANY:
            self.set_scheduler(gen_config.scheduler)
        if gen_config.denoise and gen_config.denoise > 0:
            self.set_denoise(gen_config.denoise)

    def set_sampler_steps(self, steps):
        if not steps:
            return
        self.get_ksampler_node_inputs()["steps"] = steps

    def set_sampler_cfg(self, cfg):
        if not cfg:
            return
        self.get_ksampler_node_inputs()["cfg"] = cfg

    def set_sampler(self, sampler):
        if not sampler:
            return
        self.get_ksampler_node_inputs()["sampler_name"] = sampler.value

    def set_scheduler(self, scheduler):
        if not scheduler:
            return
        self.get_ksampler_node_inputs()["scheduler"] = scheduler.value

    def set_denoise(self, denoise):
        if not denoise:
            return
        self.get_ksampler_node_inputs()["denoise"] = denoise

    def set_lora(self, lora):
        if not lora:
            return
        if isinstance(lora, LoraBundle):
            if len(lora.loras) > 2:
                raise Exception("Only two bundled loras are supported for this workflow at the moment.")
            node = self.find_node_of_class_type(ComfyNodeName.LOAD_LORA, i=0)
            self.set_lora_node(node, lora.loras[0])
            node = self.find_node_of_class_type(ComfyNodeName.LOAD_LORA, i=1)
            self.set_lora_node(node, lora.loras[1])
        else:
            node = self.find_node_of_class_type(ComfyNodeName.LOAD_LORA)
            self.set_lora_node(node, lora)

    def set_lora_node(self, node, lora):
        node[WorkflowPrompt.INPUTS]["lora_name"] = lora.path
        if lora.lora_strength is not None:
            node[WorkflowPrompt.INPUTS]["strength_model"] = lora.lora_strength
            if lora.lora_strength_clip is not None:
                node[WorkflowPrompt.INPUTS]["strength_clip"] = lora.lora_strength_clip
            else:
                node[WorkflowPrompt.INPUTS]["strength_clip"] = lora.lora_strength

    def set_upscaler_model(self, model):
        if not model:
            return
        self.set_for_class_type("UpscaleModelLoader", "model_name", model)

    def set_control_net_image(self, image_path):
        if not image_path:
            return
        self.set_linked_input_node(image_path, ComfyNodeName.CONTROL_NET)

    def set_control_net_strength(self, strength):
        if not strength:
            return
        self.set_for_class_type(ComfyNodeName.CONTROL_NET, "strength", strength)

    def set_control_net(self, control_net):
        if not control_net:
            return
        self.set_control_net_image(control_net.id)
        self.set_control_net_strength(control_net.strength)

    def set_clip_vision_model(self, model):
        if not model:
            return
        self.set_for_class_type(ComfyNodeName.CLIP_VISION, "clip_name", model)

    def set_ip_adapter_image(self, image_path):
        if not image_path:
            return
        self.set_linked_input_node(image_path, ComfyNodeName.IP_ADAPTER_ADVANCED)

    def set_ip_adapter_model(self, model):
        if not model:
            return
        try:
            self.set_for_class_type(ComfyNodeName.IP_ADAPTER_ADVANCED, "model_name", model)
        except Exception:
            self.set_for_class_type(ComfyNodeName.IP_ADAPTER_MODEL_LOADER, "ipadapter_file", model)

    def set_ip_adapter_strength(self, strength):
        if not strength:
            print("NO STRENGTH FOUND")
            return
        self.set_for_class_type(ComfyNodeName.IP_ADAPTER_ADVANCED, "weight", strength)

    def set_image_scale_to_side(self, longest):
        if not longest:
            return
        self.set_for_class_type(ComfyNodeName.IMAGE_SCALE_TO_SIDE, "side_length", longest)

    def validate_api_prompt(self):
        # Unfortunately there is no way to turn a UI workflow into an API workflow at this time.
        if not self.json or "nodes" in self.json:
            return False
        if len(self.json) == 0:
            return False
        for key, node in self.json.items():
            try:
                int(key)
            except Exception:
                return False
            if "class_type" not in node:
                return False
        return True

    def change_preview_images_to_save_images(self):
        preview_image_node = self.find_node_of_class_type(ComfyNodeName.PREVIEW_IMAGE, raise_exc=False)
        counter = 0
        while preview_image_node is not None and counter < 3:
            preview_image_node[WorkflowPrompt.CLASS_TYPE] = ComfyNodeName.SAVE_IMAGE

    def find_non_api_node_of_type(self, node_type, node_index=0):
        found_count = 0
        for node in self.json["nodes"]:
            if "type" in node and node["type"] == node_type:
                if found_count == node_index:
                    return node
                found_count += 1
        return None

    def get_non_api_values(self, node_type, node_index=0):
        node = self.find_non_api_node_of_type(node_type, node_index=node_index)
        if node:
            return node[WorkflowPrompt.NON_API_INPUTS]
        return []

    def get_non_api_value(self, node_type, input_index=0, node_index=0):
        values = self.get_non_api_values(node_type, node_index)
        if len(values) == 0:
            return None
        elif len(values) <= input_index:
            raise Exception(f"Invalid index for {node_type} inputs: {input_index}")
        return values[input_index]

    def get_non_api_clip_text(self):
        first = self.get_non_api_value(ComfyNodeName.CLIP_TEXT_ENCODE)
        second = self.get_non_api_value(ComfyNodeName.CLIP_TEXT_ENCODE, node_index=1)
        if not first or not second:
            return None, None
        if len(first) < len(second): # TODO improve this to find the link to sampler node where positive/negative bifurcated
            return second, first
        return first, second

    def get_non_api_ksampler_inputs(self):
        ksampler_node_values = self.get_non_api_values(ComfyNodeName.KSAMPLER)
        if len(ksampler_node_values):
            return KSamplerInputs(ksampler_node_values, node_type=ComfyNodeName.KSAMPLER)
        ksampler_node_values = self.get_non_api_values(ComfyNodeName.KSAMPLER_ADVANCED)
        if len(ksampler_node_values):
            return KSamplerInputs(ksampler_node_values, node_type=ComfyNodeName.KSAMPLER_ADVANCED)
        raise Exception("No sampler node found in non-api workflow.")

    def get_non_api_resolution(self):
        latent_values = self.get_non_api_values(ComfyNodeName.EMPTY_LATENT)
        if len(latent_values) < 3:
            return None
        return Resolution(latent_values[0], latent_values[1])

    def get_non_api_control_net(self):
        # might not be needed, hard to find any instant lora that have been created this way
        return None

    def get_non_api_ip_adapter(self):
        # might not be needed, hard to find any instant lora that have been created this way
        return None

    def try_set_workflow_non_api_prompt(self):
        if not self.json or not "nodes" in self.json:
            print("JSON not found or nodes not found in JSON")
            return False
        try:
            model = Model.get_model(self.get_non_api_value(ComfyNodeName.LOAD_CHECKPOINT))
        except Exception:
            model = Model.get_model(self.get_non_api_value(ComfyNodeName.LOAD_CHECKPOINT), inpainting=True)
        if not model or model == "":
            print("Model not found")
            return False
        clip_last_layer = self.get_non_api_value("ClipSetLastLayer")
        positive, negative = self.get_non_api_clip_text()
        ksampler_inputs = self.get_non_api_ksampler_inputs()
        resolution = self.get_non_api_resolution()
        vae = self.get_non_api_value(ComfyNodeName.LOAD_VAE)
        lora = self.get_non_api_value(ComfyNodeName.LOAD_LORA)
        control_net = self.get_non_api_control_net()
        ip_adapter = self.get_non_api_ip_adapter()
        self.temp_redo_inputs = TempRedoInputs(model, ksampler_inputs, clip_last_layer, positive, negative,
                                               resolution, vae, lora, control_net, ip_adapter)

        if lora:
            self.workflow_filename = "simple_image_gen_lora.json"
        elif self.find_non_api_node_of_type("ImageUpscaleWithModel"):
            self.workflow_filename = "upscale_simple.json"
        elif (self.find_non_api_node_of_type("CLIPTextEncodeSDXLRefiner")
                and self.find_non_api_node_of_type("PrimitiveNode")):
            self.workflow_filename = "upscale_better.json"
        elif model.is_turbo:
            self.workflow_filename = "turbo2.json"
        elif self.find_non_api_node_of_type("VHS_VideoCombine"):
            if self.find_non_api_node_of_type(ComfyNodeName.LOAD_IMAGE):
                self.workflow_filename = "animate_diff.json"
            else:
                self.workflow_filename = "animate_diff_simple.json"
        else:
            self.workflow_filename = "simple_image_gen.json"

        return True

    def is_existing_image_xl(self):
        if self.is_xl is not None:
            return self.is_xl
        self.is_xl = Globals.get_image_data_extractor().is_xl(self.workflow_filename)
        return self.is_xl

    def check_model(self, model):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and not model.is_xl:
            return Model.get_xl_model(model)
        elif not is_xl and model.is_xl:
            return Model.get_sd15_model(model)
        return model

    def check_vae(self, vae):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and vae != Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SDXL_VAE
        elif not is_xl and vae == Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SD15_VAE
        return vae

    def check_resolution(self, resolution):
        is_xl = self.is_existing_image_xl() or self.get_model().is_xl
        if (is_xl and not resolution.is_xl()) or (not is_xl and resolution.is_xl()):
            resolution.switch_mode(is_xl)

    # TODO
    def check_for_existing_image(self, model, vae=None, resolution=None):
        if resolution:
            prompt.check_resolution(resolution)
        if model:
            model = prompt.check_model(model)
        if vae:
            vae = prompt.check_vae(vae)
        return model, vae

    def handle_old_prompt_image_location(self):
        for node_id, node in self.json.items():
            if node[WorkflowPrompt.CLASS_TYPE] == ComfyNodeName.LOAD_IMAGE:
                image_location = node[WorkflowPrompt.INPUTS]["image"]
                if image_location.startswith("C:\\") and not os.path.exists(image_location):
                    print("Attempting to fix invalid file location: " + image_location)
                    if image_location.startswith(config.sd_webui_loc) or image_location.startswith(config.img_dir):
                        image_location = image_location.replace(Globals.HOME, "D:\\")
                    if not os.path.exists(image_location):
                        raise Exception("Could not find expected external path for image: " + image_location)
                    print("Will try with external image location " + image_location)
                    node[WorkflowPrompt.INPUTS]["image"] = image_location



class WorkflowPromptSDWebUI(WorkflowPrompt):
    """
    Used for creating new prompts to serve to the SD Web UI API
    Can also be used for gathering information about prompts stored in images already created by Comfy
    """
    PROMPTS_LOC = os.path.join(WorkflowPrompt.PROMPTS_LOC, "sdwebui")
    ALWAYSON_SCRIPTS_KEY = "alwayson_scripts"
    CONTROLNET_KEY = "ControlNet"

    def __init__(self, workflow_filename):
        if workflow_filename.endswith(".png"):
            raise Exception("Redo not yet supported for SDWebUI")
            # self.full_path = workflow_filename
            # self.json = Globals.get_image_data_extractor().extract_prompt(self.full_path)
        else:
            self.workflow_filename = PromptTypeSDWebUI.convert_to_sd_webui_filename(workflow_filename)
            self.full_path = os.path.join(WorkflowPromptSDWebUI.PROMPTS_LOC, self.workflow_filename)
            self.json = json.load(open(self.full_path, "r"))
        assert self.json is not None
        self.temp_redo_inputs = None
        self.is_xl = None

    def set_from_workflow(self, workflow_filename):
        # TODO this will need to be changed if Redo is implemented for SDWebUI
        self.workflow_filename = workflow_filename
        self.full_path = os.path.join(WorkflowPrompt.PROMPTS_LOC, workflow_filename)
        if self.workflow_filename.endswith(".png"):
            raise Exception("No preset workflow: " + self.workflow_filename)
        self.json = json.load(open(self.full_path, "r"))

    def get_json(self):
        with open(WorkflowPrompt.LAST_PROMPT_FILE, "w") as store:
            json.dump(self.json, store, indent=2)
        return json.dumps(self.json).encode('utf-8')

    def set_by_id(self, id_key, value):
        self.json[id_key] = value

    def set_model(self, model):
        if not model:
            return
        override_settings = self.json["override_settings"] if "override_settings" in self.json else {}
        override_settings["sd_model_checkpoint"] = model.path
        self.json["override_settings"] = override_settings

    def get_model(self):
        return self.json["override_settings"]["sd_model_checkpoint"]

    def set_vae(self, vae):
        pass # Nothing to do here

    def get_vae(self):
        return None

    def get_scripts(self):
        return self.json[WorkflowPromptSDWebUI.ALWAYSON_SCRIPTS_KEY]

    def set_empty_latents(self, n_latents):
        if not n_latents:
            return
        self.set_by_id("batch_size", n_latents)
    
    def set_image_duplicator(self, n_latents):
        self.set_empty_latents(n_latents)

    def set_latent_dimensions(self, resolution):
        if not resolution:
            return
        self.set_by_id("width", resolution.width)
        self.set_by_id("height", resolution.height)

    def set_clip_text(self, text, model, positive=True):
        if not text:
            return
        if model:
            if positive:
                text, negative = model.get_model_text(text, "")
            else:
                _positive, text = model.get_model_text("", text)
            if model.clip_req:
                pass # Nothing to do here
        if positive:
            self.set_by_id("prompt", text)
        else:
            self.set_by_id("negative_prompt", text)

    # Have to use IDs because these nodes use the same class type CLIPTextEncode
    def set_clip_texts(self, positive, negative, model=None):
        if not (positive or negative):
            return
        if model:
            positive, negative = model.get_model_text(positive, negative)
            if model.clip_req:
                self.set_clip_last_layer(model.clip_req)
        if positive:
            self.set_by_id("prompt", positive)
        if negative:
            self.set_by_id("negative_prompt", negative)

    def set_clip_last_layer(self, clip_last_layer):
        if not clip_last_layer:
            return
        pass

    def set_clip_seg(self, text):
        if not text:
            return
        pass

    def set_load_image(self, image_path):
        if not image_path:
            return
        pass

    def set_load_image_mask(self, image_path):
        if not image_path:
            return
        pass

    def set_seed(self, seed_val):
        if not seed_val:
            return
        self.set_by_id("seed", seed_val)

    def set_other_sampler_inputs(self, gen_config):
        if gen_config.steps and gen_config.steps > 0:
            self.set_sampler_steps(gen_config.steps)
        if gen_config.cfg and gen_config.cfg > 0:
            self.set_sampler_cfg(gen_config.cfg)
        if gen_config.sampler and gen_config.sampler != Sampler.ACCEPT_ANY:
            self.set_sampler(gen_config.sampler)
        if gen_config.scheduler and gen_config.scheduler != Scheduler.ACCEPT_ANY:
            self.set_scheduler(gen_config.scheduler)
        if gen_config.denoise and gen_config.denoise > 0:
            self.set_denoise(gen_config.denoise)

    def set_sampler_steps(self, steps):
        if not steps:
            return
        self.set_by_id("steps", steps)

    def set_sampler_cfg(self, cfg):
        if not cfg:
            return
        self.set_by_id("cfg", cfg)

    def set_sampler(self, sampler):
        if not sampler:
            return
        self.set_by_id("sampler_name", sampler)

    def set_scheduler(self, scheduler):
        if not scheduler:
            return
        pass
#        self.set_by_id("scheduler", scheduler)

    def set_denoise(self, denoise):
        if not denoise:
            return
        self.set_by_id("denoising_strength", denoise)

    def set_lora(self, lora):
        if not lora:
            return
        assert self.json is not None
        if not "prompt" in self.json or not isinstance(self.json["prompt"], str):
            raise Exception("prompt not found on JSON.")
        positive = self.json["prompt"]

        if isinstance(lora, LoraBundle):
            if len(lora.loras) > 2:
                raise Exception("Only two bundled loras are supported for this workflow at the moment.")
            positive += lora.loras[0].get_lora_text()
            positive += lora.loras[1].get_lora_text()
        else:
            positive += lora.get_lora_text()
        self.json["prompt"] = positive

    def set_upscaler_model(self, model):
        if not model:
            return
        pass
#        self.set_for_class_type("UpscaleModelLoader", "model_name", model)

    def get_controlnet_script_args(self):
        return self.get_scripts()[WorkflowPromptSDWebUI.CONTROLNET_KEY]["args"][0]

    def set_control_net_image(self, image):
        if not image:
            return
        controlnet_script = self.get_controlnet_script_args()
        controlnet_script["image"]["image"] = image

    def set_control_net_strength(self, strength):
        if not strength:
            return
        controlnet_script = self.get_controlnet_script_args()
        controlnet_script["weight"] = strength * 2

    def set_control_net(self, control_net):
        if not control_net:
            return
        self.set_control_net_image(control_net.id)
        self.set_control_net_strength(control_net.strength)

    def set_clip_vision_model(self, model):
        if not model:
            return
        pass
#        self.set_for_class_type(ComfyNodeName.CLIP_VISION, "clip_name", model)

    def set_img2img_image(self, image_path):
        if not image_path:
            return
        self.set_by_id("init_images", [image_path])

    def set_ip_adapter_model(self, model):
        if not model:
            return
        pass

    def set_ip_adapter_strength(self, strength):
        if not strength:
            print("NO STRENGTH FOUND")
            return
        pass

    def set_image_scale_to_side(self, longest):
        if not longest:
            return
        pass

    def validate_api_prompt(self):
        return True

    def is_existing_image_xl(self):
        if self.is_xl is not None:
            return self.is_xl
        self.is_xl = Globals.get_image_data_extractor().is_xl(self.workflow_filename)
        return self.is_xl

    def check_model(self, model):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and not model.is_xl:
            return Model.get_xl_model(model)
        elif not is_xl and model.is_xl:
            return Model.get_sd15_model(model)
        return model

    def check_vae(self, vae):
        is_xl = self.get_model().is_xl or self.is_existing_image_xl()
        if is_xl and vae != Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SDXL_VAE
        elif not is_xl and vae == Model.DEFAULT_SDXL_VAE:
            return Model.DEFAULT_SD15_VAE
        return vae

    def check_resolution(self, resolution):
        is_xl = self.is_existing_image_xl() or self.get_model().is_xl
        if (is_xl and not resolution.is_xl()) or (not is_xl and resolution.is_xl()):
            resolution.switch_mode(is_xl)


