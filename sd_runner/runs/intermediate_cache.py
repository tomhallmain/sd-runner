"""Reuse of pre-pass generations across runs that differ only in what follows.

A pre-pass transforms the user's source image before their own run consumes it.
Runs that share a source image and a pre-pass produce the same intermediate, so
the work is worth doing once -- ten edit requests over one photograph should pay
for the transformation once between them.

The intermediate is not the end result, only an input to the change the user
asked for, so the key is deliberately narrow: the source image, the prompt, and
the workflow. Seed, model and the sampler settings are left out. Including them
would be more faithful and would hit far less often; on the default seed of -1,
which draws fresh per generation, a seed-keyed entry would never be reused at
all and "run it once" would quietly never happen.
"""

import hashlib
import json
import os
import random
import threading

from utils.logging_setup import get_logger

logger = get_logger("runs.intermediate_cache")


class IntermediateCache:
    CACHE_KEY = "intermediate_generations"

    #: Distinct source-image/prompt combinations to remember. Each holds at
    #: most its prompt's variant count, so the ceiling is this times that.
    MAX_KEYS = 200

    _locks: dict = {}
    _locks_guard = threading.Lock()

    # ------------------------------------------------------------------
    # Key
    # ------------------------------------------------------------------
    @staticmethod
    def _source_identity(source_path: str) -> str:
        """Path, plus size and mtime when they can be read.

        A path alone is stable but its contents are not, so an edited or
        replaced file would otherwise keep returning the intermediate made from
        what used to be there.
        """
        try:
            stat = os.stat(source_path)
            return f"{source_path}|{stat.st_size}|{int(stat.st_mtime)}"
        except OSError:
            return source_path

    @staticmethod
    def key_for(prompt: dict, source_path: str) -> str:
        """The cache key for *prompt* applied to *source_path*.

        Hashed rather than concatenated because the parts include free text of
        any length, and this is used as a dict key in the persisted cache.
        """
        parts = {
            "source": IntermediateCache._source_identity(source_path),
            "positive": prompt.get("positive_tags") or "",
            "negative": (prompt.get("negative_tags") or "") if prompt.get("use_negative") else "",
            "workflow": prompt.get("workflow_type") or "",
        }
        blob = json.dumps(parts, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    # ------------------------------------------------------------------
    # Storage
    # ------------------------------------------------------------------
    @staticmethod
    def _read() -> dict:
        from utils.app_info_cache import app_info_cache
        stored = app_info_cache.get(IntermediateCache.CACHE_KEY, default_val={})
        return stored if isinstance(stored, dict) else {}

    @staticmethod
    def _write(entries: dict) -> None:
        from utils.app_info_cache import app_info_cache
        app_info_cache.set(IntermediateCache.CACHE_KEY, entries)

    @staticmethod
    def get(key: str) -> "str | None":
        """A usable intermediate for *key*, or None.

        Every hit is confirmed against the filesystem: the files live in the
        backend's output directory, which this app does not manage, so a user
        tidying that folder must regenerate rather than break. Paths that have
        gone are dropped as they are found.

        Picks at random when several are stored, which is what makes a variant
        count above one worth setting: the alternative is generating several
        and always handing back the same one.
        """
        entries = IntermediateCache._read()
        paths = entries.get(key) or []
        live = [path for path in paths if os.path.isfile(path)]
        if len(live) != len(paths):
            if live:
                entries[key] = live
            else:
                entries.pop(key, None)
            IntermediateCache._write(entries)
        if not live:
            return None
        return random.choice(live)

    @staticmethod
    def count(key: str) -> int:
        """How many intermediates are already stored for *key*."""
        return len(IntermediateCache._read().get(key) or [])

    @staticmethod
    def put(key: str, path: str, max_variants: int = 1) -> None:
        """Remember *path* for *key*, keeping at most *max_variants* of them."""
        if not path:
            return
        entries = IntermediateCache._read()
        paths = [p for p in (entries.get(key) or []) if p != path]
        paths.append(path)
        limit = max(1, int(max_variants or 1))
        entries[key] = paths[-limit:]
        if len(entries) > IntermediateCache.MAX_KEYS:
            for stale in list(entries)[: len(entries) - IntermediateCache.MAX_KEYS]:
                del entries[stale]
        IntermediateCache._write(entries)

    # ------------------------------------------------------------------
    # In-flight coordination
    # ------------------------------------------------------------------
    @staticmethod
    def lock(key: str) -> threading.Lock:
        """The lock guarding *key*'s generation.

        Runs are serialized, so ten requests never race -- but one run
        dispatches several workflows onto a shared executor at once, and
        without this they would all miss the same empty entry and all generate.
        Held across the generation so the first caller does the work and the
        rest wait for its result rather than duplicating it.
        """
        with IntermediateCache._locks_guard:
            if key not in IntermediateCache._locks:
                IntermediateCache._locks[key] = threading.Lock()
            return IntermediateCache._locks[key]

    @staticmethod
    def clear() -> None:
        """Drop every entry. For tests and for a user-facing reset."""
        IntermediateCache._write({})
        with IntermediateCache._locks_guard:
            IntermediateCache._locks.clear()
