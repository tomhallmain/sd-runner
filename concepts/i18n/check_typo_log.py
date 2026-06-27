#!/usr/bin/env python3
"""
Inspect docs/source_typos_log.tsv against the concepts/ catalog.

Helps decide rename vs remove vs defer before editing concepts/*.txt.

Run from concepts/i18n/ or repo root:

  python check_typo_log.py
  python check_typo_log.py --status open
  python check_typo_log.py --source Christs
  python check_typo_log.py --source Thruer --locale-dir Konzepte
"""

from __future__ import annotations

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from catalog_common import (  # noqa: E402
    DEFAULT_LOCALE_DIR,
    DEFAULT_SOURCE_DIR,
    find_line_indices,
    load_catalog_file,
    resolve_concepts_dir,
)

DEFAULT_TYPO_LOG = REPO_ROOT / "docs" / "source_typos_log.tsv"


@dataclass
class TypoRow:
    status: str
    msgctxt: str
    source: str
    suggested: str
    chunk: str
    notes: str


def load_typo_log(path: Path) -> list[TypoRow]:
    rows: list[TypoRow] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if parts[0] not in {"open", "fixed", "wontfix", "deferred"}:
                continue
            if len(parts) < 5:
                continue
            notes = parts[5] if len(parts) > 5 else ""
            rows.append(TypoRow(parts[0], parts[1], parts[2], parts[3], parts[4], notes))
    return rows


def filename_for_msgctxt(msgctxt: str) -> str:
    return msgctxt if msgctxt.endswith(".txt") else f"{msgctxt}.txt"


def analyze_row(
    row: TypoRow,
    *,
    source_dir: Path,
    locale_dir: Path | None,
) -> dict[str, object]:
    filename = filename_for_msgctxt(row.msgctxt)
    source_path = source_dir / filename
    source_lines = load_catalog_file(source_dir, filename) if source_path.is_file() else []
    locale_lines: list[str] = []
    if locale_dir is not None:
        locale_path = locale_dir / filename
        if locale_path.is_file():
            locale_lines = load_catalog_file(locale_dir, filename)

    source_hits = find_line_indices(source_lines, row.source)
    suggested_hits = (
        find_line_indices(source_lines, row.suggested)
        if row.suggested and not row.suggested.startswith("(")
        else []
    )

    locale_source_hits: list[int] = []
    locale_suggested_hits: list[int] = []
    if locale_lines:
        if source_hits:
            locale_source_hits = [i for i in source_hits if i < len(locale_lines)]
        if suggested_hits:
            locale_suggested_hits = [i for i in suggested_hits if i < len(locale_lines)]

    if not source_hits:
        action = "missing-from-catalog"
    elif suggested_hits:
        action = "remove-duplicate" if row.source != row.suggested else "already-fixed"
    elif row.suggested.startswith("(") or "remove" in row.suggested.lower():
        action = "manual-review"
    else:
        action = "rename"

    return {
        "filename": filename,
        "source_hits": source_hits,
        "suggested_hits": suggested_hits,
        "locale_source_hits": locale_source_hits,
        "locale_suggested_hits": locale_suggested_hits,
        "action": action,
    }


def _safe_print(text: str) -> None:
    try:
        print(text)
    except UnicodeEncodeError:
        print(text.encode(sys.stdout.encoding or "utf-8", errors="replace").decode(
            sys.stdout.encoding or "utf-8", errors="replace"
        ))


def print_row_report(row: TypoRow, info: dict[str, object], *, locale_dir: Path | None) -> None:
    _safe_print(f"[{row.status}] {row.msgctxt}\t{row.source}")
    _safe_print(f"  suggested: {row.suggested}")
    _safe_print(f"  source @{info['source_hits']}")
    if info["suggested_hits"]:
        _safe_print(f"  suggested already @{info['suggested_hits']}  -> {info['action']}")
    else:
        _safe_print(f"  suggested hits: none  -> {info['action']}")
    if locale_dir is not None and info["source_hits"]:
        idxs = info["source_hits"]
        assert isinstance(idxs, list)
        filename = info["filename"]
        assert isinstance(filename, str)
        locale_lines = load_catalog_file(locale_dir, filename)
        for i in idxs:
            if i < len(locale_lines):
                _safe_print(f"  Konzepte @{i}: {locale_lines[i]}")
    if row.notes:
        _safe_print(f"  notes: {row.notes}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Check typo log rows against concepts catalogs.")
    parser.add_argument("--log", default=str(DEFAULT_TYPO_LOG), help="Path to source_typos_log.tsv")
    parser.add_argument("--source-dir", default="concepts", help="English catalog directory")
    parser.add_argument(
        "--locale-dir",
        default="Konzepte",
        help="Locale catalog directory for index pairing (use '' to skip)",
    )
    parser.add_argument("--status", help="Filter by status (open, fixed, deferred, wontfix)")
    parser.add_argument("--source", help="Show one source_as_in_catalog value only")
    parser.add_argument(
        "--action",
        help="Filter by recommended action (rename, remove-duplicate, manual-review, missing-from-catalog)",
    )
    args = parser.parse_args()

    log_path = Path(args.log)
    if not log_path.is_file():
        print(f"Typo log not found: {log_path}", file=sys.stderr)
        return 1

    source_dir = resolve_concepts_dir(args.source_dir)
    locale_dir = resolve_concepts_dir(args.locale_dir) if args.locale_dir else None

    rows = load_typo_log(log_path)
    if args.status:
        rows = [r for r in rows if r.status == args.status]
    if args.source:
        rows = [r for r in rows if r.source == args.source]

    if not rows:
        print("No matching typo log rows.")
        return 1

    shown = 0
    for row in rows:
        info = analyze_row(row, source_dir=source_dir, locale_dir=locale_dir)
        if args.action and info["action"] != args.action:
            continue
        print_row_report(row, info, locale_dir=locale_dir)
        shown += 1

    if shown == 0:
        print("No rows matched filters.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
