"""Encrypt the trimmed Urban Dictionary corpus for the runtime.

Reads the trimmed plain list (sd_runner/data/urban_dictionary.txt by default,
git-ignored, written by the trim pipeline's ship step) and writes
Concepts.URBAN_DICTIONARY_CORPUS_PATH in the default blacklist's obfuscated
format, then decrypts it again to confirm the round trip.

    python scripts/encrypt_urban_dictionary.py --dry-run
    python scripts/encrypt_urban_dictionary.py
    python scripts/encrypt_urban_dictionary.py --input path/to/list.txt
"""
import argparse
import os
import sys

# Run from the project root so imports and relative paths resolve.
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.prompts.concepts import Concepts  # noqa: E402

# Plain source of the .enc beside it; git-ignored.
DEFAULT_INPUT = os.path.join(PROJECT_ROOT, "sd_runner", "data", "urban_dictionary.txt")
SAMPLE = 20


def _read_terms(path):
    with open(path, encoding="utf-8", newline="") as f:
        return [line.rstrip("\r\n") for line in f if line.strip()]


def _runtime_view(terms):
    """What load_urban_dictionary_corpus returns for these lines."""
    out = []
    for line in terms:
        value = line.split("#", 1)[0].strip()
        if value:
            out.append(value)
    return out


def _load_existing():
    if not os.path.isfile(Concepts.URBAN_DICTIONARY_CORPUS_PATH):
        print(f"No existing encrypted corpus at {Concepts.URBAN_DICTIONARY_CORPUS_PATH}")
        return []
    existing = Concepts.load_urban_dictionary_corpus()
    print(f"Entries in existing encrypted corpus: {len(existing):,}")
    return existing


def dry_run(input_path):
    """Print what would change without writing anything."""
    new = set(_runtime_view(_read_terms(input_path)))
    old = set(_load_existing())
    added, removed = new - old, old - new
    print("\n--- Dry Run Summary ---")
    print(f"Unchanged : {len(new & old):,}")
    print(f"To add    : {len(added):,}")
    print(f"To remove : {len(removed):,}")
    for label, items in (("ADDED", added), ("REMOVED", removed)):
        if items:
            print(f"\nFirst {min(SAMPLE, len(items))} {label} of {len(items):,}:")
            for s in sorted(items)[:SAMPLE]:
                print(f"  {'+' if label == 'ADDED' else '-'} {s}")
    if not added and not removed:
        print("\nNo changes -- encrypted corpus is already up to date.")


def encrypt(input_path):
    terms = _read_terms(input_path)
    expected = _runtime_view(terms)
    previous = len(_load_existing())
    print(f"Lines in {input_path}: {len(terms):,} ({len(expected):,} after '#' comments)")

    Concepts.encrypt_urban_dictionary_corpus(terms)
    size = os.path.getsize(Concepts.URBAN_DICTIONARY_CORPUS_PATH)
    print(f"Encrypted corpus written: {Concepts.URBAN_DICTIONARY_CORPUS_PATH} ({size / 1_000_000:.1f} MB)")

    # load_urban_dictionary_corpus reports a path once; clear it so a failed
    # round trip is reported here rather than swallowed.
    Concepts._missing_files_reported.discard(Concepts.URBAN_DICTIONARY_CORPUS_PATH)
    decrypted = Concepts.load_urban_dictionary_corpus()
    if decrypted == expected:
        print(f"✓ Round trip matches: {len(decrypted):,} entries")
    else:
        print(f"⚠ Round trip mismatch: expected {len(expected):,}, got {len(decrypted):,}")
        sys.exit(1)
    if previous:
        print(f"Change from previous encrypted corpus: {len(decrypted) - previous:+,} entries")


def main():
    parser = argparse.ArgumentParser(description="Encrypt the trimmed Urban Dictionary corpus.")
    parser.add_argument("--input", default=DEFAULT_INPUT, help="plain list, one term per line")
    parser.add_argument("--dry-run", "-n", action="store_true",
                        help="show what would be added/removed without writing the encrypted file")
    args = parser.parse_args()
    if not os.path.isfile(args.input):
        sys.exit(f"Input not found: {args.input}")
    if args.dry_run:
        dry_run(args.input)
    else:
        encrypt(args.input)


if __name__ == "__main__":
    main()
