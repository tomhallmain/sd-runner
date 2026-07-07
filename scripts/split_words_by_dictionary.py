#!/usr/bin/env python3
"""
Split a word list into words that are known (found in the app's dictionary
concept lists) and words that are unknown (not found).

Run from the repository root:

    python scripts/split_words_by_dictionary.py --input some_word_list.txt
    python scripts/split_words_by_dictionary.py --input some_word_list.txt --capitalize --keep-found
"""

import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sd_runner.concepts import BASE_DIR, Concepts

# Additional dictionary consulted alongside whichever concepts dir is currently
# configured (Concepts.ALL_WORDS_LIST_FILENAME / Concepts.CONCEPTS_DIR), so
# words known to either count as "found".
KONZEPTE_DICTIONARY_PATH = os.path.join(BASE_DIR, "Konzepte", "dictionary.txt")


def _load_dictionary_words():
    if not Concepts.ALL_WORDS_LIST:
        Concepts.ALL_WORDS_LIST = Concepts.load(Concepts.ALL_WORDS_LIST_FILENAME)
    words = set(Concepts.ALL_WORDS_LIST)
    words.update(Concepts.load(KONZEPTE_DICTIONARY_PATH))
    if not words:
        raise Exception("No words found in the dictionary concept files")
    return words


def split_words_by_dictionary(words):
    """Return (found, unknown) lists, comparing lowercased words against the dictionaries."""
    dictionary_words = _load_dictionary_words()

    found = []
    unknown = []
    seen = set()
    for word in words:
        lower = word.lower()
        if lower in seen:
            continue
        seen.add(lower)
        if lower in dictionary_words:
            found.append(lower)
        else:
            unknown.append(lower)
    return found, unknown


def main(input_path, capitalize=False, keep_found=False):
    words = Concepts.load(input_path)
    found, unknown = split_words_by_dictionary(words)

    if capitalize:
        found = [w[0].upper() + w[1:] for w in found]
        unknown = [w[0].upper() + w[1:] for w in unknown]

    input_base = os.path.splitext(os.path.basename(input_path))[0]
    output_dir = os.path.join(Concepts.CONCEPTS_DIR, "temp")
    os.makedirs(output_dir, exist_ok=True)

    unknown_path = os.path.join(output_dir, f"{input_base}_unknown.txt")
    with open(unknown_path, "w", encoding="utf8") as f:
        for word in unknown:
            f.write(word + "\n")
    print(f"Wrote {len(unknown)} unknown words to {unknown_path}")

    if keep_found:
        found_path = os.path.join(output_dir, f"{input_base}_found.txt")
        with open(found_path, "w", encoding="utf8") as f:
            for word in found:
                f.write(word + "\n")
        print(f"Wrote {len(found)} found words to {found_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Word list file to split (resolved via Concepts.load)")
    parser.add_argument("--capitalize", action="store_true", help="Capitalize the first letter of each output word")
    parser.add_argument("--keep-found", action="store_true", help="Also write the words found in the dictionary")
    args = parser.parse_args()
    main(args.input, capitalize=args.capitalize, keep_found=args.keep_found)
