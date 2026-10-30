"""What a concept set's manifest says about where the set came from, and the
map from a translated set's lines back to the lines they translate.

The manifest never selects which blacklist items apply: those follow the text
being checked, whichever set is loaded.
"""

from dataclasses import dataclass
import functools
import json
import os

from lib.logging_setup import get_logger
from lib.pickleable_cache import fingerprint_string_sequence
from sd_runner.app_paths import concepts_dir
from sd_runner.config import config
from sd_runner.prompts.language_codes import normalize_language_code

logger = get_logger("prompts.concept_sets")

MANIFEST_FILENAME = "concept_set.json"
#: Each set has its own dictionary, which is not a translation of the other's.
_UNPAIRED_FILES = frozenset({"dictionary.txt"})
_NO_SOURCES: frozenset[str] = frozenset()


def read_concept_lines(filepath: str) -> list[str]:
    """The concepts in a file: blank lines and # comments removed."""
    lines = []
    with open(filepath, encoding="utf-8") as f:
        for line in f:
            value = line.split("#", 1)[0].strip()
            if value:
                lines.append(value)
    return lines


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


def _pairs_align(source_lines: list[str], lines: list[str]) -> bool:
    """Whether two files of equal length still correspond line for line.

    Equal length alone does not show it: a line inserted into both at different
    places keeps the counts equal and pairs everything between them wrongly.
    A line left untranslated sits in the same place in both files, so most lines
    the files share being elsewhere means they have drifted apart. A file sharing
    no lines gives no evidence and passes.
    """
    source_set = set(source_lines)
    shared = [(source, line) for source, line in zip(source_lines, lines) if line in source_set]
    displaced = sum(source != line for source, line in shared)
    return displaced * 2 <= len(shared)


class SourceAnchors:
    """Maps each line of a translated set to the source lines it translates.

    Pairs lines by position, since the translation catalogue is not shipped and
    the two folders are all a build has. A file that no longer pairs is skipped
    with one warning, and its lines get the plain check until the next
    translation pass.
    """

    _cache: dict[str, tuple[tuple, "SourceAnchors"]] = {}
    _unpaired_reported: set[str] = set()

    def __init__(self, sources: dict[str, frozenset[str]], language: str | None, fingerprint: str):
        self._sources = sources
        #: The basket the source lines are checked in; empty for an English source.
        self.source_languages = frozenset({language}) if language else frozenset()
        self.fingerprint = fingerprint

    def sources(self, line: str) -> frozenset[str]:
        return self._sources.get(line, _NO_SOURCES)

    @classmethod
    def for_set(cls, info: ConceptSetInfo) -> "SourceAnchors | None":
        """The map for a translated set, rebuilt when its files change; None for any other set."""
        if info.source_path is None:
            return None
        try:
            names = sorted(cls._pairable_files(info.path) & cls._pairable_files(info.source_path))
            stamp = max(
                (os.path.getmtime(os.path.join(folder, name))
                 for folder in (info.path, info.source_path) for name in names),
                default=0.0,
            )
        except OSError as e:
            logger.warning(f"Could not read the concept sets at {info.path}: {e}")
            return None
        key = (tuple(names), stamp)
        cached = cls._cache.get(info.path)
        if cached is not None and cached[0] == key:
            return cached[1]
        anchors = cls._build(info, names)
        cls._cache[info.path] = (key, anchors)
        return anchors

    @staticmethod
    def _pairable_files(folder: str) -> set[str]:
        return {name for name in os.listdir(folder)
                if name.endswith(".txt") and name not in _UNPAIRED_FILES}

    @classmethod
    def _build(cls, info: ConceptSetInfo, names: list[str]) -> "SourceAnchors":
        collected: dict[str, set[str]] = {}
        for name in names:
            path = os.path.join(info.path, name)
            try:
                source_lines = read_concept_lines(os.path.join(info.source_path, name))
                lines = read_concept_lines(path)
            except (OSError, UnicodeDecodeError) as e:
                logger.warning(f"Could not pair {path} with its source: {e}")
                continue
            if len(source_lines) != len(lines) or not _pairs_align(source_lines, lines):
                if path not in cls._unpaired_reported:
                    cls._unpaired_reported.add(path)
                    logger.warning(f"{path} no longer pairs with its source file; "
                                   "its lines are not judged by their source until the next translation pass")
                continue
            for source, line in zip(source_lines, lines):
                # An untranslated line gets the same answer from the plain check.
                if source != line:
                    collected.setdefault(line, set()).add(source)

        sources = {line: frozenset(found) for line, found in collected.items()}
        language = concept_set_info(info.source_path).language
        fingerprint = fingerprint_string_sequence(
            [language or ""] + ["\x1f".join((line, *sorted(sources[line]))) for line in sorted(sources)]
        )
        return cls(sources, language, fingerprint)

    @classmethod
    def reset_cache(cls) -> None:
        cls._cache = {}
        cls._unpaired_reported = set()
