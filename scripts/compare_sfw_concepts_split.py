#!/usr/bin/env python3
"""
Compare the union of the three new split concept files against sfw_concepts.txt
to identify which original concepts are covered and which remain as excess.

The three target split files are:
  concepts/plants.txt
  concepts/object.txt
  concepts/media_features.txt

Run from the repository root:

    python scripts/compare_sfw_concepts_split.py
    python scripts/compare_sfw_concepts_split.py --csv reports/sfw_split_coverage.csv
    python scripts/compare_sfw_concepts_split.py --case-sensitive
    python scripts/compare_sfw_concepts_split.py --show-covered

Exits with code 0.  Use --csv to dump full results to a CSV for easier review.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

CONCEPTS_DIR = Path(PROJECT_ROOT) / "concepts"

SPLIT_FILES = [
    CONCEPTS_DIR / "plants.txt",
    CONCEPTS_DIR / "object.txt",
    CONCEPTS_DIR / "media_features.txt",
]

SOURCE_FILE = CONCEPTS_DIR / "sfw_concepts.txt"


def _parse_line(line: str) -> str:
    """Mirror Concepts.load line handling: strip everything after '#', then strip whitespace."""
    val = ""
    for c in line:
        if c == "#":
            break
        val += c
    return val.strip()


def load_file(filepath: Path) -> list[str]:
    """Load a concepts file and return non-empty, comment-stripped lines."""
    out: list[str] = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                v = _parse_line(line)
                if v:
                    out.append(v)
    except OSError as e:
        print(f"Warning: could not read {filepath}: {e}", file=sys.stderr)
    return out


def build_lookup(concepts: list[str], case_sensitive: bool) -> set[str]:
    if case_sensitive:
        return set(concepts)
    return {c.lower() for c in concepts}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare sfw_concepts.txt against the union of plants/object/media_features split files."
    )
    parser.add_argument(
        "--csv",
        metavar="PATH",
        help="Write full results to a CSV file at this path.",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        default=False,
        help="Use case-sensitive matching (default: case-insensitive).",
    )
    parser.add_argument(
        "--show-covered",
        action="store_true",
        default=False,
        help="Also print the list of covered concepts (by default only excess is printed).",
    )
    parser.add_argument(
        "--source",
        metavar="PATH",
        default=str(SOURCE_FILE),
        help=f"Source file to compare against (default: {SOURCE_FILE}).",
    )
    parser.add_argument(
        "--split-files",
        metavar="PATH",
        nargs="+",
        default=[str(p) for p in SPLIT_FILES],
        help="Split files whose union is compared against the source (default: plants/object/media_features).",
    )
    args = parser.parse_args()

    case_sensitive: bool = args.case_sensitive

    # Load source
    source_path = Path(args.source)
    source_concepts = load_file(source_path)
    if not source_concepts:
        print(f"ERROR: No concepts loaded from source file: {source_path}", file=sys.stderr)
        sys.exit(1)

    # Load each split file and build union lookup
    split_paths = [Path(p) for p in args.split_files]
    split_union_lookup: set[str] = set()
    split_file_counts: dict[str, int] = {}
    for sp in split_paths:
        items = load_file(sp)
        split_file_counts[sp.name] = len(items)
        split_union_lookup |= build_lookup(items, case_sensitive)

    # Compare
    covered: list[str] = []
    excess: list[str] = []
    for concept in source_concepts:
        key = concept if case_sensitive else concept.lower()
        if key in split_union_lookup:
            covered.append(concept)
        else:
            excess.append(concept)

    total = len(source_concepts)
    n_covered = len(covered)
    n_excess = len(excess)
    pct = (n_covered / total * 100) if total else 0.0

    # ── Summary ──────────────────────────────────────────────────────────────
    print("=" * 70)
    print("sfw_concepts.txt  →  Split-file coverage report")
    print("=" * 70)
    print(f"Source file   : {source_path}")
    print(f"Source total  : {total} concepts")
    print()
    print("Split files (concept counts):")
    for sp in split_paths:
        n = split_file_counts.get(sp.name, 0)
        status = "OK" if sp.exists() else "MISSING"
        print(f"  [{status}]  {sp.name}: {n}")
    union_total = len(split_union_lookup)
    print(f"  Union (unique): {union_total}")
    print()
    print(f"Covered by union : {n_covered:4d} / {total}  ({pct:.1f}%)")
    print(f"Excess (not yet  : {n_excess:4d} concepts remain uncategorised in split files")
    print("=" * 70)

    # ── Excess list ──────────────────────────────────────────────────────────
    if excess:
        print(f"\n{'─'*70}")
        print(f"EXCESS ({n_excess} concepts in sfw_concepts.txt not in any split file):")
        print(f"{'─'*70}")
        for c in excess:
            print(f"  {c}")
    else:
        print("\nAll concepts in sfw_concepts.txt are covered by the split files.")

    # ── Covered list (optional) ───────────────────────────────────────────────
    if args.show_covered and covered:
        print(f"\n{'─'*70}")
        print(f"COVERED ({n_covered} concepts found in at least one split file):")
        print(f"{'─'*70}")
        for c in covered:
            print(f"  {c}")

    # ── CSV export ────────────────────────────────────────────────────────────
    if args.csv:
        csv_path = Path(args.csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)

        # For CSV, also note WHICH split file(s) each concept appears in
        # Build per-file lookups
        per_file_lookups: dict[str, set[str]] = {}
        for sp in split_paths:
            items = load_file(sp)
            per_file_lookups[sp.name] = build_lookup(items, case_sensitive)

        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            fieldnames = ["concept", "status"] + [sp.name for sp in split_paths]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for concept in source_concepts:
                key = concept if case_sensitive else concept.lower()
                in_union = key in split_union_lookup
                row: dict = {
                    "concept": concept,
                    "status": "covered" if in_union else "excess",
                }
                for sp in split_paths:
                    row[sp.name] = "yes" if key in per_file_lookups.get(sp.name, set()) else ""
                writer.writerow(row)
        print(f"\nCSV written to: {csv_path}")


if __name__ == "__main__":
    main()
