"""
Export concepts directory to a gettext POT template and import a locale's
concepts PO file back into a localized concepts directory.

Excludes dictionary.txt by default so locales can use a separate dictionary.
Excludes any .txt files whose basename starts with temp_.
Uses gettext context (msgctxt) = file basename and msgid = concept string
for uniqueness and translator-friendly keys.

Workflow:
  1. Export: python concepts_gettext.py export
     -> Writes locale/concepts.pot from default concepts/ (excludes dictionary.txt).
  2. Create/update locale PO: e.g. msgmerge -U locale/de/LC_MESSAGES/concepts.po locale/concepts.pot
  3. Translate in concepts.po (msgstr).
  4. Import: python concepts_gettext.py import --po locale/de/LC_MESSAGES/concepts.po --output concepts_de
     -> Writes concepts_de/ with translated lines; add that path to config concepts_dirs.
"""

import argparse
import os
import re
import sys


# Default filename to exclude from concepts i18n (use separate dictionary per locale)
DEFAULT_EXCLUDE_FILES = frozenset({
    "dictionary.txt",
    "artists.txt",
    "boring_concepts.txt",
    "glitch.txt",
    "exclusionary_concepts.txt",
    "hard_concepts.txt",
    "mangakas.txt",
    "mangakas_raw.txt",
    "negatives.txt",
    "painters.txt",
})


def load_concepts_file(filepath: str) -> list[str]:
    """Load concept lines from a file. Same logic as sd_runner.concepts.Concepts.load:
    strip content after #, skip empty lines."""
    result = []
    try:
        with open(filepath, encoding="utf-8") as f:
            for line in f:
                val = ""
                for c in line:
                    if c == "#":
                        break
                    val += c
                val = val.strip()
                if len(val) > 0:
                    result.append(val)
    except OSError as e:
        print(f"Failed to load concepts file: {filepath}: {e}", file=sys.stderr)
    return result


def get_concept_txt_files(concepts_dir: str, exclude_files: frozenset[str] | None = None) -> list[str]:
    """Return sorted list of .txt filenames in concepts_dir, excluding given filenames and temp_*."""
    exclude = exclude_files if exclude_files is not None else DEFAULT_EXCLUDE_FILES
    names = []
    for name in os.listdir(concepts_dir):
        if (
            name.endswith(".txt")
            and name not in exclude
            and not name.startswith("temp_")
        ):
            path = os.path.join(concepts_dir, name)
            if os.path.isfile(path):
                names.append(name)
    return sorted(names)


def escape_po_string(s: str) -> str:
    """Escape a string for use inside gettext "" quotes."""
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def write_pot_string(f, key: str, value: str, indent: str = "") -> None:
    """Write one key (msgctxt or msgid or msgstr) with value; handle multiline."""
    escaped = escape_po_string(value)
    if "\n" in value or len(escaped) > 78:
        # Multiline: opening quote, then "\\n" lines
        f.write(f'{indent}{key} ""\n')
        for line in value.split("\n"):
            f.write(f'{indent}"{escape_po_string(line)}\\n"\n')
    else:
        f.write(f'{indent}{key} "{escaped}"\n')


def export_concepts_to_pot(
    concepts_dir: str,
    pot_path: str,
    exclude_files: frozenset[str] | None = None,
    domain: str = "concepts",
) -> None:
    """
    Scan concepts_dir for .txt files (excluding exclude_files), load each,
    and write a gettext POT template to pot_path.
    Uses msgctxt = file basename (no .txt) and msgid = concept line.
    """
    exclude = exclude_files if exclude_files is not None else DEFAULT_EXCLUDE_FILES
    files = get_concept_txt_files(concepts_dir, exclude)
    os.makedirs(os.path.dirname(pot_path) or ".", exist_ok=True)

    with open(pot_path, "w", encoding="utf-8") as f:
        f.write(
            f'# Concepts template for domain "{domain}".\n'
            "# Export from concepts directory; msgctxt = file basename, msgid = concept string.\n"
            "# Excluded files (e.g. dictionary.txt) use a separate dictionary per locale.\n"
            "#\n"
            'msgid ""\n'
            'msgstr ""\n'
            '"Content-Type: text/plain; charset=UTF-8\\n"\n'
            '"Content-Transfer-Encoding: 8bit\\n"\n'
            "\n"
        )
        for filename in files:
            filepath = os.path.join(concepts_dir, filename)
            basename = os.path.splitext(filename)[0]
            lines = load_concepts_file(filepath)
            for line in lines:
                f.write(f"# {filename}\n")
                write_pot_string(f, "msgctxt", basename)
                write_pot_string(f, "msgid", line)
                write_pot_string(f, "msgstr", "")
                f.write("\n")


def _unescape_po(raw: str) -> str:
    """Unescape gettext string content (\\, \", \\n, \\t)."""
    decoded = []
    j = 0
    while j < len(raw):
        if raw[j] == "\\" and j + 1 < len(raw):
            n = raw[j + 1]
            if n == "n":
                decoded.append("\n")
            elif n == "t":
                decoded.append("\t")
            elif n == '"':
                decoded.append('"')
            elif n == "\\":
                decoded.append("\\")
            else:
                decoded.append(n)
            j += 2
        else:
            decoded.append(raw[j])
            j += 1
    return "".join(decoded)


def _parse_po_string(lines: list[str], start_list: list[int]) -> tuple[str, int]:
    """Parse a quoted string value from PO lines. start_list is [current_index] so we can mutate."""
    i = start_list[0]
    parts = []
    # First line may be "msgctxt \"value\"" or "msgid \"\""
    m = re.search(r'"((?:[^"\\]|\\.)*)"', lines[i])
    if not m:
        start_list[0] = i
        return ("", i)
    parts.append(_unescape_po(m.group(1)))
    i += 1
    # Continuation lines: line is only a single quoted string
    while i < len(lines):
        m = re.match(r'^\s*"((?:[^"\\]|\\.)*)"\s*$', lines[i])
        if not m:
            break
        parts.append(_unescape_po(m.group(1)))
        i += 1
    start_list[0] = i
    return ("".join(parts), i)


def parse_po(po_path: str) -> dict[tuple[str, str], str]:
    """
    Parse a PO file and return a mapping (msgctxt, msgid) -> msgstr.
    Skips the header (empty msgid). Includes only entries that have msgctxt
    (our concepts use context = file basename).
    """
    with open(po_path, encoding="utf-8") as f:
        content = f.read()
    lines = content.split("\n")
    result = {}
    idx = [0]
    while idx[0] < len(lines):
        i = idx[0]
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("msgctxt "):
            idx[0] = i
            msgctxt, _ = _parse_po_string(lines, idx)
            if idx[0] < len(lines) and lines[idx[0]].strip().startswith("msgid "):
                msgid, _ = _parse_po_string(lines, idx)
                msgstr = ""
                if idx[0] < len(lines) and lines[idx[0]].strip().startswith("msgstr "):
                    msgstr, _ = _parse_po_string(lines, idx)
                if msgctxt:
                    result[(msgctxt, msgid)] = msgstr
            continue
        if stripped.startswith("msgid "):
            msgid, _ = _parse_po_string(lines, idx)
            if idx[0] < len(lines) and lines[idx[0]].strip().startswith("msgstr "):
                msgstr, _ = _parse_po_string(lines, idx)
            # Skip header; we only store entries with context from export
            continue
        idx[0] += 1
    return result


def import_locale_to_concepts(
    concepts_dir_source: str,
    po_path: str,
    output_concepts_dir: str,
    exclude_files: frozenset[str] | None = None,
) -> None:
    """
    Build a localized concepts directory from the source concepts dir and
    a locale's concepts PO file. For each (file, line) in source, use the
    translation from the PO if present, else the original. Order is preserved.
    Excluded files (e.g. dictionary.txt) are skipped; use a separate dictionary
    for that locale.
    """
    exclude = exclude_files if exclude_files is not None else DEFAULT_EXCLUDE_FILES
    translations = parse_po(po_path)
    files = get_concept_txt_files(concepts_dir_source, exclude)
    os.makedirs(output_concepts_dir, exist_ok=True)

    for filename in files:
        filepath = os.path.join(concepts_dir_source, filename)
        basename = os.path.splitext(filename)[0]
        lines = load_concepts_file(filepath)
        out_path = os.path.join(output_concepts_dir, filename)
        with open(out_path, "w", encoding="utf-8") as f:
            for line in lines:
                key = (basename, line)
                out_line = translations.get(key) or line
                if not out_line:
                    out_line = line
                f.write(out_line + "\n")


def _resolve_path(path: str, base: str) -> str:
    if os.path.isabs(path):
        return path
    return os.path.normpath(os.path.join(base, path))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export concepts to gettext POT or import a locale PO into a concepts directory."
    )
    parser.add_argument(
        "action",
        choices=["export", "import"],
        help="Export concepts dir to POT, or import a locale PO into an output concepts dir.",
    )
    parser.add_argument(
        "--concepts-dir",
        default=None,
        help="Concepts directory. For export: source; for import: source for order/lookup. Default: repo concepts/.",
    )
    parser.add_argument(
        "--pot",
        default=None,
        help="Path to concepts.pot (export). Default: locale/concepts.pot relative to concepts dir.",
    )
    parser.add_argument(
        "--po",
        default=None,
        help="Path to locale concepts.po (import). e.g. locale/de/LC_MESSAGES/concepts.po",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output concepts directory (import only). e.g. concepts_de",
    )
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=None,
        help=f"Filenames to exclude (default: {list(DEFAULT_EXCLUDE_FILES)}).",
    )
    args = parser.parse_args()

    base = os.path.abspath(os.path.dirname(__file__))
    repo_root = os.path.abspath(os.path.join(base, "..", ".."))
    default_concepts = os.path.join(repo_root, "concepts")
    default_locale = os.path.join(repo_root, "locale")

    concepts_dir = _resolve_path(args.concepts_dir or "concepts", repo_root)
    if not os.path.isdir(concepts_dir):
        print(f"Concepts directory not found: {concepts_dir}", file=sys.stderr)
        return 1

    exclude = frozenset(args.exclude) if args.exclude is not None else DEFAULT_EXCLUDE_FILES

    if args.action == "export":
        pot_path = args.pot
        if pot_path is None:
            pot_path = os.path.join(default_locale, "concepts.pot")
        else:
            pot_path = _resolve_path(pot_path, repo_root)
        export_concepts_to_pot(concepts_dir, pot_path, exclude_files=exclude)
        print(f"Exported to {pot_path}")

    else:
        if args.po is None:
            print("Import requires --po (path to locale concepts.po).", file=sys.stderr)
            return 1
        if args.output is None:
            print("Import requires --output (path to output concepts directory).", file=sys.stderr)
            return 1
        po_path = _resolve_path(args.po, repo_root)
        output_dir = _resolve_path(args.output, repo_root)
        if not os.path.isfile(po_path):
            print(f"PO file not found: {po_path}", file=sys.stderr)
            return 1
        import_locale_to_concepts(concepts_dir, po_path, output_dir, exclude_files=exclude)
        print(f"Imported to {output_dir}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
