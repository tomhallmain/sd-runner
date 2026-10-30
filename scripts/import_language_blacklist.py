"""Builds a blacklist CSV from curated per-language accept files.

    python scripts/import_language_blacklist.py --accept-dir docs/Sperrliste-Verbesserungen/accept_lists \
        --against docs/Sperrliste-Verbesserungen/Sperrlisteausfuhr.csv --out blacklist_supplement.csv

    python scripts/import_language_blacklist.py --language de --accept accept_de.txt --out blacklist_de.csv

The output is imported in the Blacklist window on top of the current list. An
accept file has one entry per line, a word or a regex row, with leading markers:

    ~   no word boundary, so the row matches inside compounds
    @   user prompts only: it does not filter concept lines or dictionary words
    !   no language: it applies to all text
    =   an existing row of --against, given this language (or none, with !)

"# hold: a, b - reason" records entries left out, and other # lines are comments.
A row shared by two languages must be global, since an item is identified by its
string and has one language.
"""

import argparse
import csv
import os
import sys
import unicodedata

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.prompts.blacklist import BlacklistItem
from sd_runner.prompts.language_codes import normalize_language_code

MARKERS = "~@!="
ACCEPT_PREFIX = "accept_"
HOLD_PREFIX = "# hold:"


def parse_entry(line):
    """The marker set and row text of an accept line, or None for a blank or comment."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    markers = set()
    while line[0] in MARKERS:
        markers.add(line[0])
        line = line[1:]
    return markers, line


def parse_holds(line):
    """The entries a hold line names."""
    if not line.startswith(HOLD_PREFIX):
        return []
    names = line[len(HOLD_PREFIX):].split(" - ", 1)[0]
    return [name.strip().lower() for name in names.split(",") if name.strip()]


def build_item(markers, text, language):
    """A BlacklistItem for an accept entry that is not a retag."""
    use_regex = BlacklistItem(text).has_unflagged_regex_syntax()
    boundary = "~" not in markers and not BlacklistItem(text).has_ineffective_word_boundary()
    return BlacklistItem(
        text,
        use_regex=use_regex,
        use_word_boundary=boundary,
        apply_to_generated="@" not in markers,
        language=None if "!" in markers else language,
    )


def retag(row, language):
    """A copy of an existing row with a language."""
    data = row.to_dict()
    data["language"] = language
    return BlacklistItem.from_dict(data)


def load_rows(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [item for item in map(BlacklistItem.from_csv_row, csv.DictReader(f)) if item is not None]


def caught(item, base):
    """Whether the base list already catches a plain row that has a boundary.

    Others stay: a row with no boundary reaches compounds the base list does
    not, and a regex cannot be tested as a word.
    """
    if item.use_regex or not item.use_word_boundary or not item.apply_to_generated:
        return False
    return any(row.matches_tag(item.string) for row in base if row.language is None)


def process_language(language, accept_path, base):
    """The items of one accept file, and what was left out and why."""
    by_string = {row.string: row for row in base}
    items, skipped, held = [], [], []
    with open(accept_path, encoding="utf-8") as f:
        for line in f:
            held.extend(parse_holds(line.strip()))
            entry = parse_entry(line)
            if entry is None:
                continue
            markers, text = entry
            if "=" in markers:
                if text not in by_string:
                    raise ValueError(f"{accept_path}: {text} is not in the --against list")
                items.append(retag(by_string[text], None if "!" in markers else language))
                continue
            item = build_item(markers, text, language)
            if item.string in by_string and by_string[item.string].language is None:
                # It would replace the global item and narrow it to this language.
                skipped.append((item.string, "already global"))
            elif caught(item, base):
                skipped.append((item.string, "already caught"))
            else:
                items.append(item)
    return items, skipped, held


def folded(text):
    """Lowercase without accents: hold lines are written without them."""
    decomposed = unicodedata.normalize("NFD", text.lower())
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def source_files(folder, language):
    """The source lists in *folder* for a language; regional lists merge into it."""
    return [os.path.join(folder, name) for name in sorted(os.listdir(folder))
            if normalize_language_code(name) == language]


def unreviewed(source_paths, items, base, held):
    """Entries of the source lists that no row covers and no hold line names."""
    entries = []
    for path in source_paths:
        with open(path, encoding="utf-8") as f:
            entries += [line.strip() for line in f if line.strip()]
    rows = items + base
    held = {folded(name) for name in held}
    return [entry for entry in entries
            if folded(entry) not in held and not any(row.matches_tag(entry) for row in rows)]


def accept_files(args):
    if args.accept_dir:
        for name in sorted(os.listdir(args.accept_dir)):
            if name.startswith(ACCEPT_PREFIX) and name.endswith(".txt"):
                yield name[len(ACCEPT_PREFIX):-len(".txt")], os.path.join(args.accept_dir, name)
    else:
        yield args.language, args.accept


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--language", help="Language code of --accept")
    parser.add_argument("--accept", help="A curated accept file")
    parser.add_argument("--accept-dir", help="A folder of accept_<code>.txt files, written to one CSV")
    parser.add_argument("--against", help="CSV of the current list, to skip what it already has")
    parser.add_argument("--ldnoobw", help="Source list, or folder of them, to report entries nothing covers")
    parser.add_argument("--out", required=True, help="CSV to write")
    args = parser.parse_args()
    if not args.accept_dir and not (args.language and args.accept):
        parser.error("give --accept-dir, or --language with --accept")

    base = load_rows(args.against) if args.against else []
    results = [(language, *process_language(language, path, base)) for language, path in accept_files(args)]
    # A global row covers every language's source list, not only its own.
    global_items = [item for _language, items, _skipped, _held in results for item in items if item.language is None]
    written = {}
    for language, items, skipped, held in results:
        for item in items:
            if item.string in written and written[item.string].language != item.language:
                print(f"WARNING: {item.string} is in two languages; make it global with !", file=sys.stderr)
            written[item.string] = item
        print(f"{language}: {len(items)} rows, {len(skipped)} skipped, {len(held)} held")
        for string, reason in skipped:
            print(f"    skipped {string} ({reason})")
        if args.ldnoobw:
            sources = source_files(args.ldnoobw, language) if os.path.isdir(args.ldnoobw) else [args.ldnoobw]
            if sources:
                missing = unreviewed(sources, items + global_items, base, held)
                print(f"    {len(missing)} source entries not covered or held: {missing}")

    with open(args.out, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(BlacklistItem.CSV_FIELDNAMES))
        writer.writeheader()
        for item in written.values():
            writer.writerow(item.to_dict())
    print(f"Wrote {len(written)} rows to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
