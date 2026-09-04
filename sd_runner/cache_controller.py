"""
CacheController -- persistence layer for SD Runner.

Owns loading and storing:
- ``RunnerAppConfig`` history via ``app_info_cache``
- Blacklist, presets, schedules, expansions, timed schedules, recent adapters
- Security config
- Display position and virtual-screen info

Qt is imported inside ``start_periodic_store``, the one method that needs it, so
this module can be imported by a process that has no display. Such a process
writes the cache on every run and at shutdown, leaves the timer unstarted, and
never asks about display position -- those methods hand the window to
``app_info_cache``, which does its own Qt inside.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional, Union

from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from PySide6.QtCore import QTimer
    from sd_runner.headless_app import HeadlessApp
    from sd_runner.ui.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("cache_controller")


class CacheController:
    """
    Owns persistence: loading and storing the application info cache,
    RunnerAppConfig history, and display position.
    Also owns the periodic cache-store timer.
    """

    PENDING_SD_RUNS_KEY = "pending_sd_runs"
    PENDING_SERVER_REQUESTS_KEY = "pending_server_requests"
    GENERATION_TIMING_KEY = "generation_timing"

    def __init__(self, app_window: Union[AppWindow, HeadlessApp]):
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

        Run state only. The two windows that also restore something from the
        cache are left to the caller that has them: importing either from here
        would put Qt in a process that has no display, and on a machine with no
        PySide6 at all the ImportError would land in the catch below and
        abandon the rest of the load -- losing the presets, the schedules and
        the pending queues without saying so.
        """
        from utils.runner_app_config import RunnerAppConfig
        from sd_runner import blacklist_state
        from sd_runner.presets_state import PresetsState
        from sd_runner.schedules_state import SchedulesState
        from sd_runner.expansions_state import set_expansions as _set_expansions
        from sd_runner.recent_adapters_state import RecentAdaptersState
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from sd_runner.ui.auth.password_core import get_security_config

        try:
            self._app.config_history_index = app_info_cache.get(
                "config_history_index", default_val=0
            )
            blacklist_state.set_blacklist()
            # Run cache post-init once, now that blacklist settings have been restored.
            app_info_cache.post_init()
            self._app.config_history_index = app_info_cache.clamp_config_history_index(self._app.config_history_index)
            PresetsState.set_recent_presets()
            PresetsState.set_stashed_configs()
            PresetsState.set_intermediate_prompts()
            SchedulesState.set_schedules()
            _set_expansions()
            timed_schedules_manager.set_schedules()
            RecentAdaptersState.load_recent_adapters()
            # Security config is loaded automatically when first accessed
            get_security_config()
            runner_config = RunnerAppConfig.from_dict(
                app_info_cache.get_history(0)
            )
            self._restore_pending_queues()
            self._restore_generation_timing()
            return runner_config
        except Exception as e:
            logger.error(f"Failed to load info cache: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return RunnerAppConfig()

    def _restore_generation_timing(self) -> None:
        """Reload measured generation rates from the previous session."""
        from utils.generation_timing import generation_timing

        try:
            generation_timing.load_from_dict(
                app_info_cache.get(self.GENERATION_TIMING_KEY) or {}
            )
        except Exception as e:
            logger.warning(f"Failed to restore generation timing: {e}")

    def _store_generation_timing(self) -> None:
        """Persist measured generation rates.

        Averages rather than raw samples, so this stays a few hundred bytes
        however long the app runs.
        """
        from utils.generation_timing import generation_timing

        try:
            app_info_cache.set(self.GENERATION_TIMING_KEY, generation_timing.to_dict())
        except Exception as e:
            logger.warning(f"Failed to store generation timing: {e}")

    def _restore_pending_queues(self) -> None:
        """Restore pending SD runs and server staging requests saved at last shutdown."""
        from sd_runner.run_config import RunConfig

        runs_data = app_info_cache.get(self.PENDING_SD_RUNS_KEY) or []
        if runs_data:
            restored = 0
            for run_dict in runs_data:
                try:
                    self._app.job_queue.pending_jobs.append(RunConfig.from_dict(run_dict))
                    restored += 1
                except Exception as exc:
                    logger.warning(f"Failed to restore pending run: {exc}")
            if restored:
                self._app.job_queue.paused = True
                logger.info(f"Restored {restored} pending SD run(s) from previous session")
            app_info_cache.set(self.PENDING_SD_RUNS_KEY, [])

        requests_data = app_info_cache.get(self.PENDING_SERVER_REQUESTS_KEY) or []
        if requests_data:
            from extensions.sd_runner_server import CommandType
            restored = 0
            for req in requests_data:
                try:
                    # "command_type" is the current key. Cache files written before
                    # this restore path was corrected stored the same CommandType
                    # member name under the stale key "workflow_type" -- the writer
                    # already held a CommandType there, just mislabeled -- so that
                    # key is still a valid CommandType lookup and is tried as a
                    # fallback rather than discarding pre-existing staged requests.
                    name = req["command_type"] if "command_type" in req else req["workflow_type"]
                    command_type = CommandType[name]
                    # Absent in entries written before requests carried their
                    # client; those restore with an empty origin.
                    self._app.server_staging_queue._requests.append(
                        (command_type, req.get("args", {}), req.get("client_id", ""))
                    )
                    restored += 1
                except Exception as exc:
                    logger.warning(f"Failed to restore staging request: {exc}")
            if restored:
                logger.info(f"Restored {restored} server staging request(s) from previous session")
            app_info_cache.set(self.PENDING_SERVER_REQUESTS_KEY, [])

    # ------------------------------------------------------------------
    # Store
    # ------------------------------------------------------------------
    def store_info_cache(self, only_if_changed: bool = False) -> None:
        """
        Persist all application state to the encrypted cache.

        *only_if_changed* is for the periodic timer: the subsystem state is
        still collected (that is what makes the change detection accurate), but
        the encrypt-and-write is skipped when nothing moved. Every other caller
        leaves it False, so a save tied to a prompt execution always writes and
        therefore always runs the blacklist history purge.
        """
        from sd_runner import blacklist_state
        from sd_runner.presets_state import PresetsState
        from sd_runner.schedules_state import SchedulesState
        from sd_runner.expansions_state import store_expansions as _store_expansions
        from sd_runner.recent_adapters_state import RecentAdaptersState
        from sd_runner.timed_schedules_manager import timed_schedules_manager
        from sd_runner.ui.auth.password_core import get_security_config

        try:
            logger.debug("Storing info cache...")
            runner_config = self._app.runner_app_config
            if runner_config is not None:
                if app_info_cache.set_history(runner_config):
                    if self._app.config_history_index > 0:
                        self._app.config_history_index -= 1
            app_info_cache.set("config_history_index", self._app.config_history_index)
            # persist=False throughout: these subsystems write through on their
            # own edit handlers, but here they are only collecting, and the
            # single write below covers all of them at once.
            logger.debug("Storing blacklist...")
            blacklist_state.store_blacklist(persist=False)
            logger.debug("Storing presets...")
            PresetsState.store_recent_presets(persist=False)
            PresetsState.store_stashed_configs(persist=False)
            PresetsState.store_intermediate_prompts(persist=False)
            logger.debug("Storing schedules...")
            SchedulesState.store_schedules(persist=False)
            logger.debug("Storing expansions...")
            _store_expansions(persist=False)
            logger.debug("Storing timed schedules...")
            timed_schedules_manager.store_schedules()
            logger.debug("Storing recent adapters...")
            RecentAdaptersState.save_recent_adapters(persist=False)
            logger.debug("Storing security config...")
            get_security_config().save_settings()
            logger.debug("Storing pending queues...")
            self.store_pending_queues()
            logger.debug("Storing generation timing...")
            self._store_generation_timing()
            logger.debug("Storing app info cache...")
            app_info_cache.store(only_if_changed=only_if_changed)
            logger.debug("Info cache stored successfully")
        except Exception as e:
            logger.error(f"Failed to store info cache: {e}")

    # ------------------------------------------------------------------
    # Pending queues (cross-session persistence)
    # ------------------------------------------------------------------
    def store_pending_queues(self) -> None:
        """
        Snapshot pending SD runs and server staging requests into the cache
        so they can be restored in the next session.

        Called from store_info_cache, so it runs on every save path rather than
        only at shutdown. Saving these only on a clean exit covered the one case
        where nothing was at risk and missed every case where it was -- a crash
        or a kill lost the whole queue. Cost is bounded by the queue sizes
        (SDRunsQueue caps at 50, and staging entries are lightweight dicts).
        """
        try:
            job_queue = getattr(self._app, "job_queue", None)
            runs_data: list = []
            if job_queue is not None:
                for run_config in job_queue.pending_jobs:
                    try:
                        runs_data.append(run_config.to_dict())
                    except Exception as exc:
                        logger.warning(f"Failed to serialize pending run: {exc}")
            app_info_cache.set(self.PENDING_SD_RUNS_KEY, runs_data)

            staging = getattr(self._app, "server_staging_queue", None)
            requests_data: list = []
            if staging is not None:
                for entry in staging._requests:
                    # Unpacked inside the guard, not in the for-target: an entry
                    # of an unexpected shape then costs that one entry, matching
                    # the restore side, instead of aborting the whole store and
                    # silently saving no staged requests at all.
                    try:
                        command_type, args_dict, client_id = entry
                        requests_data.append({
                            "command_type": command_type.name if hasattr(command_type, "name") else str(command_type),
                            "args": args_dict,
                            "client_id": client_id,
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
    def start_periodic_store(self, interval_ms: Optional[int] = None) -> None:
        """
        Start a periodic timer to store the cache at intervals.

        With no argument the interval comes from
        ``config.cache_store_interval_seconds`` (default 300). Zero or less
        disables the timer, in which case the cache is still written on every
        run, on preset creation, and at shutdown.

        Replaces the async ``do_periodic_store_cache`` pattern.
        """
        if interval_ms is None:
            from utils.config import config
            try:
                interval_ms = int(config.cache_store_interval_seconds) * 1000
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid cache_store_interval_seconds; falling back to 300s"
                )
                interval_ms = 300_000
        if interval_ms <= 0:
            logger.info("Periodic cache store disabled by configuration")
            return
        from PySide6.QtCore import QTimer
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
            self.store_info_cache(only_if_changed=True)
        except Exception as e:
            logger.debug(f"Error in periodic store info cache: {e}")
