"""What a concept set's manifest says about where the set came from.

The manifest never selects which blacklist items apply: those follow the text
being checked, whichever set is loaded.
"""

from dataclasses import dataclass
import functools
import json
import os

from lib.logging_setup import get_logger
from sd_runner.app_paths import concepts_dir
from sd_runner.config import config
from sd_runner.prompts.language_codes import normalize_language_code

logger = get_logger("prompts.concept_sets")

MANIFEST_FILENAME = "concept_set.json"


@dataclass(frozen=True)
class ConceptSetInfo:
    path: str
    language: str | None  # normalised: None for English or no manifest
    source_path: str | None  # folder of the set this one was translated from


def _resolve_source_set(name: object) -> str | None:
    if not isinstance(name, str) or not name.strip():
        return None
    name = name.strip()
    path = None if name == "concepts" else config.concepts_dirs.get(name)
    return path if path else concepts_dir(name)


@functools.lru_cache(maxsize=None)
def concept_set_info(path: str) -> ConceptSetInfo:
    """The manifest of the set at *path*. A set may have none: no language, no source."""
    manifest_path = os.path.join(path, MANIFEST_FILENAME)
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
        if not isinstance(manifest, dict):
            raise ValueError("not a JSON object")
    except FileNotFoundError:
        return ConceptSetInfo(path, None, None)
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read {manifest_path}: {e}")
        return ConceptSetInfo(path, None, None)

    source_path = _resolve_source_set(manifest.get("source_set"))
    if source_path is not None and not os.path.isdir(source_path):
        logger.warning(f"{manifest_path} names a source set that was not found: {source_path}")
        source_path = None
    return ConceptSetInfo(path, normalize_language_code(manifest.get("language")), source_path)
