import argparse
import os
import sys

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

from sd_runner.blacklist import Blacklist
from ui_qt.prompts.blacklist_window import BlacklistWindow


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Filter lines in a text file against the tag blacklist.",
    )
    parser.add_argument(
        "input_file",
        help="Text file to check (one phrase per line)",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Write non-blacklisted lines to this file",
    )
    args = parser.parse_args()

    if not os.path.exists(args.input_file):
        print(f"Input file not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)

    BlacklistWindow.set_blacklist()

    with open(args.input_file, "r", encoding="utf-8") as f:
        lines = [line.rstrip("\n\r") for line in f]

    non_blacklisted, blacklisted = Blacklist.filter_file_lines(lines, do_cache=False)

    for line in blacklisted:
        print(line)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            for line in non_blacklisted:
                f.write(line + "\n")
        print(
            f"Wrote {len(non_blacklisted)} non-blacklisted lines to {args.output}",
            file=sys.stderr,
        )

    if blacklisted:
        print(
            f"{len(blacklisted)} of {len(lines)} lines blacklisted",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
