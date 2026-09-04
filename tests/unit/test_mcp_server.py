"""The MCP front end's own logic.

Everything here is the part that does not touch the MCP SDK: the tool surface,
argument handling, command routing, and the authorisation gate. The SDK binding
in ``_serve`` is deliberately outside this — it could not be compiled against an
installed copy, which is exactly why it is one method and this is the rest.

The routing assertions are really assertions that this front end and
``SDRunnerServer`` cannot drift: both resolve through the same ``CommandType``.
"""

import pytest

from extensions.mcp_server import (
    MCPServerExtension, MCPToolError, MCP_CLIENT_ID, tool_descriptors,
)
from extensions.sd_runner_server import CommandType


class Recorder:
    """Stands in for the five callbacks, recording how each was called."""

    def __init__(self):
        self.calls = []

    def run(self, command_type, args, client_id):
        self.calls.append(("run", command_type, args, client_id))
        return {"queued": True}

    def cancel(self, event=None, reason=None):
        self.calls.append(("cancel", event, reason))

    def revert(self, client_id=""):
        self.calls.append(("revert", client_id))

    def batch(self, requests, client_id=""):
        self.calls.append(("batch", requests, client_id))
        # The shape server_batch_enqueue really returns.
        return {"count": len(requests)}

    def health(self, level=1, timeout=60, software=""):
        self.calls.append(("health", level, timeout, software))
        return {"status": "ok"}

    def run_status(self, origin="", run_id=""):
        self.calls.append(("run_status", origin, run_id))
        return {"running": False, "queued": 0, "staged": 0, "mine_running": False}


def make_server(recorder=None, **kwargs):
    recorder = recorder or Recorder()
    kwargs.setdefault("host", "localhost")
    kwargs.setdefault("port", 9000)
    kwargs.setdefault("token", "")
    server = MCPServerExtension(
        recorder.run, recorder.cancel, recorder.revert,
        recorder.batch, recorder.health, recorder.run_status, **kwargs
    )
    return server, recorder


# ---------------------------------------------------------------------------
# Tool surface
# ---------------------------------------------------------------------------

class TestToolSurface:
    def test_every_callback_is_reachable(self):
        """Five callables in, five things a client can ask for."""
        names = {tool["name"] for tool in tool_descriptors()}
        assert names == {
            "generate", "generate_batch", "cancel",
            "revert_to_simple_gen", "health_check", "run_status",
        }

    def test_each_tool_describes_itself(self):
        for tool in tool_descriptors():
            assert tool["description"].strip()


# ---------------------------------------------------------------------------
# Routing — the same decisions SDRunnerServer.run_command makes
# ---------------------------------------------------------------------------

class TestGenerate:
    def test_it_resolves_the_command_and_passes_it_on(self, app_config):
        server, rec = make_server()
        server.dispatch("generate", {"command": CommandType.IMG2IMG.value, "args": {}})
        kind, command_type, _args, client_id = rec.calls[0]
        assert kind == "run"
        assert isinstance(command_type, CommandType)
        assert client_id == MCP_CLIENT_ID

    def test_it_normalises_args_through_the_command(self, app_config):
        """TAKE_PROMPT renames image -> source_prompt; the front end must not
        have its own idea of that."""
        server, rec = make_server()
        server.dispatch("generate", {
            "command": CommandType.TAKE_PROMPT.value,
            "args": {"image": "/tmp/a.png"},
        })
        _kind, _ct, args, _cid = rec.calls[0]
        assert args.get("source_prompt") == "/tmp/a.png"
        assert "image" not in args

    def test_an_unknown_command_is_refused(self, app_config):
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("generate", {"command": "not_a_command"})

    def test_a_missing_command_is_refused(self, app_config):
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("generate", {})

    def test_non_object_args_are_refused(self, app_config):
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("generate", {
                "command": CommandType.IMG2IMG.value, "args": ["not", "a", "dict"],
            })

    def test_state_commands_are_not_reachable_through_generate(self, app_config):
        """They have their own tools; two ways to say one thing is a bug."""
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("generate", {"command": CommandType.CANCEL.value})


class TestReplyTranslation:
    """The reader is a model reading JSON, not a client that knows the protocol."""

    def test_an_empty_reply_says_it_was_accepted(self, app_config):
        """An enqueued run replies {} on the other protocol; {} tells a model
        nothing."""
        rec = Recorder()
        rec.run = lambda *a, **k: {}
        server, _ = make_server(rec)
        result = server.dispatch("generate", {"command": CommandType.IMG2IMG.value})
        assert result == {"status": "accepted"}

    def test_a_staged_reply_keeps_its_position(self, app_config):
        rec = Recorder()
        rec.run = lambda *a, **k: {"queued": "staged", "position": 3}
        server, _ = make_server(rec)
        result = server.dispatch("generate", {"command": CommandType.IMG2IMG.value})
        assert result == {"status": "staged", "position": 3}

    def test_an_error_reply_is_raised_not_returned(self, app_config):
        """Returned, the protocol marks the call a success carrying an error."""
        rec = Recorder()
        rec.run = lambda *a, **k: {"error": "no models found", "data": "check models_dir"}
        server, _ = make_server(rec)
        with pytest.raises(MCPToolError) as excinfo:
            server.dispatch("generate", {"command": CommandType.IMG2IMG.value})
        assert "no models found" in str(excinfo.value)

    def test_a_batch_error_is_raised_too(self, app_config):
        rec = Recorder()
        rec.batch = lambda requests, client_id="": {"error": "staging queue not available", "count": 0}
        server, _ = make_server(rec)
        with pytest.raises(MCPToolError):
            server.dispatch("generate_batch", {"requests": [{"a": 1}]})

    def test_other_reply_fields_survive(self, app_config):
        rec = Recorder()
        rec.batch = lambda requests, client_id="": {"count": 4}
        server, _ = make_server(rec)
        assert server.dispatch("generate_batch", {"requests": []}) == {
            "status": "accepted", "count": 4,
        }


class TestStateTools:
    def test_cancel_passes_its_reason_by_keyword(self, app_config):
        """cancel()'s first parameter is the widget event -- positionally the
        reason lands there and the cancel message loses it."""
        server, rec = make_server()
        server.dispatch("cancel")
        kind, event, reason = rec.calls[0]
        assert kind == "cancel"
        assert event is None
        assert reason

    def test_revert_identifies_the_caller(self, app_config):
        server, rec = make_server()
        server.dispatch("revert_to_simple_gen")
        assert rec.calls[0] == ("revert", MCP_CLIENT_ID)

    def test_batch_requires_a_list(self, app_config):
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("generate_batch", {"requests": "not a list"})

    def test_batch_passes_the_requests_through(self, app_config):
        server, rec = make_server()
        result = server.dispatch("generate_batch", {"requests": [{"a": 1}]})
        assert rec.calls[0] == ("batch", [{"a": 1}], MCP_CLIENT_ID)
        assert result == {"status": "accepted", "count": 1}

    def test_health_check_defaults_match_the_other_server(self, app_config):
        server, rec = make_server()
        server.dispatch("health_check")
        assert rec.calls[0] == ("health", 1, 60, "")

    def test_health_check_forwards_its_arguments(self, app_config):
        server, rec = make_server()
        server.dispatch("health_check", {"level": 2, "timeout": 5, "software": "ComfyUI"})
        assert rec.calls[0] == ("health", 2, 5, "ComfyUI")

    def test_run_status_asks_about_this_client(self, app_config):
        """Polling is how a client learns its run finished, so it has to ask
        about its own work rather than the app's in general."""
        server, rec = make_server()
        result = server.dispatch("run_status")
        assert rec.calls[0] == ("run_status", MCP_CLIENT_ID, "")
        assert "mine_running" in result

    def test_run_status_forwards_a_run_id(self, app_config):
        """The handle a client was given at accept time is how it asks about
        one run rather than about all of its work."""
        server, rec = make_server()
        server.dispatch("run_status", {"run_id": "abc123"})
        assert rec.calls[0] == ("run_status", MCP_CLIENT_ID, "abc123")

    def test_the_run_status_tool_accepts_a_run_id(self, app_config):
        """The SDK reads a tool's parameters off its handler's annotations, so
        a run_id the description advertises but the handler does not take
        would be undeliverable -- the description would promise a parameter no
        client could pass."""
        import inspect

        server, _rec = make_server()
        registered = {}

        class FakeSDKServer:
            def tool(self, name=None, description=None):
                def decorator(fn):
                    registered[name] = fn
                    return fn
                return decorator

        server._register_tools(FakeSDKServer())
        assert "run_id" in inspect.signature(registered["run_status"]).parameters

    def test_an_unknown_tool_is_refused(self, app_config):
        server, _rec = make_server()
        with pytest.raises(MCPToolError):
            server.dispatch("drop_database")


# ---------------------------------------------------------------------------
# Authorisation
# ---------------------------------------------------------------------------

class TestAuthorisation:
    def test_a_remote_bind_refuses_to_start(self, app_config):
        """The other server's authkey does not carry to HTTP, and the SDK's
        answer is an OAuth resource server rather than a shared secret."""
        server, _rec = make_server(host="0.0.0.0", token="")
        assert server.refuses_to_start()

    def test_a_remote_bind_with_a_token_still_refuses(self, app_config):
        """The token cannot be enforced yet, so it does not unlock a bind."""
        server, _rec = make_server(host="0.0.0.0", token="s3cret")
        assert server.refuses_to_start()

    def test_an_unenforceable_token_refuses_rather_than_being_ignored(self, app_config):
        """Serving with a token sitting unenforced would leave someone
        believing they are protected."""
        server, _rec = make_server(host="localhost", token="s3cret")
        assert server.refuses_to_start()

    def test_a_loopback_bind_without_a_token_may_start(self, app_config):
        server, _rec = make_server(host="localhost", token="")
        assert server.refuses_to_start() is None

    def test_no_port_refuses_to_start(self, app_config):
        """Absent configuration means off, not a default port."""
        server, _rec = make_server(port=0)
        assert server.refuses_to_start()


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------

class TestLifecycle:
    def test_it_does_not_start_when_it_must_not(self, app_config):
        server, _rec = make_server(host="0.0.0.0", token="")
        assert server.start() is False
        assert server.is_running() is False

    def test_a_missing_sdk_is_not_an_error(self, app_config, monkeypatch):
        """An optional dependency nobody asked for must not fail startup."""
        import builtins
        real_import = builtins.__import__

        def no_mcp(name, *args, **kwargs):
            if name == "mcp.server" or name.startswith("mcp."):
                raise ImportError("no mcp")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", no_mcp)
        server, _rec = make_server()
        assert server.start() is False

    def test_stopping_one_that_never_started_is_harmless(self, app_config):
        server, _rec = make_server()
        server.stop()
        assert server.is_running() is False
