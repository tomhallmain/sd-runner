"""Backlog of concepts added since the last translation pass.

Written as plain JSON rather than into the encrypted app cache: the consumer is
the ``concepts/i18n`` tooling, which needs to read this without decrypting
anything. Nothing here is sensitive -- it is a list of concepts the user just
typed into the editor, all of which are already sitting in ``concepts/``.

Entries record concept text plus source file, and deliberately **no line index**.
``ConceptsFile.add_concept`` inserts alphabetically, so a position captured at
add time is wrong as soon as anything else is inserted into the same file. It is
also unnecessary: ``Konzepte/`` mirrors ``concepts/`` line-for-line, so the
insertion point for a translation is recomputable from the concept's current
position at the time the batch pass runs.

Deliberately Qt-free so the i18n scripts can import it directly.
"""

import json
import os

from lib.logging_setup import get_logger

logger = get_logger("prompts.pending_translation")

#: sd_runner/prompts/ -> sd_runner/ -> repo root. Named once so a move
#: corrects one line rather than a count buried in a dirname chain.
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_DEFAULT_DIR = os.path.join(_REPO_ROOT, "configs")

#: dictionary.txt is excluded from the gettext export and maintained on its own
#: schedule, so additions to it are never staged.
EXCLUDED_FILES = ("dictionary.txt",)


def resolve_pending_translation_file() -> str:
    """Path to the backlog file.

    Honours ``SD_RUNNER_CACHE_DIR`` so tests redirect it automatically, and
    otherwise lands in ``configs/``, which is gitignored -- mirroring how the
    blacklist filter cache resolves its own path.
    """
    override = os.environ.get("SD_RUNNER_CACHE_DIR")
    base = override if override else _DEFAULT_DIR
    return os.path.join(base, "pending_translation.json")


def get_pending_translations() -> list:
    """Staged entries, oldest first. ``[{"concept": str, "file": str}, ...]``.

    A missing or unreadable file is an empty backlog, not an error -- this is a
    convenience list, and failing to read it must never block a concept edit.
    """
    path = resolve_pending_translation_file()
    if not os.path.isfile(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            entries = json.load(f)
    except Exception as e:
        logger.warning(f"Could not read the pending translation list at {path}: {e}")
        return []
    return entries if isinstance(entries, list) else []


def _write(entries: list) -> None:
    path = resolve_pending_translation_file()
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entries, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logger.warning(f"Could not write the pending translation list at {path}: {e}")


def stage_for_translation(concepts, source_file: str) -> int:
    """Record newly added *concepts* as awaiting translation.

    Returns how many entries were added. Already-staged ``(concept, file)``
    pairs are skipped, so re-adding a concept still in the backlog does not
    duplicate it.
    """
    if not source_file or os.path.basename(source_file) in EXCLUDED_FILES:
        return 0
    if isinstance(concepts, str):
        concepts = [concepts]

    pending = get_pending_translations()
    already = {(entry.get("concept"), entry.get("file")) for entry in pending}
    added = 0
    for concept in concepts:
        concept = str(concept).strip()
        if not concept or (concept, source_file) in already:
            continue
        pending.append({"concept": concept, "file": source_file})
        already.add((concept, source_file))
        added += 1

    if added:
        _write(pending)
        logger.info(f"Staged {added} concept(s) from {source_file} for translation")
    return added


def clear_pending_translations(entries=None) -> None:
    """Drop the whole backlog, or just *entries* once they have been translated."""
    if entries is None:
        _write([])
        return
    done = {(e.get("concept"), e.get("file")) for e in entries}
    remaining = [
        entry for entry in get_pending_translations()
        if (entry.get("concept"), entry.get("file")) not in done
    ]
    _write(remaining)
