"""
CacheController -- persistence layer for SD Runner.

Owns loading and storing:
- ``RunnerAppConfig`` history via ``app_info_cache``
- Blacklist, presets, schedules, expansions, timed schedules, recent adapters
- Security config
- Display position and virtual-screen info
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import QTimer

from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("ui_qt.cache_controller")


class CacheController:
    """
    Owns persistence: loading and storing the application info cache,
    RunnerAppConfig history, and display position.
    Also owns the periodic cache-store timer.
    """

    PENDING_SD_RUNS_KEY = "pending_sd_runs"
    PENDING_SERVER_REQUESTS_KEY = "pending_server_requests"

    def __init__(self, app_window: AppWindow):
        self._app = app_window
        self._store_cache_timer: Optional[QTimer] = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_info_cache(self):
        """
        Load all caches from disk and return a ``RunnerAppConfig``.

        Calls the static loaders on every module that persists data through
        the app_info_cache.
        """
        from utils.runner_app_config import RunnerAppConfig
        from ui_qt.prompts.blacklist_window import BlacklistWindow
        from ui_qt.presets.presets_window import PresetsWindow
        from ui_qt.presets.schedules_window import SchedulesWindow
        from ui_qt.prompts.expansions_window import set_expansions as _set_expansions
        from ui_qt.models.recent_adapters_window import RecentAdaptersWindow
        from ui_qt.prompts.prompt_config_window import PromptConfigWindow
        from ui_qt.prompts.image_to_prompt_window import ImageToPromptWindow
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from ui_qt.auth.password_core import get_security_config

        try:
            self._app.config_history_index = app_info_cache.get(
                "config_history_index", default_val=0
            )
            BlacklistWindow.set_blacklist()
            # Run cache post-init once, now that blacklist settings have been restored.
            app_info_cache.post_init()
            self._app.config_history_index = app_info_cache.clamp_config_history_index(self._app.config_history_index)
            PresetsWindow.set_recent_presets()
            SchedulesWindow.set_schedules()
            _set_expansions()
            timed_schedules_manager.set_schedules()
            RecentAdaptersWindow.load_recent_adapters()
            ImageToPromptWindow.load_last_from_cache()
            # Security config is loaded automatically when first accessed
            get_security_config()
            runner_config = RunnerAppConfig.from_dict(
                app_info_cache.get_history(0)
            )
            PromptConfigWindow.set_runner_app_config(runner_config)
            self._restore_pending_queues()
            return runner_config
        except Exception as e:
            logger.error(f"Failed to load info cache: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return RunnerAppConfig()

    def _restore_pending_queues(self) -> None:
        """Restore pending SD runs and server staging requests saved at last shutdown."""
        from copy import deepcopy
        from sd_runner.run_config import RunConfig
        from utils.runner_app_config import RunnerAppConfig

        runs_data = app_info_cache.get(self.PENDING_SD_RUNS_KEY) or []
        if runs_data:
            restored = 0
            for run_dict in runs_data:
                try:
                    runner_cfg = RunnerAppConfig.from_dict(deepcopy(run_dict))
                    self._app.job_queue.pending_jobs.append(RunConfig(args=runner_cfg))
                    restored += 1
                except Exception as exc:
                    logger.warning(f"Failed to restore pending run: {exc}")
            if restored:
                self._app.job_queue.paused = True
                logger.info(f"Restored {restored} pending SD run(s) from previous session")
            app_info_cache.set(self.PENDING_SD_RUNS_KEY, [])

        requests_data = app_info_cache.get(self.PENDING_SERVER_REQUESTS_KEY) or []
        if requests_data:
            from utils.globals import WorkflowType
            restored = 0
            for req in requests_data:
                try:
                    wf_type = WorkflowType[req["workflow_type"]]
                    self._app.server_staging_queue._requests.append((wf_type, req.get("args", {})))
                    restored += 1
                except Exception as exc:
                    logger.warning(f"Failed to restore staging request: {exc}")
            if restored:
                logger.info(f"Restored {restored} server staging request(s) from previous session")
            app_info_cache.set(self.PENDING_SERVER_REQUESTS_KEY, [])

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------
    def store_info_cache(self) -> None:
        """
        Persist all application state to the encrypted cache.
        """
        from ui_qt.prompts.blacklist_window import BlacklistWindow
        from ui_qt.presets.presets_window import PresetsWindow
        from ui_qt.presets.schedules_window import SchedulesWindow
        from ui_qt.prompts.expansions_window import store_expansions as _store_expansions
        from ui_qt.models.recent_adapters_window import RecentAdaptersWindow
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from ui_qt.auth.password_core import get_security_config

        try:
            logger.debug("Storing info cache...")
            runner_config = self._app.runner_app_config
            if runner_config is not None:
                if app_info_cache.set_history(runner_config):
                    if self._app.config_history_index > 0:
                        self._app.config_history_index -= 1
            app_info_cache.set("config_history_index", self._app.config_history_index)
            logger.debug("Storing blacklist...")
            BlacklistWindow.store_blacklist()
            logger.debug("Storing presets...")
            PresetsWindow.store_recent_presets()
            logger.debug("Storing schedules...")
            SchedulesWindow.store_schedules()
            logger.debug("Storing expansions...")
            _store_expansions()
            logger.debug("Storing timed schedules...")
            timed_schedules_manager.store_schedules()
            logger.debug("Storing recent adapters...")
            RecentAdaptersWindow.save_recent_adapters()
            logger.debug("Storing security config...")
            get_security_config().save_settings()
            logger.debug("Storing app info cache...")
            app_info_cache.store()
            logger.debug("Info cache stored successfully")
        except Exception as e:
            logger.error(f"Failed to store info cache: {e}")

    # ------------------------------------------------------------------
    # Pending queues (cross-session persistence)
    # ------------------------------------------------------------------
    def store_pending_queues(self) -> None:
        """
        Snapshot pending SD runs and server staging requests into the cache
        so they can be restored in the next session.  Called once at shutdown,
        not during periodic saves.
        """
        try:
            from copy import deepcopy

            job_queue = getattr(self._app, "job_queue", None)
            runs_data: list = []
            if job_queue is not None:
                for run_config in job_queue.pending_jobs:
                    try:
                        args = getattr(run_config, "args", None)
                        if args is None:
                            continue
                        if hasattr(args, "to_dict"):
                            runs_data.append(args.to_dict())
                        elif isinstance(args, dict):
                            runs_data.append(deepcopy(args))
                    except Exception as exc:
                        logger.warning(f"Failed to serialize pending run: {exc}")
            app_info_cache.set(self.PENDING_SD_RUNS_KEY, runs_data)

            staging = getattr(self._app, "server_staging_queue", None)
            requests_data: list = []
            if staging is not None:
                for wf_type, args_dict in staging._requests:
                    try:
                        requests_data.append({
                            "workflow_type": wf_type.name if hasattr(wf_type, "name") else str(wf_type),
                            "args": args_dict,
                        })
                    except Exception as exc:
                        logger.warning(f"Failed to serialize staging request: {exc}")
            app_info_cache.set(self.PENDING_SERVER_REQUESTS_KEY, requests_data)

            logger.debug(
                f"Saved {len(runs_data)} pending SD run(s) and "
                f"{len(requests_data)} server request(s) to cache"
            )
        except Exception as e:
            logger.error(f"Failed to store pending queues: {e}")

    # ------------------------------------------------------------------
    # Display position
    # ------------------------------------------------------------------
    def store_display_position(self) -> None:
        """Save current window position and virtual screen info to cache."""
        try:
            app_info_cache.set_display_position(self._app)
            app_info_cache.set_virtual_screen_info(self._app)
        except Exception as e:
            logger.warning(f"Failed to store display position: {e}")

    def apply_cached_display_position(self) -> bool:
        """
        Restore the window geometry from the cached display position.
        Returns True if a position was applied.
        """
        try:
            position_data = app_info_cache.get_display_position()
            if not position_data or not position_data.is_valid():
                return False
            if not position_data.is_visible_on_display():
                return False
            self._app.setGeometry(
                position_data.x,
                position_data.y,
                position_data.width,
                position_data.height,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to apply cached display position: {e}")
            return False

    # ------------------------------------------------------------------
    # Periodic cache store
    # ------------------------------------------------------------------
    def start_periodic_store(self, interval_ms: int = 300_000) -> None:
        """
        Start a periodic timer to store the cache at intervals.
        Default is 5 minutes (300 000 ms).

        Replaces the async ``do_periodic_store_cache`` pattern.
        """
        if interval_ms <= 0:
            return
        self._store_cache_timer = QTimer()
        self._store_cache_timer.timeout.connect(self._on_periodic_store)
        self._store_cache_timer.start(interval_ms)

    def stop_periodic_store(self) -> None:
        if self._store_cache_timer is not None:
            self._store_cache_timer.stop()
            self._store_cache_timer = None

    def _on_periodic_store(self) -> None:
        """
        Called on the main thread by QTimer.

        Stores position and cache together so both stay in sync.
        """
        try:
            self.store_display_position()
            self.store_info_cache()
        except Exception as e:
            logger.debug(f"Error in periodic store info cache: {e}")
