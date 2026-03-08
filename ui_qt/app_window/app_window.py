"""
AppWindow -- main application window orchestrator (PySide6).

This is the thin shell described in APP_DECOMPOSITION.md.  It owns the
top-level SmartMainWindow, instantiates all controller objects, assembles
the AppActions dict, and handles top-level lifecycle events.

All substantial logic lives in the controller modules:
    SidebarPanel, RunController, WindowLauncher, KeyBindingManager,
    NotificationController, CacheController.
"""

import functools
import os
import threading
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal, Slot, QThread, QMetaObject
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QVBoxLayout, QWidget, QFrame,
)

from lib.custom_title_bar import FramelessWindowMixin, WindowResizeHandler
from lib.multi_display_qt import SmartMainWindow
from run import Run
from sd_runner.comfy_gen import ComfyGen
from sd_runner.models import Model
from ui.app_actions import AppActions
from ui_qt.models.recent_adapters_window import RecentAdaptersWindow
from ui_qt.app_style import AppStyle
from ui_qt.app_window.cache_controller import CacheController
from ui_qt.app_window.key_binding_manager import KeyBindingManager
from ui_qt.app_window.notification_controller import NotificationController
from ui_qt.app_window.run_controller import RunController
from ui_qt.app_window.sidebar_panel import SidebarPanel
from ui_qt.app_window.window_launcher import WindowLauncher
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.job_queue import SDRunsQueue, PresetSchedulesQueue
from utils.logging_setup import get_logger, set_logger_level
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("ui_qt.app_window")


# ======================================================================
# Thread-safety bridge
# ======================================================================

class _MainThreadBridge(QWidget):
    """Marshals arbitrary callables from worker threads to the main/GUI thread.

    Uses ``QMetaObject.invokeMethod`` with ``BlockingQueuedConnection`` so that
    the calling (worker) thread blocks until the callable finishes on the main
    thread.  When already on the main thread the callable runs directly.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hide()  # invisible helper widget
        self._lock = threading.Lock()
        self._func = None
        self._args = ()
        self._kwargs = {}
        self._result = None
        self._error = None

    @Slot()
    def _execute(self):
        try:
            self._result = self._func(*self._args, **self._kwargs)
        except Exception as e:
            self._error = e

    def invoke(self, func, *args, **kwargs):
        """Call *func* on the main thread, blocking until it returns."""
        app = QApplication.instance()
        if app is None or QThread.currentThread() == app.thread():
            return func(*args, **kwargs)
        with self._lock:
            self._func = func
            self._args = args
            self._kwargs = kwargs
            self._result = None
            self._error = None
            QMetaObject.invokeMethod(
                self, "_execute", Qt.ConnectionType.BlockingQueuedConnection,
            )
            if self._error:
                raise self._error
            return self._result

    def wrap(self, func):
        """Return a wrapper that always invokes *func* on the main thread."""
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            return self.invoke(func, *args, **kwargs)
        return wrapper


# ======================================================================
# Main window
# ======================================================================

class AppWindow(FramelessWindowMixin, SmartMainWindow):
    """
    Main application window for SD Runner.

    Orchestrates controllers via composition.  Each controller receives the
    dependencies it needs at construction time; the AppWindow itself keeps
    only cross-cutting state and top-level lifecycle methods.

    Inherits FramelessWindowMixin for a custom draggable title bar, and
    SmartMainWindow for automatic geometry persistence.
    """

    # Signal for thread-safe title updates.
    _sig_set_title = Signal(str)

    def __init__(self):
        super().__init__(restore_geometry=True)

        # Set up frameless window with custom title bar
        self.setup_frameless_window(
            title=_(" SD Runner "), corner_radius=10,
        )

        # Set icon in the custom title bar
        _root = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
        )
        icon_path = os.path.join(_root, "assets", "icon.png")
        if os.path.isfile(icon_path):
            title_bar = self.get_title_bar()
            if title_bar:
                title_bar.set_icon(icon_path)

        # Thread-safe title signal → slot
        self._sig_set_title.connect(self._on_set_title)

        # ------------------------------------------------------------------
        # Core state
        # ------------------------------------------------------------------
        self.config_history_index: int = 0
        self.runner_app_config: RunnerAppConfig | None = None
        from sd_runner.run_config import RunConfig
        self.current_run: Run = Run(RunConfig())
        self.job_queue = SDRunsQueue()
        self.job_queue_preset_schedules: PresetSchedulesQueue | None = None

        # Window title
        self.setWindowTitle(_(" SD Runner "))

        # ------------------------------------------------------------------
        # Central widget: frameless structure with custom title bar
        # ------------------------------------------------------------------
        grip_size = getattr(self, "_frameless_grip_size", 8)

        outer_widget = QWidget()
        outer_widget.setObjectName("transparentOuter")
        outer_widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCentralWidget(outer_widget)
        outer_layout = QVBoxLayout(outer_widget)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        self._main_frame = QFrame()
        self._main_frame.setObjectName("mainFrame")
        outer_layout.addWidget(self._main_frame)

        root_layout = QVBoxLayout(self._main_frame)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # Custom title bar at the top
        title_bar = self.get_title_bar()
        if title_bar:
            root_layout.addWidget(title_bar)

        # Content area below title bar
        content_widget = QWidget()
        content_widget.setObjectName("contentArea")
        content_layout = QHBoxLayout(content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        root_layout.addWidget(content_widget)

        # ------------------------------------------------------------------
        # Controllers -- notification first (others may toast during init)
        # ------------------------------------------------------------------
        self.notification_ctrl = NotificationController(app_window=self)

        # ------------------------------------------------------------------
        # Load cache (needs to happen before sidebar is built)
        # ------------------------------------------------------------------
        self.cache_ctrl = CacheController(app_window=self)
        self.runner_app_config = self.cache_ctrl.load_info_cache()

        # Load models so autocomplete lists are populated
        Model.load_all()

        # ------------------------------------------------------------------
        # Sidebar panel (the main content of the window)
        # ------------------------------------------------------------------
        self.sidebar_panel = SidebarPanel(parent=content_widget, app_window=self)
        content_layout.addWidget(self.sidebar_panel)

        # Install resize handler for frameless edge resizing
        self._resize_handler = WindowResizeHandler(self, grip_size)

        # Apply combined stylesheet (base + frameless)
        self._apply_theme()

        # ------------------------------------------------------------------
        # Remaining controllers
        # ------------------------------------------------------------------
        self.run_ctrl = RunController(app_window=self)
        self.window_launcher = WindowLauncher(app_window=self)

        # Job queue for preset schedules (needs run_ctrl references)
        from ui_qt.presets.schedules_window import SchedulesWindow
        self.job_queue_preset_schedules = PresetSchedulesQueue(
            get_run_config_callback=self.get_basic_run_config,
            get_current_schedule_callback=lambda: SchedulesWindow.current_schedule,
        )

        # ------------------------------------------------------------------
        # Thread-safety bridge
        # ------------------------------------------------------------------
        self._thread_bridge = _MainThreadBridge(parent=self)

        # ------------------------------------------------------------------
        # Assemble AppActions dict
        # ------------------------------------------------------------------
        self.app_actions = self._build_app_actions()

        # Set UI callbacks for Blacklist filtering notifications
        from sd_runner.blacklist import Blacklist
        Blacklist.set_ui_callbacks(self.app_actions)

        # ------------------------------------------------------------------
        # Key bindings (need app_actions / controllers ready)
        # ------------------------------------------------------------------
        self.key_binding_mgr = KeyBindingManager(app_window=self)

        # ------------------------------------------------------------------
        # Server
        # ------------------------------------------------------------------
        self.server = self._setup_server()

        # ------------------------------------------------------------------
        # Start periodic cache store
        # ------------------------------------------------------------------
        self.cache_ctrl.start_periodic_store()

        # Restore window geometry (SmartMainWindow feature)
        self.restore_window_geometry()

        # Sync all widget values into Globals (signals don't fire during init)
        self.sidebar_panel.sync_globals_from_widgets()

        # Close autocomplete popups and focus
        self.sidebar_panel.close_autocomplete_popups()
        self.sidebar_panel.run_btn.setFocus()

        logger.info("AppWindow created")

    # ------------------------------------------------------------------
    # AppActions assembly
    # ------------------------------------------------------------------
    def _build_app_actions(self) -> AppActions:
        """Wire the AppActions dict, mapping action names to controller methods.

        Actions that touch the Qt GUI are wrapped via :class:`_MainThreadBridge`
        so that the generation engine (which runs on a worker thread) can call
        them safely.  Pure-data / thread-safe getters are left unwrapped.
        """
        ts = self._thread_bridge.wrap  # shorthand

        actions = {
            # Window title -- thread-safe via Signal
            "title": self._sig_set_title.emit,
            # Progress / run lifecycle
            "update_progress": ts(self.run_ctrl.update_progress),
            "update_pending": ts(self.run_ctrl.update_pending),
            "update_time_estimation": ts(self.run_ctrl.update_time_estimation),
            "clear_progress": ts(self.run_ctrl.clear_progress),
            "run": ts(self.run_ctrl.run),
            "cancel": ts(self.run_ctrl.cancel),
            "revert_to_simple_gen": ts(self.run_ctrl.revert_to_simple_gen),
            "has_runs_pending": self.run_ctrl.has_runs_pending,
            "validate_blacklist": self.run_ctrl.validate_blacklist,
            # Presets
            "construct_preset": self.sidebar_panel.construct_preset,
            "set_widgets_from_preset": ts(self.sidebar_panel.set_widgets_from_preset),
            "next_preset": ts(self.sidebar_panel.next_preset),
            # Config
            "set_default_config": ts(self.set_default_config),
            "set_widgets_from_config": ts(self._set_widgets_from_config),
            "store_info_cache": self.cache_ctrl.store_info_cache,
            # Window launchers
            "open_password_admin_window": ts(
                self.window_launcher.open_password_admin_window
            ),
            # Models / adapters
            "set_model_from_models_window": ts(self._set_model_from_models_window),
            "set_adapter_from_adapters_window": ts(
                self._set_adapter_from_adapters_window
            ),
            "add_recent_adapter_file": RecentAdaptersWindow.add_recent_adapter_file,
            "add_recent_source_prompt": RecentAdaptersWindow.add_recent_source_prompt,
            "contains_recent_adapter_file": RecentAdaptersWindow.contains_recent_adapter_file,
            # Notifications (warn/success are AppActions convenience methods)
            "toast": ts(self.notification_ctrl.toast),
            "_alert": ts(self.notification_ctrl.alert),
            "title_notify": ts(self.notification_ctrl.title_notify),
        }
        return AppActions(actions=actions, master=self)

    # ------------------------------------------------------------------
    # Title bar / theme helpers
    # ------------------------------------------------------------------
    def setWindowTitle(self, title: str) -> None:
        """Override to keep the custom title bar text in sync."""
        super().setWindowTitle(title)
        title_bar = self.get_title_bar()
        if title_bar:
            title_bar.set_title(title)

    def _on_set_title(self, title: str) -> None:
        """Slot for ``_sig_set_title`` -- always runs on the GUI thread."""
        self.setWindowTitle(title)
        QApplication.processEvents()

    def _apply_theme(self) -> None:
        """Apply the combined base + frameless stylesheet and title bar theme."""
        is_dark = AppStyle.IS_DEFAULT_THEME
        stylesheet = AppStyle.get_stylesheet() + AppStyle.get_frameless_stylesheet(is_dark)
        self.setStyleSheet(stylesheet)
        self.apply_frameless_theme(is_dark)

    def toggle_theme(self, to_theme: str | None = None, do_toast: bool = True) -> None:
        """Switch between dark and light themes."""
        AppStyle.toggle_theme(to_theme)
        self._apply_theme()
        if do_toast:
            self.notification_ctrl.toast(
                _("Theme switched to {0}.").format(AppStyle.get_theme_name())
            )

    def toggle_debug(self) -> None:
        config.debug = not config.debug
        set_logger_level(config.debug)
        suffix = " (Debug)" if config.debug else ""
        self.setWindowTitle(_(" SD Runner ") + suffix)
        self.notification_ctrl.toast(
            _("Debug mode toggled.")
            + (" (Enabled)" if config.debug else " (Disabled)")
        )

    # ------------------------------------------------------------------
    # Config history navigation
    # ------------------------------------------------------------------
    def one_config_away(self, change: int = 1) -> None:
        """Navigate forward/backward in the config history."""
        assert isinstance(self.config_history_index, int)
        self.config_history_index += change
        try:
            self.runner_app_config = RunnerAppConfig.from_dict(
                app_info_cache.get_history(self.config_history_index)
            )
            self._set_widgets_from_config()
            self.sidebar_panel.close_autocomplete_popups()
        except Exception:
            self.config_history_index -= change

    def first_config(self, end: bool = False) -> None:
        """Jump to first or last config in history."""
        self.config_history_index = (
            app_info_cache.get_last_history_index() if end else 0
        )
        try:
            self.runner_app_config = RunnerAppConfig.from_dict(
                app_info_cache.get_history(self.config_history_index)
            )
            self._set_widgets_from_config()
            self.sidebar_panel.close_autocomplete_popups()
        except Exception:
            self.config_history_index = 0

    def _set_widgets_from_config(self) -> None:
        """Push ``runner_app_config`` values into all sidebar widgets."""
        cfg = self.runner_app_config
        if cfg is None:
            return
        sp = self.sidebar_panel
        from utils.globals import WorkflowType, PromptMode

        sp.software_combo.setCurrentText(cfg.software_type)
        sp.workflow_combo.setCurrentText(
            WorkflowType.get(cfg.workflow_type).get_translation()
        )
        sp.n_latents_combo.setCurrentText(str(cfg.n_latents))
        sp.total_combo.setCurrentText(str(cfg.total))
        sp.batch_limit_combo.setCurrentText(str(cfg.batch_limit))
        sp.delay_combo.setCurrentText(str(cfg.delay_time_seconds))
        sp.resolutions_entry.setText(cfg.resolutions)
        from utils.globals import ResolutionGroup
        sp.resolution_group_combo.setCurrentText(ResolutionGroup.get(str(cfg.resolution_group)).get_description())
        sp.model_tags_entry.setText(cfg.model_tags)
        if cfg.lora_tags:
            sp.lora_tags_entry.setText(cfg.lora_tags)
        sp.lora_strength_slider.setValue(int(float(cfg.lora_strength) * 100))
        sp.bw_colorization_entry.setText(cfg.b_w_colorization)
        sp.controlnet_file_entry.setText(cfg.control_net_file)
        sp.controlnet_strength_slider.setValue(
            int(float(cfg.control_net_strength) * 100)
        )
        sp.ipadapter_file_entry.setText(cfg.ip_adapter_file)
        sp.source_prompt_file_entry.setText(getattr(cfg, "source_prompt_file", ""))
        sp.source_prompt_add_user_prompt_check.setChecked(
            bool(getattr(cfg, "source_prompt_add_user_prompt", False))
        )
        sp.ipadapter_strength_slider.setValue(
            int(float(cfg.ip_adapter_strength) * 100)
        )
        sp.redo_params_entry.setText(cfg.redo_params)

        # Prompter config
        sp.prompt_mode_combo.setCurrentText(
            cfg.prompter_config.prompt_mode.display()
        )
        if getattr(cfg, "source_prompt_file", "").strip():
            sp.prompt_mode_combo.setCurrentText(PromptMode.TAKE.display())
        sp.override_resolution_check.setChecked(cfg.override_resolution)
        sp.inpainting_check.setChecked(cfg.inpainting)
        sp.override_negative_check.setChecked(cfg.override_negative)
        sp.continuous_seed_var_check.setChecked(cfg.continuous_seed_variation)

        sp.prompt_massage_tags_box.setPlainText(cfg.prompt_massage_tags)
        sp.positive_tags_box.setPlainText(cfg.positive_tags)
        sp.negative_tags_box.setPlainText(cfg.negative_tags)

        from ui_qt.prompts.prompt_config_window import PromptConfigWindow
        PromptConfigWindow.set_runner_app_config(cfg)

        # Re-sync globals since programmatic widget updates don't fire signals
        sp.sync_globals_from_widgets()

    # ------------------------------------------------------------------
    # Build run config from UI (ported from App.get_basic_run_config)
    # ------------------------------------------------------------------
    def get_basic_run_config(self):
        """Build a base ``RunConfig`` from the current widget values.

        Ported from ``App.get_basic_run_config``.  Sets all scalar fields
        and -- critically -- copies the ``prompter_config`` from
        ``runner_app_config`` so that ``RunConfig.validate()`` succeeds.
        """
        from sd_runner.run_config import RunConfig
        from utils.globals import PromptMode, WorkflowType
        from ui_qt.prompts.prompt_config_window import PromptConfigWindow

        sp = self.sidebar_panel

        args = RunConfig()
        args.software_type = sp.software_combo.currentText()
        args.auto_run = True

        # workflow_tag must be the enum *name*, not the display translation
        args.workflow_tag = WorkflowType.get(sp.workflow_combo.currentText()).name

        args.n_latents = int(sp.n_latents_combo.currentText())
        args.total = int(sp.total_combo.currentText())
        args.batch_limit = int(sp.batch_limit_combo.currentText())
        args.res_tags = sp.resolutions_entry.text()
        args.resolution_group = sp.resolution_group_combo.currentText()
        args.model_tags = sp.model_tags_entry.text()
        args.lora_tags = sp.lora_tags_entry.text()
        args.override_resolution = sp.override_resolution_check.isChecked()
        args.inpainting = sp.inpainting_check.isChecked()

        # Sync prompt mode into runner_app_config before copying
        prompt_mode = PromptMode.get(sp.prompt_mode_combo.currentText())
        self.runner_app_config.prompter_config.prompt_mode = prompt_mode

        # Let PromptConfigWindow push its detailed settings into runner_app_config
        PromptConfigWindow.set_args_from_prompter_config(args)

        # Copy the full prompter config so RunConfig.validate() has it
        args.prompter_config = self.runner_app_config.get_prompter_config_copy()

        # Preserve original prompt decomposition for EXIF embedding
        args.prompter_config.original_positive_tags = self.runner_app_config.positive_tags
        args.prompter_config.original_negative_tags = self.runner_app_config.negative_tags

        return args

    def get_args(self):
        """Build a full run config with workflow-specific options.

        Returns ``(args, args_copy)`` where ``args_copy`` is a deepcopy
        for storing in the config cache.

        Ported from ``App.get_args``.  Syncs all sidebar widget values
        into ``runner_app_config`` and builds the ``RunConfig``.
        """
        from copy import deepcopy
        from ui_qt.app_window.run_controller import clear_quotes
        from utils.globals import WorkflowType

        sp = self.sidebar_panel

        # Sync concepts dir, tags, and strengths before reading
        sp.set_prompt_massage_tags()
        sp.set_positive_tags()
        sp.set_negative_tags()

        args = self.get_basic_run_config()

        # B/W colorization
        args.b_w_colorization = sp.bw_colorization_entry.text()
        self.runner_app_config.b_w_colorization = args.b_w_colorization

        # ControlNet / Redo file
        controlnet_file = clear_quotes(sp.controlnet_file_entry.text())
        self.runner_app_config.control_net_file = str(controlnet_file)
        RecentAdaptersWindow.add_recent_controlnet(controlnet_file)

        if args.workflow_tag == WorkflowType.REDO_PROMPT.name:
            args.workflow_tag = controlnet_file
            args.redo_params = sp.redo_params_entry.text()
        else:
            args.control_nets = controlnet_file
            if config.debug:
                logger.debug(f"Control Net file: {controlnet_file}")

        args.control_net_strength = sp.controlnet_strength_slider.value() / 100.0

        # IPAdapter file
        ipadapter_file = clear_quotes(sp.ipadapter_file_entry.text())
        self.runner_app_config.ip_adapter_file = str(ipadapter_file)
        args.ip_adapters = ipadapter_file
        RecentAdaptersWindow.add_recent_ipadapter(ipadapter_file)

        source_prompt_file = clear_quotes(sp.source_prompt_file_entry.text())
        self.runner_app_config.source_prompt_file = str(source_prompt_file)
        args.source_prompts = source_prompt_file
        RecentAdaptersWindow.add_recent_adapter_file(source_prompt_file)
        source_prompt_add = sp.source_prompt_add_user_prompt_check.isChecked()
        self.runner_app_config.source_prompt_add_user_prompt = source_prompt_add
        args.source_prompts_add_user_prompt = source_prompt_add
        if source_prompt_file.strip():
            from utils.globals import PromptMode
            self.runner_app_config.prompter_config.prompt_mode = PromptMode.TAKE
            if args.prompter_config is not None:
                args.prompter_config.prompt_mode = PromptMode.TAKE

        args.ip_adapter_strength = sp.ipadapter_strength_slider.value() / 100.0
        args.redo_params = sp.redo_params_entry.text()

        args_copy = deepcopy(args)
        return args, args_copy

    # ------------------------------------------------------------------
    # Model / adapter callbacks (wired into AppActions)
    # ------------------------------------------------------------------
    def _set_model_from_models_window(
        self, model_name: str, is_lora: bool = False, replace: bool = False,
    ) -> None:
        """Insert a model name into the model or LoRA tags entry.

        Ported from ``App.set_model_from_models_window``.

        *replace* = True  → overwrite the field with just the new name.
        *replace* = False → append with the appropriate separator.
        """
        entry = (
            self.sidebar_panel.lora_tags_entry
            if is_lora
            else self.sidebar_panel.model_tags_entry
        )
        current = entry.text().strip()

        if is_lora:
            if replace or current == "":
                new_val = model_name
            else:
                sep = "+" if current.endswith("+") or "+" in current else ","
                if not current.endswith(sep):
                    new_val = current + sep + model_name
                else:
                    new_val = current + model_name
        else:
            if replace or current == "":
                new_val = model_name
            else:
                sep = ","
                if not current.endswith(sep):
                    new_val = current + sep + model_name
                else:
                    new_val = current + model_name

        entry.setText(new_val)

        if not is_lora:
            self.sidebar_panel._set_model_dependent_fields(new_val)

    def _set_adapter_from_adapters_window(
        self,
        path: str,
        adapter_type: str = "controlnet",
        replace: bool = True,
        is_controlnet: bool | None = None,
    ) -> None:
        """Insert an adapter path into the appropriate entry."""
        if is_controlnet is not None:
            adapter_type = "controlnet" if is_controlnet else "ipadapter"

        if adapter_type == "source_prompt":
            entry = self.sidebar_panel.source_prompt_file_entry
        elif adapter_type == "ipadapter":
            entry = self.sidebar_panel.ipadapter_file_entry
        else:
            entry = self.sidebar_panel.controlnet_file_entry

        current = (entry.text() or "").strip()
        if replace or not current:
            entry.setText(path)
            return
        if path in [p.strip() for p in current.split(",") if p.strip()]:
            entry.setText(current)
        else:
            entry.setText(current + "," + path)

    # ------------------------------------------------------------------
    # Default config reset
    # ------------------------------------------------------------------
    def set_default_config(self, event=None) -> None:
        """Reset to a fresh ``RunnerAppConfig`` and repopulate all widgets."""
        self.runner_app_config = RunnerAppConfig()
        self._set_widgets_from_config()
        self.sidebar_panel.close_autocomplete_popups()

    # ------------------------------------------------------------------
    # Server
    # ------------------------------------------------------------------
    def _setup_server(self):
        """Start the SD Runner server in a background thread."""
        from extensions.sd_runner_server import SDRunnerServer

        # Server callbacks are invoked on the listener thread, but they
        # touch Qt widgets.  Wrap them through _MainThreadBridge so every
        # call is marshalled to the GUI thread (BlockingQueuedConnection).
        bridge = self._thread_bridge.wrap
        server = SDRunnerServer(
            bridge(self.run_ctrl.server_run_callback),
            bridge(self.run_ctrl.cancel),
            bridge(self.run_ctrl.revert_to_simple_gen),
        )
        try:
            Utils.start_thread(server.start)
            return server
        except Exception as e:
            logger.error(f"Failed to start server: {e}")
            return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    _closing = False

    def on_closing(self) -> None:
        """Clean up and prepare for shutdown.

        Performs cache persistence first (the critical path), then
        best-effort cleanup of server, run threads, and executors.
        Schedules a hard ``os._exit`` failsafe so that stranded
        background threads (server listener, websocket connections,
        generation workers) can never keep the process alive.
        """
        import threading

        # -- Critical path: persist state on a background thread ----------
        # Run cache persistence off the main thread so we can show a
        # progress dialog if _purge_blacklisted_history takes a while.
        Utils.prevent_sleep(False)
        store_done = threading.Event()

        def _store_cache():
            try:
                self.cache_ctrl.store_display_position()
                self.cache_ctrl.store_info_cache()
                app_info_cache.wipe_instance()
            except Exception as e:
                logger.error(f"Error during cache persistence: {e}")
            finally:
                store_done.set()

        store_thread = threading.Thread(target=_store_cache, daemon=True)
        store_thread.start()

        # Wait briefly; most shutdowns finish in < 1 second.
        store_done.wait(timeout=3.0)

        if not store_done.is_set():
            # Still saving -- show a dialog so the user knows not to
            # force-close.  Keep processing Qt events so it stays visible.
            from PySide6.QtWidgets import QProgressDialog
            if app_info_cache.purging_history:
                msg = _("Updating history for blacklist changes — please wait…")
            else:
                msg = _("Saving application data is taking longer than expected — please wait…")
            progress = QProgressDialog(msg, None, 0, 0, self)
            progress.setWindowTitle(_("Closing"))
            progress.setCancelButton(None)
            progress.setMinimumDuration(0)
            progress.show()

            while not store_done.is_set():
                QApplication.processEvents()
                store_done.wait(timeout=0.1)
                # Update label in case purge started after dialog opened
                if app_info_cache.purging_history:
                    progress.setLabelText(
                        _("Updating history for blacklist changes — please wait…")
                    )
            progress.close()

        # -- Failsafe: hard-kill if cleanup below hangs ------------------
        def _force_exit():
            logger.warning("Failsafe: forcing process exit (stranded threads?)")
            os._exit(0)

        failsafe = threading.Timer(10.0, _force_exit)
        failsafe.daemon = True
        failsafe.start()

        # -- Best-effort cleanup -----------------------------------------
        try:
            ComfyGen.close_all_connections()
        except Exception as e:
            logger.error(f"Error closing ComfyGen connections: {e}")

        # Stop server
        if self.server is not None:
            try:
                self.server.stop()
            except Exception as e:
                logger.error(f"Error stopping server: {e}")

        # Cancel running jobs
        if self.current_run is not None:
            try:
                self.current_run.cancel("Application shutdown")
            except Exception:
                pass
        if self.job_queue is not None:
            try:
                self.job_queue.cancel()
            except Exception:
                pass
        if self.job_queue_preset_schedules is not None:
            try:
                self.job_queue_preset_schedules.cancel()
            except Exception:
                pass

        # Stop periodic cache store
        self.cache_ctrl.stop_periodic_store()

        # Shutdown executor and clean up temp files
        try:
            from sd_runner.base_image_generator import BaseImageGenerator
            BaseImageGenerator.shutdown_executor(wait=False)
            BaseImageGenerator.cleanup_image_converter()
        except Exception as e:
            logger.error(f"Error during executor shutdown: {e}")

        # Cancel the failsafe if we got here cleanly
        failsafe.cancel()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._closing:
            event.accept()
            return
        self._closing = True
        self.on_closing()
        event.accept()
        QApplication.instance().quit()

    def quit(self, event=None) -> None:
        """Prompt the user and quit the application."""
        if self.app_actions.alert(
            _("Confirm Quit"),
            _("Would you like to quit the application?"),
            kind="askokcancel",
        ):
            logger.warning("Exiting application")
            self.on_closing()
            QApplication.instance().quit()
