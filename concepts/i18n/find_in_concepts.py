#!/usr/bin/env python3
"""
Search for concept strings in a catalog directory and report every index hit.

Run from concepts/i18n/ or repo root:

  python find_in_concepts.py Thesis --file sfw_characters.txt
  python find_in_concepts.py sleeping --all-files --ignore-case
  python find_in_concepts.py --substring leep --file sfw_actions.txt
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from catalog_common import (  # noqa: E402
    DEFAULT_SOURCE_DIR,
    find_line_indices,
    list_catalog_files,
    load_catalog_file,
    resolve_concepts_dir,
)


def search_file(
    concepts_dir: Path,
    filename: str,
    needles: list[str],
    *,
    ignore_case: bool,
    substring: bool,
) -> list[tuple[str, str, list[int]]]:
    lines = load_catalog_file(concepts_dir, filename)
    hits: list[tuple[str, str, list[int]]] = []
    for needle in needles:
        indices = find_line_indices(
            lines,
            needle,
            ignore_case=ignore_case,
            substring=substring,
        )
        if indices:
            hits.append((filename, needle, indices))
    return hits


def main() -> int:
    parser = argparse.ArgumentParser(description="Find concept strings and report line indices.")
    parser.add_argument("terms", nargs="+", help="One or more strings to find")
    parser.add_argument("--dir", default="concepts", help="Catalog directory (default: concepts)")
    parser.add_argument("--file", help="Limit to one .txt file (basename)")
    parser.add_argument("--all-files", action="store_true", help="Search every catalog .txt file")
    parser.add_argument("--ignore-case", action="store_true", help="Case-insensitive exact match")
    parser.add_argument("--substring", action="store_true", help="Substring match instead of exact line")
    parser.add_argument(
        "--include-dictionary",
        action="store_true",
        help="Include dictionary.txt when searching all files",
    )
    args = parser.parse_args()

    concepts_dir = resolve_concepts_dir(args.dir)
    if not concepts_dir.is_dir():
        print(f"Directory not found: {concepts_dir}", file=sys.stderr)
        return 1

    if args.file:
        files = [args.file]
    else:
        files = list_catalog_files(
            concepts_dir,
            include_all_txt=args.include_dictionary,
        )

    total = 0
    for filename in files:
        for fname, needle, indices in search_file(
            concepts_dir,
            filename,
            args.terms,
            ignore_case=args.ignore_case,
            substring=args.substring,
        ):
            total += len(indices)
            idx_text = ", ".join(str(i) for i in indices)
            print(f"{fname}\t{needle}\t[{idx_text}]")
            if args.file and len(indices) <= 5:
                lines = load_catalog_file(concepts_dir, fname)
                for i in indices:
                    print(f"  @{i}: {lines[i]}")

    if total == 0:
        print("No matches.")
        return 1
    print(f"\n{total} hit(s) across {len(files)} file(s) searched.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
