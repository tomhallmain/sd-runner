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

    def __init__(self, app_window: AppWindow):
        self._app = app_window
        self._store_cache_timer: Optional[QTimer] = None

    # ------------------------------------------------------------------
    # Load
    # ------------------------------------------------------------------
    def load_info_cache(self):
        """
        Load all caches from disk and return a ``RunnerAppConfig``.

        Ported from App.load_info_cache -- calls the static loaders on
        every module that persists data through the app_info_cache.
        """
        from utils.runner_app_config import RunnerAppConfig
        from ui.tags_blacklist_window import BlacklistWindow
        from ui.presets_window import PresetsWindow
        from ui.schedules_windows import SchedulesWindow
        from ui.expansions_window import ExpansionsWindow
        from ui.recent_adapters_window import RecentAdaptersWindow
        from ui.prompt_config_window import PromptConfigWindow
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from ui_qt.auth.password_core import get_security_config

        try:
            self._app.config_history_index = app_info_cache.get(
                "config_history_index", default_val=0
            )
            BlacklistWindow.set_blacklist()
            # Run cache post-init once, now that blacklist settings have been
            # restored.
            app_info_cache.post_init()
            PresetsWindow.set_recent_presets()
            SchedulesWindow.set_schedules()
            ExpansionsWindow.set_expansions()
            timed_schedules_manager.set_schedules()
            RecentAdaptersWindow.load_recent_adapters()
            # Security config is loaded automatically when first accessed
            get_security_config()
            runner_config = RunnerAppConfig.from_dict(
                app_info_cache.get_history(0)
            )
            PromptConfigWindow.set_runner_app_config(runner_config)
            return runner_config
        except Exception as e:
            logger.error(f"Failed to load info cache: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return RunnerAppConfig()

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------
    def store_info_cache(self) -> None:
        """
        Persist all application state to the encrypted cache.

        Ported from App.store_info_cache.
        """
        from ui.tags_blacklist_window import BlacklistWindow
        from ui.presets_window import PresetsWindow
        from ui.schedules_windows import SchedulesWindow
        from ui.expansions_window import ExpansionsWindow
        from ui.recent_adapters_window import RecentAdaptersWindow
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from ui_qt.auth.password_core import get_security_config

        try:
            runner_config = self._app.runner_app_config
            if runner_config is not None:
                if app_info_cache.set_history(runner_config):
                    if self._app.config_history_index > 0:
                        self._app.config_history_index -= 1
            app_info_cache.set("config_history_index", self._app.config_history_index)
            BlacklistWindow.store_blacklist()
            PresetsWindow.store_recent_presets()
            SchedulesWindow.store_schedules()
            ExpansionsWindow.store_expansions()
            timed_schedules_manager.store_schedules()
            RecentAdaptersWindow.save_recent_adapters()
            get_security_config().save_settings()
            app_info_cache.store()
        except Exception as e:
            logger.error(f"Failed to store info cache: {e}")

    # ------------------------------------------------------------------
    # Display position
    # ------------------------------------------------------------------
    def store_display_position(self) -> None:
        """Save current window position and virtual screen info to cache."""
        try:
            from utils.app_info_cache_qt import app_info_cache as qt_cache
            qt_cache.set_display_position(self._app)
            qt_cache.set_virtual_screen_info(self._app)
        except Exception as e:
            logger.warning(f"Failed to store display position: {e}")

    def apply_cached_display_position(self) -> bool:
        """
        Restore the window geometry from the cached display position.
        Returns True if a position was applied.

        Ported from App.apply_cached_display_position (sibling project).
        """
        try:
            from utils.app_info_cache_qt import app_info_cache as qt_cache
            from lib.position_data_qt import PositionData

            position_data = qt_cache.get_display_position()
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
