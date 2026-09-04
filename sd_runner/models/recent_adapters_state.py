"""Recently used adapter files, and the favourites among them.

Run configuration: the ControlNet, IP adapter and source prompt paths a run has
used, the split file list behind them, and the favourites. The run path writes
these on every adapter it touches, so a server running without a window reaches
them through here; ``RecentAdaptersWindow`` is the browser for the same state
and keeps the display rows it builds from them.

A favourite is a path that still exists: both load and save sanitize the list,
so a file removed on disk drops out rather than being carried forward.

The ``app_info_cache`` import stays inside each function: it builds its
singleton at import time, and importing this module should not force that.
"""

import os

from lib.logging_setup import get_logger
from lib.utils import Utils

logger = get_logger("models.recent_adapters_state")


class RecentAdaptersState:
    """The recent lists and favourites, and the cache they persist to."""

    # Persistent storage for recent adapters (just file paths)
    _recent_controlnets: list[str] = []
    _recent_ipadapters: list[str] = []
    _recent_source_prompts: list[str] = []
    _recent_adapter_files_split: list[str] = []
    _favorite_adapters: list[str] = []

    # Default constants
    DEFAULT_MAX_RECENT_ITEMS = 1000
    DEFAULT_MAX_RECENT_SPLIT_ITEMS = 2000
    MAX_RECENT_ITEMS_KEY = "max_recent_items"
    MAX_RECENT_SPLIT_ITEMS_KEY = "max_recent_split_items"
    RECENT_CONTROLNETS_KEY = "recent_controlnets"
    RECENT_IPADAPTERS_KEY = "recent_ipadapters"
    RECENT_SOURCE_PROMPTS_KEY = "recent_source_prompts"
    RECENT_ADAPTER_FILES_SPLIT_KEY = "recent_adapter_files_split"
    FAVORITE_ADAPTERS_KEY = "favorite_adapters"

    @staticmethod
    def _normalize_path(path: str) -> str:
        try:
            return os.path.abspath(path.strip())
        except Exception:
            return path.strip()

    @staticmethod
    def _sanitize_favorites(paths: list[str]) -> list[str]:
        """Normalize, dedupe, and keep only existing favorite paths."""
        sanitized: list[str] = []
        for path in paths:
            if not isinstance(path, str) or not path.strip():
                continue
            norm = RecentAdaptersState._normalize_path(path)
            if norm in sanitized:
                continue
            if Utils.exists_with_retry(norm):
                sanitized.append(norm)
            else:
                logger.warning(f"Favorite path {norm} does not exist, skipping")
                if path in RecentAdaptersState._recent_controlnets:
                    RecentAdaptersState._recent_controlnets.remove(path)
                if path in RecentAdaptersState._recent_ipadapters:
                    RecentAdaptersState._recent_ipadapters.remove(path)
                if path in RecentAdaptersState._recent_source_prompts:
                    RecentAdaptersState._recent_source_prompts.remove(path)
                if path in RecentAdaptersState._recent_adapter_files_split:
                    RecentAdaptersState._recent_adapter_files_split.remove(path)
        return sanitized

    @staticmethod
    def _get_max_recent_items() -> int:
        from sd_runner.persistence.app_info_cache import app_info_cache
        return app_info_cache.get(
            RecentAdaptersState.MAX_RECENT_ITEMS_KEY,
            default_val=RecentAdaptersState.DEFAULT_MAX_RECENT_ITEMS
        )

    @staticmethod
    def _get_max_recent_split_items() -> int:
        from sd_runner.persistence.app_info_cache import app_info_cache
        return app_info_cache.get(
            RecentAdaptersState.MAX_RECENT_SPLIT_ITEMS_KEY,
            default_val=RecentAdaptersState.DEFAULT_MAX_RECENT_SPLIT_ITEMS
        )

    @staticmethod
    def load_recent_adapters() -> None:
        from sd_runner.persistence.app_info_cache import app_info_cache
        try:
            max_recent_items = RecentAdaptersState._get_max_recent_items()
            max_recent_split_items = RecentAdaptersState._get_max_recent_split_items()
            RecentAdaptersState._recent_controlnets = app_info_cache.get(RecentAdaptersState.RECENT_CONTROLNETS_KEY, [])
            RecentAdaptersState._recent_ipadapters = app_info_cache.get(RecentAdaptersState.RECENT_IPADAPTERS_KEY, [])
            RecentAdaptersState._recent_source_prompts = app_info_cache.get(RecentAdaptersState.RECENT_SOURCE_PROMPTS_KEY, [])
            RecentAdaptersState._recent_adapter_files_split = app_info_cache.get(RecentAdaptersState.RECENT_ADAPTER_FILES_SPLIT_KEY, [])
            RecentAdaptersState._favorite_adapters = app_info_cache.get(RecentAdaptersState.FAVORITE_ADAPTERS_KEY, [])
            if len(RecentAdaptersState._recent_controlnets) > max_recent_items:
                RecentAdaptersState._recent_controlnets = RecentAdaptersState._recent_controlnets[:max_recent_items]
            if len(RecentAdaptersState._recent_ipadapters) > max_recent_items:
                RecentAdaptersState._recent_ipadapters = RecentAdaptersState._recent_ipadapters[:max_recent_items]
            if len(RecentAdaptersState._recent_source_prompts) > max_recent_items:
                RecentAdaptersState._recent_source_prompts = RecentAdaptersState._recent_source_prompts[:max_recent_items]
            if len(RecentAdaptersState._recent_adapter_files_split) > max_recent_split_items:
                RecentAdaptersState._recent_adapter_files_split = RecentAdaptersState._recent_adapter_files_split[:max_recent_split_items]

            # Keep only valid, normalized favorites and preserve ordering.
            RecentAdaptersState._favorite_adapters = RecentAdaptersState._sanitize_favorites(
                RecentAdaptersState._favorite_adapters
            )

            # Auto-favorite directories from recents so high-value folders
            # remain easy to access.
            for path in (
                RecentAdaptersState._recent_controlnets
                + RecentAdaptersState._recent_ipadapters
                + RecentAdaptersState._recent_source_prompts
            ):
                if isinstance(path, str) and path.strip():
                    norm = RecentAdaptersState._normalize_path(path)
                    if os.path.isdir(norm):
                        RecentAdaptersState.add_favorite_adapter(norm, save=False)
        except Exception as e:
            logger.error(f"Failed to load recent adapters from cache: {e}")
            RecentAdaptersState._recent_controlnets = []
            RecentAdaptersState._recent_ipadapters = []
            RecentAdaptersState._recent_source_prompts = []
            RecentAdaptersState._recent_adapter_files_split = []
            RecentAdaptersState._favorite_adapters = []

    @staticmethod
    def save_recent_adapters(persist: bool = True) -> None:
        """Store recent and favorite adapters to cache.

        Writes through to disk unless *persist* is False. The write is skipped
        when nothing actually changed, so calling this from an edit handler is
        cheap even when the edit was a no-op. store_info_cache passes False
        because it writes once itself after collecting every subsystem.
        """
        from sd_runner.persistence.app_info_cache import app_info_cache
        try:
            # Re-check existence before saving so stale favorites are not persisted.
            RecentAdaptersState._favorite_adapters = RecentAdaptersState._sanitize_favorites(
                RecentAdaptersState._favorite_adapters
            )
            app_info_cache.set(RecentAdaptersState.RECENT_CONTROLNETS_KEY, RecentAdaptersState._recent_controlnets)
            app_info_cache.set(RecentAdaptersState.RECENT_IPADAPTERS_KEY, RecentAdaptersState._recent_ipadapters)
            app_info_cache.set(RecentAdaptersState.RECENT_SOURCE_PROMPTS_KEY, RecentAdaptersState._recent_source_prompts)
            app_info_cache.set(RecentAdaptersState.RECENT_ADAPTER_FILES_SPLIT_KEY, RecentAdaptersState._recent_adapter_files_split)
            app_info_cache.set(RecentAdaptersState.FAVORITE_ADAPTERS_KEY, RecentAdaptersState._favorite_adapters)
            if persist:
                app_info_cache.store(only_if_changed=True)
        except Exception as e:
            logger.error(f"Failed to save recent adapters to cache: {e}")

    @staticmethod
    def add_favorite_adapter(file_path: str, save: bool = True) -> bool:
        if not file_path or not file_path.strip():
            return False
        path = RecentAdaptersState._normalize_path(file_path)
        if not os.path.exists(path):
            return False
        if path in RecentAdaptersState._favorite_adapters:
            return False
        RecentAdaptersState._favorite_adapters.insert(0, path)
        if save:
            RecentAdaptersState.save_recent_adapters()
        return True

    @staticmethod
    def remove_favorite_adapter(file_path: str, save: bool = True) -> bool:
        if not file_path or not file_path.strip():
            return False
        path = RecentAdaptersState._normalize_path(file_path)
        if path not in RecentAdaptersState._favorite_adapters:
            return False
        RecentAdaptersState._favorite_adapters.remove(path)
        if save:
            RecentAdaptersState.save_recent_adapters()
        return True

    @staticmethod
    def _validate_and_process_file_paths(file_paths: str) -> list[str]:
        if not file_paths or file_paths.strip() == "":
            return []
        valid_paths = []
        for file_path in file_paths.split(","):
            file_path = file_path.strip()
            if file_path and os.path.exists(file_path):
                valid_paths.append(file_path)
        return valid_paths

    @staticmethod
    def add_recent_controlnet(file_path: str) -> None:
        max_recent_items = RecentAdaptersState._get_max_recent_items()
        valid_paths = RecentAdaptersState._validate_and_process_file_paths(file_path)
        for path in valid_paths:
            if path in RecentAdaptersState._recent_controlnets:
                RecentAdaptersState._recent_controlnets.remove(path)
            RecentAdaptersState._recent_controlnets.insert(0, path)
            if os.path.isdir(path):
                RecentAdaptersState.add_favorite_adapter(path, save=False)
        if len(RecentAdaptersState._recent_controlnets) > max_recent_items:
            RecentAdaptersState._recent_controlnets = RecentAdaptersState._recent_controlnets[:max_recent_items]

    @staticmethod
    def add_recent_ipadapter(file_path: str) -> None:
        max_recent_items = RecentAdaptersState._get_max_recent_items()
        valid_paths = RecentAdaptersState._validate_and_process_file_paths(file_path)
        for path in valid_paths:
            if path in RecentAdaptersState._recent_ipadapters:
                RecentAdaptersState._recent_ipadapters.remove(path)
            RecentAdaptersState._recent_ipadapters.insert(0, path)
            if os.path.isdir(path):
                RecentAdaptersState.add_favorite_adapter(path, save=False)
        if len(RecentAdaptersState._recent_ipadapters) > max_recent_items:
            RecentAdaptersState._recent_ipadapters = RecentAdaptersState._recent_ipadapters[:max_recent_items]

    @staticmethod
    def add_recent_source_prompt(file_path: str) -> None:
        max_recent_items = RecentAdaptersState._get_max_recent_items()
        valid_paths = RecentAdaptersState._validate_and_process_file_paths(file_path)
        for path in valid_paths:
            if path in RecentAdaptersState._recent_source_prompts:
                RecentAdaptersState._recent_source_prompts.remove(path)
            RecentAdaptersState._recent_source_prompts.insert(0, path)
            if os.path.isdir(path):
                RecentAdaptersState.add_favorite_adapter(path, save=False)
            RecentAdaptersState.add_recent_adapter_file(path)
        if len(RecentAdaptersState._recent_source_prompts) > max_recent_items:
            RecentAdaptersState._recent_source_prompts = RecentAdaptersState._recent_source_prompts[:max_recent_items]

    @staticmethod
    def add_recent_adapter_file(file_path: str) -> None:
        if not file_path or file_path.strip() == "":
            return
        path = file_path.strip()
        try:
            if not os.path.isfile(path):
                return
        except Exception:
            return
        try:
            norm = os.path.abspath(path)
        except Exception:
            norm = path
        if norm in RecentAdaptersState._recent_adapter_files_split:
            RecentAdaptersState._recent_adapter_files_split.remove(norm)
        RecentAdaptersState._recent_adapter_files_split.insert(0, norm)
        max_recent_split_items = RecentAdaptersState._get_max_recent_split_items()
        if len(RecentAdaptersState._recent_adapter_files_split) > max_recent_split_items:
            RecentAdaptersState._recent_adapter_files_split = RecentAdaptersState._recent_adapter_files_split[:max_recent_split_items]

    @staticmethod
    def contains_recent_adapter_file(file_path: str) -> int:
        if not file_path or file_path.strip() == "":
            return -1
        try:
            norm = os.path.abspath(file_path.strip())
        except Exception:
            norm = file_path.strip()
        try:
            return RecentAdaptersState._recent_adapter_files_split.index(norm)
        except ValueError:
            return -1
