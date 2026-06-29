#!/usr/bin/env python3
"""
Diagnose and optionally repair trailing-newline mismatches in concepts PO msgids.

Note: the root cause of msgid drift (write_pot_string appending a spurious
trailing \\n for long single-line strings) has been fixed in concepts_gettext.py.
After regenerating the POT/PO from a clean export, new drift no longer occurs and
this script is not needed for routine maintenance. It is retained as a one-shot
diagnostic tool for pre-existing PO files that accumulated drift before the fix.

Problem
-------
Some PO msgid values accumulated extra trailing newlines (gettext multiline
continuation lines) while chunk column 2 kept the shape from an earlier split.
That makes byte-exact (msgctxt, msgid) keys differ even though the text matches
after rstrip("\\n").

The source catalog (concepts/*.txt) is clean — this is PO key-shape drift, not
a source typo. merge and import in concepts_po_chunks / concepts_gettext already
fall back to normalized msgid lookup, so translations still apply. This script
helps when you want a report of orphan keys or a PO rewritten with canonical
msgids from source (without editing chunk TSV column 2).

Defaults target locale/de/; pass --po and --chunks-dir for other languages.

Usage (from concepts/i18n/)
---------------------------
  # Report only (default) — lists norm-matchable orphans, no file changes
  python repair_po_merge_keys.py

  # Rewrite PO msgids from source, backup original, rebuild chunk key cache
  python repair_po_merge_keys.py --apply

After --apply, run merge again only if you want msgstr refreshed from chunks:
  python concepts_po_chunks.py merge --po locale/de/LC_MESSAGES/concepts.po \\
    --chunks-dir locale/de/chunks
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from io import StringIO

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from concepts_gettext import (  # noqa: E402
    DEFAULT_EXCLUDE_FILES,
    _parse_po_string,
    get_concept_txt_files,
    load_concepts_file,
    lookup_po_translation,
    normalize_po_msgid,
    po_translation_lookups,
    write_pot_string,
)
from concepts_po_chunks import (  # noqa: E402
    PoEntry,
    parse_po_entries,
    read_chunk_translations,
    rebuild_chunk_keys_cache,
    write_po_entries,
)

DEFAULT_CONCEPTS_DIR = os.path.normpath(os.path.join(SCRIPT_DIR, ".."))
DEFAULT_PO = os.path.join(SCRIPT_DIR, "locale", "de", "LC_MESSAGES", "concepts.po")
DEFAULT_CHUNKS_DIR = os.path.join(SCRIPT_DIR, "locale", "de", "chunks")


def _resolve(path: str, base: str) -> str:
    return path if os.path.isabs(path) else os.path.normpath(os.path.join(base, path))


def canonical_msgid(source_line: str) -> str:
    """msgid bytes after export write/parse round-trip (matches a clean POT/PO)."""
    body = StringIO()
    write_pot_string(body, "msgid", source_line)
    lines = body.getvalue().strip().split("\n")
    idx = [0]
    return _parse_po_string(lines, idx)[0]


def norm_key(msgctxt: str, msgid: str) -> tuple[str, str]:
    return (msgctxt, normalize_po_msgid(msgid))


def load_source_catalog(concepts_dir: str) -> list[tuple[str, str, str]]:
    """(msgctxt, source_line, canonical_msgid) in export order."""
    rows: list[tuple[str, str, str]] = []
    for filename in get_concept_txt_files(concepts_dir, DEFAULT_EXCLUDE_FILES):
        basename = os.path.splitext(filename)[0]
        filepath = os.path.join(concepts_dir, filename)
        for line in load_concepts_file(filepath):
            rows.append((basename, line, canonical_msgid(line)))
    return rows


def build_translation_lookup(
    chunk_translations: dict[tuple[str, str], str],
    existing_po: dict[tuple[str, str], str],
) -> dict[tuple[str, str], str]:
    """
    Resolve msgstr by normalized (msgctxt, msgid.rstrip) key.
    Prefer chunk translations over existing PO msgstr when both exist.
    """
    by_norm: dict[tuple[str, str], str] = {}

    for (msgctxt, msgid), msgstr in existing_po.items():
        if msgstr:
            by_norm[norm_key(msgctxt, msgid)] = msgstr

    for (msgctxt, msgid), msgstr in chunk_translations.items():
        if msgstr:
            by_norm[norm_key(msgctxt, msgid)] = msgstr

    return by_norm


def analyze(
    po_path: str,
    chunks_dir: str,
    concepts_dir: str,
) -> dict:
    header, po_entries = parse_po_entries(po_path)
    chunk_translations = read_chunk_translations(chunks_dir)
    existing_po = {(e.msgctxt, e.msgid): e.msgstr for e in po_entries}
    catalog = load_source_catalog(concepts_dir)
    by_norm = build_translation_lookup(chunk_translations, existing_po)

    exact_merge = sum(1 for e in po_entries if (e.msgctxt, e.msgid) in chunk_translations)
    orphans: list[dict] = []
    for entry in po_entries:
        key = (entry.msgctxt, entry.msgid)
        if key in chunk_translations:
            continue
        nk = norm_key(entry.msgctxt, entry.msgid)
        chunk_match = any(
            norm_key(c, m) == nk and (c, m) in chunk_translations
            for (c, m) in chunk_translations
        )
        if chunk_match:
            orphans.append(
                {
                    "msgctxt": entry.msgctxt,
                    "po_newlines": entry.msgid.count("\n"),
                    "po_tail": repr(entry.msgid[-24:]),
                    "norm_tail": repr(nk[1][-24:]),
                }
            )

    repaired_entries: list[PoEntry] = []
    missing_after: list[tuple[str, str]] = []
    for msgctxt, _source_line, canon_msgid in catalog:
        nk = norm_key(msgctxt, canon_msgid)
        msgstr = by_norm.get(nk, "")
        if not msgstr:
            missing_after.append((msgctxt, canon_msgid))
        repaired_entries.append(
            PoEntry(
                comment=f"# {msgctxt}.txt",
                msgctxt=msgctxt,
                msgid=canon_msgid,
                msgstr=msgstr,
            )
        )

    orphan_ctx = Counter(row["msgctxt"] for row in orphans)
    post_exact_merge = sum(
        1 for e in repaired_entries if (e.msgctxt, e.msgid) in chunk_translations
    )

    return {
        "header": header,
        "po_path": po_path,
        "po_entry_count": len(po_entries),
        "catalog_entry_count": len(catalog),
        "chunk_unique_keys": len(chunk_translations),
        "exact_merge_before": exact_merge,
        "orphan_count": len(orphans),
        "orphans_by_msgctxt": dict(orphan_ctx),
        "orphan_samples": orphans[:8],
        "repaired_entry_count": len(repaired_entries),
        "repaired_with_msgstr": sum(1 for e in repaired_entries if e.msgstr),
        "missing_after_repair": missing_after,
        "post_exact_merge_simulated": post_exact_merge,
        "repaired_entries": repaired_entries,
    }


def print_report(report: dict) -> None:
    print("=== concepts PO merge-key repair (dry-run) ===")
    print(f"PO file:           {report['po_path']}")
    print(f"PO entries:        {report['po_entry_count']}")
    print(f"Source catalog:    {report['catalog_entry_count']} entries")
    print(f"Chunk unique keys: {report['chunk_unique_keys']}")
    print()
    print("--- Before repair ---")
    print(f"Exact chunk->PO merge matches: {report['exact_merge_before']}")
    print(f"Orphans (norm-matchable):      {report['orphan_count']}")
    if report["orphans_by_msgctxt"]:
        print("Orphans by msgctxt:")
        for ctx, count in sorted(report["orphans_by_msgctxt"].items(), key=lambda x: (-x[1], x[0])):
            print(f"  {ctx}: {count}")
    if report["orphan_samples"]:
        print("Sample orphans (PO tail vs normalized key tail):")
        for row in report["orphan_samples"]:
            print(
                f"  [{row['msgctxt']}] po_nl={row['po_newlines']} "
                f"po={row['po_tail']} norm={row['norm_tail']}"
            )
    print()
    print("--- After repair (simulated) ---")
    print(f"Rebuilt PO entries:            {report['repaired_entry_count']}")
    print(f"Entries with msgstr:           {report['repaired_with_msgstr']}")
    print(f"Simulated exact merge matches: {report['post_exact_merge_simulated']}")
    missing = report["missing_after_repair"]
    print(f"Still missing translation:       {len(missing)}")
    if missing:
        print("First missing entries:")
        for msgctxt, msgid in missing[:10]:
            tail = repr(msgid[-48:])
            print(f"  [{msgctxt}] {tail}")
    print()
    if report["orphan_count"] and not missing:
        print(
            "OK: All current orphans are norm-matchable; repair would restore "
            "full merge coverage from chunks."
        )
    elif not report["orphan_count"]:
        print("OK: No orphans detected; PO keys already match chunks.")
    else:
        print("WARNING: Some entries would still lack translations after repair.")


def apply_repair(
    po_path: str,
    chunks_dir: str,
    concepts_dir: str,
    *,
    backup: bool = True,
) -> None:
    report = analyze(po_path, chunks_dir, concepts_dir)
    if report["missing_after_repair"]:
        print(
            f"Refusing to apply: {len(report['missing_after_repair'])} entries would "
            "still lack translations.",
            file=sys.stderr,
        )
        sys.exit(1)

    if backup:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup_path = f"{po_path}.bak.{stamp}"
        shutil.copy2(po_path, backup_path)
        print(f"Backup written: {backup_path}")

    write_po_entries(po_path, report["header"], report["repaired_entries"])
    print(f"Repaired PO written: {po_path}")

    rc = rebuild_chunk_keys_cache(chunks_dir, from_chunks=False)
    if rc != 0:
        sys.exit(rc)
    print("Rebuilt chunk key cache from repaired PO.")

    _, entries = parse_po_entries(po_path)
    translations = read_chunk_translations(chunks_dir)
    exact, by_norm = po_translation_lookups(translations)
    merged = sum(
        1
        for e in entries
        if lookup_po_translation(e.msgctxt, e.msgid, exact, by_norm) is not None
    )
    with_msgstr = sum(1 for e in entries if e.msgstr.strip())
    print(f"Post-repair merge matches: {merged}/{len(entries)}")
    print(f"Post-repair entries with msgstr: {with_msgstr}/{len(entries)}")

    if with_msgstr != len(entries):
        print(
            "WARNING: not all PO entries have msgstr after repair.",
            file=sys.stderr,
        )
        sys.exit(1)

    print("Repair complete. Run merge to refresh msgstr from chunks if desired.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Repair PO msgid keys for full chunk merge coverage.",
    )
    parser.add_argument(
        "--po",
        default=DEFAULT_PO,
        help=f"Target PO file (default: {DEFAULT_PO})",
    )
    parser.add_argument(
        "--chunks-dir",
        default=DEFAULT_CHUNKS_DIR,
        help=f"Chunk TSV directory (default: {DEFAULT_CHUNKS_DIR})",
    )
    parser.add_argument(
        "--concepts-dir",
        default=DEFAULT_CONCEPTS_DIR,
        help=f"Source concepts directory (default: {DEFAULT_CONCEPTS_DIR})",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Backup PO, write repaired PO, rebuild cache, verify merge coverage "
        "(default is dry-run report only)",
    )
    args = parser.parse_args()

    po_path = _resolve(args.po, SCRIPT_DIR)
    chunks_dir = _resolve(args.chunks_dir, SCRIPT_DIR)
    concepts_dir = _resolve(args.concepts_dir, SCRIPT_DIR)

    if not os.path.isfile(po_path):
        print(f"PO file not found: {po_path}", file=sys.stderr)
        return 1
    if not os.path.isdir(chunks_dir):
        print(f"Chunks directory not found: {chunks_dir}", file=sys.stderr)
        return 1
    if not os.path.isdir(concepts_dir):
        print(f"Concepts directory not found: {concepts_dir}", file=sys.stderr)
        return 1

    if args.apply:
        apply_repair(po_path, chunks_dir, concepts_dir)
        return 0

    report = analyze(po_path, chunks_dir, concepts_dir)
    print_report(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
