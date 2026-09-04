from concurrent.futures import ThreadPoolExecutor, Future
from abc import ABC, abstractmethod
from copy import copy
from pathlib import Path
from typing import Optional, Dict, Any, Type
import functools
import os
import random
import shutil
import time
import threading
import traceback

from utils.globals import Globals, WorkflowType, SoftwareType, image_input_field

from sd_runner.prompts.blacklist import Blacklist
from sd_runner.runs.gen_config import GenConfig
from sd_runner.image_converter import convert_image_if_needed, cleanup_converter, clear_converter_cache
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from sd_runner.workflow_prompts.base import WorkflowPrompt
from sd_runner.ui.app_actions import AppActions
from utils.config import config
from utils.logging_setup import get_logger
from utils.utils import Utils

logger = get_logger("base_image_generator")

class BaseImageGenerator(ABC):
    ORDER = config.gen_order
    RANDOM_SKIP_CHANCE = config.dict["random_skip_chance"]

    _executor = ThreadPoolExecutor(max_workers=config.max_executor_threads)  # Central executor
    _executor_lock = threading.Lock()  # For thread-safe counter updates

    #: The model each backend most recently generated with, so a timing sample
    #: can be told from one that also paid for a checkpoint load. Keyed by
    #: backend rather than held per generator instance, because it is the
    #: backend process that holds the loaded model -- and it outlives any one
    #: run. Only ever read and written together, under _timing_lock.
    _last_dispatched_model: dict = {}
    _timing_lock = threading.Lock()

    @classmethod
    def shutdown_executor(cls, wait: bool = False) -> None:
        """
        Shutdown the shared thread pool executor.
        
        Args:
            wait: Whether to wait for all tasks to complete before shutting down
        """
        if cls._executor is not None:
            cls._executor.shutdown(wait=wait)
    
    @classmethod
    def cleanup_image_converter(cls) -> None:
        """Clean up the image converter temporary files."""
        cleanup_converter()
    
    @classmethod
    def clear_image_converter_cache(cls) -> None:
        """Clear the image converter cache."""
        clear_converter_cache()
    
    def __init__(self, config: GenConfig = GenConfig(), ui_callbacks: Optional[AppActions] = None):
        self.gen_config = config
        self.ui_callbacks = ui_callbacks
        self.counter = 0
        self.latent_counter = 0
        #: Generations dispatched by this generator and not yet accounted for.
        #: Per instance, so the pending label reports one generator's work: a
        #: run spanning several workflow tags -- a redo over several files --
        #: builds one generator per tag, and can read low while an earlier
        #: tag's work is still in flight. Sharing it would need a class-level
        #: lock, and would change pacing too, which reads this counter.
        self.pending_counter = 0
        self.captioner = None
        self.has_run_one_workflow = False
        self._lock = threading.Lock()  # Instance-specific lock
        # How many decrements the dispatch running on this thread still owes
        # the pending count. Raised when a task starts, spent by whichever of
        # the backend or the task wrapper gets there first, so a generation
        # that dies before reaching a backend is still accounted for.
        self._pending_release = threading.local()
        # Per-thread override for the image a generation is derived from. The
        # run-wide source lives on gen_config and is shared by every worker, so
        # a second derivative -- whose parent is the image its own task just
        # made -- cannot record its lineage there without corrupting the others.
        self._related_image_override = threading.local()
        # Per-thread record of what the task on this thread is generating, so
        # queue_prompt can attribute a duration without every workflow method
        # having to pass the model and resolution down to it.
        self._timing_context = threading.local()
        # Set while this thread is producing a pre-pass intermediate rather
        # than the run's own output. Per thread because gen_config is shared by
        # every worker, so suppressing the treatments there would suppress them
        # for concurrent runs too.
        self._intermediate_context = threading.local()

    # Shared methods -----------------------------------------------------------
    def get_seed(self):
        return self.gen_config.get_seed()

    # ------------------------------------------------------------------
    # Generation timing
    # ------------------------------------------------------------------
    def _backend_name(self) -> str:
        return str(getattr(self.gen_config, "software_type", "") or type(self).__name__)

    def record_generation_timing(self, execution_seconds: Optional[float]) -> None:
        """Record how long the backend took for the generation on this thread.

        Called by the backend once it knows the duration of the work itself,
        with the queue wait excluded. Never raises: a timing sample is not
        worth failing a generation that already produced its image.
        """
        if not execution_seconds or execution_seconds <= 0:
            return
        context = getattr(self._timing_context, "descriptors", None)
        if not context:
            return
        try:
            from utils.generation_timing import generation_timing

            backend = self._backend_name()
            warm = self._classify_and_remember(backend, context["model"])
            generation_timing.record(
                backend=backend,
                architecture=context["architecture"],
                model=context["model"],
                seconds=execution_seconds,
                width=context["width"],
                height=context["height"],
                steps=context["steps"],
                n_latents=context["n_latents"],
                warm=warm,
            )
        except Exception as e:
            logger.debug(f"Could not record generation timing: {e}")

    @classmethod
    def _classify_and_remember(cls, backend: str, model: str) -> bool:
        """Whether this generation ran on an already-loaded model.

        Decided at completion rather than at dispatch: prompts are dispatched
        several at a time but the backend runs them single file, so completion
        order is execution order and is what says which one paid for the load.

        The check and the update are one section -- splitting them would let
        two completions both see the previous model and both count as cold.
        """
        with cls._timing_lock:
            warm = cls._last_dispatched_model.get(backend) == model
            cls._last_dispatched_model[backend] = model
            return warm

    def _timing_descriptors(self, kwargs: dict) -> Optional[dict]:
        """What a timing sample needs, from a scheduled task's arguments.

        None when the task carries no model or resolution -- an upscale, say --
        which is not something the rate model describes.
        """
        model = kwargs.get("model")
        resolution = kwargs.get("resolution")
        if model is None or resolution is None:
            return None
        architecture = getattr(model, "architecture_type", None)
        return {
            "model": str(getattr(model, "id", model)),
            "architecture": getattr(architecture, "name", str(architecture)),
            "width": getattr(resolution, "width", 0),
            "height": getattr(resolution, "height", 0),
            "steps": getattr(self.gen_config, "steps", -1) or -1,
            "n_latents": kwargs.get("n_latents") or 1,
        }

    def related_image_path(self) -> Optional[str]:
        """The image the generation running on this thread is derived from.

        The run's own source image, except inside a second-derivative pass,
        where it is the image that pass was made from. Drives the EXIF lineage
        and the edit-suffix rename, both of which should name the direct parent
        rather than the start of the chain.
        """
        override = getattr(self._related_image_override, "path", None)
        if override:
            return override
        return self.gen_config.prompt_image_path or None

    def reset_counters(self) -> None:
        """Zero the reporting tallies. NOTE needs the lock already acquired.

        ``pending_counter`` is deliberately not among them: these are counts of
        what has been started, zeroed once print_stats has reported them, while
        pending_counter is live in-flight work. Zeroing it here would discard
        generations that are still running.
        """
        self.counter = 0
        self.latent_counter = 0

    def get_captioner(self):
        if self.captioner is None:
            # Lazy import avoids requiring BLIP/torch stack for flows that never caption.
            from sd_runner.captioner import Captioner
            self.captioner = Captioner()
        return self.captioner

    def maybe_caption_image(self, image_path: str, positive: Optional[str]) -> str:
        """A caption of *image_path* when no positive prompt was given.

        Callers pass the adapter's ``id``, not its ``generation_path``, so an
        intermediate-pass run still describes the user's original. Captioning
        the transformed image instead would put the transformation into the
        prompt -- "a pencil drawing of a house" -- and push the next pass
        further that way than the pre-pass asked for.
        """
        if not positive:
            return self.get_captioner().caption(image_path)
        return positive

    def random_skip(self) -> bool:
        skip_chance = getattr(self, 'RANDOM_SKIP_CHANCE', 0.0)
        if skip_chance > 0 and random.random() < skip_chance:
            logger.info(f"Skipping by random chance ({skip_chance*100}%)")
            return True
        return False

    def print_stats(self) -> None:
        with self._lock:
            if self.counter > 0:
                logger.info(f"Started {self.counter} prompts, {self.latent_counter} images to be saved if all complete")
            self.reset_counters()

    def print_pre(self, action: str, **kw):
        out = f"{Utils.format_white(action)} with config: "
        for item in kw.items():
            if not item[1]:
                continue
            if item[0] != "negative" or Globals.PRINT_NEGATIVES:
                out += f"\n{Utils.format_white(item[0])}: {item[1]}"
        if config.debug:
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
                                args = [_1, _2, _3, _4, _5, _6]
                                resolution = args[BaseImageGenerator.ORDER.index("resolutions")]
                                control_net = args[BaseImageGenerator.ORDER.index("control_nets")]
                                ip_adapter = args[BaseImageGenerator.ORDER.index("ip_adapters")]

                                if self.random_skip():
                                    self.gen_config.resolutions_skipped += 1
                                    continue

                                if resolution.should_be_randomly_skipped() or \
                                        self.should_skip_resolution(workflow_id, resolution, control_net, ip_adapter):
                                    self.gen_config.resolutions_skipped += 1
                                    continue

                                if not self.gen_config.register_run():
                                    break

                                model = args[BaseImageGenerator.ORDER.index("models")]
                                vae = args[BaseImageGenerator.ORDER.index("vaes")]
                                if vae is None:
                                    vae = model.get_default_vae()
                                    logger.debug(f"Set default VAE: {vae}")
                                # Chroma and ZImageTurbo models must use their specific VAE, override if needed
                                if model.is_chroma() or model.is_z_image_turbo():
                                    vae = model.get_default_vae()
                                    logger.debug(f"Overriding VAE for {model.architecture_type} model to default: {vae}")
                                model.validate_vae(vae)
                                lora = args[BaseImageGenerator.ORDER.index("loras")]
                                positive_copy = str(positive)
                                if ip_adapter:
                                    positive_copy += ip_adapter.modifiers
                                    positive_copy = ip_adapter.b_w_coloration_modifier(positive_copy)

                                # Final blacklist validation before generation
                                positive_copy = self.validate_prompt_against_blacklist(positive_copy)

                                if self.gen_config.is_redo_prompt():
                                    sw = SoftwareType[self.gen_config.software_type]
                                    if sw != SoftwareType.ComfyUI:
                                        raise Exception(f"Redo prompt is not supported for {sw.value}.")
                                    self.redo_with_different_parameter(source_file=workflow_id, model=model, vae=vae, lora=lora, resolution=resolution,
                                                                       n_latents=self.gen_config.n_latents, control_net=control_net, ip_adapter=ip_adapter)
                                    self.has_run_one_workflow = True
                                else:
                                    if not self.run_workflow(workflow_id, prompt=None, resolution=resolution, model=model, vae=vae, n_latents=n_latents, positive=positive_copy,
                                                             negative=negative, lora=lora, control_net=control_net, ip_adapter=ip_adapter):
                                        self.gen_config.resolutions_skipped += 1
        self.print_stats()
        return

    def should_skip_resolution(self, workflow_id, resolution, control_net, ip_adapter):
        return False
        # TODO if the control net or IP Adapter image is the other aspect ratio
        # (portrait vs landscape for the main resolution, or vice versa)
        # add a high chance to skip this resolution because those combinations
        # often produce incoherent results

    def run_workflow(self, workflow_id: str, **kwargs) -> bool:
        """Route to specific workflow implementation. Returns False if skipped, True if scheduled."""
        if self.random_skip():
            return False

        # Keep static selected resolutions unchanged and only randomize dimensions
        # at the final generation call boundary.
        resolution = kwargs.get("resolution")
        if (
            isinstance(resolution, Resolution)
            and getattr(self.gen_config, "dimension_variation", False)
            and not self.gen_config.is_redo_prompt()
        ):
            kwargs["resolution"] = resolution.with_random_variation()

        # Convert adapter images if needed
        control_net = kwargs.get('control_net')
        ip_adapter = kwargs.get('ip_adapter')
        converted_control_net, converted_ip_adapter = self.convert_adapter_images(control_net, ip_adapter)

        # Update kwargs with converted images
        kwargs['control_net'] = converted_control_net
        kwargs['ip_adapter'] = converted_ip_adapter

        workflow_method = self.validate_workflow(workflow_id, **kwargs)
        # Wrapped outermost so the pre-pass runs before the user's workflow and
        # any derivative of it, which derives from the user's output.
        task = self._with_intermediate_pass(
            workflow_id, self._with_second_derivative(workflow_id, workflow_method)
        )
        # schedule_generation raises the pending count itself, so that the
        # increment and its release are owned by the same pair of methods.
        self.schedule_generation(task, **kwargs)
        with self._lock:
            self.counter += 1
            self.latent_counter += kwargs.get('n_latents', 1)
            self.has_run_one_workflow = True
        time.sleep(0.2)
        return True

    def validate_workflow(self, workflow_id: str, **kwargs) -> None:
        """Validate the workflow and its parameters"""
        workflow_methods = self._get_workflows()
        if workflow_id not in workflow_methods:
            raise ValueError(f"Unknown workflow: {workflow_id}")
        if workflow_id == WorkflowType.SIMPLE_IMAGE_GEN_LORA:
            if kwargs.get("lora") is None:
                raise Exception("Image gen with lora - lora not set!")
        return workflow_methods[workflow_id]

    # ------------------------------------------------------------------
    # Intermediate pass
    # ------------------------------------------------------------------
    def _with_intermediate_pass(self, workflow_id, workflow_method: callable) -> callable:
        """Wrap *workflow_method* so a pre-pass transforms its input image first.

        Returns the method untouched when no pre-pass is configured or the
        workflow takes no image, leaving the scheduled callable unchanged.

        Unlike a second derivative this runs *before*, on the user's own source
        image rather than on an output, and with its own workflow and prompt
        rather than the user's. Everything else about the run -- model,
        resolution, strength, prompt mode -- is inherited.

        The pre-pass arrives as a plain dict so that it survives a run being
        serialized and restored; nothing here knows the UI type that produced
        it.
        """
        prompt = getattr(self.gen_config, "intermediate_prompt", None)
        if not prompt:
            return workflow_method
        field = image_input_field(workflow_id)
        if field is None:
            return workflow_method

        @functools.wraps(workflow_method)
        def with_intermediate(**kwargs):
            return workflow_method(**self._run_intermediate_pass(prompt, field, kwargs))

        return with_intermediate

    def _run_intermediate_pass(self, prompt: dict, field: str, kwargs: dict) -> dict:
        """*kwargs* with its input image swapped for the pre-pass's output.

        Returns *kwargs* unchanged when the pass cannot or should not run, so a
        pre-pass that fails to produce an image degrades to the plain run
        rather than failing it.
        """
        source = kwargs.get(field)
        if source is None:
            logger.warning("Intermediate pass skipped: no image on the run to transform")
            return kwargs

        prepass_id = self._intermediate_workflow_id(prompt)
        if prepass_id is None:
            return kwargs
        prepass_field = image_input_field(prepass_id)
        prepass_method = self._get_workflows().get(prepass_id)
        if prepass_field is None or prepass_method is None:
            logger.warning(f"Intermediate pass skipped: {prepass_id} cannot take an image")
            return kwargs

        prepass_kwargs = dict(kwargs)
        prepass_kwargs["positive"] = prompt.get("positive_tags") or ""
        if prompt.get("use_negative"):
            prepass_kwargs["negative"] = prompt.get("negative_tags") or ""
        # The pre-pass reads the image from its own workflow's field, which is
        # not necessarily the one the user's workflow reads it from.
        if prepass_field != field:
            prepass_kwargs.pop(field, None)
        prepass_kwargs[prepass_field] = self._adapter_for_field(prepass_field, source)

        intermediate_path = self._intermediate_image(
            prompt, source, prepass_method, prepass_kwargs
        )
        if intermediate_path is None:
            logger.error("Intermediate pass produced no image; running on the original")
            return kwargs

        derived = dict(kwargs)
        # generation_path moves to the intermediate; id stays on the user's real
        # source, which is what EXIF lineage and the edit-suffix rename read.
        derived[field] = self._derived_adapter(source, intermediate_path, keep_id=True)
        return derived

    def _intermediate_image(self, prompt: dict, source, prepass_method, prepass_kwargs) -> "str | None":
        """A transformed image for this pre-pass, generating it only if needed.

        The lock is held across the generation, not just the lookup: a run
        dispatches several workflows onto the shared executor at once, and
        without it they would all miss the same empty entry and all generate.
        """
        from sd_runner.runs.intermediate_cache import IntermediateCache

        key = IntermediateCache.key_for(prompt, source.id)
        max_variants = max(1, int(prompt.get("max_variants") or 1))
        with IntermediateCache.lock(key):
            if IntermediateCache.count(key) >= max_variants:
                cached = IntermediateCache.get(key)
                if cached is not None:
                    logger.info(f"Reusing cached intermediate generation: {cached}")
                    return cached

            output_paths = self._run_intermediate_generation(prepass_method, prepass_kwargs)
            if not output_paths:
                return None
            IntermediateCache.put(key, output_paths[0], max_variants)
            return output_paths[0]

    def _intermediate_workflow_id(self, prompt: dict):
        """The pre-pass's workflow, or None when it names one we cannot run."""
        raw = prompt.get("workflow_type")
        if raw is None:
            return None
        try:
            return WorkflowType.get(raw) if isinstance(raw, str) else raw
        except Exception:
            logger.warning(f"Intermediate pass skipped: unknown workflow {raw!r}")
            return None

    def _run_intermediate_generation(self, prepass_method: callable, prepass_kwargs: dict) -> list:
        """Run the pre-pass, counted as a generation and marked as intermediate.

        The mark is what keeps the output from taking the deliverable's name or
        destination; the count is what keeps the pending total honest, since
        this is a real generation the run is waiting on.
        """
        self.count_pending_dispatch()
        self._arm_pending_release()
        self._intermediate_context.active = True
        try:
            return prepass_method(**prepass_kwargs) or []
        finally:
            self._intermediate_context.active = False
            self.release_pending()

    # ------------------------------------------------------------------
    # Second derivative
    # ------------------------------------------------------------------
    def _with_second_derivative(self, workflow_id, workflow_method: callable) -> callable:
        """Wrap *workflow_method* so each image it makes is fed back through it.

        Returns the method untouched when the feature is off or the workflow
        takes no image, leaving the scheduled callable unchanged.

        The derivative runs inside the task that produced its parent rather
        than as its own job: it follows its parent immediately instead of
        landing behind unrelated work, and needs no chaining machinery, being
        the same callable with one argument changed. It also means a derived
        pass that raises fails the parent's task, after the parent's own image
        is written -- catch per pass here if that ever needs containing.
        """
        if not getattr(self.gen_config, "second_derivative", False):
            return workflow_method
        if image_input_field(workflow_id) is None:
            return workflow_method

        @functools.wraps(workflow_method)
        def with_derivative(**kwargs):
            output_paths = workflow_method(**kwargs)
            self._run_second_derivative(workflow_id, workflow_method, output_paths, kwargs)
            return output_paths

        return with_derivative

    def _run_second_derivative(self, workflow_id, workflow_method, output_paths, kwargs) -> None:
        """Re-run *workflow_method* once per produced image, on that image."""
        if not output_paths:
            # A failed generation, or a backend that does not report its output
            # paths. Nothing to derive from, but the parent image was still
            # produced and the rest of the run is unaffected.
            logger.error(
                f"Second derivative skipped for {workflow_id}: the generation reported "
                "no output image path"
            )
            return

        field = image_input_field(workflow_id)
        for parent_path in output_paths:
            derived = dict(kwargs)
            adapter = self._derived_adapter(kwargs.get(field), parent_path)
            if adapter is None:
                logger.error(
                    f"Second derivative skipped for {workflow_id}: no {field} to "
                    "carry the generated image"
                )
                return
            derived[field] = adapter

            # A derived pass is a second generation and is counted as one. Its
            # arm owes its own release, so the pass is accounted for whether it
            # reaches a backend or fails first.
            self.count_pending_dispatch()
            self._arm_pending_release()

            self._related_image_override.path = parent_path
            try:
                workflow_method(**derived)
            finally:
                self.release_pending()
                self._related_image_override.path = None

    @staticmethod
    def _derived_adapter(adapter, image_path: str, keep_id: bool = False):
        """A copy of *adapter* pointing at *image_path*.

        A copy, not a mutation: the same adapter instance is shared across
        iterations of the run loop, so writing to it would silently redirect
        later iterations at this iteration's output. Everything else --
        strength above all -- is carried over untouched, which is what makes
        the second pass the same generation rather than a different one.

        *keep_id* moves only ``generation_path``, leaving ``id`` on whatever the
        adapter already named. A second derivative wants the default, since its
        parent really is the image it was made from; a pre-pass wants ``id``
        left on the user's original, which is what EXIF lineage and the
        edit-suffix rename read.
        """
        if adapter is None:
            return None
        derived = copy(adapter)
        if not keep_id:
            derived.id = image_path
        derived.generation_path = image_path
        return derived

    @staticmethod
    def _adapter_for_field(field: str, source):
        """An adapter of the type *field* expects, carrying *source*'s image.

        A copy of *source* when it already belongs in that field; otherwise a
        fresh adapter of the other type, since a pre-pass may read its image
        from a different field than the run it precedes.
        """
        from sd_runner.models.model_adapters import ControlNet, IPAdapter

        wanted = ControlNet if field == "control_net" else IPAdapter
        if isinstance(source, wanted):
            return copy(source)
        return wanted(source.generation_path)

    def schedule_generation(self, task_fn: callable, *args, **kwargs) -> Future:
        """Submit a generation task to the shared executor.

        The pending count is raised here rather than by the caller so that it
        is paired with the release in ``_wrap_task``: everything submitted
        lowers it exactly once, including a task that raises before it reaches
        a backend.
        """
        self.count_pending_dispatch()
        try:
            with BaseImageGenerator._executor_lock:
                return self._executor.submit(
                    self._wrap_task(task_fn),
                    *args, **kwargs
                )
        except BaseException:
            # Nothing will run, so no worker will ever release what was just
            # taken. Undo it directly -- release_pending answers to the worker
            # thread's arming, not this one's.
            with self._lock:
                self.pending_counter -= 1
                self.update_ui_pending()
            raise

    def update_ui_pending(self):
        if self.ui_callbacks is not None:
            self.ui_callbacks.update_pending(self.pending_counter)

    # ------------------------------------------------------------------
    # Pending-count accounting
    #
    # One dispatch raises the count once and lowers it once. The two are
    # deliberately not paired by a single `with`, because the raise happens on
    # the dispatching thread and the lowering on a pool worker.
    # ------------------------------------------------------------------

    def count_pending_dispatch(self) -> None:
        """Record one generation as in flight."""
        with self._lock:
            self.pending_counter += 1
            self.update_ui_pending()

    def _arm_pending_release(self) -> None:
        """Record that this thread's dispatch owes one more decrement.

        A depth count rather than a flag, because the arms nest: a derived pass
        arms while its parent's arm may still be outstanding. A flag would let
        the second arm overwrite the first, and the parent's increment would
        never be released.
        """
        self._pending_release.owed = getattr(self._pending_release, "owed", 0) + 1

    def release_pending(self) -> None:
        """Account for one finished dispatch, at most once per arm.

        Backends call this where they used to decrement directly, so the count
        still drops the moment a generation finishes. ``_wrap_task`` calls it
        again as the task unwinds, which is what catches a failure that never
        reached a backend at all. A release with nothing owed is a no-op, so
        the two callers cannot both spend the same increment.

        Takes ``_lock`` itself, and ``_lock`` is not reentrant -- never call
        this from inside a ``with self._lock`` block.
        """
        owed = getattr(self._pending_release, "owed", 0)
        if owed <= 0:
            return
        self._pending_release.owed = owed - 1
        with self._lock:
            self.pending_counter -= 1
            self.update_ui_pending()

    def _wrap_task(self, task_fn: callable) -> callable:
        """Add common error handling and logging"""
        def wrapped(*args, **kwargs):
            # First statement, so that anything below failing still leaves the
            # dispatch accountable to the release in the finally.
            self._arm_pending_release()
            # What this thread is generating, for the backend to attribute its
            # timing to. Set here rather than passed down because the workflow
            # methods all reach queue_prompt without carrying their arguments
            # that far. The duration itself is NOT this method's start_time
            # below: that includes the wait behind other prompts in the
            # backend's queue, which is not a cost of this image.
            self._timing_context.descriptors = self._timing_descriptors(kwargs)
            try:
                logger.debug(f"Starting {task_fn.__name__}")
                start_time = time.time()
                result = task_fn(*args, **kwargs)
                logger.debug(f"Completed {task_fn.__name__} in {time.time()-start_time:.2f}s")
                # Record recently used adapter files when a task completes
                try:
                    control_net = kwargs.get("control_net")
                    ip_adapter = kwargs.get("ip_adapter")
                    prompt_image_path = getattr(self.gen_config, "prompt_image_path", "")
                    self._record_recent_adapters(control_net, ip_adapter, prompt_image_path)
                except Exception:
                    pass
                return result
            except Exception as e:
                self._handle_error(e, task_fn.__name__)
                raise
            finally:
                # Catches a dispatch the backend never got to account for.
                # A no-op when the backend already released it.
                self.release_pending()
                # Pool threads are reused; a stale context would attribute the
                # next task's duration to this task's model.
                self._timing_context.descriptors = None
        return wrapped

    def _record_recent_adapters(self, control_net, ip_adapter, prompt_image_path: str = "") -> None:
        """Record adapters/source prompt used for a started generation."""
        if self.ui_callbacks is None:
            return
        if control_net is not None and hasattr(control_net, "id") and control_net.id:
            self.ui_callbacks.add_recent_adapter_file(control_net.id)
        if ip_adapter is not None and hasattr(ip_adapter, "id") and ip_adapter.id:
            self.ui_callbacks.add_recent_adapter_file(ip_adapter.id)
        if prompt_image_path and hasattr(self.ui_callbacks, "add_recent_source_prompt"):
            self.ui_callbacks.add_recent_source_prompt(prompt_image_path)

    def _handle_error(self, error: Exception, task_name: str) -> None:
        from sd_runner.image_converter import ImageHandlingError
        
        if isinstance(error, ImageHandlingError):
            # For image handling errors, they should already be logged by the converter
            pass
        else:
            # For other errors, log and show traceback in debug mode
            logger.warning(f"Error in {task_name}: {str(error)}")
            if config.debug:
                traceback.print_exc()

    def validate_prompt_against_blacklist(self, prompt: str) -> str:
        """Validate a prompt against the blacklist and return the filtered version.
        
        Args:
            prompt: The prompt to validate
            
        Returns:
            str: The filtered prompt with blacklisted terms removed
        """
        concepts = [c.strip() for c in prompt.split(',')]
        whitelist, filtered = Blacklist.filter_concepts(concepts, prompt_mode=self.gen_config.get_prompt_mode())
        
        if len(filtered) > 0:
            if config.debug:
                print(f"Filtered concepts from blacklisted tags: {filtered}")        
            return ', '.join(whitelist)
        else:
            return prompt

    def convert_adapter_images(self, control_net=None, ip_adapter=None) -> tuple:
        """
        Convert adapter images to standard formats if needed.
        
        Each adapter is updated **in place**: ``generation_path`` is pointed at
        the converted file while ``id`` keeps naming the user's original, which
        is what EXIF lineage and the edit-suffix rename read. The same objects
        are returned for convenience, not as copies.

        Args:
            control_net: ControlNet adapter object
            ip_adapter: IP Adapter object

        Returns:
            tuple: the same (control_net, ip_adapter) passed in, now carrying
            converted ``generation_path`` values

        Raises:
            ConversionFailedError: If image conversion fails and is required
        """
        # Convert control_net image if needed
        if control_net and hasattr(control_net, 'id') and control_net.id:
            converted_path = convert_image_if_needed(control_net.id)
            control_net.generation_path = converted_path
            if converted_path != control_net.id:
                logger.info(f"Converted control_net image: {control_net.id} -> {converted_path}")
        
        # Convert ip_adapter image if needed
        if ip_adapter and hasattr(ip_adapter, 'id') and ip_adapter.id:
            converted_path = convert_image_if_needed(ip_adapter.id)
            ip_adapter.generation_path = converted_path
            if converted_path != ip_adapter.id:
                logger.info(f"Converted ip_adapter image: {ip_adapter.id} -> {converted_path}")
        
        return control_net, ip_adapter

    @staticmethod
    def rename_to_edit_suffix(save_path: str, related_image_path: str, edit_suffix: str) -> str:
        """Rename a generated edit output to {source_stem}{edit_suffix}{ext}, resolving collisions.

        Collision detection consults the application's edit history before the
        filesystem, so a counter suffix is added even when a prior output has
        been moved out of the directory.

        Returns the final on-disk path after renaming.
        """
        from utils.app_info_cache import app_info_cache
        stem = Path(related_image_path).stem
        ext = Path(save_path).suffix
        dest_dir = os.path.dirname(save_path)
        separator = " " if " " in stem else "_"
        new_path = os.path.join(dest_dir, f"{stem}{separator}{edit_suffix}{ext}")
        if app_info_cache.edit_output_exists(os.path.basename(new_path)) or os.path.exists(new_path):
            base = new_path[:-len(ext)]
            i = 2
            while True:
                candidate = f"{base}_{i}{ext}"
                if not app_info_cache.edit_output_exists(os.path.basename(candidate)) and not os.path.exists(candidate):
                    break
                i += 1
            new_path = candidate
        os.rename(save_path, new_path)
        app_info_cache.record_edit_output(os.path.basename(new_path))
        logger.debug(f"Renamed edit output: {save_path} -> {new_path}")
        return new_path

    @staticmethod
    def _normalize_target_dir(target_dir: str | None) -> str | None:
        if target_dir is None:
            return None
        normalized = str(target_dir).strip()
        if not normalized:
            return None
        if "{HOME}" in normalized:
            normalized = normalized.replace("{HOME}", os.path.expanduser("~"))
        normalized = os.path.normpath(normalized.replace("\\", os.sep))
        if not os.path.isdir(normalized):
            logger.warning(f"target_dir is not a valid directory, skipping move: {normalized}")
            return None
        return normalized

    @staticmethod
    def move_to_target_dir(save_path: str, target_dir: str | None) -> str:
        """Move *save_path* into *target_dir* when it is a valid directory.

        Returns the final path (unchanged when no move is performed).
        """
        dest_dir = BaseImageGenerator._normalize_target_dir(target_dir)
        if dest_dir is None or not save_path:
            return save_path
        if not os.path.isfile(save_path):
            logger.warning(f"target_dir move skipped, output file not found: {save_path}")
            return save_path

        filename = os.path.basename(save_path)
        dest_path = os.path.join(dest_dir, filename)
        if os.path.exists(dest_path):
            stem, ext = os.path.splitext(filename)
            i = 2
            while os.path.exists(dest_path):
                dest_path = os.path.join(dest_dir, f"{stem}_{i}{ext}")
                i += 1

        shutil.move(save_path, dest_path)
        logger.info(f"Moved output to target_dir: {save_path} -> {dest_path}")
        return dest_path

    @staticmethod
    def apply_output_postprocessing(
        save_path: str,
        target_dir: str | None,
        edit_suffix: str = "",
        related_image_path: str | None = None,
    ) -> str:
        """Rename for edit workflows, then relocate to ``target_dir`` when configured."""
        if edit_suffix and related_image_path:
            save_path = BaseImageGenerator.rename_to_edit_suffix(
                save_path, related_image_path, edit_suffix
            )
        return BaseImageGenerator.move_to_target_dir(save_path, target_dir)

    @staticmethod
    def recover_related_image_path(image_path: str) -> str | None:
        """The input image a previously generated image was produced from.

        Every generator records this through finalize_output_path, so reading it
        back is not specific to any backend. It matters most where the backend's
        own metadata omits the input: A1111 notes that ControlNet ran and with
        what settings but never on which image, so this is what allows such a
        generation to be rebuilt.

        Returns None when nothing was recorded, when the image came from another
        tool, or when the recorded path no longer resolves -- it is a path from
        the generating machine and the file may since have moved.
        """
        try:
            related = Globals.get_image_data_extractor().get_related_image_path(image_path)
        except Exception as e:
            logger.warning(f"Could not read the related image path: {e}")
            return None
        if not related:
            return None
        if not os.path.isfile(related):
            logger.warning(f"Recorded source image no longer exists: {related}")
            return None
        return related

    def is_producing_intermediate(self) -> bool:
        """Whether this thread's generation is a pre-pass rather than the run's."""
        return bool(getattr(self._intermediate_context, "active", False))

    def output_treatments(self) -> tuple:
        """The (edit_suffix, target_dir) this thread's output should receive.

        Both are dropped for a pre-pass intermediate. It is a real generated
        image and is kept, but it is not the run's output, so it must not take
        the deliverable's name or be moved into the target directory. Skipping
        the rename also skips the edit-history record, which lives inside it.
        """
        if self.is_producing_intermediate():
            return "", None
        return self.gen_config.active_edit_suffix, getattr(self.gen_config, "target_dir", None)

    def _output_related_image_path(self, related_image_path: str | None = None) -> str | None:
        if related_image_path:
            return related_image_path
        prompt_image = getattr(self.gen_config, "prompt_image_path", "") or ""
        return prompt_image or None

    def finalize_output_path(self, save_path: str, related_image_path: str | None = None) -> str:
        """Apply edit-suffix rename and ``target_dir`` relocation after save."""
        edit_suffix, target_dir = self.output_treatments()
        return BaseImageGenerator.apply_output_postprocessing(
            save_path,
            target_dir,
            edit_suffix,
            self._output_related_image_path(related_image_path),
        )

    # Abstract methods to be implemented per generator -------------------------

    @abstractmethod
    def _get_workflows(self) -> dict:
        """Return a dictionary mapping workflow IDs to methods"""
        pass

    @abstractmethod
    def prompt_setup(self, workflow_type: WorkflowType, action: str, prompt: Optional[WorkflowPrompt], model: Model, vae=None, resolution=None, **kw):
        pass

    @abstractmethod
    def simple_image_gen(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, **kw):
        pass

    @abstractmethod
    def simple_image_gen_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, **kw):
        pass

    @abstractmethod
    def upscale_simple(self, prompt="", model=None, control_net=None, **kw):
        pass

    @abstractmethod
    def control_net(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, **kw):
        pass

    @abstractmethod
    def ip_adapter(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        pass

    @abstractmethod
    def img2img(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        pass

    @abstractmethod
    def instant_lora(self, prompt="", resolution=None, model=None, vae=None, n_latents=None, positive=None, negative=None, lora=None, control_net=None, ip_adapter=None, **kw):
        pass

    @abstractmethod
    def redo_with_different_parameter(self, source_file="", resolution=None, model=None, vae=None,
                                      lora=None, positive=None, negative=None, n_latents=None,
                                      control_net=None, ip_adapter=None, **kw):
        pass
