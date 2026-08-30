"""Server command classification.

A server request used to be flattened to a ``WorkflowType`` before it reached
the app, and several commands select no workflow -- so ``last_settings`` and
``take_prompt`` arrived as the same thing and were told apart only by the shape
of their args. ``CommandType`` now carries what the command is and what it does,
and these cover that contract: the wire values external clients send, the
kind that decides how a command may be handled, and the arg normalisation that
both the single-request and batch entry points share.
"""

import pytest

from extensions.sd_runner_server import CommandKind, CommandType
from utils.globals import WorkflowType


STATE_COMMANDS = {CommandType.CANCEL, CommandType.REVERT_TO_SIMPLE_GEN}


# ---------------------------------------------------------------------------
# Wire protocol
# ---------------------------------------------------------------------------

class TestWireValues:
    """The values are sent by an external client, so renaming one breaks it."""

    def test_expected_command_set(self):
        assert {c.value for c in CommandType} == {
            'redo_prompt', 'renoiser', 'control_net', 'ip_adapter', 'image_edit',
            'img2img', 'take_prompt', 'last_settings', 'cancel', 'revert_to_simple_gen',
        }

    def test_values_are_unique(self):
        """A duplicate value would silently alias two members into one."""
        values = [c.value for c in CommandType]
        assert len(values) == len(set(values))

    @pytest.mark.parametrize("text", ['renoiser', 'RENOISER', 'Control Net', 'control_net'])
    def test_resolve_accepts_case_and_space_variants(self, text):
        assert CommandType.resolve(text) in CommandType

    def test_resolve_maps_spaces_to_underscores(self):
        assert CommandType.resolve('take prompt') is CommandType.TAKE_PROMPT

    @pytest.mark.parametrize("text", ['', None, 'not_a_command'])
    def test_resolve_rejects_unusable_input(self, text):
        with pytest.raises(ValueError):
            CommandType.resolve(text)


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

class TestKind:
    def test_every_command_has_a_kind(self):
        for command in CommandType:
            assert isinstance(command.kind, CommandKind)

    def test_only_cancel_and_revert_are_state(self):
        assert {c for c in CommandType if c.kind is CommandKind.STATE} == STATE_COMMANDS

    def test_last_settings_is_the_only_contextual_generate(self):
        contextual = {c for c in CommandType if c.kind is CommandKind.CONTEXTUAL_GENERATE}
        assert contextual == {CommandType.LAST_SETTINGS}

    def test_state_commands_do_not_generate(self):
        for command in STATE_COMMANDS:
            assert command.is_generate() is False

    def test_everything_else_generates(self):
        for command in CommandType:
            if command not in STATE_COMMANDS:
                assert command.is_generate() is True

    def test_state_commands_are_not_batchable(self):
        """Staging one would defer an action meant to take effect now."""
        for command in STATE_COMMANDS:
            assert command.is_batchable() is False

    def test_generate_commands_are_batchable(self):
        for command in CommandType:
            if command.is_generate():
                assert command.is_batchable() is True


class TestWorkflowSelection:
    def test_state_commands_select_no_workflow(self):
        for command in STATE_COMMANDS:
            assert command.workflow_type is None

    def test_last_settings_selects_no_workflow(self):
        """It runs under whatever the UI currently holds -- that is its purpose."""
        assert CommandType.LAST_SETTINGS.workflow_type is None

    def test_take_prompt_selects_no_workflow(self):
        """It carries a source prompt but not a workflow."""
        assert CommandType.TAKE_PROMPT.workflow_type is None

    @pytest.mark.parametrize("command,workflow", [
        (CommandType.REDO_PROMPT, WorkflowType.REDO_PROMPT),
        (CommandType.RENOISER, WorkflowType.RENOISER),
        (CommandType.CONTROL_NET, WorkflowType.CONTROLNET),
        (CommandType.IP_ADAPTER, WorkflowType.IP_ADAPTER),
        (CommandType.IMAGE_EDIT, WorkflowType.IMAGE_EDIT),
        (CommandType.IMG2IMG, WorkflowType.IMG2IMG),
    ])
    def test_workflow_selecting_commands(self, command, workflow):
        assert command.workflow_type is workflow

    def test_a_null_workflow_no_longer_identifies_a_command(self):
        """The regression this classification exists to prevent.

        Three commands select no workflow and mean three different things, so
        the workflow alone cannot say which one arrived.
        """
        no_workflow = {c for c in CommandType if c.workflow_type is None}
        assert CommandType.LAST_SETTINGS in no_workflow
        assert CommandType.TAKE_PROMPT in no_workflow
        assert CommandType.LAST_SETTINGS.kind is not CommandType.TAKE_PROMPT.kind


# ---------------------------------------------------------------------------
# Arg normalisation
# ---------------------------------------------------------------------------

class TestNormalizeArgs:
    def test_take_prompt_moves_image_to_source_prompt(self):
        assert CommandType.TAKE_PROMPT.normalize_args({"image": "a.png"}) == {
            "source_prompt": "a.png"
        }

    def test_take_prompt_drops_image_even_when_source_prompt_is_set(self):
        """A leftover image would additionally route into a control net field."""
        result = CommandType.TAKE_PROMPT.normalize_args(
            {"image": "a.png", "source_prompt": "b.png"}
        )
        assert result == {"source_prompt": "b.png"}

    def test_take_prompt_does_not_overwrite_an_explicit_source_prompt(self):
        result = CommandType.TAKE_PROMPT.normalize_args(
            {"image": "a.png", "source_prompt": "b.png"}
        )
        assert result["source_prompt"] == "b.png"

    def test_take_prompt_keeps_other_args(self):
        result = CommandType.TAKE_PROMPT.normalize_args({"image": "a.png", "append": True})
        assert result["append"] is True

    @pytest.mark.parametrize("command", [
        CommandType.RENOISER, CommandType.CONTROL_NET, CommandType.IP_ADAPTER,
        CommandType.IMAGE_EDIT, CommandType.IMG2IMG, CommandType.REDO_PROMPT,
        CommandType.LAST_SETTINGS,
    ])
    def test_other_commands_pass_args_through(self, command):
        args = {"image": "a.png", "append": True}
        assert command.normalize_args(args) == args

    def test_returns_a_copy(self):
        """The caller's dict is the request payload; normalising must not edit it."""
        args = {"image": "a.png"}
        CommandType.TAKE_PROMPT.normalize_args(args)
        assert args == {"image": "a.png"}

    @pytest.mark.parametrize("args", [None, {}])
    def test_missing_args_yield_an_empty_dict(self, args):
        assert CommandType.TAKE_PROMPT.normalize_args(args) == {}
