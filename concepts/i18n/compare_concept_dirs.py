#!/usr/bin/env python3
"""
Compare two concepts catalog directories by line index (typically concepts/ vs Konzepte/).

Run from concepts/i18n/ or repo root:

  python compare_concept_dirs.py counts
  python compare_concept_dirs.py counts --only-mismatches
  python compare_concept_dirs.py diff --file sfw_characters.txt --start 1085 --limit 15
  python compare_concept_dirs.py drift --file objects_food.txt
  python compare_concept_dirs.py pair --file plants.txt --index 333

`drift` reports count mismatches only when comparing en/de dirs (text always differs).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from catalog_common import (  # noqa: E402
    DEFAULT_LOCALE_DIR,
    DEFAULT_SOURCE_DIR,
    aligned_rows,
    count_lines_by_file,
    first_differing_index,
    format_pair,
    load_catalog_file,
    resolve_concepts_dir,
)


def cmd_counts(args: argparse.Namespace) -> int:
    left = resolve_concepts_dir(args.left)
    right = resolve_concepts_dir(args.right)
    rows = count_lines_by_file(left, right)
    mismatches = [r for r in rows if not r.matches]
    show = mismatches if args.only_mismatches else rows
    if not show:
        print("All shared catalog files have matching line counts.")
        return 0
    print(f"{'file':<40} {'left':>8} {'right':>8}")
    print("-" * 60)
    for row in show:
        flag = "" if row.matches else "  <-- mismatch"
        print(f"{row.filename:<40} {row.left:>8} {row.right:>8}{flag}")
    print()
    print(f"Total files: {len(rows)}; mismatches: {len(mismatches)}")
    return 1 if mismatches else 0


def cmd_diff(args: argparse.Namespace) -> int:
    left = resolve_concepts_dir(args.left)
    right = resolve_concepts_dir(args.right)
    left_lines = load_catalog_file(left, args.file)
    right_lines = load_catalog_file(right, args.file)
    print(f"{args.file}: {len(left_lines)} vs {len(right_lines)} lines")
    if args.left != args.right:
        print(
            "( ! marks differing text; expected for English vs German at each index. "
            "Use counts for alignment; use pair to inspect one row.)"
        )
    print(f"{'':>7}  {'left (' + args.left + ')':<72}  |  right ({args.right})")
    print("-" * 155)
    rows = aligned_rows(left_lines, right_lines, start=args.start, limit=args.limit)
    if args.changed_only:
        rows = [r for r in rows if not r.same]
    for row in rows:
        print(format_pair(row.index, row.left, row.right))
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    left = resolve_concepts_dir(args.left)
    right = resolve_concepts_dir(args.right)
    left_lines = load_catalog_file(left, args.file)
    right_lines = load_catalog_file(right, args.file)
    if len(left_lines) != len(right_lines):
        print(
            f"{args.file}: line count mismatch ({len(left_lines)} vs {len(right_lines)}). "
            "Index pairing is unreliable until counts match."
        )
        return 1
    if args.left != args.right:
        print(
            f"{args.file}: line counts match ({len(left_lines)} lines). "
            "Text differs at every index for en/de catalogs — that is expected. "
            "Use pair or diff to inspect specific indices."
        )
        return 0
    idx = first_differing_index(left_lines, right_lines)
    if idx is None:
        print(f"{args.file}: line counts match and all index pairs have identical text.")
        print("(German dir may still differ semantically while text matches English.)")
        return 0
    print(f"{args.file}: first index with different text: {idx}")
    start = max(0, idx - args.context)
    end = min(len(left_lines), idx + args.context + 1)
    for row in aligned_rows(left_lines, right_lines, start=start, limit=end - start):
        print(format_pair(row.index, row.left, row.right))
    return 0


def cmd_pair(args: argparse.Namespace) -> int:
    left = resolve_concepts_dir(args.left)
    right = resolve_concepts_dir(args.right)
    left_lines = load_catalog_file(left, args.file)
    right_lines = load_catalog_file(right, args.file)
    left_line = left_lines[args.index] if args.index < len(left_lines) else None
    right_line = right_lines[args.index] if args.index < len(right_lines) else None
    print(format_pair(args.index, left_line, right_line, width=100))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Compare two concepts catalog directories by index.")
    parser.add_argument("--left", default="concepts", help="Source/English directory (default: concepts)")
    parser.add_argument("--right", default="Konzepte", help="Locale directory (default: Konzepte)")
    sub = parser.add_subparsers(dest="command", required=True)

    counts = sub.add_parser("counts", help="Line counts per .txt file")
    counts.add_argument("--only-mismatches", action="store_true", help="Show only files where counts differ")
    counts.set_defaults(func=cmd_counts)

    diff = sub.add_parser("diff", help="Side-by-side lines for an index range")
    diff.add_argument("--file", required=True, help="Catalog filename, e.g. sfw_characters.txt")
    diff.add_argument("--start", type=int, default=0, help="Start index (0-based)")
    diff.add_argument("--limit", type=int, default=20, help="Number of rows to show")
    diff.add_argument("--changed-only", action="store_true", help="Only print rows where text differs")
    diff.set_defaults(func=cmd_diff)

    drift = sub.add_parser("drift", help="Report first index where paired lines differ")
    drift.add_argument("--file", required=True, help="Catalog filename")
    drift.add_argument("--context", type=int, default=3, help="Context rows around first drift index")
    drift.set_defaults(func=cmd_drift)

    pair = sub.add_parser("pair", help="Show one index pair")
    pair.add_argument("--file", required=True, help="Catalog filename")
    pair.add_argument("--index", type=int, required=True, help="0-based line index")
    pair.set_defaults(func=cmd_pair)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
