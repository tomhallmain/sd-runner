from concurrent.futures import ThreadPoolExecutor, Future
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Type
import random
import time
import threading
import traceback

from utils.globals import Globals, WorkflowType

from sd_runner.captioner import Captioner
from sd_runner.gen_config import GenConfig
from ui.app_actions import AppActions
from utils.config import config
from utils.utils import Utils

class BaseImageGenerator(ABC):
    ORDER = config.gen_order
    RANDOM_SKIP_CHANCE = config.dict["random_skip_chance"]

    _executor = ThreadPoolExecutor(max_workers=8)  # Central executor
    _executor_lock = threading.Lock()  # For thread-safe counter updates
    
    pending_counter = 0
    
    def __init__(self, config: GenConfig = GenConfig(), ui_callbacks: Optional[AppActions] = None):
        self.gen_config = config
        self.ui_callbacks = ui_callbacks
        self.counter = 0
        self.latent_counter = 0
        self.captioner = None
        self.has_run_one_workflow = False
        self._lock = threading.Lock()  # Instance-specific lock

    # Shared methods -----------------------------------------------------------
    def get_seed(self):
        return self.gen_config.get_seed()

    def reset_counters(self) -> None:
        # NOTE needs to be called with the lock acquired
        self.counter = 0
        self.latent_counter = 0

    def get_captioner(self):
        if self.captioner is None:
            self.captioner = Captioner()
        return self.captioner

    def maybe_caption_image(self, image_path: str, positive: Optional[str]) -> str:
        if not positive:
            return self.get_captioner().caption(image_path)
        return positive

    def random_skip(self) -> bool:
        skip_chance = getattr(self, 'RANDOM_SKIP_CHANCE', 0.0)
        if skip_chance > 0 and random.random() < skip_chance:
            print(f"Skipping by random chance ({skip_chance*100}%)")
            return True
        return False

    def print_stats(self) -> None:
        with self._lock:
            print(f"Started {self.counter} prompts, {self.latent_counter} images to be saved if all complete")
            self.reset_counters()

    def print_pre(self, action, **kw):
        if not "n_latents" in kw:
            raise Exception("Missing n_latents setting!")
        self.latent_counter += kw["n_latents"]
        out = f"{Utils.format_white(action)} with config: "
        for item in kw.items():
            if not item[1]:
                continue
            if item[0] != "negative" or Globals.PRINT_NEGATIVES:
                out += f"\n{Utils.format_white(item[0])}: {item[1]}"
        print(out)

    def run(self):
        self.has_run_one_workflow = False
        self.gen_config.prepare()
        workflow_id = self.gen_config.workflow_id
        n_latents = self.gen_config.n_latents
        positive = self.gen_config.positive
        negative = self.gen_config.negative
        if workflow_id is None or workflow_id == "":
            raise Exception("Invalid workflow ID.")
        for _1 in getattr(self.gen_config, BaseImageGenerator.ORDER[0]):
            for _2 in getattr(self.gen_config, BaseImageGenerator.ORDER[1]):
                for _3 in getattr(self.gen_config, BaseImageGenerator.ORDER[2]):
                    for _4 in getattr(self.gen_config, BaseImageGenerator.ORDER[3]):
                        for _5 in getattr(self.gen_config, BaseImageGenerator.ORDER[4]):
                            for _6 in getattr(self.gen_config, BaseImageGenerator.ORDER[5]):
                                if self.random_skip():
                                    continue

                                args = [_1, _2, _3, _4, _5, _6]
                                resolution = args[BaseImageGenerator.ORDER.index("resolutions")]

                                if resolution.should_be_randomly_skipped():
                                    self.gen_config.resolutions_skipped += 1
                                    continue

                                if not self.gen_config.register_run():
                                    break

                                model = args[BaseImageGenerator.ORDER.index("models")]
                                vae = args[BaseImageGenerator.ORDER.index("vaes")]
                                if vae is None:
                                    vae = model.get_default_vae()
                                model.validate_vae(vae)
                                lora = args[BaseImageGenerator.ORDER.index("loras")]
                                control_net = args[BaseImageGenerator.ORDER.index("control_nets")]
                                ip_adapter = args[BaseImageGenerator.ORDER.index("ip_adapters")]
                                positive_copy = str(positive)
                                if ip_adapter:
                                    positive_copy += ip_adapter.modifiers
                                    positive_copy = ip_adapter.b_w_coloration_modifier(positive_copy)
                                
                                if self.gen_config.is_redo_prompt():
                                    if self.gen_config.software_type == "SDWebUI":
                                        raise Exception("Redo prompt is not supported for SD Web UI.")
                                    self.redo_with_different_parameter(source_file=workflow_id, model=model, vae=vae, lora=lora, resolution=resolution,
                                                                       n_latents=self.gen_config.n_latents, control_net=control_net, ip_adapter=ip_adapter)
                                else:
                                    self.run_workflow(workflow_id, prompt=None, resolution=resolution, model=model, vae=vae, n_latents=n_latents, positive=positive_copy,
                                                      negative=negative, lora=lora, control_net=control_net, ip_adapter=ip_adapter)
                                self.has_run_one_workflow = True
        self.print_stats()
        return

    def run_workflow(self, workflow_id: str, **kwargs) -> None:
        """Route to specific workflow implementation"""
        if self.random_skip():
            return

        workflow_method = self.validate_workflow(workflow_id, **kwargs)
        self.schedule_generation(workflow_method, **kwargs)
        with self._lock:
            self.pending_counter += 1
            self.counter += 1
            self.has_run_one_workflow = True
            self.update_ui_pending()
        time.sleep(0.2)

    def validate_workflow(self, workflow_id: str, **kwargs) -> None:
        """Validate the workflow and its parameters"""
        workflow_methods = self._get_workflows()
        if workflow_id not in workflow_methods:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        if workflow_id == WorkflowType.SIMPLE_IMAGE_GEN_LORA:
            if kwargs.get("lora") is None:
                raise Exception("Image gen with lora - lora not set!")
        return workflow_methods[workflow_id]

    def schedule_generation(self, task_fn: callable, *args, **kwargs) -> Future:
        """Submit a generation task to the shared executor"""
        with BaseImageGenerator._executor_lock:
            future = self._executor.submit(
                self._wrap_task(task_fn),
                *args, **kwargs
            )
            return future

    def update_ui_pending(self):
        if self.ui_callbacks is not None:
            self.ui_callbacks.update_pending(self.pending_counter)

    def _wrap_task(self, task_fn: callable) -> callable:
        """Add common error handling and logging"""
        def wrapped(*args, **kwargs):
            try:
                print(f"Starting {task_fn.__name__}")
                start_time = time.time()
                result = task_fn(*args, **kwargs)
                print(f"Completed {task_fn.__name__} in {time.time()-start_time:.2f}s")
                return result
            except Exception as e:
                self._handle_error(e, task_fn.__name__)
                raise
        return wrapped

    def _handle_error(self, error: Exception, task_name: str) -> None:
        print(f"Error in {task_name}: {str(error)}")
        traceback.print_exc()

    # Abstract methods to be implemented per generator -------------------------

    @abstractmethod
    def _get_workflows(self) -> dict:
        """Return a dictionary mapping workflow IDs to methods"""
        pass

    @abstractmethod
    def prompt_setup(self, workflow_type, action, prompt, model, vae=None, resolution=None, **kw):
        pass

    @abstractmethod
    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None):
        pass

    @abstractmethod
    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None):
        pass

    @abstractmethod
    def upscale_simple(self, prompt="", model=None, control_net=None):
        pass

    @abstractmethod
    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None):
        pass

    @abstractmethod
    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None):
        pass

    @abstractmethod
    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None):
        pass

    @abstractmethod
    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None):
        pass
