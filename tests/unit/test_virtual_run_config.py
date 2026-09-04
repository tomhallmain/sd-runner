"""Building a server run's RunConfig without the UI.

A server request used to be written into the sidebar widgets and read straight
back out, so a remote run mutated what the user had open and depended on it.
These build the same config from stored state instead. That this module needs
no AppWindow -- no Qt at all -- is itself part of what the change bought.
"""

from types import SimpleNamespace

import pytest

from extensions.sd_runner_server import CommandType
from sd_runner.virtual_run_config import (
    ATTRIBUTE_ONLY_FIELDS,
    apply_preset,
    apply_prompt_globals,
    apply_request_args,
    base_args_from_app_config,
    build_virtual_run_config,
    escape_path,
)
from utils.globals import PromptMode, WorkflowType
from utils.runner_app_config import RunnerAppConfig


@pytest.fixture
def app_config():
    cfg = RunnerAppConfig()
    cfg.model_tags = "somemodel"
    cfg.positive_tags = "user positive"
    cfg.negative_tags = "user negative"
    return cfg


def build(cfg, command, request=None, preset=None):
    return build_virtual_run_config(cfg, command, request or {}, preset=preset)


# ---------------------------------------------------------------------------
# The base snapshot
# ---------------------------------------------------------------------------

class TestBaseSnapshot:
    def test_stored_values_are_already_in_run_config_form(self, app_config):
        """software_type and workflow_tag are enum names on both sides."""
        args = base_args_from_app_config(app_config)
        assert args["software_type"] == app_config.software_type
        assert args["workflow_tag"] == app_config.workflow_type

    def test_resolution_group_is_accepted_by_its_own_parser(self, app_config):
        """The widget path passes a display description; the stored name also resolves."""
        from utils.globals import ResolutionGroup
        args = base_args_from_app_config(app_config)
        assert ResolutionGroup.get(args["resolution_group"]) is not None

    def test_numeric_fields_are_coerced(self, app_config):
        app_config.n_latents = "3"
        app_config.total = "7"
        args = base_args_from_app_config(app_config)
        assert args["n_latents"] == 3
        assert args["total"] == 7

    def test_unparseable_numbers_fall_back(self, app_config):
        app_config.seed = "not a number"
        assert base_args_from_app_config(app_config)["seed"] == -1

    def test_prompter_config_is_a_copy(self, app_config):
        """Mutating the run's copy must not reach the stored config."""
        args = base_args_from_app_config(app_config)
        args["prompter_config"].prompt_mode = PromptMode.NSFW
        assert app_config.prompter_config.prompt_mode is not PromptMode.NSFW

    def test_prompt_text_is_carried(self, app_config):
        """It reaches generation via process globals, so it must ride along."""
        args = base_args_from_app_config(app_config)
        assert args["positive_tags"] == "user positive"
        assert args["negative_tags"] == "user negative"


# ---------------------------------------------------------------------------
# Workflow selection
# ---------------------------------------------------------------------------

class TestWorkflowSelection:
    def test_command_workflow_overrides_the_stored_one(self, app_config):
        run_config = build(app_config, CommandType.RENOISER)
        assert run_config.workflow_tag == WorkflowType.RENOISER.name

    def test_take_prompt_inherits_the_stored_workflow(self, app_config):
        """It carries a source prompt but selects no workflow of its own."""
        app_config.workflow_type = WorkflowType.SIMPLE_IMAGE_GEN_LORA.name
        run_config = build(app_config, CommandType.TAKE_PROMPT, {"source_prompt": "a.png"})
        assert run_config.workflow_tag == WorkflowType.SIMPLE_IMAGE_GEN_LORA.name

    def test_redo_prompt_moves_its_target_into_the_workflow_tag(self, app_config):
        run_config = build(app_config, CommandType.REDO_PROMPT, {"image": "redo.png"})
        assert run_config.workflow_tag == "redo.png"


# ---------------------------------------------------------------------------
# Request overlay
# ---------------------------------------------------------------------------

class TestImageRouting:
    @pytest.mark.parametrize("command", [CommandType.CONTROL_NET, CommandType.RENOISER])
    def test_control_net_workflows_take_the_image_as_a_control_net(self, app_config, command):
        run_config = build(app_config, command, {"image": "in.png"})
        assert run_config.control_nets == "in.png"

    @pytest.mark.parametrize("command", [
        CommandType.IP_ADAPTER, CommandType.IMG2IMG, CommandType.IMAGE_EDIT,
    ])
    def test_ip_adapter_workflows_take_the_image_as_an_ip_adapter(self, app_config, command):
        run_config = build(app_config, command, {"image": "in.png"})
        assert run_config.ip_adapters == "in.png"

    def test_image_edit_also_accepts_an_explicit_control_net(self, app_config):
        run_config = build(
            app_config, CommandType.IMAGE_EDIT, {"image": "a.png", "control_net": "cn.png"}
        )
        assert run_config.ip_adapters == "a.png"
        assert run_config.control_nets == "cn.png"

    def test_commas_in_a_path_are_escaped(self, app_config):
        """These fields join several paths with commas."""
        run_config = build(app_config, CommandType.CONTROL_NET, {"image": "a,b.png"})
        assert run_config.control_nets == "a\\,b.png"


class TestImageRoutingForWorkflowsWithoutACommand:
    """Routing is keyed on the workflow, not the command that selected it.

    No `CommandType` selects these yet, so they are exercised through
    `apply_request_args` directly. They were previously absent from both
    workflow tuples, so an image sent for one of them hit the fallback branch
    and was dropped with a warning rather than routed.
    """

    @pytest.mark.parametrize("workflow_type, field", [
        (WorkflowType.INSTANT_LORA, "ip_adapters"),
        (WorkflowType.INPAINT_CLIPSEG, "control_nets"),
        (WorkflowType.UPSCALE_SIMPLE, "control_nets"),
        (WorkflowType.UPSCALE_BETTER, "control_nets"),
    ])
    def test_the_image_reaches_the_field_the_workflow_reads(
        self, workflow_type, field
    ):
        args = apply_request_args({}, workflow_type, {"image": "in.png"})
        assert args[field] == "in.png"

    def test_instant_lora_can_take_both_images(self):
        """Its structural image is still nameable alongside the content one."""
        args = apply_request_args(
            {}, WorkflowType.INSTANT_LORA, {"image": "a.png", "control_net": "cn.png"}
        )
        assert args["ip_adapters"] == "a.png"
        assert args["control_nets"] == "cn.png"

    def test_a_workflow_that_takes_no_image_still_drops_it(self):
        args = apply_request_args({}, WorkflowType.SIMPLE_IMAGE_GEN, {"image": "in.png"})
        assert not args.get("control_nets")
        assert not args.get("ip_adapters")


class TestExplicitControlNet:
    """`control_net` names the control net regardless of workflow.

    It used to be read only for IMAGE_EDIT and dropped everywhere else, which
    made it useless for the control net workflow itself. The main client only
    ever sends `image`, so widening this can only add capability.
    """

    def test_honoured_for_the_control_net_workflow(self, app_config):
        run_config = build(app_config, CommandType.CONTROL_NET, {"control_net": "cn.png"})
        assert run_config.control_nets == "cn.png"

    def test_honoured_for_renoiser(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"control_net": "cn.png"})
        assert run_config.control_nets == "cn.png"

    def test_explicit_control_net_wins_over_the_generic_image(self, app_config):
        """Naming the field is more specific than the generic image slot."""
        run_config = build(
            app_config, CommandType.CONTROL_NET, {"image": "img.png", "control_net": "cn.png"}
        )
        assert run_config.control_nets == "cn.png"

    def test_image_edit_still_routes_both(self, app_config):
        run_config = build(
            app_config, CommandType.IMAGE_EDIT, {"image": "a.png", "control_net": "cn.png"}
        )
        assert run_config.ip_adapters == "a.png"
        assert run_config.control_nets == "cn.png"


class TestExplicitPrompts:
    """The client sends these; the server used to drop them on the floor.

    RunConfig has carried the fields all along and falls back to the configured
    defaults when unset, so populating them was the only missing link.
    """

    def test_positive_prompt_is_honoured(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"positive_prompt": "a red car"})
        assert run_config.positive_prompt == "a red car"

    def test_negative_prompt_is_honoured(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"negative_prompt": "blurry"})
        assert run_config.negative_prompt == "blurry"

    def test_absent_prompts_stay_unset(self, app_config):
        """Unset means "use the configured default", which the run resolves."""
        run_config = build(app_config, CommandType.RENOISER, {"image": "a.png"})
        assert run_config.positive_prompt is None
        assert run_config.negative_prompt is None

    def test_an_empty_prompt_is_kept_distinct_from_absent(self, app_config):
        """The client omits the key rather than sending None, so "" is deliberate."""
        run_config = build(app_config, CommandType.RENOISER, {"positive_prompt": ""})
        assert run_config.positive_prompt == ""

    def test_prompts_do_not_disturb_the_tag_fields(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"positive_prompt": "a red car"})
        assert run_config.positive_tags == "user positive"


class TestAppend:
    def test_append_extends_the_stored_value(self, app_config):
        app_config.control_net_file = "existing.png"
        run_config = build(app_config, CommandType.CONTROL_NET, {"image": "new.png", "append": True})
        assert run_config.control_nets == "existing.png,new.png"

    def test_without_append_the_request_replaces(self, app_config):
        app_config.control_net_file = "existing.png"
        run_config = build(app_config, CommandType.CONTROL_NET, {"image": "new.png"})
        assert run_config.control_nets == "new.png"

    def test_append_to_an_empty_value_does_not_leave_a_separator(self, app_config):
        app_config.control_net_file = ""
        run_config = build(app_config, CommandType.CONTROL_NET, {"image": "new.png", "append": True})
        assert run_config.control_nets == "new.png"


class TestOtherArgs:
    def test_target_dir_is_overlaid(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"target_dir": "/out"})
        assert run_config.target_dir == "/out"

    def test_empty_target_dir_becomes_none(self, app_config):
        run_config = build(app_config, CommandType.RENOISER, {"target_dir": ""})
        assert run_config.target_dir is None

    def test_a_source_prompt_forces_take_mode(self, app_config):
        """The prompt comes from an image rather than being generated."""
        run_config = build(app_config, CommandType.TAKE_PROMPT, {"source_prompt": "a.png"})
        assert run_config.prompter_config.prompt_mode is PromptMode.TAKE

    def test_no_source_prompt_leaves_the_mode_alone(self, app_config):
        app_config.prompter_config.prompt_mode = PromptMode.SFW
        run_config = build(app_config, CommandType.RENOISER, {"image": "a.png"})
        assert run_config.prompter_config.prompt_mode is PromptMode.SFW


# ---------------------------------------------------------------------------
# Presets — the edit_suffix path, previously a direct widget overwrite
# ---------------------------------------------------------------------------

class FakePreset:
    name = "test preset"
    prompt_mode = PromptMode.NSFW.name
    positive_tags = "preset positive"
    negative_tags = "preset negative"
    edit_suffix = "_edited"


class TestPresetOverlay:
    def test_preset_replaces_the_prompt_text(self, app_config):
        run_config = build(app_config, CommandType.IMAGE_EDIT, {}, preset=FakePreset())
        assert run_config.positive_tags == "preset positive"
        assert run_config.negative_tags == "preset negative"

    def test_preset_sets_the_prompt_mode(self, app_config):
        run_config = build(app_config, CommandType.IMAGE_EDIT, {}, preset=FakePreset())
        assert run_config.prompter_config.prompt_mode is PromptMode.NSFW

    def test_preset_sets_the_edit_suffix(self, app_config):
        run_config = build(app_config, CommandType.IMAGE_EDIT, {}, preset=FakePreset())
        assert run_config.edit_suffix == "_edited"

    def test_an_unrecognised_prompt_mode_is_survivable(self, app_config):
        """A bad preset should not take the run down with it."""
        preset = FakePreset()
        preset.prompt_mode = "not a mode"
        run_config = build(app_config, CommandType.IMAGE_EDIT, {}, preset=preset)
        assert run_config.positive_tags == "preset positive"

    def test_no_preset_keeps_the_stored_text(self, app_config):
        run_config = build(app_config, CommandType.IMAGE_EDIT, {})
        assert run_config.positive_tags == "user positive"

    def test_apply_preset_tolerates_a_missing_prompter_config(self):
        assert apply_preset({"prompter_config": None}, FakePreset())["edit_suffix"] == "_edited"


# ---------------------------------------------------------------------------
# Shape of the result
# ---------------------------------------------------------------------------

class TestResultShape:
    @pytest.mark.parametrize("field", ATTRIBUTE_ONLY_FIELDS)
    def test_attribute_only_fields_are_set(self, app_config, field):
        """RunConfig.__init__ ignores these; downstream reads them by attribute."""
        run_config = build(app_config, CommandType.RENOISER)
        assert hasattr(run_config, field)

    def test_original_tags_are_recorded_for_metadata(self, app_config):
        run_config = build(app_config, CommandType.RENOISER)
        assert run_config.prompter_config.original_positive_tags == "user positive"

    def test_the_stored_config_is_not_mutated(self, app_config):
        """The whole point: a server request must not disturb the user's state."""
        before = dict(vars(app_config))
        build(app_config, CommandType.CONTROL_NET,
              {"image": "x.png", "target_dir": "/out", "append": True})
        after = dict(vars(app_config))
        assert before == after


class TestEscapePath:
    def test_plain_path_unchanged(self):
        assert escape_path("a.png") == "a.png"

    def test_comma_escaped(self):
        assert escape_path("a,b.png") == "a\\,b.png"

    def test_none_becomes_empty(self):
        assert escape_path(None) == ""


# ---------------------------------------------------------------------------
# Settings the run carries because generation reads them off somewhere else
# ---------------------------------------------------------------------------

class TestCarriedProcessWideSettings:
    """The skip chance and the tags-at-start flag are held on
    BaseImageGenerator and Prompter, not read off the run config, so the run
    has to carry them and apply_prompt_globals has to set them at its start.
    """

    def test_the_snapshot_carries_the_skip_chance(self, app_config):
        app_config.random_skip_chance = "0.25"
        assert base_args_from_app_config(app_config)["random_skip_chance"] == "0.25"

    def test_the_snapshot_carries_the_tags_flag(self, app_config):
        app_config.tags_apply_to_start = False
        assert base_args_from_app_config(app_config)["tags_apply_to_start"] is False

    def test_sparse_mixed_tags_reaches_the_carried_prompter_config(self, app_config):
        """It is stored on RunnerAppConfig and read off the prompter config."""
        app_config.sparse_mixed_tags = True
        args = base_args_from_app_config(app_config)
        assert args["prompter_config"].sparse_mixed_tags is True

    def test_the_stored_prompter_config_keeps_its_own_value(self, app_config):
        app_config.sparse_mixed_tags = True
        base_args_from_app_config(app_config)
        assert app_config.prompter_config.sparse_mixed_tags is False


class TestApplyPromptGlobals:
    """Applied at the run's start, so a queued run uses its own values."""

    def test_it_sets_the_skip_chance_the_run_carries(self, monkeypatch):
        from sd_runner.generators.base import BaseImageGenerator
        monkeypatch.setattr(BaseImageGenerator, "RANDOM_SKIP_CHANCE", 0.0)
        apply_prompt_globals(SimpleNamespace(random_skip_chance="0.75"))
        assert BaseImageGenerator.RANDOM_SKIP_CHANCE == 0.75

    def test_it_sets_the_tags_flag_the_run_carries(self):
        from sd_runner.prompter import Prompter
        Prompter.set_tags_apply_to_start(True)
        apply_prompt_globals(SimpleNamespace(tags_apply_to_start=False))
        assert Prompter.TAGS_APPLY_TO_START is False

    def test_a_run_carrying_neither_leaves_them_alone(self, monkeypatch):
        """A config assembled outside both run paths carries nothing."""
        from sd_runner.generators.base import BaseImageGenerator
        from sd_runner.prompter import Prompter
        monkeypatch.setattr(BaseImageGenerator, "RANDOM_SKIP_CHANCE", 0.4)
        Prompter.set_tags_apply_to_start(False)

        apply_prompt_globals(SimpleNamespace())

        assert BaseImageGenerator.RANDOM_SKIP_CHANCE == 0.4
        assert Prompter.TAGS_APPLY_TO_START is False

    def test_an_unreadable_skip_chance_leaves_it_alone(self, monkeypatch):
        """Losing the run to a bad stored value would be the worse failure."""
        from sd_runner.generators.base import BaseImageGenerator
        monkeypatch.setattr(BaseImageGenerator, "RANDOM_SKIP_CHANCE", 0.4)
        apply_prompt_globals(SimpleNamespace(random_skip_chance="not a number"))
        assert BaseImageGenerator.RANDOM_SKIP_CHANCE == 0.4
