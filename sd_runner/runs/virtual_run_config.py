"""Build a ``RunConfig`` for a server request without reading the UI.

A server-triggered run used to be assembled by writing the request's values into
the sidebar widgets and reading them straight back out through ``get_args()``.
That made a remote request mutate what the user was looking at, overwrite their
saved settings, and forced the whole read/write cycle to happen on the main
thread while the listener blocked.

This module builds the same ``RunConfig`` from stored state instead: the base
comes from ``RunnerAppConfig``, and the request's own args are overlaid on top.
Nothing here imports Qt, so the result can be constructed and asserted without
an ``AppWindow``.

``RunnerAppConfig`` is the source, so it has to be current when the base is
taken. In a process that has a sidebar it is not current on its own -- most of
the run fields have no change handler and are written back only when the user
starts a run -- so the caller writes the widgets through first. That is why the
base is taken through ``RunController._snapshot_for_server_run`` rather than
here.

Only commands that carry their own parameters go through here.
``CommandKind.CONTEXTUAL_GENERATE`` (``last_settings``) means "reuse whatever is
currently set", which is a widget read by definition, and ``CommandKind.STATE``
commands never reach a run at all.
"""

from copy import deepcopy

from sd_runner.runs.run_config import RunConfig
from utils.globals import (
    CONTROL_NET_IMAGE_WORKFLOWS, IP_ADAPTER_IMAGE_WORKFLOWS,
    PromptMode, Sampler, Scheduler, WorkflowType,
)
from utils.logging_setup import get_logger

logger = get_logger("runs.virtual_run_config")


def escape_path(path: str) -> str:
    """Escape a path for a comma-separated adapter field.

    These fields hold several paths joined by commas, so a comma inside one
    would otherwise split it into two nonexistent files.
    """
    return str(path or "").replace(",", "\\,")


def _join(existing: str, addition: str, append: bool) -> str:
    """Return *addition*, or both joined, when appending to a non-empty value."""
    existing = str(existing or "").strip()
    if append and existing:
        return existing + "," + addition
    return addition


def _to_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _to_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def base_args_from_app_config(runner_app_config) -> dict:
    """Snapshot ``RunnerAppConfig`` as the plain dict ``RunConfig`` accepts.

    The stored values are already in the form the run wants: ``software_type``
    and ``workflow_type`` are enum *names*, and ``resolution_group`` is a name
    that ``ResolutionGroup.get`` accepts alongside its display description. The
    widget path converts display text back into these; starting from the stored
    values skips the round trip rather than reproducing it.
    """
    cfg = runner_app_config
    # sparse_mixed_tags is stored on RunnerAppConfig and read off the prompter
    # config, so the copy the run carries has to be told about it.
    prompter_config = cfg.get_prompter_config_copy()
    if prompter_config is not None:
        prompter_config.sparse_mixed_tags = cfg.sparse_mixed_tags
    return {
        "software_type": cfg.software_type,
        "auto_run": True,
        "workflow_tag": cfg.workflow_type,
        "n_latents": _to_int(cfg.n_latents, 1),
        "total": _to_int(cfg.total, 1),
        "batch_limit": _to_int(cfg.batch_limit, -1),
        "res_tags": cfg.resolutions,
        "resolution_group": cfg.resolution_group,
        "model_tags": cfg.model_tags,
        "lora_tags": cfg.lora_tags,
        "override_resolution": bool(cfg.override_resolution),
        "inpainting": bool(cfg.inpainting),
        "continuous_seed_variation": bool(cfg.continuous_seed_variation),
        "dimension_variation": bool(cfg.dimension_variation),
        "second_derivative": bool(getattr(cfg, "second_derivative", False)),
        "seed": _to_int(cfg.seed, -1),
        "steps": _to_int(cfg.steps, -1),
        "cfg": _to_float(cfg.cfg, -1.0),
        "denoise": _to_float(cfg.denoise, -1.0),
        "sampler": Sampler.get(cfg.sampler),
        "scheduler": Scheduler.get(cfg.scheduler),
        "b_w_colorization": cfg.b_w_colorization,
        "control_nets": cfg.control_net_file,
        "control_net_strength": _to_float(cfg.control_net_strength, 1.0),
        "ip_adapters": cfg.ip_adapter_file,
        "ip_adapter_strength": _to_float(cfg.ip_adapter_strength, 1.0),
        "source_prompts": cfg.source_prompt_file,
        "source_prompts_add_user_prompt": bool(cfg.source_prompt_add_user_prompt),
        "redo_params": cfg.redo_params,
        "edit_suffix": cfg.edit_suffix,
        "target_dir": cfg.target_dir or None,
        "prompter_config": prompter_config,
        # Prompt text reaches a run through process-wide Prompter/Globals state
        # rather than through RunConfig, so it has to be carried here explicitly
        # or the run would generate from whatever the sidebar last pushed.
        # See apply_prompt_globals.
        "positive_tags": cfg.positive_tags,
        "negative_tags": cfg.negative_tags,
        "prompt_massage_tags": cfg.prompt_massage_tags,
        "exclusion_tags": cfg.exclusion_tags,
        # Carried for the same reason: BaseImageGenerator and Prompter hold
        # these process-wide, and apply_prompt_globals sets them at run start.
        "random_skip_chance": cfg.random_skip_chance,
        "tags_apply_to_start": cfg.tags_apply_to_start,
    }


#: Set by get_args() as plain attributes after RunConfig is built, because
#: RunConfig.__init__ does not read them from its args dict. Downstream code
#: reaches them by attribute, so the virtual path has to set them the same way.
ATTRIBUTE_ONLY_FIELDS = (
    "b_w_colorization",
    "control_net_strength",
    "ip_adapter_strength",
    "edit_suffix",
    "redo_params",
    "positive_tags",
    "negative_tags",
    "prompt_massage_tags",
    "exclusion_tags",
)


def carries_prompt_text(run_config) -> bool:
    """Whether a run brought its own prompt text for apply_prompt_globals."""
    return getattr(run_config, "positive_tags", None) is not None


def apply_prompt_globals(run_config) -> None:
    """Push a run's prompt settings into the process-wide Prompter/Globals state.

    Prompt tags, the random skip chance and the tags-at-start flag are not read
    off the run config at generation time -- they are read off ``Prompter``,
    ``Globals`` and ``BaseImageGenerator``. Applying them when the run starts
    rather than when it is queued is what keeps a queued run from generating
    with values some later run pushed while it waited.

    Every field is applied only when the run carries it. A run config assembled
    without going through either run path carries none of them; leave the
    existing state alone rather than blanking it.
    """
    from sd_runner.prompter import Prompter
    from utils.globals import Globals

    if carries_prompt_text(run_config):
        Globals.set_prompt_massage_tags(getattr(run_config, "prompt_massage_tags", "") or "")
        Prompter.set_positive_tags(getattr(run_config, "positive_tags", "") or "")
        Prompter.set_negative_tags(getattr(run_config, "negative_tags", "") or "")
        Prompter.set_exclusion_tags(getattr(run_config, "exclusion_tags", "") or "")

    skip_chance = getattr(run_config, "random_skip_chance", None)
    if skip_chance is not None:
        from sd_runner.generators.base import BaseImageGenerator
        try:
            BaseImageGenerator.RANDOM_SKIP_CHANCE = float(skip_chance)
        except (TypeError, ValueError):
            logger.warning(f"Ignoring unreadable random_skip_chance: {skip_chance!r}")

    tags_apply_to_start = getattr(run_config, "tags_apply_to_start", None)
    if tags_apply_to_start is not None:
        Prompter.set_tags_apply_to_start(tags_apply_to_start)


def apply_preset(args: dict, preset) -> dict:
    """Overlay a preset's fields, mirroring what the sidebar applies from one.

    ``set_widgets_from_preset`` sets four things -- prompt mode, positive tags,
    negative tags, edit suffix -- so those are what a preset means here. The
    run-preset-schedule checkbox it also touches is UI-only state.
    """
    prompt_mode = getattr(preset, "prompt_mode", None)
    if prompt_mode is not None and args.get("prompter_config") is not None:
        try:
            args["prompter_config"].prompt_mode = PromptMode.get(prompt_mode)
        except Exception:
            logger.warning(f"Preset carried an unrecognised prompt mode: {prompt_mode!r}")
    args["positive_tags"] = getattr(preset, "positive_tags", "")
    args["negative_tags"] = getattr(preset, "negative_tags", "")
    args["edit_suffix"] = getattr(preset, "edit_suffix", "")
    return args


def apply_request_args(args: dict, workflow_type, request: dict) -> dict:
    """Overlay one server request's own parameters onto the base *args*.

    Mirrors what the widget-backed path wrote into the sidebar, including
    ``append`` -- which there meant "add to what the field already holds" and
    here means "add to the stored value", the same value the field was showing.
    """
    request = request or {}
    append = bool(request.get("append"))

    if "target_dir" in request:
        args["target_dir"] = str(request["target_dir"] or "") or None

    if "source_prompt" in request:
        args["source_prompts"] = _join(
            args.get("source_prompts"), escape_path(request["source_prompt"]), append
        )

    # An explicit prompt seeds the generation; the prompter still decorates it.
    # RunConfig has carried these fields all along and falls back to the
    # configured defaults when they are unset -- only the server handler never
    # populated them, so a client sending a prompt was silently ignored.
    if request.get("positive_prompt") is not None:
        args["positive_prompt"] = request["positive_prompt"]
    if request.get("negative_prompt") is not None:
        args["negative_prompt"] = request["negative_prompt"]

    if "image" in request:
        image_path = escape_path(request["image"])
        if workflow_type in CONTROL_NET_IMAGE_WORKFLOWS:
            args["control_nets"] = _join(args.get("control_nets"), image_path, append)
        elif workflow_type in IP_ADAPTER_IMAGE_WORKFLOWS:
            args["ip_adapters"] = _join(args.get("ip_adapters"), image_path, append)
        else:
            logger.warning(
                f"Server request carried an image but {workflow_type} has nowhere to put it"
            )

    # Applied after "image" and for every workflow, not just IMAGE_EDIT: naming
    # the control net explicitly is more specific than the generic image slot,
    # so it wins where a workflow routes both to the same field.
    if "control_net" in request:
        args["control_nets"] = _join(
            args.get("control_nets"), escape_path(request["control_net"]), append
        )

    return args


def build_virtual_run_config(runner_app_config, command_type, request: dict, preset=None):
    """Build a ``RunConfig`` for one server request, reading no widgets.

    *preset* is resolved by the caller when the request carries an
    ``edit_suffix``; looking it up here would pull in the presets window.
    """
    return build_from_base_args(
        base_args_from_app_config(runner_app_config), command_type, request, preset=preset
    )


def build_from_base_args(base_args: dict, command_type, request: dict, preset=None):
    """Overlay a request onto an already-taken base snapshot.

    Split from ``build_virtual_run_config`` so a caller on a worker thread can
    take the snapshot on the GUI thread -- ``RunnerAppConfig`` is shared mutable
    state that the sidebar writes as the user types, and reading its two dozen
    fields off-thread could otherwise catch it mid-update. Everything from here
    down works on the snapshot and touches nothing shared.
    """
    args = dict(base_args)

    # The command's own workflow wins over the stored one. take_prompt selects
    # none, so it inherits whichever workflow is stored -- the widget path let
    # it inherit whatever the combo happened to show.
    workflow_type = command_type.workflow_type
    if workflow_type is not None:
        args["workflow_tag"] = workflow_type.name
    else:
        try:
            workflow_type = WorkflowType[args["workflow_tag"]]
        except (KeyError, TypeError):
            workflow_type = None

    if preset is not None:
        args = apply_preset(args, preset)

    args = apply_request_args(args, workflow_type, request)

    # A source prompt means the prompt is taken from an image rather than
    # generated, which is what TAKE mode does. The widget path forces this for
    # the same reason.
    if str(args.get("source_prompts") or "").strip() and args.get("prompter_config") is not None:
        args["prompter_config"].prompt_mode = PromptMode.TAKE

    # REDO_PROMPT carries its redo target in workflow_tag rather than in
    # control_nets -- an established contract of the redo path, not a quirk of
    # how the sidebar stored it.
    if args["workflow_tag"] == WorkflowType.REDO_PROMPT.name:
        args["workflow_tag"] = args.get("control_nets") or ""

    prompter_config = args.get("prompter_config")
    if prompter_config is not None:
        prompter_config.original_positive_tags = args.get("positive_tags", "")
        prompter_config.original_negative_tags = args.get("negative_tags", "")

    run_config = RunConfig(args=deepcopy(args))
    for field in ATTRIBUTE_ONLY_FIELDS:
        setattr(run_config, field, args.get(field))
    return run_config
