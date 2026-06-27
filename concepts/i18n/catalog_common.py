"""
Shared helpers for comparing and searching concepts catalog directories.

Used by compare_concept_dirs.py, find_in_concepts.py, and check_typo_log.py.
Run scripts from concepts/i18n/ or the repository root.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from concepts_gettext import DEFAULT_EXCLUDE_FILES, get_concept_txt_files, load_concepts_file

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
DEFAULT_SOURCE_DIR = REPO_ROOT / "concepts"
DEFAULT_LOCALE_DIR = REPO_ROOT / "Konzepte"


def resolve_concepts_dir(path: str | Path, *, base: Path | None = None) -> Path:
    """Resolve a concepts directory path relative to repo root unless absolute."""
    p = Path(path)
    if p.is_absolute():
        return p
    return (base or REPO_ROOT) / p


def load_catalog_file(concepts_dir: Path, filename: str) -> list[str]:
    return load_concepts_file(str(concepts_dir / filename))


def list_catalog_files(
    concepts_dir: Path,
    *,
    exclude_files: frozenset[str] | None = None,
    include_all_txt: bool = False,
) -> list[str]:
    if include_all_txt:
        return sorted(
            name
            for name in os.listdir(concepts_dir)
            if name.endswith(".txt") and not name.startswith("temp_")
            and (concepts_dir / name).is_file()
        )
    return get_concept_txt_files(str(concepts_dir), exclude_files)


def find_line_indices(
    lines: list[str],
    needle: str,
    *,
    ignore_case: bool = False,
    substring: bool = False,
) -> list[int]:
    indices: list[int] = []
    if ignore_case:
        needle_cmp = needle.casefold()
        for i, line in enumerate(lines):
            hay = line.casefold()
            if (substring and needle_cmp in hay) or (not substring and hay == needle_cmp):
                indices.append(i)
    else:
        for i, line in enumerate(lines):
            if (substring and needle in line) or (not substring and line == needle):
                indices.append(i)
    return indices


@dataclass
class FileCount:
    filename: str
    left: int
    right: int

    @property
    def matches(self) -> bool:
        return self.left == self.right


@dataclass
class AlignedRow:
    index: int
    left: str | None
    right: str | None

    @property
    def same(self) -> bool:
        return self.left == self.right


def count_lines_by_file(
    left_dir: Path,
    right_dir: Path,
    *,
    filenames: list[str] | None = None,
) -> list[FileCount]:
    left_names = set(list_catalog_files(left_dir))
    right_names = set(list_catalog_files(right_dir))
    all_names = sorted(filenames or (left_names | right_names))
    rows: list[FileCount] = []
    for name in all_names:
        left_n = len(load_catalog_file(left_dir, name)) if name in left_names else 0
        right_n = len(load_catalog_file(right_dir, name)) if name in right_names else 0
        rows.append(FileCount(name, left_n, right_n))
    return rows


def aligned_rows(
    left_lines: list[str],
    right_lines: list[str],
    *,
    start: int = 0,
    limit: int | None = None,
) -> list[AlignedRow]:
    max_len = max(len(left_lines), len(right_lines))
    end = max_len if limit is None else min(max_len, start + limit)
    rows: list[AlignedRow] = []
    for i in range(start, end):
        left = left_lines[i] if i < len(left_lines) else None
        right = right_lines[i] if i < len(right_lines) else None
        rows.append(AlignedRow(i, left, right))
    return rows


def first_differing_index(left_lines: list[str], right_lines: list[str]) -> int | None:
    """First index where line text differs (only meaningful when counts match)."""
    for i, (left, right) in enumerate(zip(left_lines, right_lines, strict=False)):
        if left != right:
            return i
    if len(left_lines) != len(right_lines):
        return min(len(left_lines), len(right_lines))
    return None


def format_pair(index: int, left: str | None, right: str | None, *, width: int = 72) -> str:
    def clip(value: str | None) -> str:
        if value is None:
            return "(missing)"
        if len(value) <= width:
            return value
        return value[: width - 3] + "..."

    marker = " " if left == right else "!"
    return f"{marker} {index:5d}  {clip(left):<{width}}  |  {clip(right)}"
