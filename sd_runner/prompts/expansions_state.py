"""Prompt expansions as they are stored and restored.

Run configuration: the named text expansions a prompt can refer to. A test or a
server running without a window reaches them through here; ``ExpansionsWindow``
is the editor for the same state.

``Expansion`` holds the list itself; this module is the wiring between it and
the stored application state, so the cache key is known on one side only.

The ``app_info_cache`` import stays inside each function: it builds its
singleton at import time, and importing this module should not force that.
"""

from sd_runner.prompts.expansion import Expansion

EXPANSIONS_CACHE_KEY = "expansions"


def set_expansions():
    from utils.app_info_cache import app_info_cache

    for expansion_dict in list(app_info_cache.get(EXPANSIONS_CACHE_KEY, default_val=[])):
        Expansion.expansions.append(Expansion.from_dict(expansion_dict))


def store_expansions(persist: bool = True):
    """Store expansions to cache.

    Writes through to disk unless *persist* is False. The write is skipped
    when nothing actually changed, so calling this from an edit handler is
    cheap even when the edit was a no-op. store_info_cache passes False
    because it writes once itself after collecting every subsystem.
    """
    from utils.app_info_cache import app_info_cache

    expansion_dicts = [expansion.to_dict() for expansion in Expansion.expansions]
    app_info_cache.set(EXPANSIONS_CACHE_KEY, expansion_dicts)

    if persist:
        app_info_cache.store(only_if_changed=True)


