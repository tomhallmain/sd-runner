import os

from utils.config import config
from utils.globals import WorkflowType, ComfyNodeName
from sd_runner.control_nets import ControlNet
from sd_runner.ip_adapters import IPAdapter


def _is_api_node_id(key: str) -> bool:
    """Return True for integer node IDs and subgraph node IDs (e.g. '75:42')."""
    try:
        int(key)
        return True
    except ValueError:
        parts = key.split(":")
        if len(parts) == 2:
            try:
                int(parts[0])
                int(parts[1])
                return True
            except ValueError:
                pass
    return False


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
    save_prompt = config.save_last_prompt

    def __init__(self, workflow_filename):
        pass

    def get_json(self):
        raise NotImplementedError("WorkflowPrompt.get_json() must be implemented by subclasses")

    def set_from_workflow(self, workflow_filename):
        raise NotImplementedError("WorkflowPrompt.set_from_workflow() must be implemented by subclasses")

    @staticmethod
    def setup_workflow(workflow_tag: str, control_nets: list[ControlNet], ip_adapters: list[IPAdapter]) -> str | WorkflowType:
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
                WorkflowType.IP_ADAPTER,
                WorkflowType.IMG2IMG,
                WorkflowType.IMAGE_EDIT]:
            if workflow != WorkflowType.ANIMATE_DIFF or len(ip_adapters) > 1:
                ip_adapters.clear()
                ip_adapters.append(None)
        if workflow not in [
                WorkflowType.CONTROLNET,
                WorkflowType.INSTANT_LORA,
                WorkflowType.RENOISER,
                WorkflowType.UPSCALE_SIMPLE,
                WorkflowType.UPSCALE_BETTER,
                WorkflowType.ANIMATE_DIFF,
                WorkflowType.IMAGE_EDIT]:
            control_nets.clear()
            control_nets.append(None)
        return workflow




