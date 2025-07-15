import os
import sys

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.concepts import Concepts
from sd_runner.blacklist import Blacklist
from ui.tags_blacklist_window import BlacklistWindow

# Set the input file path here for your use case
INPUT_PATH = Concepts.URBAN_DICTIONARY_CORPUS_PATH


def main(input_path):
    if not os.path.exists(input_path):
        print(f"Input file not found: {input_path}")
        return

    # Prepare output file paths based on the input file
    input_dir = os.path.dirname(input_path)
    input_base = os.path.splitext(os.path.basename(input_path))[0]
    whitelisted_path = os.path.join(input_dir, f"{input_base}_whitelisted.txt")
    blacklisted_path = os.path.join(input_dir, f"{input_base}_blacklisted.txt")

    # Load concepts
    with open(input_path, 'r', encoding='utf-8') as f:
        concepts = [line.strip() for line in f if line.strip()]

    # Use the Blacklist to split the concepts
    BlacklistWindow.set_blacklist()
    whitelist, filtered = Blacklist.filter_concepts(concepts, do_cache=False, user_prompt=False)
    blacklist = list(filtered.keys())

    # Write whitelisted concepts
    with open(whitelisted_path, 'w', encoding='utf-8') as f:
        for concept in sorted(whitelist):
            f.write(concept + '\n')
    print(f"Wrote {len(whitelist)} whitelisted concepts to {whitelisted_path}")

    # Write blacklisted concepts
    with open(blacklisted_path, 'w', encoding='utf-8') as f:
        for concept in sorted(blacklist):
            f.write(concept + '\n')
    print(f"Wrote {len(blacklist)} blacklisted concepts to {blacklisted_path}")

if __name__ == "__main__":
    main(INPUT_PATH)