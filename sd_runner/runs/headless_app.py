"""Running the servers with no window.

The application object a ``RunController`` is given when there is no GUI. It
supplies the same attributes ``AppWindow`` does -- the queues, the current run,
the stored config, the managed backends -- and the degenerate form of each one
that only exists to reach a window: no thread to marshal to, and nobody to show
a dialog to.

What it deliberately does *not* supply is ``sidebar_panel``. That absence is the
feature: a command meaning "reuse what is currently set" has no answer here, and
``RunController`` refuses those commands by finding no sidebar rather than by
consulting a flag. The commands that carry their own parameters are built by
``virtual_run_config`` from stored state and need no widgets at all.

Nothing here imports Qt, and neither does anything it constructs.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from lib.logging_setup import get_logger
from lib.translations import I18N

_ = I18N._
logger = get_logger("runs.headless_app")


class DirectBridge:
    """The thread bridge, where there is no thread to cross.

    ``AppWindow`` marshals work onto the thread that draws the window. With no
    window there is no such thread, so the sections that would be marshalled
    simply run where they are: ``invoke`` calls, and ``wrap`` hands the callable
    back. The blocking contract is unchanged -- a direct call also returns only
    when the work is done -- so callers cannot tell the difference, which is
    what lets them stay written one way.
    """

    def invoke(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        return func(*args, **kwargs)

    def wrap(self, func: Callable[..., Any]) -> Callable[..., Any]:
        return func


class LoggingNotifications:
    """Where a dialog would go when there is nobody to read it.

    Every message becomes a log line. The one that carries a decision is
    ``alert``: the Qt implementation returns what the user clicked, and a
    question with nobody to answer it must not be treated as answered. A
    confirmation is therefore declined rather than assumed -- the interactive
    path asks before a long run, and here that run is refused -- while a purely
    informational alert has nothing to decline and reports success.
    """

    #: The alert kinds that ask rather than tell.
    ASKING_KINDS = ("askokcancel", "askyesno", "askyesnocancel")

    def toast(self, message: str, duration_ms: int = 2000, bg_color=None) -> None:
        logger.info(f"Toast: {str(message).replace(chr(10), ' ')}")

    def title_notify(self, message: str, base_message: str = "",
                     time_in_seconds: int = 3) -> None:
        logger.info(f"Notice: {message}")

    def alert(self, title: str, message: str, kind: str = "info",
              severity: str = "normal", master=None) -> bool:
        answered = kind not in LoggingNotifications.ASKING_KINDS
        logger.warning(
            f'Alert - Title: "{title}" Message: {message}'
            + ("" if answered else " -- declined, nobody to ask")
        )
        return answered

    def handle_error(self, error_text: str, title: Optional[str] = None,
                     kind: str = "error") -> None:
        logger.error(f"{title or _('Error')}: {error_text}")

    def set_label_state(self, text: str = "", **kwargs) -> None:
        return None


class HeadlessApp:
    """An application with the run path and none of the window.

    Constructed by the headless entry point, and given to ``RunController`` in
    place of ``AppWindow``. Attribute for attribute it answers what that
    controller reads, so the controller needs no headless branch of its own
    beyond the two commands that mean "the user interface".
    """

    def __init__(self):
        from sd_runner.persistence.cache_controller import CacheController
        from sd_runner.runs.run_controller import RunController
        from sd_runner.runs.job_queue import SDRunsQueue, ServerStagingQueue
        from sd_runner.runs.ui_responsiveness import NullResponsiveness

        self.current_run = None
        self.config_history_index = 0
        self.job_queue = SDRunsQueue()
        self.server_staging_queue = ServerStagingQueue()
        # None, not an empty queue: a preset schedule is started from the window
        # and reads the sidebar for every task it runs, so there is no headless
        # form of one. Every caller on this path already guards for None, which
        # is also the state the window holds before it builds its own.
        self.job_queue_preset_schedules = None

        self.responsiveness = NullResponsiveness()
        self.notification_ctrl = LoggingNotifications()
        self._thread_bridge = DirectBridge()

        self.cache_ctrl = CacheController(app_window=self)
        self.runner_app_config = self.cache_ctrl.load_info_cache()

        self.run_ctrl = RunController(app_window=self)
        self.app_actions = self._build_app_actions()
        self.backend_processes = self._configure_managed_backends()

        self.server = None
        self.mcp_server = None
        self._closing = False
        self._install_password_gate_handler()

    # ------------------------------------------------------------------
    # Wiring
    # ------------------------------------------------------------------
    def _build_app_actions(self):
        """The same action names ``AppWindow`` binds, none of them wrapped.

        Nothing is marshalled because there is no GUI thread to marshal to.

        The progress actions are the reason this seam exists: the window's
        versions of them write sidebar labels, so they are bound here to a sink
        that logs instead. That is what the run path reports through, so it
        needs no headless branch of its own.

        The actions that exist only to drive a widget are bound to a refusal
        that names itself in the log: they are reachable only from a window, so
        one being called here is a wiring mistake worth seeing rather than a
        case to handle.
        """
        from sd_runner.models.recent_adapters_state import RecentAdaptersState
        from sd_runner.ui.app_actions import AppActions

        def unavailable(name):
            def refuse(*args, **kwargs):
                logger.warning(f"Action '{name}' needs a user interface; ignoring it")
                return None
            return refuse

        actions = {
            "title": lambda title: logger.info(f"Title: {title}"),
            "update_progress": self._log_progress,
            "update_pending": self._log_pending,
            # Time estimation is a label refresh and nothing else; the estimate
            # a run is actually held to is enforced before it is accepted.
            "update_time_estimation": lambda *a, **kw: None,
            "clear_progress": lambda *a, **kw: None,
            "set_run_controls_visible": lambda *a, **kw: None,
            "post_run": self.run_ctrl._post_run,
            "run": self.run_ctrl.run,
            "cancel": self.run_ctrl.cancel,
            "revert_to_simple_gen": self.run_ctrl.revert_to_simple_gen,
            "has_runs_pending": self.run_ctrl.has_runs_pending,
            "validate_blacklist": self.run_ctrl.validate_blacklist,
            "store_info_cache": self.cache_ctrl.store_info_cache,
            "add_recent_adapter_file": RecentAdaptersState.add_recent_adapter_file,
            "add_recent_source_prompt": RecentAdaptersState.add_recent_source_prompt,
            "contains_recent_adapter_file": RecentAdaptersState.contains_recent_adapter_file,
            "toast": self.notification_ctrl.toast,
            "_alert": self.notification_ctrl.alert,
            "title_notify": self.notification_ctrl.title_notify,
        }
        for name in ("construct_preset", "set_widgets_from_preset", "next_preset",
                     "construct_stashed_config", "set_widgets_from_stash",
                     "set_default_config", "set_widgets_from_config",
                     "open_password_admin_window", "set_model_from_models_window",
                     "set_adapter_from_adapters_window"):
            actions[name] = unavailable(name)
        return AppActions(actions=actions, master=None)

    def _install_password_gate_handler(self) -> None:
        """Answer password gates that have no window to prompt from.

        The refusal is what the default already does; this names the action in
        this application's own log so a refused request is diagnosable from the
        one place a headless operator is looking, rather than only from the
        auth module's logger.
        """
        from sd_runner.ui.auth.password_core import set_unprompted_gate_handler

        def refuse(action) -> bool:
            logger.warning(
                f"Refused protected action '{getattr(action, 'value', action)}': "
                "it needs a password and there is no window to ask from"
            )
            return False

        set_unprompted_gate_handler(refuse)

    # ------------------------------------------------------------------
    # Progress, as log lines
    # ------------------------------------------------------------------
    def _log_progress(self, current_index: int = -1, total: int = -1,
                      pending_adapters: int = 0, prepend_text: str | None = None,
                      batch_current: int | None = None, batch_limit: int | None = None,
                      override_text: str | None = None,
                      adapter_current: int | None = None,
                      adapter_total: int | None = None) -> None:
        """Report where a run has got to.

        At debug, because it is called once per generation: a long run would
        otherwise fill the log with a line per image. The counts are what a
        watcher wants; the label formatting they were arranged into is a
        property of the sidebar that showed them.
        """
        if override_text:
            logger.info(override_text)
        elif current_index >= 0 and total >= 0:
            logger.debug(f"Generating {current_index}/{total}")

    def _log_pending(self, count_pending: int = 0) -> None:
        if count_pending > 0:
            logger.debug(f"{count_pending} pending generations")

    # ------------------------------------------------------------------
    # What RunController reads off the window
    # ------------------------------------------------------------------
    def active_intermediate_prompt(self):
        """The pre-pass a run should apply as a plain dict, or None.

        The window's copy of this reads the same stored state; the pre-pass is
        run configuration rather than anything the window owns.
        """
        from sd_runner.presets.presets_state import PresetsState

        prompt = PresetsState.get_active_intermediate_prompt()
        if prompt is None:
            return None
        if not self.run_ctrl.validate_blacklist(prompt.positive_tags):
            return None
        return prompt.to_dict()

    def _configure_managed_backends(self) -> list:
        from extensions.backend_process import configured_backends
        from sd_runner.config import config

        try:
            return configured_backends(config)
        except Exception as e:
            logger.error(f"Could not read backend launch config: {e}")
            return []

    def ensure_backend_started(self, software_type) -> None:
        """Start the backend a run is about to use, unless it already is.

        A server with nothing to generate against is not useful, so a headless
        process manages backends exactly as the window does: read the launch
        commands at startup, start one the first time a run needs it.
        """
        backend = next(
            (b for b in self.backend_processes if b.software_type == software_type),
            None,
        )
        if backend is None:
            return
        try:
            backend.start()
        except Exception as e:
            logger.error(f"Failed to start {backend.name}: {e}")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    def start_servers(self) -> None:
        """Start whichever front ends are configured.

        Both are independent front ends over the same callables, and both are
        given them already wrapped -- which here means unwrapped, since
        ``DirectBridge.wrap`` is the identity. Passing them through the bridge
        anyway keeps the wiring identical to the window's, so which calls are
        marshalled stays a property of the bridge rather than of the caller.

        The two listen in one process with different exposure: the existing
        server authenticates with a ``multiprocessing`` authkey and binds where
        it is told, while ``MCPServerExtension`` refuses any non-loopback bind.
        Securing one therefore says nothing about the other, which is worth
        knowing on a machine with no display to imply a trusted desktop.
        """
        from sd_runner.config import config
        from lib.utils import Utils

        bridge = self._thread_bridge.wrap
        callbacks = (
            self.run_ctrl.server_run_callback,
            bridge(self.run_ctrl.cancel),
            bridge(self.run_ctrl.server_revert_to_simple_gen),
            bridge(self.run_ctrl.server_batch_enqueue),
            self.run_ctrl.server_health_check,
        )

        from extensions.sd_runner_server import SDRunnerServer
        try:
            self.server = SDRunnerServer(*callbacks)
            Utils.start_thread(self.server.start)
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            self.server = None

        if not getattr(config, "mcp_server_port", 0):
            return
        from extensions.mcp_server import MCPServerExtension
        try:
            self.mcp_server = MCPServerExtension(
                *callbacks,
                bridge(self.run_ctrl.run_status),
                bridge(self.run_ctrl.server_resource),
            )
            Utils.start_thread(self.mcp_server.start)
        except Exception as e:
            logger.error(f"Failed to start MCP server: {e}")
            self.mcp_server = None

    def on_closing(self) -> None:
        """Stop the servers, cancel anything running, and persist the cache."""
        if self._closing:
            return
        self._closing = True

        for server in (self.server, self.mcp_server):
            if server is None:
                continue
            try:
                server.stop()
            except Exception as e:
                logger.warning(f"Could not stop a server cleanly: {e}")

        if self.current_run is not None:
            try:
                self.current_run.cancel("Shutting down")
            except Exception as e:
                logger.warning(f"Could not cancel the current run: {e}")

        for backend in self.backend_processes:
            try:
                backend.stop()
            except Exception as e:
                logger.warning(f"Could not stop a backend cleanly: {e}")

        try:
            self.cache_ctrl.store_info_cache()
        except Exception as e:
            logger.error(f"Could not store the cache: {e}")
