from enum import Enum
from multiprocessing.connection import Listener

from utils.config import config
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("sd_runner_server")


class CommandType(Enum):
    """Enum for server command types"""
    REDO_PROMPT = 'redo_prompt'
    RENOISER = 'renoiser'
    CONTROL_NET = 'control_net'
    IP_ADAPTER = 'ip_adapter'
    IMAGE_EDIT = 'image_edit'
    TAKE_PROMPT = 'take_prompt'
    IMG2IMG = 'img2img'
    LAST_SETTINGS = 'last_settings'
    CANCEL = 'cancel'
    REVERT_TO_SIMPLE_GEN = 'revert_to_simple_gen'

    @classmethod
    def resolve(cls, command_type_str: str) -> 'CommandType':
        if not command_type_str:
            raise ValueError("Command type string is empty")
        try:
            return cls(command_type_str.lower().replace(" ", "_"))
        except ValueError:
            raise ValueError(f"Unknown command type: {command_type_str}")


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
        try:
            # Resolve string to enum for type-safe comparison
            command_type = CommandType.resolve(_type)
            
            if command_type == CommandType.LAST_SETTINGS:
                resp = self.run_callback(None, args)
            elif command_type == CommandType.CANCEL:
                self.cancel_callback("Server cancel callback")
                resp = {}
            elif command_type == CommandType.REVERT_TO_SIMPLE_GEN:
                self.revert_callback()
                resp = {}
            elif command_type == CommandType.RENOISER:
                resp = self.run_callback(WorkflowType.RENOISER, args)
            elif command_type == CommandType.CONTROL_NET:
                resp = self.run_callback(WorkflowType.CONTROLNET, args)
            elif command_type == CommandType.IP_ADAPTER:
                resp = self.run_callback(WorkflowType.IP_ADAPTER, args)
            elif command_type == CommandType.IMAGE_EDIT:
                resp = self.run_callback(WorkflowType.IMAGE_EDIT, args)
            elif command_type == CommandType.TAKE_PROMPT:
                args_copy = dict(args or {})
                if "image" in args_copy and "source_prompt" not in args_copy:
                    args_copy["source_prompt"] = args_copy["image"]
                args_copy.pop("image", None)
                resp = self.run_callback(None, args_copy)
            elif command_type == CommandType.IMG2IMG:
                resp = self.run_callback(WorkflowType.IMG2IMG, args)
            elif command_type == CommandType.REDO_PROMPT:
                resp = self.run_callback(WorkflowType.REDO_PROMPT, args)
            else:
                self._conn.send({"error": "unhandled command type", 'data': _type})
                return
            self._conn.send(resp)
        except ValueError as e:
            self._conn.send({"error": "invalid command type", 'data': _type})
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

