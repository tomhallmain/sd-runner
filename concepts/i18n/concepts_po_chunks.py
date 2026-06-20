"""
Split a concepts PO file into LLM-friendly translation chunks and merge them back.

Each chunk line is tab-separated: context, English source, translation.
Fill column 3 with the target-language text; leave columns 1-2 unchanged.

Workflow (run from concepts/i18n/):
  1. split:
       python concepts_po_chunks.py split --po locale/de/LC_MESSAGES/concepts.po
     -> locale/de/chunks/chunk_001.tsv, chunk_002.tsv, ...
  2. Translate one chunk at a time (paste into an LLM, fill column 3).
  3. status:
       python concepts_po_chunks.py status --chunks-dir locale/de/chunks
  4. validate:
       python concepts_po_chunks.py validate --chunks-dir locale/de/chunks --chunk chunk_001.tsv
  5. complete (validate + update manifest cursor):
       python concepts_po_chunks.py complete --chunks-dir locale/de/chunks --chunk chunk_001.tsv
  6. merge:
       python concepts_po_chunks.py merge --po locale/de/LC_MESSAGES/concepts.po \\
         --chunks-dir locale/de/chunks
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass

CHUNK_KEYS_CACHE_NAME = "chunk_keys_cache.json"

SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from concepts_gettext import _parse_po_string, write_pot_string  # noqa: E402

FIELD_SEP = "\t"
CHUNK_NAME_RE = re.compile(r"^chunk_(\d+)\.(?:tsv|txt)$")
ENTRY_START_RE = re.compile(r"\n(?=# .+\.txt\nmsgctxt )")


@dataclass
class PoEntry:
    comment: str
    msgctxt: str
    msgid: str
    msgstr: str


def _resolve_path(path: str, base: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base, path))


def parse_po_entries(po_path: str) -> tuple[str, list[PoEntry]]:
    """Return PO header text and ordered concept entries."""
    with open(po_path, encoding="utf-8") as f:
        content = f.read()
    match = ENTRY_START_RE.search(content)
    if match:
        header = content[: match.start()].strip() + "\n\n"
        body_lines = content[match.start() + 1 :].split("\n")
    else:
        header = content.strip() + "\n"
        body_lines = []

    entries: list[PoEntry] = []
    idx = [0]
    while idx[0] < len(body_lines):
        stripped = body_lines[idx[0]].strip()
        if stripped.startswith("msgctxt "):
            comment = body_lines[idx[0] - 1] if idx[0] > 0 and body_lines[idx[0] - 1].startswith("#") else ""
            idx[0] = idx[0]
            msgctxt, _ = _parse_po_string(body_lines, idx)
            if idx[0] < len(body_lines) and body_lines[idx[0]].strip().startswith("msgid "):
                msgid, _ = _parse_po_string(body_lines, idx)
                msgstr = ""
                if idx[0] < len(body_lines) and body_lines[idx[0]].strip().startswith("msgstr "):
                    msgstr, _ = _parse_po_string(body_lines, idx)
                if msgctxt:
                    entries.append(PoEntry(comment, msgctxt, msgid, msgstr))
            continue
        idx[0] += 1
    return header, entries


def write_po_entries(po_path: str, header: str, entries: list[PoEntry]) -> None:
    os.makedirs(os.path.dirname(po_path) or ".", exist_ok=True)
    with open(po_path, "w", encoding="utf-8") as f:
        f.write(header.rstrip() + "\n\n")
        for entry in entries:
            if entry.comment:
                f.write(f"{entry.comment}\n")
            write_pot_string(f, "msgctxt", entry.msgctxt)
            write_pot_string(f, "msgid", entry.msgid)
            write_pot_string(f, "msgstr", entry.msgstr)
            f.write("\n")


def _escape_field(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\t", "\\t").replace("\n", "\\n").replace("\r", "\\r")


def _unescape_field(value: str) -> str:
    decoded: list[str] = []
    i = 0
    while i < len(value):
        if value[i] == "\\" and i + 1 < len(value):
            n = value[i + 1]
            if n == "t":
                decoded.append("\t")
            elif n == "n":
                decoded.append("\n")
            elif n == "r":
                decoded.append("\r")
            elif n == "\\":
                decoded.append("\\")
            else:
                decoded.append(n)
            i += 2
        else:
            decoded.append(value[i])
            i += 1
    return "".join(decoded)


def format_chunk_line(msgctxt: str, msgid: str, msgstr: str = "") -> str:
    return FIELD_SEP.join((_escape_field(msgctxt), _escape_field(msgid), _escape_field(msgstr)))


def parse_chunk_line(line: str) -> tuple[str, str, str] | None:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    parts = stripped.split(FIELD_SEP)
    if len(parts) < 2:
        return None
    msgctxt = _unescape_field(parts[0])
    msgid = _unescape_field(parts[1])
    msgstr = _unescape_field(parts[2]) if len(parts) > 2 else ""
    return msgctxt, msgid, msgstr


def _chunk_header(
    chunk_no: int,
    chunk_total: int,
    locale: str,
    target_language: str,
    entry_count: int,
) -> str:
    return (
        f"# concepts translation chunk {chunk_no:03d}/{chunk_total:03d}\n"
        f"# locale: {locale}\n"
        f"# target language: {target_language}\n"
        f"# entries: {entry_count}\n"
        "# format: context<TAB>source<TAB>translation\n"
        "# Fill column 3 only. Keep columns 1-2 unchanged. One entry per line.\n"
        "#\n"
    )


def _default_chunks_dir(po_path: str) -> str:
    po_dir = os.path.dirname(po_path)
    locale_dir = os.path.dirname(po_dir)
    return os.path.join(locale_dir, "chunks")


def _is_untranslated(entry: PoEntry) -> bool:
    return not entry.msgstr or entry.msgstr == entry.msgid


def split_po(
    po_path: str,
    chunks_dir: str,
    *,
    entries_per_chunk: int = 75,
    only_untranslated: bool = True,
    target_language: str = "",
) -> None:
    header, entries = parse_po_entries(po_path)
    work_entries = [entry for entry in entries if not only_untranslated or _is_untranslated(entry)]
    if not work_entries:
        print("No entries to split.")
        return

    os.makedirs(chunks_dir, exist_ok=True)
    locale = _locale_from_header(header) or "unknown"
    if not target_language:
        target_language = locale

    chunks: list[list[PoEntry]] = []
    for i in range(0, len(work_entries), entries_per_chunk):
        chunks.append(work_entries[i : i + entries_per_chunk])

    old_manifest = _load_manifest(chunks_dir)
    preserve_completed: set[int] = set()
    if old_manifest.get("completed_chunks"):
        same_split_params = (
            old_manifest.get("entries_per_chunk") == entries_per_chunk
            and old_manifest.get("only_untranslated") == only_untranslated
            and os.path.normpath(os.path.abspath(old_manifest.get("po_path", "")))
            == os.path.normpath(os.path.abspath(po_path))
        )
        if same_split_params:
            preserve_completed = {
                chunk_no
                for chunk_no in old_manifest["completed_chunks"]
                if 1 <= chunk_no <= len(chunks)
            }
            dropped = len(old_manifest["completed_chunks"]) - len(preserve_completed)
            if dropped:
                print(
                    f"Warning: {dropped} completed chunk(s) dropped because chunk count shrank.",
                    file=sys.stderr,
                )
        else:
            print(
                "Warning: split settings changed; completed chunks will not be preserved.",
                file=sys.stderr,
            )

    manifest = {
        "po_path": po_path,
        "locale": locale,
        "target_language": target_language,
        "entries_per_chunk": entries_per_chunk,
        "only_untranslated": only_untranslated,
        "chunk_count": len(chunks),
        "entry_count": len(work_entries),
        "format": "context\\tsource\\ttranslation",
        "completed_chunks": sorted(preserve_completed),
    }
    _apply_manifest_cursor(manifest)
    _save_manifest(chunks_dir, manifest)

    _save_chunk_keys_cache(chunks_dir, _build_chunk_keys_cache_from_tsv(chunks_dir, manifest))

    written = 0
    preserved = 0
    for chunk_no, chunk_entries in enumerate(chunks, start=1):
        if chunk_no in preserve_completed:
            preserved += 1
            continue
        chunk_path = os.path.join(chunks_dir, f"chunk_{chunk_no:03d}.tsv")
        with open(chunk_path, "w", encoding="utf-8") as f:
            f.write(
                _chunk_header(
                    chunk_no,
                    len(chunks),
                    locale,
                    target_language,
                    len(chunk_entries),
                )
            )
            for entry in chunk_entries:
                f.write(format_chunk_line(entry.msgctxt, entry.msgid) + "\n")
        written += 1

    print(
        f"Split {len(work_entries)} entries into {len(chunks)} chunks at {chunks_dir} "
        f"({written} written, {preserved} completed preserved)"
    )


def _locale_from_header(header: str) -> str | None:
    match = re.search(r'"Language:\s*([^\n\\]+)\\n"', header)
    if match:
        return match.group(1).strip()
    return None


def _manifest_path(chunks_dir: str) -> str:
    return os.path.join(chunks_dir, "manifest.json")


def _load_manifest(chunks_dir: str) -> dict:
    manifest_path = _manifest_path(chunks_dir)
    if not os.path.isfile(manifest_path):
        return {}
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _save_manifest(chunks_dir: str, manifest: dict) -> None:
    with open(_manifest_path(chunks_dir), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n")


def _next_uncompleted_chunk(manifest: dict) -> int | None:
    completed = set(manifest.get("completed_chunks", []))
    chunk_count = manifest.get("chunk_count", 0)
    for chunk_no in range(1, chunk_count + 1):
        if chunk_no not in completed:
            return chunk_no
    return None


def _apply_manifest_cursor(manifest: dict) -> None:
    completed = sorted(set(manifest.get("completed_chunks", [])))
    manifest["completed_chunks"] = completed
    manifest["last_completed_chunk"] = max(completed) if completed else None
    next_chunk = _next_uncompleted_chunk(manifest)
    manifest["next_chunk"] = next_chunk
    manifest["next_chunk_file"] = f"chunk_{next_chunk:03d}.tsv" if next_chunk else None


def mark_chunk_complete(chunks_dir: str, chunk_no: int) -> None:
    manifest = _load_manifest(chunks_dir)
    if not manifest:
        raise FileNotFoundError(f"manifest.json not found in {chunks_dir}")

    completed = sorted(set(manifest.get("completed_chunks", [])) | {chunk_no})
    manifest["completed_chunks"] = completed
    _apply_manifest_cursor(manifest)
    _save_manifest(chunks_dir, manifest)


def _iter_chunk_files(chunks_dir: str) -> list[tuple[int, str]]:
    files: list[tuple[int, str]] = []
    for name in os.listdir(chunks_dir):
        match = CHUNK_NAME_RE.match(name)
        if match:
            files.append((int(match.group(1)), os.path.join(chunks_dir, name)))
    return sorted(files, key=lambda item: item[0])


def parse_chunk_file(chunk_path: str) -> tuple[int | None, list[tuple[str, str, str]]]:
    """Return (expected entry count from header, parsed data rows)."""
    expected_count: int | None = None
    entries: list[tuple[str, str, str]] = []
    with open(chunk_path, encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("# entries:"):
                try:
                    expected_count = int(stripped.split(":", 1)[1].strip())
                except ValueError:
                    pass
                continue
            parsed = parse_chunk_line(line)
            if parsed is not None:
                entries.append(parsed)
    return expected_count, entries


def _chunk_keys_cache_path(chunks_dir: str) -> str:
    return os.path.join(chunks_dir, CHUNK_KEYS_CACHE_NAME)


def _cache_fingerprint(manifest: dict, po_path: str) -> dict:
    try:
        stat = os.stat(po_path)
        po_mtime = stat.st_mtime
        po_size = stat.st_size
    except OSError:
        po_mtime = None
        po_size = None
    return {
        "po_path": os.path.normpath(os.path.abspath(po_path)),
        "po_mtime": po_mtime,
        "po_size": po_size,
        "entries_per_chunk": manifest.get("entries_per_chunk", 75),
        "only_untranslated": manifest.get("only_untranslated", True),
    }


def _cache_is_current(cache: dict, manifest: dict, po_path: str) -> bool:
    source = cache.get("source", {})
    if source.get("derived_from") == "chunk_files":
        return source.get("chunk_count") == manifest.get("chunk_count")
    return cache.get("source") == _cache_fingerprint(manifest, po_path)


def _build_chunk_keys_cache_from_tsv(chunks_dir: str, manifest: dict) -> dict:
    """Build expected keys from chunk TSV files (matches what's on disk)."""
    chunks: list[list[list[str]]] = []
    for _, chunk_path in _iter_chunk_files(chunks_dir):
        _, entries = parse_chunk_file(chunk_path)
        chunks.append([[msgctxt, msgid] for msgctxt, msgid, _ in entries])
    return {
        "source": {
            "derived_from": "chunk_files",
            "chunk_count": len(chunks),
            "entry_count": sum(len(chunk) for chunk in chunks),
            "entries_per_chunk": manifest.get("entries_per_chunk", 75),
        },
        "chunks": chunks,
    }


def _build_chunk_keys_cache(manifest: dict, po_path: str) -> dict:
    entries_per_chunk = manifest.get("entries_per_chunk", 75)
    only_untranslated = manifest.get("only_untranslated", True)
    _, entries = parse_po_entries(po_path)
    work_entries = [
        entry for entry in entries if not only_untranslated or _is_untranslated(entry)
    ]
    chunks: list[list[list[str]]] = []
    for i in range(0, len(work_entries), entries_per_chunk):
        chunk_entries = work_entries[i : i + entries_per_chunk]
        chunks.append([[entry.msgctxt, entry.msgid] for entry in chunk_entries])
    return {
        "source": _cache_fingerprint(manifest, po_path),
        "chunks": chunks,
    }


def _save_chunk_keys_cache(chunks_dir: str, cache: dict) -> None:
    with open(_chunk_keys_cache_path(chunks_dir), "w", encoding="utf-8") as f:
        json.dump(cache, f, separators=(",", ":"))
        f.write("\n")


def _load_chunk_keys_cache(chunks_dir: str) -> dict | None:
    cache_path = _chunk_keys_cache_path(chunks_dir)
    if not os.path.isfile(cache_path):
        return None
    with open(cache_path, encoding="utf-8") as f:
        return json.load(f)


def _get_chunk_keys_cache(chunks_dir: str, manifest: dict) -> dict:
    po_path = manifest.get("po_path")
    if not po_path or not os.path.isfile(po_path):
        raise FileNotFoundError(f"PO file from manifest not found: {po_path}")

    cache = _load_chunk_keys_cache(chunks_dir)
    if cache and _cache_is_current(cache, manifest, po_path):
        return cache

    cache = _build_chunk_keys_cache(manifest, po_path)
    _save_chunk_keys_cache(chunks_dir, cache)
    return cache


def _expected_keys_for_chunk(chunks_dir: str, chunk_no: int) -> list[tuple[str, str]]:
    manifest = _load_manifest(chunks_dir)
    cache = _get_chunk_keys_cache(chunks_dir, manifest)
    chunks = cache.get("chunks", [])
    if chunk_no < 1 or chunk_no > len(chunks):
        return []
    return [(row[0], row[1]) for row in chunks[chunk_no - 1]]


def validate_chunk_file(
    chunk_path: str,
    expected_keys: list[tuple[str, str]] | None = None,
) -> list[str]:
    """Validate one chunk file. Returns a list of error messages (empty if valid)."""
    errors: list[str] = []
    chunk_name = os.path.basename(chunk_path)
    expected_count, entries = parse_chunk_file(chunk_path)

    if expected_count is not None and len(entries) != expected_count:
        errors.append(f"{chunk_name}: expected {expected_count} entries, found {len(entries)}")

    for line_no, (msgctxt, msgid, msgstr) in enumerate(entries, start=1):
        if not msgctxt:
            errors.append(f"{chunk_name}: line {line_no}: empty context")
        if not msgid:
            errors.append(f"{chunk_name}: line {line_no}: empty source")
        if not msgstr.strip():
            errors.append(f"{chunk_name}: line {line_no}: missing translation for {msgctxt!r} / {msgid!r}")

    if expected_keys is not None:
        actual_keys = [(msgctxt, msgid) for msgctxt, msgid, _ in entries]
        if len(actual_keys) != len(expected_keys):
            errors.append(
                f"{chunk_name}: expected {len(expected_keys)} keys from split, found {len(actual_keys)}"
            )
        else:
            for i, (expected, actual) in enumerate(zip(expected_keys, actual_keys, strict=False), start=1):
                if expected != actual:
                    errors.append(
                        f"{chunk_name}: key mismatch at row {i}: "
                        f"expected {expected[0]!r} / {expected[1]!r}, "
                        f"got {actual[0]!r} / {actual[1]!r}"
                    )

    return errors


def validate_chunks(
    chunks_dir: str,
    *,
    chunk_name: str | None = None,
    rebuild_cache: bool = False,
) -> int:
    if not os.path.isdir(chunks_dir):
        print(f"Chunks directory not found: {chunks_dir}", file=sys.stderr)
        return 1

    chunk_files = _iter_chunk_files(chunks_dir)
    if not chunk_files:
        print(f"No chunk files found in {chunks_dir}", file=sys.stderr)
        return 1

    if chunk_name:
        match = CHUNK_NAME_RE.match(chunk_name)
        if not match:
            print(f"Not a chunk file name: {chunk_name}", file=sys.stderr)
            return 1
        chunk_no = int(match.group(1))
        chunk_path = os.path.join(chunks_dir, chunk_name)
        if not os.path.isfile(chunk_path):
            print(f"Chunk file not found: {chunk_path}", file=sys.stderr)
            return 1
        chunk_files = [(chunk_no, chunk_path)]

    manifest = _load_manifest(chunks_dir)
    if not manifest:
        print("Warning: manifest.json not found; checking counts and translations only.", file=sys.stderr)
    elif rebuild_cache:
        po_path = manifest.get("po_path")
        if not po_path or not os.path.isfile(po_path):
            print(f"PO file from manifest not found: {po_path}", file=sys.stderr)
            return 1
        _save_chunk_keys_cache(chunks_dir, _build_chunk_keys_cache(manifest, po_path))
    else:
        try:
            _get_chunk_keys_cache(chunks_dir, manifest)
        except OSError as e:
            print(f"Warning: could not load chunk key cache: {e}", file=sys.stderr)

    all_errors: list[str] = []
    validated = 0
    for chunk_no, chunk_path in chunk_files:
        expected_keys: list[tuple[str, str]] | None = None
        if manifest:
            try:
                expected_keys = _expected_keys_for_chunk(chunks_dir, chunk_no)
            except OSError as e:
                all_errors.append(f"{os.path.basename(chunk_path)}: {e}")
                continue
        all_errors.extend(validate_chunk_file(chunk_path, expected_keys))
        validated += 1

    if all_errors:
        print(f"Validation failed for {chunks_dir} ({validated} chunk(s) checked):")
        for error in all_errors:
            print(f"  - {error}")
        return 1

    print(f"Validation passed ({validated} chunk(s) checked).")
    return 0


def rebuild_chunk_keys_cache(chunks_dir: str, *, from_chunks: bool = True) -> int:
    manifest = _load_manifest(chunks_dir)
    if not manifest:
        print(f"manifest.json not found in {chunks_dir}", file=sys.stderr)
        return 1
    if from_chunks:
        cache = _build_chunk_keys_cache_from_tsv(chunks_dir, manifest)
        _save_chunk_keys_cache(chunks_dir, cache)
        print(
            f"Rebuilt cache from chunk files "
            f"({cache['source']['chunk_count']} chunks, {cache['source']['entry_count']} entries)."
        )
    else:
        po_path = manifest.get("po_path")
        if not po_path or not os.path.isfile(po_path):
            print(f"PO file from manifest not found: {po_path}", file=sys.stderr)
            return 1
        cache = _build_chunk_keys_cache(manifest, po_path)
        _save_chunk_keys_cache(chunks_dir, cache)
        print(
            f"Rebuilt cache from PO "
            f"({len(cache['chunks'])} chunks, {sum(len(c) for c in cache['chunks'])} entries)."
        )
    return 0


def complete_chunk(chunks_dir: str, chunk_name: str) -> int:
    if validate_chunks(chunks_dir, chunk_name=chunk_name) != 0:
        return 1
    match = CHUNK_NAME_RE.match(chunk_name)
    if not match:
        print(f"Not a chunk file name: {chunk_name}", file=sys.stderr)
        return 1
    chunk_no = int(match.group(1))
    try:
        mark_chunk_complete(chunks_dir, chunk_no)
    except OSError as e:
        print(str(e), file=sys.stderr)
        return 1
    manifest = _load_manifest(chunks_dir)
    completed = len(manifest.get("completed_chunks", []))
    chunk_count = manifest.get("chunk_count", "?")
    next_file = manifest.get("next_chunk_file")
    print(f"Marked {chunk_name} complete ({completed}/{chunk_count} chunks done).")
    if next_file:
        print(f"Next: {next_file}")
    else:
        print("All chunks complete.")
    return 0


def read_chunk_translations(chunks_dir: str) -> dict[tuple[str, str], str]:
    translations: dict[tuple[str, str], str] = {}
    for _, chunk_path in _iter_chunk_files(chunks_dir):
        with open(chunk_path, encoding="utf-8") as f:
            for line in f:
                parsed = parse_chunk_line(line)
                if parsed is None:
                    continue
                msgctxt, msgid, msgstr = parsed
                if msgstr:
                    translations[(msgctxt, msgid)] = msgstr
    return translations


def merge_chunks(po_path: str, chunks_dir: str, *, output: str | None = None) -> int:
    header, entries = parse_po_entries(po_path)
    translations = read_chunk_translations(chunks_dir)
    if not translations:
        print("No translations found in chunk files.", file=sys.stderr)
        return 1

    updated = 0
    for entry in entries:
        key = (entry.msgctxt, entry.msgid)
        if key in translations:
            entry.msgstr = translations[key]
            updated += 1

    out_path = output or po_path
    write_po_entries(out_path, header, entries)
    print(f"Merged {updated} translations into {out_path}")
    return 0


def chunk_status(chunks_dir: str) -> int:
    if not os.path.isdir(chunks_dir):
        print(f"Chunks directory not found: {chunks_dir}", file=sys.stderr)
        return 1

    manifest = _load_manifest(chunks_dir)
    chunk_files = _iter_chunk_files(chunks_dir)
    if not chunk_files:
        print(f"No chunk files found in {chunks_dir}", file=sys.stderr)
        return 1

    total_entries = 0
    translated_entries = 0
    completed_chunks = 0
    for _, chunk_path in chunk_files:
        chunk_total = 0
        chunk_done = 0
        with open(chunk_path, encoding="utf-8") as f:
            for line in f:
                parsed = parse_chunk_line(line)
                if parsed is None:
                    continue
                chunk_total += 1
                if parsed[2]:
                    chunk_done += 1
        total_entries += chunk_total
        translated_entries += chunk_done
        if chunk_total and chunk_done == chunk_total:
            completed_chunks += 1

    locale = manifest.get("locale", "?")
    target = manifest.get("target_language", "?")
    chunk_count = len(chunk_files)
    manifest_completed = manifest.get("completed_chunks", [])
    next_file = manifest.get("next_chunk_file")
    print(
        f"{translated_entries}/{total_entries} entries translated "
        f"({completed_chunks}/{chunk_count} chunks complete, {locale} -> {target})"
    )
    if manifest_completed:
        print(
            f"Manifest cursor: {len(manifest_completed)}/{manifest.get('chunk_count', chunk_count)} "
            f"marked complete, last=chunk_{manifest.get('last_completed_chunk', 0):03d}.tsv"
        )
    if next_file:
        print(f"Next chunk: {next_file}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Split concepts PO files into translation chunks and merge them back."
    )
    subparsers = parser.add_subparsers(dest="action", required=True)

    split_parser = subparsers.add_parser("split", help="Split a PO file into chunk files.")
    split_parser.add_argument(
        "--po",
        required=True,
        help="Source PO file, e.g. locale/de/LC_MESSAGES/concepts.po",
    )
    split_parser.add_argument(
        "--chunks-dir",
        default=None,
        help="Output directory for chunks. Default: sibling chunks/ dir of the PO file.",
    )
    split_parser.add_argument(
        "--entries",
        type=int,
        default=75,
        help="Entries per chunk (~75 entries ≈ 300 PO lines). Default: 75.",
    )
    split_parser.add_argument(
        "--all-entries",
        action="store_true",
        help="Include already-translated entries (default: only untranslated).",
    )
    split_parser.add_argument(
        "--target-language",
        default="",
        help="Hint for translators in chunk headers (default: PO header Language).",
    )

    merge_parser = subparsers.add_parser("merge", help="Merge translated chunks into a PO file.")
    merge_parser.add_argument(
        "--po",
        required=True,
        help="PO file to update, e.g. locale/de/LC_MESSAGES/concepts.po",
    )
    merge_parser.add_argument(
        "--chunks-dir",
        required=True,
        help="Directory containing chunk_*.tsv files.",
    )
    merge_parser.add_argument(
        "--output",
        default=None,
        help="Write merged PO here instead of overwriting --po.",
    )

    status_parser = subparsers.add_parser("status", help="Show translation progress in chunk files.")
    status_parser.add_argument(
        "--chunks-dir",
        required=True,
        help="Directory containing chunk_*.tsv files.",
    )

    validate_parser = subparsers.add_parser(
        "validate",
        help="Check chunk keys and non-empty translations against the split manifest.",
    )
    validate_parser.add_argument(
        "--chunks-dir",
        required=True,
        help="Directory containing chunk_*.tsv files and manifest.json.",
    )
    validate_parser.add_argument(
        "--chunk",
        default=None,
        help="Validate one chunk file only, e.g. chunk_001.tsv",
    )
    validate_parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="Rebuild chunk_keys_cache.json from the PO before validating.",
    )

    complete_parser = subparsers.add_parser(
        "complete",
        help="Validate a chunk and record it as complete in manifest.json.",
    )
    complete_parser.add_argument(
        "--chunks-dir",
        required=True,
        help="Directory containing chunk_*.tsv files and manifest.json.",
    )
    complete_parser.add_argument(
        "--chunk",
        required=True,
        help="Chunk file to mark complete, e.g. chunk_001.tsv",
    )

    rebuild_cache_parser = subparsers.add_parser(
        "rebuild-cache",
        help="Rebuild chunk_keys_cache.json from chunk TSV files or the PO.",
    )
    rebuild_cache_parser.add_argument(
        "--chunks-dir",
        required=True,
        help="Directory containing chunk_*.tsv files and manifest.json.",
    )
    rebuild_cache_parser.add_argument(
        "--from-po",
        action="store_true",
        help="Rebuild from the PO file instead of chunk TSV files (default: from chunks).",
    )

    args = parser.parse_args()
    base = SCRIPT_DIR

    if args.action == "split":
        po_path = _resolve_path(args.po, base)
        if not os.path.isfile(po_path):
            print(f"PO file not found: {po_path}", file=sys.stderr)
            return 1
        chunks_dir = _resolve_path(args.chunks_dir or _default_chunks_dir(po_path), base)
        split_po(
            po_path,
            chunks_dir,
            entries_per_chunk=max(1, args.entries),
            only_untranslated=not args.all_entries,
            target_language=args.target_language,
        )
        return 0

    if args.action == "merge":
        po_path = _resolve_path(args.po, base)
        chunks_dir = _resolve_path(args.chunks_dir, base)
        if not os.path.isfile(po_path):
            print(f"PO file not found: {po_path}", file=sys.stderr)
            return 1
        if not os.path.isdir(chunks_dir):
            print(f"Chunks directory not found: {chunks_dir}", file=sys.stderr)
            return 1
        output = _resolve_path(args.output, base) if args.output else None
        return merge_chunks(po_path, chunks_dir, output=output)

    if args.action == "validate":
        return validate_chunks(
            _resolve_path(args.chunks_dir, base),
            chunk_name=args.chunk,
            rebuild_cache=args.rebuild_cache,
        )

    if args.action == "complete":
        return complete_chunk(
            _resolve_path(args.chunks_dir, base),
            args.chunk,
        )

    if args.action == "rebuild-cache":
        return rebuild_chunk_keys_cache(
            _resolve_path(args.chunks_dir, base),
            from_chunks=not args.from_po,
        )

    return chunk_status(_resolve_path(args.chunks_dir, base))


if __name__ == "__main__":
    sys.exit(main())
