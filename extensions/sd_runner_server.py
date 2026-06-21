import queue
import threading
from enum import Enum
from multiprocessing.connection import Listener

from utils.config import config
from utils.globals import WorkflowType
from utils.logging_setup import get_logger

logger = get_logger("sd_runner_server")

_GEN_QUEUE_ITEM_DELAY = 1.0  # seconds to wait between consecutive queued generation requests


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
        host: str = 'localhost',
        port: int = config.server_port,
    ):
        self._running = False
        self._is_stopping = False
        self._host = host
        self._port = port
        self.listener = None
        self._conn = None
        self.run_callback = run_callback
        self.cancel_callback = cancel_callback
        self.revert_callback = revert_callback
        self._gen_queue: queue.Queue = queue.Queue()
        self._gen_worker_thread: threading.Thread | None = None

    def start(self) -> None:
        self._gen_worker_thread = threading.Thread(
            target=self._process_gen_queue, daemon=True, name="sd-gen-queue-worker"
        )
        self._gen_worker_thread.start()
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

    def _process_gen_queue(self) -> None:
        """Worker thread: drain the generation queue one item at a time."""
        import time
        idle = True
        while True:
            try:
                fn = self._gen_queue.get(timeout=1.0)
            except queue.Empty:
                if not idle:
                    logger.info("Generation queue drained.")
                    idle = True
                if self._is_stopping:
                    break
                continue
            if fn is None:  # shutdown sentinel
                break
            if idle:
                logger.info(
                    "Generation queue worker starting batch (%d item(s) pending).",
                    self._gen_queue.qsize() + 1,  # +1 for the item just dequeued
                )
                idle = False
            try:
                fn()
            except Exception as e:
                logger.error("Error processing queued generation: %s", e)
            finally:
                self._gen_queue.task_done()
            if not self._gen_queue.empty():
                time.sleep(_GEN_QUEUE_ITEM_DELAY)

    def _make_queue_item(self, type_str: str, args: dict):
        """Return a zero-argument callable for the given command type and args."""
        command_type = CommandType.resolve(type_str)
        if command_type == CommandType.LAST_SETTINGS:
            return lambda: self.run_callback(None, args)
        elif command_type == CommandType.RENOISER:
            return lambda: self.run_callback(WorkflowType.RENOISER, args)
        elif command_type == CommandType.CONTROL_NET:
            return lambda: self.run_callback(WorkflowType.CONTROLNET, args)
        elif command_type == CommandType.IP_ADAPTER:
            return lambda: self.run_callback(WorkflowType.IP_ADAPTER, args)
        elif command_type == CommandType.IMAGE_EDIT:
            return lambda: self.run_callback(WorkflowType.IMAGE_EDIT, args)
        elif command_type == CommandType.TAKE_PROMPT:
            args_copy = dict(args or {})
            if "image" in args_copy and "source_prompt" not in args_copy:
                args_copy["source_prompt"] = args_copy["image"]
            args_copy.pop("image", None)
            return lambda: self.run_callback(None, args_copy)
        elif command_type == CommandType.IMG2IMG:
            return lambda: self.run_callback(WorkflowType.IMG2IMG, args)
        elif command_type == CommandType.REDO_PROMPT:
            return lambda: self.run_callback(WorkflowType.REDO_PROMPT, args)
        else:
            raise ValueError(f"Command type {command_type} cannot be batched")

    def _handle_run_batch(self, msg: dict) -> None:
        """Enqueue all requests from a run_batch message and ack immediately."""
        requests = msg.get('requests', [])
        enqueued = 0
        for req in requests:
            if 'type' not in req or 'args' not in req:
                logger.warning("Skipping malformed batch request: %s", req)
                continue
            try:
                self._gen_queue.put(self._make_queue_item(req['type'], req['args']))
                enqueued += 1
            except ValueError as e:
                logger.warning("Skipping un-batchable request: %s", e)
        logger.info("run_batch: enqueued %d of %d item(s)", enqueued, len(requests))
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
        # Signal the queue worker to drain and exit.
        self._gen_queue.put(None)
        if self._gen_worker_thread is not None:
            self._gen_worker_thread.join(timeout=5.0)

