#!/usr/bin/env python3
"""
Compare concepts from an external wildcards directory (e.g. sd-wildcards) against
concepts already present in this repository's concept files.

Run from the repository root:

    python scripts/compare_wildcards_to_repo_concepts.py
    python scripts/compare_wildcards_to_repo_concepts.py --wildcards-dir concepts/temp/sd-wildcards/wildcards
    python scripts/compare_wildcards_to_repo_concepts.py --wildcards-dir concepts/temp/sd-wildcards/wildcards --include-dictionary
    python -m scripts.compare_wildcards_to_repo_concepts --wildcards-dir concepts/temp/sd-wildcards/wildcards --csv wildcard_coverage.csv

Uses the same line parsing as ``Concepts.load`` (strip, stop at ``#``).
Matching is case-insensitive unless ``--case-sensitive`` is passed.

By default, NSFW wildcard files (filename contains ``nsfw``, case-insensitive) are skipped.
Repository concepts default to SFW + Art Styles only (NSFW/NSFL/Dictionary off) unless flags change that.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


# Run as if from project root (same pattern as other scripts in this folder)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def _parse_line_like_concepts_load(line: str) -> str:
    """Mirror sd_runner.concepts.Concepts.load line handling."""
    val = ""
    for c in line:
        if c == "#":
            break
        val += c
    return val.strip()


def load_concepts_from_path(filepath: Path) -> list[str]:
    """Load one text file; return non-empty stripped lines (comments removed)."""
    out: list[str] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                v = _parse_line_like_concepts_load(line)
                if v:
                    out.append(v)
    except OSError as e:
        print(f"Warning: could not read {filepath}: {e}", file=sys.stderr)
    return out


def is_nsfw_wildcard_file(name: str) -> bool:
    n = name.lower()
    return "nsfw" in n


def build_repo_concept_set(
    *,
    include_dictionary: bool,
    include_nsfw: bool,
    include_nsfl: bool,
    case_sensitive: bool,
) -> set[str]:
    """Union of all concept strings from enabled repo categories."""
    from sd_runner.concepts import Concepts

    category_states = {
        "SFW": True,
        "NSFW": bool(include_nsfw),
        "NSFL": bool(include_nsfl),
        "Art Styles": True,
        "Dictionary": bool(include_dictionary),
    }
    cmap = Concepts.get_concepts_map(category_states)
    exact: set[str] = set()
    for _fn, concepts in cmap.items():
        exact.update(concepts)
    if case_sensitive:
        return exact
    return {c.casefold() for c in exact}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare wildcards .txt lines to repo concept union."
    )
    parser.add_argument(
        "--wildcards-dir",
        type=Path,
        default=Path("concepts") / "temp" / "sd-wildcards" / "wildcards",
        help="Directory containing wildcard .txt files (default: concepts/temp/sd-wildcards/wildcards)",
    )
    parser.add_argument(
        "--include-dictionary",
        action="store_true",
        help="Include dictionary.txt in the repo union (very large).",
    )
    parser.add_argument(
        "--include-nsfw-categories",
        action="store_true",
        help="Include NSFW/NSFL concept files from this repo in the union.",
    )
    parser.add_argument(
        "--include-nsfw-wildcard-files",
        action="store_true",
        help="Do not skip wildcard files whose names contain 'nsfw'.",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Match lines exactly (default: case-insensitive).",
    )
    parser.add_argument(
        "--max-missing-list",
        type=int,
        default=40,
        help="Max missing lines to print per file (default: 40).",
    )
    parser.add_argument(
        "--csv",
        type=Path,
        default=None,
        help="Optional path to write a CSV summary (file, lines, present, missing, pct).",
    )
    args = parser.parse_args()

    wild_dir: Path = args.wildcards_dir
    if not wild_dir.is_dir():
        print(f"Error: wildcards directory not found: {wild_dir.resolve()}", file=sys.stderr)
        return 1

    repo_set = build_repo_concept_set(
        include_dictionary=args.include_dictionary,
        include_nsfw=args.include_nsfw_categories,
        include_nsfl=args.include_nsfw_categories,
        case_sensitive=args.case_sensitive,
    )

    def key(s: str) -> str:
        return s if args.case_sensitive else s.casefold()

    txt_files = sorted(wild_dir.glob("*.txt"))
    if not txt_files:
        print(f"No .txt files under {wild_dir}", file=sys.stderr)
        return 1

    rows: list[tuple[str, int, int, int, float]] = []
    total_lines = 0
    total_present = 0

    print(f"Repo concept union size: {len(repo_set)}")
    print(f"Wildcards dir: {wild_dir.resolve()}")
    print()

    for fp in txt_files:
        if not args.include_nsfw_wildcard_files and is_nsfw_wildcard_file(fp.name):
            print(f"--- skip (nsfw in name): {fp.name}")
            continue

        lines = load_concepts_from_path(fp)
        present = 0
        missing: list[str] = []
        for line in lines:
            k = key(line)
            if k in repo_set:
                present += 1
            else:
                missing.append(line)

        n = len(lines)
        miss_n = n - present
        pct = (100.0 * present / n) if n else 0.0
        rows.append((fp.name, n, present, miss_n, pct))
        total_lines += n
        total_present += present

        print(f"=== {fp.name} ===")
        print(f"  lines: {n}  already in repo (by rule): {present}  missing: {miss_n}  ({pct:.1f}% covered)")
        if missing and args.max_missing_list > 0:
            show = missing[: args.max_missing_list]
            for m in show:
                print(f"    - {m}")
            if len(missing) > len(show):
                print(f"    ... ({len(missing) - len(show)} more missing)")
        print()

    overall_pct = (100.0 * total_present / total_lines) if total_lines else 0.0
    print("=== Overall (non-skipped files) ===")
    print(f"  total lines: {total_lines}")
    print(f"  present in repo: {total_present}")
    print(f"  missing: {total_lines - total_present}")
    print(f"  coverage: {overall_pct:.1f}%")

    if args.csv:
        import csv

        args.csv.parent.mkdir(parents=True, exist_ok=True)
        with open(args.csv, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["file", "lines", "present", "missing", "coverage_pct"])
            for name, n, pres, miss, pct in rows:
                w.writerow([name, n, pres, miss, f"{pct:.2f}"])
        print(f"Wrote {args.csv.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
