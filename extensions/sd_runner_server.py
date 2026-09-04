from enum import Enum
from multiprocessing.connection import Listener

from sd_runner.config import config
from sd_runner.globals import WorkflowType
from lib.logging_setup import get_logger

logger = get_logger("sd_runner_server")

#: Longest client id kept. The value arrives over the wire and ends up in the
#: runs window and the encrypted cache, so it is bounded and stripped of
#: unprintable characters before reaching either.
MAX_CLIENT_ID_LEN = 64

#: Peer hosts that identify nothing. The listener binds config.server_host,
#: which is loopback by default, so every client that reaches it shares this
#: address -- it separates no one from anyone and must not be used as an id.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


def sanitize_client_id(value) -> str:
    """Reduce a client-supplied id to something safe to display and persist."""
    if value is None:
        return ""
    text = "".join(ch for ch in str(value).strip() if ch.isprintable())
    return text[:MAX_CLIENT_ID_LEN]


class CommandKind(Enum):
    """What a server command does, which decides how it may be handled.

    STATE changes app state and never enqueues a run. CONTEXTUAL_GENERATE
    deliberately reuses whatever the UI currently holds -- that is the point of
    the command, so it cannot be built independently of the UI.
    PARAMETERIZED_GENERATE carries the parameters that distinguish its run.
    """
    STATE = 'state'
    CONTEXTUAL_GENERATE = 'contextual_generate'
    PARAMETERIZED_GENERATE = 'parameterized_generate'


class CommandType(Enum):
    """A server command, with what it does and which workflow (if any) it selects.

    Several commands select no workflow, so a null workflow cannot tell them
    apart -- the kind is what distinguishes "reuse current settings" from a
    request that brought its own. Keeping both on the member means the command
    survives the hand-off to the app instead of being flattened to a workflow
    that may be None for more than one reason.

    The string values are the wire protocol and are fixed by external clients.
    """

    def __new__(cls, value, kind, workflow_type):
        obj = object.__new__(cls)
        obj._value_ = value
        obj.kind = kind
        obj.workflow_type = workflow_type
        return obj

    REDO_PROMPT = ('redo_prompt', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.REDO_PROMPT)
    RENOISER = ('renoiser', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.RENOISER)
    CONTROL_NET = ('control_net', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.CONTROLNET)
    IP_ADAPTER = ('ip_adapter', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.IP_ADAPTER)
    IMAGE_EDIT = ('image_edit', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.IMAGE_EDIT)
    IMG2IMG = ('img2img', CommandKind.PARAMETERIZED_GENERATE, WorkflowType.IMG2IMG)
    # Carries its own source prompt but selects no workflow -- it runs under
    # whichever one is currently set.
    TAKE_PROMPT = ('take_prompt', CommandKind.PARAMETERIZED_GENERATE, None)
    LAST_SETTINGS = ('last_settings', CommandKind.CONTEXTUAL_GENERATE, None)
    CANCEL = ('cancel', CommandKind.STATE, None)
    REVERT_TO_SIMPLE_GEN = ('revert_to_simple_gen', CommandKind.STATE, None)

    @classmethod
    def resolve(cls, command_type_str: str) -> 'CommandType':
        if not command_type_str:
            raise ValueError("Command type string is empty")
        try:
            return cls(command_type_str.lower().replace(" ", "_"))
        except ValueError:
            raise ValueError(f"Unknown command type: {command_type_str}")

    def is_generate(self) -> bool:
        return self.kind is not CommandKind.STATE

    def is_batchable(self) -> bool:
        """STATE commands act on the app now; queueing them would defer the act."""
        return self.is_generate()

    def normalize_args(self, args: dict) -> dict:
        """Return a copy of *args* in the form the run callback expects.

        Only TAKE_PROMPT needs this: clients send the image to take a prompt
        from as "image", but the receiver reads it as a source prompt file, and
        leaving "image" set would additionally route the path into a control net
        or IP adapter field. Living on the member keeps the single-request and
        batch entry points from drifting apart.
        """
        args = dict(args or {})
        if self is CommandType.TAKE_PROMPT:
            if "image" in args and "source_prompt" not in args:
                args["source_prompt"] = args["image"]
            args.pop("image", None)
        return args


class SDRunnerServer:
    def __init__(
        self,
        run_callback: callable,
        cancel_callback: callable,
        revert_callback: callable,
        batch_enqueue_callback: callable,
        health_check_callback: callable = None,
        host: str = None,
        port: int = None,
    ):
        # Resolved at call time via a local import rather than the module-level
        # `config` binding (or a parameter default, which is bound once at
        # first import): tests swap in a fresh Config instance per test by
        # patching the sd_runner.config.config attribute, and only a fresh lookup
        # of that attribute picks up the swap.
        from sd_runner.config import config as _config
        self._running = False
        self._is_stopping = False
        self._host = host if host is not None else _config.server_host
        self._port = port if port is not None else _config.server_port
        self.listener = None
        self._conn = None
        # Per-connection identity. _client_id is whatever the client called
        # itself; _peer_host is the fallback derived from the socket.
        self._client_id = ""
        self._peer_host = ""
        self.run_callback = run_callback
        self.cancel_callback = cancel_callback
        self.revert_callback = revert_callback
        self.batch_enqueue_callback = batch_enqueue_callback
        self.health_check_callback = health_check_callback

    def start(self) -> None:
        self.listener = Listener((self._host, self._port), authkey=str.encode(config.server_password))
        self._running = True
        while self._running and not self._is_stopping:
            # Errors here are Listener-level (port in use, closed listener) — unrecoverable.
            try:
                self._conn = self.listener.accept()
                self._adopt_peer(self.listener.last_accepted)
                logger.debug('connection accepted from: ' + str(self.listener.last_accepted))
            except OSError as e:
                if not self._is_stopping:
                    logger.error(f"Listener error: {e}")
                break
            except Exception as e:
                if not self._is_stopping:
                    logger.error(f"Unexpected listener error: {e}")
                break

            self._handle_connection()

        if self.listener:
            try:
                self.listener.close()
            except Exception:
                pass
        self._running = False
        self._is_stopping = False

    def _adopt_peer(self, address) -> None:
        """Reset per-connection identity and record the peer host.

        Called once per accepted connection. The client's own id, if it sends
        one, replaces the host on the first message that carries it.

        A loopback peer is recorded as no host at all. It is the default bind
        address, so it would otherwise be the answer for every client and would
        read as an identity while carrying none. The host is also put through
        sanitize_client_id: it is displayed and persisted exactly like a
        client-supplied id, so it gets the same bounding.
        """
        self._client_id = ""
        host = ""
        if isinstance(address, tuple) and address:
            host = str(address[0] or "")
        elif isinstance(address, str):
            host = address
        self._peer_host = "" if host in LOOPBACK_HOSTS else sanitize_client_id(host)

    def client_id(self) -> str:
        """Who is sending on the current connection, or "" when nothing says.

        The client's own ``client_id`` when it sends one, otherwise the peer
        host when that host distinguishes anyone. A non-loopback host is stable
        across reconnects and across app restarts, unlike the ephemeral source
        port, which changes every connection -- but it still cannot separate two
        client processes on one machine, and on the default loopback bind it
        cannot separate anything at all. A client that needs to be told apart
        from its neighbours, or to be recognised by a name of its own, sends
        ``client_id``; that is the only way, and it is why the field exists.

        Naming what an unidentified request becomes is the caller's job, so
        there is one sentinel for it rather than two that could disagree.
        """
        return self._client_id or self._peer_host

    def _handle_health_check(self, msg: dict) -> None:
        """Answer a client asking whether a backend is operational.

        Runs on the listener thread. The callback bridges its own brief UI
        reads and does its HTTP work here, so this blocks only this connection
        -- not the GUI, and not another client's.
        """
        if self.health_check_callback is None:
            self._conn.send({'status': 'error', 'error': 'health checks unavailable'})
            return
        try:
            level = int(msg.get('level', 1))
            timeout = int(msg.get('timeout', 60))
        except (TypeError, ValueError):
            self._conn.send({'status': 'error', 'error': 'invalid level or timeout'})
            return
        try:
            result = self.health_check_callback(
                level=level, timeout=timeout, software=str(msg.get('software', '') or '')
            )
        except Exception as e:
            logger.error(f"health_check failed: {e}")
            self._conn.send({'status': 'error', 'error': 'health check failed',
                             'detail': str(e)})
            return
        self._conn.send(result)

    def _handle_run_batch(self, msg: dict) -> None:
        """Send all batch requests to the staging queue via a single bridge call."""
        requests = [
            req for req in msg.get('requests', [])
            if 'type' in req and 'args' in req
        ]
        skipped = len(msg.get('requests', [])) - len(requests)
        if skipped:
            logger.warning("run_batch: skipping %d malformed request(s)", skipped)
        try:
            result = self.batch_enqueue_callback(requests, self.client_id())
            enqueued = result.get('count', len(requests)) if isinstance(result, dict) else len(requests)
        except Exception as e:
            logger.error("run_batch: batch_enqueue_callback failed: %s", e)
            self._conn.send({'error': 'batch enqueue failed', 'data': str(e)})
            return
        logger.info("run_batch: staged %d of %d item(s)", enqueued, len(requests))
        self._conn.send({'status': 'queued', 'count': enqueued})

    def _handle_connection(self) -> None:
        """Read and dispatch messages on self._conn until the client disconnects or an error occurs.

        Connection-level errors (EOFError, ConnectionResetError, broken pipe) cause this method
        to return so the outer loop can accept the next client.  The connection is always closed
        on exit.
        """
        try:
            while not self._is_stopping:
                try:
                    msg = self._conn.recv()
                    if msg is None:
                        continue
                    if config.debug:
                        print(msg)
                    if msg == 'close server' or msg == 'close connection':
                        self._conn.close()
                        if msg == 'close server':
                            self._running = False
                        return
                    if msg == 'validate':
                        self._conn.send('valid')
                    elif isinstance(msg, dict):
                        # Optional and additive: a client that never sends it
                        # keeps working and is identified by its host instead.
                        # Sticky for the connection, so it need only be sent
                        # once rather than on every request.
                        named = sanitize_client_id(msg.get('client_id'))
                        if named:
                            self._client_id = named
                        command = msg.get('command')
                        if command == 'health_check':
                            self._handle_health_check(msg)
                        elif command == 'run_batch':
                            self._handle_run_batch(msg)
                        elif command == 'run':
                            if "type" not in msg or "args" not in msg:
                                self._conn.send({"error": "invalid command", "data": msg})
                            else:
                                self.run_command(command, msg["type"], msg["args"])
                        else:
                            self._conn.send({"error": "invalid command", "data": msg})
                except KeyboardInterrupt:
                    pass
                except EOFError:
                    # Client closed the connection cleanly.
                    logger.debug("Client disconnected (EOF)")
                    return
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    logger.warning(f"Client connection lost: {e}")
                    return
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
                    try:
                        self._conn.send({'error': 'server error', 'data': str(e)})
                    except Exception:
                        pass  # Connection may already be dead; drop it.
                    return
        finally:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    def run_command(self, command: str, _type: str, args: dict) -> None:
        if self._conn is None:
            raise Exception("connection closed before run command execution")
        if command != 'run':
            self._conn.send({"error": "invalid command", 'data': command})
            return
        # Resolved outside the run try-block: a ValueError raised while handling
        # the command would otherwise be reported back as an invalid type.
        try:
            command_type = CommandType.resolve(_type)
        except ValueError:
            self._conn.send({"error": "invalid command type", 'data': _type})
            return

        try:
            # State commands act on the app directly; everything else is a run
            # request and goes out as the command itself, so the receiver can
            # tell "reuse current settings" from a request that brought its own.
            if command_type == CommandType.CANCEL:
                # By keyword: cancel()'s first parameter is the widget event, so
                # passing this positionally put the reason there and left the
                # cancel message without it.
                self.cancel_callback(reason="Server cancel callback")
                resp = {}
            elif command_type == CommandType.REVERT_TO_SIMPLE_GEN:
                self.revert_callback(self.client_id())
                resp = {}
            else:
                resp = self.run_callback(
                    command_type, command_type.normalize_args(args), self.client_id()
                )
            self._conn.send(resp)
        except Exception as e:
            logger.error(e)
            self._conn.send({'error': 'run error', 'data': str(e)})

    def stop(self) -> None:
        self._is_stopping = True
        self._running = False
        if self._conn:
            try:
                self._conn.close()
            except Exception:
                pass
        if self.listener:
            # Closing the listener while accept() is blocking raises OSError inside
            # start(), which checks _is_stopping and exits cleanly.
            try:
                self.listener.close()
            except Exception:
                pass

