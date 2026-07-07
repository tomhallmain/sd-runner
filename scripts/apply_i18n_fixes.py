"""Apply targeted i18n translation fixes from a JSON file to locale PO catalogs."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
LOCALE_DIR = REPO_ROOT / "locale"
DEFAULT_FIXES_PATH = SCRIPT_DIR / "i18n_fixes.json"


def load_fixes(path: Path) -> tuple[dict[tuple[str, str], str], dict[tuple[str, str], list[str]]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    fixes: dict[tuple[str, str], str] = {}
    for locale, entries in data.get("fixes", {}).items():
        for msgid, msgstr in entries.items():
            fixes[(locale, msgid)] = msgstr
    multiline_fixes: dict[tuple[str, str], list[str]] = {}
    for locale, entries in data.get("multiline_fixes", {}).items():
        for msgid, parts in entries.items():
            multiline_fixes[(locale, msgid)] = parts
    return fixes, multiline_fixes


def unescape_po(s: str) -> str:
    return s.replace("\\n", "\n").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def escape_po(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\t", "\\t")


def read_quoted_lines(lines: list[str], start: int) -> tuple[str, int]:
    """Read msgid/msgstr block starting at `start`. Returns (text, next_index)."""
    parts: list[str] = []
    i = start
    if i >= len(lines):
        return "", i
    first = lines[i].strip()
    if first == 'msgid ""' or first == 'msgstr ""':
        i += 1
        while i < len(lines) and lines[i].startswith('"'):
            parts.append(unescape_po(lines[i].strip()[1:-1]))
            i += 1
        return "".join(parts), i
    if first.startswith("msgid ") or first.startswith("msgstr "):
        m = re.match(r'msg(?:id|str) "(.*)"\s*$', first)
        if m:
            return unescape_po(m.group(1)), i + 1
    return "", start + 1


def format_msgstr(text: str) -> list[str]:
    if "\n" in text or len(text) > 70:
        out = ['msgstr ""']
        remaining = text
        while remaining:
            chunk = remaining[:70]
            if len(remaining) > 70:
                sp = chunk.rfind(" ")
                if sp > 40:
                    chunk = remaining[: sp + 1]
            out.append(f'"{escape_po(chunk)}"')
            remaining = remaining[len(chunk) :]
        return out
    return [f'msgstr "{escape_po(text)}"']


def update_po_file(
    path: Path,
    locale: str,
    fixes: dict[tuple[str, str], str],
    multiline_fixes: dict[tuple[str, str], list[str]],
) -> int:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    out: list[str] = []
    changed = 0
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("msgid "):
            msgid, next_i = read_quoted_lines([l.rstrip("\n") for l in lines], i)
            block = lines[i:next_i]
            out.extend(block)
            i = next_i
            if i < len(lines) and lines[i].strip().startswith("msgstr"):
                _old_msgstr, after_msgstr = read_quoted_lines(
                    [l.rstrip("\n") for l in lines], i
                )
                key = (locale, msgid)
                if key in fixes:
                    for nl in format_msgstr(fixes[key]):
                        out.append(nl + "\n")
                    changed += 1
                    i = after_msgstr
                    continue
                if key in multiline_fixes:
                    out.append('msgstr ""\n')
                    for part in multiline_fixes[key]:
                        out.append(f'"{escape_po(part)}"\n')
                    changed += 1
                    i = after_msgstr
                    continue
                out.extend(lines[i:after_msgstr])
                i = after_msgstr
                continue
        out.append(line)
        i += 1
    if changed:
        path.write_text("".join(out), encoding="utf-8")
    return changed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Apply msgstr overrides from a JSON fixes file to locale PO catalogs.",
    )
    parser.add_argument(
        "--fixes",
        type=Path,
        default=DEFAULT_FIXES_PATH,
        help=f"Path to fixes JSON (default: {DEFAULT_FIXES_PATH.name})",
    )
    parser.add_argument(
        "--include-en",
        action="store_true",
        help="Also apply fixes for the en catalog (skipped by default).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fixes_path = args.fixes.resolve()
    if not fixes_path.is_file():
        print(
            f"Fixes file not found: {fixes_path}\n"
            f"Copy {SCRIPT_DIR / 'i18n_fixes.example.json'} to {DEFAULT_FIXES_PATH.name} "
            "and add your overrides.",
            file=sys.stderr,
        )
        return 1

    fixes, multiline_fixes = load_fixes(fixes_path)
    if not fixes and not multiline_fixes:
        print(f"No fixes defined in {fixes_path}", file=sys.stderr)
        return 1

    total = 0
    for po in sorted(LOCALE_DIR.glob("*/LC_MESSAGES/base.po")):
        locale = po.parent.parent.name
        if locale == "en" and not args.include_en:
            continue
        n = update_po_file(po, locale, fixes, multiline_fixes)
        if n:
            print(f"{locale}: {n} fixes")
            total += n
    print(f"Total: {total} fixes applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
