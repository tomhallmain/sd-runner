"""Model Context Protocol front end.

A second front end over the same five callables ``SDRunnerServer`` is built
from, so an MCP client can drive generation without either server knowing about
the other. ``sd_runner_server`` is imported read-only, for its command
vocabulary, and is never modified: two front ends with two ideas of what a
command means is the failure that import avoids.

Everything except :meth:`MCPServerExtension._serve` is ordinary code and is
tested as such. ``_serve`` is the only part that touches the MCP SDK, kept
small deliberately -- see its docstring.

HTTP rather than stdio, which is MCP's usual default: under stdio the *client*
launches the server as a subprocess, and a subprocess has none of the state
every callback here depends on -- the queues, the sidebar, the backend
connections all belong to a running app the client did not start.

**Loopback only**, and ``refuses_to_start`` explains why. When remote access is
actually wanted there are three ways out, smallest first: a reverse proxy that
terminates authentication, which needs nothing here and is the usual answer for
an HTTP service that speaks one protocol; implementing ``TokenVerifier`` plus
the minimum ``AuthSettings`` the SDK insists on; or leaving remote access out of
scope. The proxy is the recommendation. This becomes pressing the moment a
headless process listens on anything but localhost, since a machine with no
display implies no trusted desktop around it.
"""

import threading

from extensions.sd_runner_server import CommandType, sanitize_client_id
from lib.logging_setup import get_logger

logger = get_logger("mcp_server")

#: Origin recorded for runs this front end starts, so a run's source is
#: attributable the way a named client is on the other server. MCP carries no
#: equivalent of that protocol's per-connection client id.
MCP_CLIENT_ID = "mcp"


class MCPToolError(Exception):
    """A request that cannot be honoured, reported to the client as-is."""


def tool_descriptors() -> list:
    """The tool surface, as plain data.

    Deliberately not the SDK's decorators: expressed this way the surface can
    be asserted without the SDK installed, and ``_serve`` becomes a loop over
    it rather than a second place the tools are defined.

    Names and descriptions only. A tool's *parameters* come from its handler's
    annotations in ``_register_tools``, which is what the SDK reads, so
    restating them here would be a second answer that could disagree.

    The names and descriptions are protocol payload, not UI text, and are
    deliberately not translated. A tool surface that changed shape with the
    user's interface language would describe different tools to a client
    depending on a setting the client cannot see, and the names have to stay
    fixed regardless -- they are what a client calls.
    """
    return [
        {
            "name": "generate",
            "description": (
                "Start an image generation run. 'command' names the kind of "
                "run; 'args' carries that command's own parameters. Returns "
                "when the run is queued, not when it has finished -- images "
                "are produced afterwards and are not part of the result."
            ),
        },
        {
            "name": "generate_batch",
            "description": (
                "Queue several generation requests at once. Returns when they "
                "are queued, not when they have finished."
            ),
        },
        {
            "name": "cancel",
            "description": "Cancel the running generation and clear the queue.",
        },
        {
            "name": "revert_to_simple_gen",
            "description": "Return the app to its simple image generation workflow.",
        },
        {
            "name": "run_status",
            "description": (
                "How much generation work is outstanding, and whether any of "
                "it came from this client. Poll this after 'generate' to find "
                "out when a run has finished. Pass the 'run_id' that "
                "'generate' returned to ask about one run in particular: "
                "run_state comes back as running, queued, staged, or unknown "
                "once it is no longer outstanding."
            ),
        },
        {
            "name": "health_check",
            "description": (
                "Whether a generation backend is usable. Level 1 confirms it "
                "answers; level 2 also confirms it has a model loaded."
            ),
        },
    ]


def resource_descriptors() -> list:
    """The read-only surface, as plain data.

    Resources answer rather than act, which is the whole distinction from
    tools: a client reads these to find out what it is driving before it asks
    for anything. Expressed the same way as ``tool_descriptors`` so both can be
    asserted without the SDK installed.

    The URIs are the client's address for each one and are protocol payload,
    so they are fixed and untranslated for the same reason the tool names are.
    """
    return [
        {
            "name": "current_workflow",
            "uri": "sdrunner://workflow/current",
            "description": (
                "What the app is currently set to generate: the workflow, "
                "model tags, resolutions and counts a run would use if one "
                "were started now."
            ),
        },
        {
            "name": "preset_names",
            "uri": "sdrunner://presets/names",
            "description": (
                "The saved preset names. A preset is addressable by name in a "
                "generate request's edit_suffix, so this is how a client "
                "learns which ones exist."
            ),
        },
        {
            "name": "run_history",
            "uri": "sdrunner://runs/history",
            "description": (
                "The most recent runs, newest first: what was generated, with "
                "what model and prompt. Capped, because the entries are "
                "near-duplicates and a client reading them has a context "
                "window."
            ),
        },
    ]


class MCPServerExtension:
    """Serves the MCP tool surface over HTTP, on its own thread.

    Takes the same callables ``SDRunnerServer`` is given, *already wrapped* at
    the construction site: most are bridged to the GUI thread, while the run
    and health-check callbacks deliberately are not, because they bridge their
    own widget sections and wrapping them would hold the caller for a whole run
    build or a multi-second health check. Receiving them pre-wrapped is what
    makes this front end inherit those decisions rather than re-derive them.
    """

    def __init__(
        self,
        run_callback: callable,
        cancel_callback: callable,
        revert_callback: callable,
        batch_enqueue_callback: callable,
        health_check_callback: callable = None,
        run_status_callback: callable = None,
        resource_callback: callable = None,
        host: str = None,
        port: int = None,
        token: str = None,
    ):
        # Resolved at call time rather than from the module-level binding, for
        # the reason SDRunnerServer documents: tests swap in a fresh Config per
        # test, and only a fresh attribute lookup sees the swap.
        from sd_runner.config import config as _config

        self.run_callback = run_callback
        self.cancel_callback = cancel_callback
        self.revert_callback = revert_callback
        self.batch_enqueue_callback = batch_enqueue_callback
        self.health_check_callback = health_check_callback
        self.run_status_callback = run_status_callback
        self.resource_callback = resource_callback

        self._host = host if host is not None else getattr(_config, "mcp_server_host", "localhost")
        self._port = port if port is not None else getattr(_config, "mcp_server_port", 0)
        self._token = token if token is not None else getattr(_config, "mcp_server_token", "")
        self._running = False
        self._server = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Authorisation
    # ------------------------------------------------------------------
    @staticmethod
    def _is_loopback(host: str) -> bool:
        return str(host or "").strip().lower() in ("", "localhost", "127.0.0.1", "::1")

    def refuses_to_start(self) -> "str | None":
        """Why this must not listen, or None when it may.

        Loopback only, for now. The other server authenticates with a
        ``multiprocessing`` authkey, which is a property of that transport and
        does not carry to HTTP; the SDK's own answer is an OAuth resource
        server -- a ``token_verifier`` is rejected unless full ``AuthSettings``
        with an issuer URL come with it -- which is more than a shared secret.

        Until that is built, a configured token is refused rather than ignored.
        Serving while a token sits unenforced would leave someone believing
        they are protected, which is worse than not serving.
        """
        if not self._port:
            return "no mcp_server_port configured"
        if not self._is_loopback(self._host):
            return (
                f"refusing to serve MCP on {self._host}: only a loopback bind is "
                "supported until authentication is implemented"
            )
        if self._token:
            return (
                "mcp_server_token is set but cannot be enforced yet; clear it to "
                "serve on loopback, where the port is reachable only as this user"
            )
        return None

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------
    def dispatch(self, tool_name: str, arguments: dict = None) -> dict:
        """Run one tool call and return what the client should see.

        Mirrors ``SDRunnerServer.run_command``: the same resolution, the same
        normalisation, and the same split between state commands and run
        requests. Kept in step with it by using its ``CommandType`` rather than
        a private copy.
        """
        arguments = arguments or {}
        if tool_name == "generate":
            return self._generate(arguments)
        if tool_name == "generate_batch":
            requests = arguments.get("requests")
            if not isinstance(requests, list):
                raise MCPToolError("generate_batch needs a list of requests")
            return self._translate_reply(
                self.batch_enqueue_callback(requests, MCP_CLIENT_ID)
            )
        if tool_name == "cancel":
            # By keyword: cancel()'s first parameter is the widget event, so
            # positionally this would land in there and leave the cancel
            # message without its reason.
            self.cancel_callback(reason="MCP cancel")
            return {}
        if tool_name == "revert_to_simple_gen":
            self.revert_callback(MCP_CLIENT_ID)
            return {}
        if tool_name == "run_status":
            if self.run_status_callback is None:
                raise MCPToolError("run status is not available")
            return self.run_status_callback(
                MCP_CLIENT_ID, str(arguments.get("run_id", "") or "")
            )
        if tool_name == "health_check":
            if self.health_check_callback is None:
                raise MCPToolError("health checks are not available")
            return self.health_check_callback(
                level=int(arguments.get("level", 1) or 1),
                timeout=int(arguments.get("timeout", 60) or 60),
                software=str(arguments.get("software", "") or ""),
            )
        raise MCPToolError(f"unknown tool: {tool_name}")

    def read_resource(self, name: str) -> dict:
        """Read one resource by name. The counterpart to ``dispatch``.

        Kept separate from the tool dispatch rather than folded into it: a
        resource takes no arguments and changes nothing, and a client that can
        only read should not have to go through the surface that acts.
        """
        if self.resource_callback is None:
            raise MCPToolError("resources are not available")
        try:
            return self.resource_callback(name)
        except KeyError:
            raise MCPToolError(f"unknown resource: {name}")

    def _generate(self, arguments: dict) -> dict:
        raw_command = arguments.get("command")
        if not raw_command:
            raise MCPToolError("generate needs a command")
        try:
            command_type = CommandType.resolve(str(raw_command))
        except ValueError:
            raise MCPToolError(f"unknown command: {raw_command}")

        args = arguments.get("args") or {}
        if not isinstance(args, dict):
            raise MCPToolError("generate args must be an object")

        # The state commands are reachable as their own tools, and routing them
        # through generate as well would give two ways to say one thing.
        if command_type in (CommandType.CANCEL, CommandType.REVERT_TO_SIMPLE_GEN):
            raise MCPToolError(
                f"{raw_command} is not a generate command; call the tool of that name"
            )

        return self._translate_reply(self.run_callback(
            command_type, command_type.normalize_args(args),
            sanitize_client_id(MCP_CLIENT_ID),
        ))

    @staticmethod
    def _translate_reply(reply) -> dict:
        """Turn a run callback's reply into a tool result.

        Two changes, both because the reader is different. The other protocol's
        clients know that an empty reply means accepted; an MCP client is a
        model reading a JSON object, so the status is said rather than implied.

        And an error reply is *raised*, not returned. Returned, the protocol
        marks the call a success whose payload happens to contain an error --
        the one shape a client is most likely to act on wrongly.
        """
        if isinstance(reply, dict) and reply.get("error"):
            detail = reply.get("data")
            raise MCPToolError(f"{reply['error']}: {detail}" if detail else str(reply["error"]))
        if not isinstance(reply, dict):
            return {"status": "accepted"}
        if reply.get("queued") == "staged":
            return {"status": "staged", "position": reply.get("position")}
        result = {"status": "accepted"}
        result.update({k: v for k, v in reply.items() if k != "queued"})
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start(self) -> bool:
        """Serve until stopped. Returns False without serving when it must not.

        Called on its own thread, as ``SDRunnerServer.start`` is. A missing SDK
        is not an error: this is an optional dependency and a user who never
        wanted MCP should not see a failure for it.
        """
        refusal = self.refuses_to_start()
        if refusal:
            logger.warning(f"MCP server not started: {refusal}")
            return False

        try:
            from mcp.server import MCPServer  # noqa: F401
        except ImportError:
            logger.info(
                "MCP server not started: the 'mcp' package is not installed "
                "(see requirements-optional.txt)"
            )
            return False

        with self._lock:
            self._running = True
        try:
            self._serve()
            return True
        except Exception as e:
            logger.error(f"MCP server stopped: {e}")
            return False
        finally:
            with self._lock:
                self._running = False

    def stop(self) -> None:
        """Mark it stopped. The listener itself ends with the process.

        ``MCPServer.run`` blocks and exposes no shutdown, so there is nothing
        to call. The thread is a daemon, so process exit ends it -- which is
        enough for an app-lifetime server, and would not be for one that needed
        restarting in place.
        """
        with self._lock:
            self._running = False

    def is_running(self) -> bool:
        with self._lock:
            return self._running

    def _serve(self) -> None:
        """Build the SDK server and serve it. The only SDK-dependent code.

        ``run`` is synchronous and blocks, which is what this thread is for.
        It cannot be stopped from outside, so the thread is a daemon and the
        process exit is what ends it -- see :meth:`stop`.
        """
        from mcp.server import MCPServer

        server = MCPServer("SD Runner")
        self._server = server
        self._register_tools(server)
        self._register_resources(server)
        server.run(transport="streamable-http", host=self._host, port=self._port)

    def _register_tools(self, server) -> None:
        """Bind each tool to a handler whose signature *is* its schema.

        The SDK derives a tool's parameters from the handler's annotations, so
        these are written out rather than generated from a ``**kwargs`` shim --
        a shim would advertise a tool that takes no arguments, and a client
        would have no way to call it properly. Descriptions come from
        ``tool_descriptors`` so the catalogue stays the one place they are said.
        """
        described = {d["name"]: d["description"] for d in tool_descriptors()}

        @server.tool(name="generate", description=described["generate"])
        def generate(command: str, args: dict | None = None) -> dict:
            return self.dispatch("generate", {"command": command, "args": args or {}})

        @server.tool(name="generate_batch", description=described["generate_batch"])
        def generate_batch(requests: list) -> dict:
            return self.dispatch("generate_batch", {"requests": requests})

        @server.tool(name="cancel", description=described["cancel"])
        def cancel() -> dict:
            return self.dispatch("cancel")

        @server.tool(
            name="revert_to_simple_gen",
            description=described["revert_to_simple_gen"],
        )
        def revert_to_simple_gen() -> dict:
            return self.dispatch("revert_to_simple_gen")

        @server.tool(name="run_status", description=described["run_status"])
        def run_status(run_id: str = "") -> dict:
            return self.dispatch("run_status", {"run_id": run_id})

        @server.tool(name="health_check", description=described["health_check"])
        def health_check(level: int = 1, timeout: int = 60, software: str = "") -> dict:
            return self.dispatch("health_check", {
                "level": level, "timeout": timeout, "software": software,
            })

    def _register_resources(self, server) -> None:
        """Bind each resource to a reader, by URI.

        A loop rather than one decorated function per resource: unlike a tool,
        a resource has no parameters, so there is no signature that would
        differ between them.

        The name is captured by a factory rather than by a default argument.
        The SDK reads a handler's signature as its schema -- the same thing
        that gives tools their parameters -- so a captured default would
        advertise the internal name as something a client passes in, on a
        surface that is supposed to take nothing.
        """
        for descriptor in resource_descriptors():
            server.resource(
                descriptor["uri"],
                name=descriptor["name"],
                description=descriptor["description"],
            )(self._resource_reader(descriptor["name"]))

    def _resource_reader(self, name: str):
        """A zero-argument reader bound to one resource name."""
        def read() -> dict:
            return self.read_resource(name)
        return read
