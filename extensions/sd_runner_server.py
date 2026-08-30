from enum import Enum
from multiprocessing.connection import Listener

from utils.config import config
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("sd_runner_server")


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
        host: str = None,
        port: int = None,
    ):
        # Resolved at call time via a local import rather than the module-level
        # `config` binding (or a parameter default, which is bound once at
        # first import): tests swap in a fresh Config instance per test by
        # patching the utils.config.config attribute, and only a fresh lookup
        # of that attribute picks up the swap.
        from utils.config import config as _config
        self._running = False
        self._is_stopping = False
        self._host = host if host is not None else _config.server_host
        self._port = port if port is not None else _config.server_port
        self.listener = None
        self._conn = None
        self.run_callback = run_callback
        self.cancel_callback = cancel_callback
        self.revert_callback = revert_callback
        self.batch_enqueue_callback = batch_enqueue_callback

    def start(self) -> None:
        self.listener = Listener((self._host, self._port), authkey=str.encode(config.server_password))
        self._running = True
        while self._running and not self._is_stopping:
            # Errors here are Listener-level (port in use, closed listener) — unrecoverable.
            try:
                self._conn = self.listener.accept()
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
            result = self.batch_enqueue_callback(requests)
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
                        command = msg.get('command')
                        if command == 'run_batch':
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
                self.cancel_callback("Server cancel callback")
                resp = {}
            elif command_type == CommandType.REVERT_TO_SIMPLE_GEN:
                self.revert_callback()
                resp = {}
            else:
                resp = self.run_callback(command_type, command_type.normalize_args(args))
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

