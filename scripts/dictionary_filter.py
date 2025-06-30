import os
import sys

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.concepts import Concepts
from sd_runner.blacklist import Blacklist

# Output files
WHITELISTED_PATH = os.path.join('concepts', 'temp', 'urban_dictionary_whitelisted.txt')
BLACKLISTED_PATH = os.path.join('concepts', 'temp', 'urban_dictionary_blacklisted.txt')

def main():
    # Load Urban Dictionary concepts
    if not os.path.exists(Concepts.URBAN_DICTIONARY_CORPUS_PATH):
        print(f"Urban Dictionary file not found: {Concepts.URBAN_DICTIONARY_CORPUS_PATH}")
        return
    with open(Concepts.URBAN_DICTIONARY_CORPUS_PATH, 'r', encoding='utf-8') as f:
        concepts = [line.strip() for line in f if line.strip()]

    # Use the Blacklist to split the concepts
    whitelist, filtered = Blacklist.filter_concepts(concepts, do_cache=False)
    blacklist = list(filtered.keys())

    # Write whitelisted concepts
    with open(WHITELISTED_PATH, 'w', encoding='utf-8') as f:
        for concept in sorted(whitelist):
            f.write(concept + '\n')
    print(f"Wrote {len(whitelist)} whitelisted concepts to {WHITELISTED_PATH}")

    # Write blacklisted concepts
    with open(BLACKLISTED_PATH, 'w', encoding='utf-8') as f:
        for concept in sorted(blacklist):
            f.write(concept + '\n')
    print(f"Wrote {len(blacklist)} blacklisted concepts to {BLACKLISTED_PATH}")

if __name__ == "__main__":
    main() 