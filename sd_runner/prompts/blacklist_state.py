"""Blacklist state as it is stored and restored.

Run configuration: which terms are blacklisted, in what mode, and the backups
taken when a list is cleared. A command-line script, a test, or a server
running without a window reaches the blacklist through here; ``BlacklistWindow``
is the editor for the same state.

``Blacklist`` holds the terms and the matching logic; this module is the wiring
between it and the stored application state, so the cache keys are known on one
side only.

The ``app_info_cache`` import stays inside each function: it builds its
singleton at import time, and importing this module should not force that.
"""

import datetime
from typing import Optional

from sd_runner.prompts.blacklist import Blacklist, SimilarityPhrase
from utils.config import config
from utils.globals import BlacklistMode, BlacklistPromptMode, ModelBlacklistMode
from utils.logging_setup import get_logger

logger = get_logger("prompts.blacklist_state")

# Cache key constants
BLACKLIST_CACHE_KEY = "tag_blacklist"
MODEL_BLACKLIST_CACHE_KEY = "model_blacklist"
BLACKLIST_BACKUP_KEY = "tag_blacklist_backup"
MODEL_BLACKLIST_BACKUP_KEY = "model_blacklist_backup"
DEFAULT_BLACKLIST_KEY = "blacklist_user_confirmed_non_default"
BLACKLIST_MODE_KEY = "blacklist_mode"
BLACKLIST_PROMPT_MODE_KEY = "blacklist_prompt_mode"
MODEL_BLACKLIST_MODE_KEY = "model_blacklist_mode"
BLACKLIST_SILENT_KEY = "blacklist_silent_removal"
MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY = "model_blacklist_all_prompt_modes"
SIMILARITY_PHRASES_KEY = "similarity_phrases"
SIMILARITY_THRESHOLD_KEY = "similarity_threshold"
SIMILARITY_ENABLED_KEY = "similarity_enabled"


def _restore_mode(enum_type, stored, current):
    """The stored mode, or *current* when the stored value is not one of them.

    Each of the three modes is read on its own, so an unreadable value costs
    that one setting and leaves the other two, and the blacklist still loads.
    """
    try:
        return enum_type(stored)
    except Exception:
        logger.error(
            f"Invalid {enum_type.__name__} in cache: {stored!r}; keeping {current}")
        return current


def set_blacklist():
    """Load blacklist from cache, validate items, and load global blacklist settings."""
    from utils.app_info_cache import app_info_cache

    expire_stale_backups()
    user_confirmed_non_default = app_info_cache.get(DEFAULT_BLACKLIST_KEY, default_val=False)
    mode_str = app_info_cache.get(BLACKLIST_MODE_KEY, default_val=str(Blacklist.get_blacklist_mode()))
    prompt_mode_str = app_info_cache.get(BLACKLIST_PROMPT_MODE_KEY, default_val=str(Blacklist.get_blacklist_prompt_mode()))
    model_mode_str = app_info_cache.get(MODEL_BLACKLIST_MODE_KEY, default_val=str(Blacklist.get_model_blacklist_mode()))
    Blacklist.set_blacklist_mode(
        _restore_mode(BlacklistMode, mode_str, Blacklist.get_blacklist_mode()))
    Blacklist.set_blacklist_prompt_mode(
        _restore_mode(BlacklistPromptMode, prompt_mode_str, Blacklist.get_blacklist_prompt_mode()))
    Blacklist.set_model_blacklist_mode(
        _restore_mode(ModelBlacklistMode, model_mode_str, Blacklist.get_model_blacklist_mode()))
    silent = app_info_cache.get(BLACKLIST_SILENT_KEY, default_val=False)
    Blacklist.set_blacklist_silent_removal(silent)
    all_prompt_modes = app_info_cache.get(MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY, default_val=False)
    Blacklist.set_model_blacklist_all_prompt_modes(all_prompt_modes)

    if not user_confirmed_non_default:
        try:
            Blacklist.decrypt_blacklist()
            logger.info("Loaded default encrypted blacklist for first-time user")
            return
        except Exception as e:
            logger.error(f"Error loading default blacklist: {e}")

    raw_blacklist = app_info_cache.get(BLACKLIST_CACHE_KEY, default_val=[])
    Blacklist.set_blacklist(raw_blacklist)
    raw_model_blacklist = app_info_cache.get(MODEL_BLACKLIST_CACHE_KEY, default_val=[])
    Blacklist.set_model_blacklist(raw_model_blacklist)

    Blacklist.set_similarity_enabled(
        bool(app_info_cache.get(SIMILARITY_ENABLED_KEY, default_val=False))
    )
    Blacklist.set_similarity_threshold(
        float(app_info_cache.get(SIMILARITY_THRESHOLD_KEY, default_val=0.85))
    )
    raw_phrases = app_info_cache.get(SIMILARITY_PHRASES_KEY, default_val=[])
    phrase_items = [SimilarityPhrase.from_dict(p) for p in raw_phrases if p]
    Blacklist.set_similarity_phrase_items([it for it in phrase_items if it is not None])


def store_blacklist(persist: bool = True):
    """Store blacklist to cache.

    Writes through to disk unless *persist* is False. The write is skipped
    when nothing actually changed, so calling this from an edit handler is
    cheap even when the edit was a no-op. store_info_cache passes False
    because it writes once itself after collecting every subsystem.
    """
    from utils.app_info_cache import app_info_cache

    Blacklist.save_cache()
    blacklist_dicts = [item.to_dict() for item in Blacklist.get_items()]
    app_info_cache.set(BLACKLIST_CACHE_KEY, blacklist_dicts)
    model_blacklist_dicts = [item.to_dict() for item in Blacklist.get_model_items()]
    app_info_cache.set(MODEL_BLACKLIST_CACHE_KEY, model_blacklist_dicts)
    app_info_cache.set(BLACKLIST_MODE_KEY, str(Blacklist.get_blacklist_mode()))
    app_info_cache.set(BLACKLIST_PROMPT_MODE_KEY, str(Blacklist.get_blacklist_prompt_mode()))
    app_info_cache.set(MODEL_BLACKLIST_MODE_KEY, str(Blacklist.get_model_blacklist_mode()))
    app_info_cache.set(BLACKLIST_SILENT_KEY, Blacklist.get_blacklist_silent_removal())
    app_info_cache.set(MODEL_BLACKLIST_ALL_PROMPT_MODES_KEY, Blacklist.get_model_blacklist_all_prompt_modes())
    app_info_cache.set(
        SIMILARITY_PHRASES_KEY,
        [it.to_dict() for it in Blacklist.get_similarity_phrase_items()],
    )
    app_info_cache.set(SIMILARITY_THRESHOLD_KEY, Blacklist.get_similarity_threshold())
    app_info_cache.set(SIMILARITY_ENABLED_KEY, Blacklist.get_similarity_enabled())
    # Once the blacklist has been persisted at least once, subsequent
    # loads should use the cached items instead of the encrypted default.
    if blacklist_dicts or model_blacklist_dicts:
        app_info_cache.set(DEFAULT_BLACKLIST_KEY, True)

    # Last: everything above has to be in the cache before it is written.
    if persist:
        app_info_cache.store(only_if_changed=True)


def mark_user_confirmed_non_default():
    """Mark that the user has explicitly confirmed they want a non-default blacklist state."""
    from utils.app_info_cache import app_info_cache
    app_info_cache.set(DEFAULT_BLACKLIST_KEY, True)


def is_in_default_state():
    """Check if the blacklist is in default state."""
    from utils.app_info_cache import app_info_cache
    return not app_info_cache.get(DEFAULT_BLACKLIST_KEY, default_val=False)


# ==================================================================
# Clear backups
#
# A clear empties the list and writes it straight to disk, so the items
# only survive if they are snapshotted before Blacklist.clear() runs.
# ==================================================================

def _merge_backup_items(older: list, newer: list) -> list:
    """Every item from both, *newer* winning where a string is in both."""
    merged = {}
    for item in list(older) + list(newer):
        if isinstance(item, dict) and isinstance(item.get("string"), str):
            merged[item["string"]] = item
    return list(merged.values())


def get_clear_backup(cache_key: str) -> Optional[dict]:
    """The restorable backup under *cache_key*, or None if there is none.

    Expiry is passive -- a backup past its retention window is dropped the
    first time anything asks for it. No timer is involved, so nothing has
    to outlive the window that took the backup. A backup whose timestamp is
    missing or unreadable is kept rather than discarded: losing the items
    is the worse failure.
    """
    from utils.app_info_cache import app_info_cache
    backup = app_info_cache.get(cache_key)
    if not isinstance(backup, dict) or not backup.get("items"):
        return None
    retention_days = config.blacklist_backup_retention_days
    if not retention_days or retention_days <= 0:
        return backup
    try:
        cleared_at = datetime.datetime.fromisoformat(backup.get("cleared_at"))
    except (TypeError, ValueError):
        return backup
    if (datetime.datetime.now() - cleared_at).days >= retention_days:
        app_info_cache.remove(cache_key)
        return None
    return backup


def expire_stale_backups() -> None:
    """Drop any backup past its retention period, even if nobody looks.

    ``get_clear_backup`` does the expiring; calling it at startup means a
    backup does not sit on disk indefinitely just because the blacklist
    window is never opened.
    """
    get_clear_backup(BLACKLIST_BACKUP_KEY)
    get_clear_backup(MODEL_BLACKLIST_BACKUP_KEY)


def store_clear_backup(cache_key: str, items: list) -> None:
    """Snapshot *items* under *cache_key* before they are cleared.

    Clearing twice inside one retention period merges rather than replaces,
    so the second clear cannot throw away what the first one saved. The
    period then runs from the most recent clear, so a fresh clear is always
    restorable for its full length.
    """
    from utils.app_info_cache import app_info_cache
    snapshot = [item.to_dict() for item in items]
    existing = get_clear_backup(cache_key)
    if existing is not None:
        snapshot = _merge_backup_items(existing.get("items", []), snapshot)
    if not snapshot:
        return
    app_info_cache.set(cache_key, {
        "items": snapshot,
        "cleared_at": datetime.datetime.now().isoformat(),
    })


def take_clear_backup(cache_key: str, current: list) -> Optional[list]:
    """A backup's items merged over *current*, and the backup dropped.

    None when nothing is live to restore. Merged rather than substituted so
    that anything added since the clear is not lost by restoring.
    """
    from utils.app_info_cache import app_info_cache
    backup = get_clear_backup(cache_key)
    if backup is None:
        return None
    merged = _merge_backup_items(
        backup.get("items", []), [item.to_dict() for item in current]
    )
    app_info_cache.remove(cache_key)
    return merged


def load_default_blacklist() -> bool:
    """Load the default encrypted blacklist without UI. Returns True on success."""
    from utils.app_info_cache import app_info_cache

    try:
        Blacklist.decrypt_blacklist()
        app_info_cache.set(DEFAULT_BLACKLIST_KEY, False)
        store_blacklist()
        return True
    except Exception:
        return False
