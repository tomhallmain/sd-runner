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

from extensions.sd_runner_server import (
    LOOPBACK_HOSTS, MAX_CLIENT_ID_LEN, CommandKind, CommandType,
    SDRunnerServer, sanitize_client_id,
)
from tests.utils import FakeServerConn
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


# ---------------------------------------------------------------------------
# Client identity
# ---------------------------------------------------------------------------

class TestSanitizeClientId:
    """The id arrives over the wire and reaches the runs window and the cache."""

    def test_plain_name_kept(self):
        assert sanitize_client_id("weidr") == "weidr"

    def test_surrounding_whitespace_stripped(self):
        assert sanitize_client_id("  weidr  ") == "weidr"

    @pytest.mark.parametrize("value", [None, "", "   "])
    def test_absent_or_blank_becomes_empty(self, value):
        assert sanitize_client_id(value) == ""

    def test_control_characters_removed(self):
        assert sanitize_client_id("we\nid\tr\x00") == "weidr"

    def test_length_is_bounded(self):
        assert len(sanitize_client_id("x" * 500)) == MAX_CLIENT_ID_LEN

    def test_non_string_coerced(self):
        assert sanitize_client_id(1234) == "1234"


class TestClientIdResolution:
    def make_server(self):
        return SDRunnerServer(
            run_callback=lambda *a: {},
            cancel_callback=lambda *a: None,
            revert_callback=lambda *a: None,
            batch_enqueue_callback=lambda *a: {},
            host="127.0.0.1",
            port=0,
        )

    def test_peer_host_is_used_when_the_client_does_not_name_itself(self):
        """The host is stable across reconnects and restarts; the port is not."""
        server = self.make_server()
        server._adopt_peer(("192.168.1.50", 54321))
        assert server.client_id() == "192.168.1.50"

    def test_the_same_host_resolves_the_same_on_a_later_connection(self):
        server = self.make_server()
        server._adopt_peer(("192.168.1.50", 54321))
        first = server.client_id()
        server._adopt_peer(("192.168.1.50", 60999))  # new ephemeral port
        assert server.client_id() == first

    def test_a_named_client_wins_over_the_host(self):
        server = self.make_server()
        server._adopt_peer(("192.168.1.50", 54321))
        server._client_id = "weidr"
        assert server.client_id() == "weidr"

    def test_a_new_connection_forgets_the_previous_name(self):
        """The id is per-connection; the next client must not inherit it."""
        server = self.make_server()
        server._adopt_peer(("192.168.1.50", 54321))
        server._client_id = "weidr"
        server._adopt_peer(("10.0.0.9", 111))
        assert server.client_id() == "10.0.0.9"

    def test_no_identity_when_there_is_no_peer_at_all(self):
        server = self.make_server()
        server._adopt_peer(None)
        assert server.client_id() == ""

    @pytest.mark.parametrize("host", sorted(LOOPBACK_HOSTS))
    def test_a_loopback_peer_is_no_identity(self, host):
        """It is the default bind address, so it is the answer for everyone."""
        server = self.make_server()
        server._adopt_peer((host, 54321))
        assert server.client_id() == ""

    def test_a_named_client_on_loopback_is_still_identified(self):
        """Which is the only way a local client can be told from its neighbours."""
        server = self.make_server()
        server._adopt_peer(("127.0.0.1", 54321))
        server._client_id = "weidr"
        assert server.client_id() == "weidr"

    def test_a_remote_host_is_bounded_like_a_supplied_id(self):
        server = self.make_server()
        server._adopt_peer(("h" * 500, 54321))
        assert len(server.client_id()) == MAX_CLIENT_ID_LEN


class TestClientIdOverTheWire:
    """The adoption itself, rather than the resolution it feeds.

    Every test above sets ``_client_id`` directly, so none of them covers the
    one line that reads the field off an incoming message -- the entry point the
    whole feature hangs on.
    """

    def make_server(self, **callbacks):
        kwargs = {
            "run_callback": lambda *a, **k: {},
            "cancel_callback": lambda *a, **k: None,
            "revert_callback": lambda *a, **k: None,
            "batch_enqueue_callback": lambda *a, **k: {},
            "host": "127.0.0.1",
            "port": 0,
        }
        kwargs.update(callbacks)
        server = SDRunnerServer(**kwargs)
        server._adopt_peer(("127.0.0.1", 54321))
        return server

    def drive(self, server, messages):
        """Run the receive loop over *messages* and return the connection.

        Returned because _handle_connection clears server._conn on the way
        out, so a test wanting to see what was sent has to hold its own
        reference.
        """
        conn = FakeServerConn(messages)
        server._conn = conn
        server._handle_connection()
        return conn

    def run_message(self, **extra):
        return {"command": "run", "type": "renoiser", "args": {}, **extra}

    def test_a_client_id_on_a_run_reaches_the_run_callback(self):
        seen = []
        server = self.make_server(
            run_callback=lambda ct, args, client_id="": (seen.append(client_id), {})[1]
        )
        self.drive(server, [self.run_message(client_id="weidr")])
        assert seen == ["weidr"]

    def test_a_client_that_never_names_itself_reaches_it_unidentified(self):
        """Loopback says nothing, so the run path is the one that names it."""
        seen = []
        server = self.make_server(
            run_callback=lambda ct, args, client_id="": (seen.append(client_id), {})[1]
        )
        self.drive(server, [self.run_message()])
        assert seen == [""]

    def test_the_id_is_sticky_for_the_rest_of_the_connection(self):
        """Sent once, not attached to every request."""
        seen = []
        server = self.make_server(
            run_callback=lambda ct, args, client_id="": (seen.append(client_id), {})[1]
        )
        self.drive(server, [self.run_message(client_id="weidr"), self.run_message()])
        assert seen == ["weidr", "weidr"]

    def test_an_unprintable_id_is_sanitized_before_it_is_adopted(self):
        seen = []
        server = self.make_server(
            run_callback=lambda ct, args, client_id="": (seen.append(client_id), {})[1]
        )
        self.drive(server, [self.run_message(client_id="we\nid\tr")])
        assert seen == ["weidr"]

    def test_a_batch_carries_the_client_too(self):
        seen = []
        server = self.make_server(
            batch_enqueue_callback=lambda reqs, client_id="": (seen.append(client_id), {})[1]
        )
        self.drive(server, [{
            "command": "run_batch",
            "client_id": "weidr",
            "requests": [{"type": "renoiser", "args": {}}],
        }])
        assert seen == ["weidr"]

    def test_cancel_passes_its_reason_not_a_widget_event(self):
        """cancel()'s first parameter is the event, so this has to be a keyword."""
        seen = {}
        server = self.make_server(
            cancel_callback=lambda event=None, reason=None: seen.update(
                event=event, reason=reason
            )
        )
        self.drive(server, [{"command": "run", "type": "cancel", "args": {}}])
        assert seen["event"] is None
        assert seen["reason"]

    def test_a_health_check_reaches_its_callback(self):
        seen = []
        server = self.make_server(
            health_check_callback=lambda **kw: (seen.append(kw), {"status": "ok"})[1]
        )
        self.drive(server, [{"command": "health_check", "level": 2, "timeout": 30}])
        assert seen == [{"level": 2, "timeout": 30, "software": ""}]

    def test_a_health_check_defaults_to_level_one(self):
        seen = []
        server = self.make_server(
            health_check_callback=lambda **kw: (seen.append(kw), {"status": "ok"})[1]
        )
        self.drive(server, [{"command": "health_check"}])
        assert seen[0]["level"] == 1

    def test_the_health_result_is_sent_back(self):
        server = self.make_server(
            health_check_callback=lambda **kw: {"status": "ok", "backend": "ComfyUI"}
        )
        conn = self.drive(server, [{"command": "health_check"}])
        assert conn.sent == [{"status": "ok", "backend": "ComfyUI"}]

    def test_a_failing_health_check_answers_rather_than_dropping(self):
        """The client is waiting on a reply; an exception would hang it."""
        def explode(**kwargs):
            raise RuntimeError("backend exploded")

        server = self.make_server(health_check_callback=explode)
        conn = self.drive(server, [{"command": "health_check"}])
        assert conn.sent[0]["status"] == "error"

    def test_a_nonsense_level_answers_rather_than_dropping(self):
        server = self.make_server(health_check_callback=lambda **kw: {"status": "ok"})
        conn = self.drive(server, [{"command": "health_check", "level": "two"}])
        assert conn.sent[0]["status"] == "error"

    def test_health_checks_can_be_unavailable(self):
        """The callback is optional, so a server built without one must say so."""
        server = self.make_server(health_check_callback=None)
        conn = self.drive(server, [{"command": "health_check"}])
        assert conn.sent[0]["status"] == "error"

    def test_revert_is_told_which_client_asked(self):
        seen = []
        server = self.make_server(revert_callback=lambda client_id="": seen.append(client_id))
        self.drive(server, [{
            "command": "run", "type": "revert_to_simple_gen",
            "args": {}, "client_id": "weidr",
        }])
        assert seen == ["weidr"]
