"""Print or save the plaintext of sd_runner's encrypted log files.

    python scripts/decrypt_logs.py                     most recent log, to stdout
    python scripts/decrypt_logs.py FILE [FILE ...]     the given files
    python scripts/decrypt_logs.py --all -o DIR        every log, as DIR/<name>.log

Must run as the user who wrote the logs: the key is derived from a passphrase in
that user's keyring (or SD_RUNNER_LOGS_PASSPHRASE, if set).
"""

import argparse
import os
import re
import sys
from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from cryptography.exceptions import InvalidTag  # noqa: E402

from lib.encryptor import iter_decrypt_log_file  # noqa: E402
from lib.logging_setup import (  # noqa: E402
    LOG_ENCRYPTION_APP_ID,
    LOG_ENCRYPTION_SERVICE,
    LOG_FILE_SUFFIX,
    app_data_dir,
)

_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def log_files() -> list[Path]:
    """Every encrypted log in the app's logs folder, oldest first."""
    return sorted(app_data_dir("logs", create=False).glob(f"*{LOG_FILE_SUFFIX}"))


def decrypt(path: Path, strip_colors: bool):
    """Yield the lines of *path*; stop at the first record that fails to decrypt."""
    count = 0
    try:
        for record in iter_decrypt_log_file(str(path), LOG_ENCRYPTION_SERVICE, LOG_ENCRYPTION_APP_ID):
            line = record.decode("utf-8", errors="replace")
            count += 1
            yield _ANSI.sub("", line) if strip_colors else line
    except InvalidTag:
        print(f"{path.name}: record {count + 1} did not decrypt (wrong key, or the file "
              "is corrupted); stopping here.", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Decrypt sd_runner's encrypted log files.")
    parser.add_argument("files", nargs="*", type=Path, help="Log files to decrypt (default: the most recent).")
    parser.add_argument("--all", action="store_true", help="Decrypt every log in the logs folder.")
    parser.add_argument("-o", "--output-dir", type=Path,
                        help="Write each log to <dir>/<name>.log instead of printing it.")
    parser.add_argument("--keep-colors", action="store_true",
                        help="Keep the ANSI colour codes the log lines were written with.")
    args = parser.parse_args()

    paths = args.files or log_files()
    if not args.files and not args.all:
        paths = paths[-1:]
    if not paths:
        print(f"No {LOG_FILE_SUFFIX} files found in {app_data_dir('logs', create=False)}", file=sys.stderr)
        return 1

    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        for path in paths:
            out = args.output_dir / path.name[: -len(".enc")]
            with open(out, "w", encoding="utf-8") as f:
                for line in decrypt(path, strip_colors=not args.keep_colors):
                    f.write(line + "\n")
            print(f"{path.name} -> {out}")
    else:
        strip = not (args.keep_colors or sys.stdout.isatty())
        for path in paths:
            if len(paths) > 1:
                print(f"===== {path.name} =====")
            for line in decrypt(path, strip_colors=strip):
                print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
