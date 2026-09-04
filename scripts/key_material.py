"""
Inspect or back up this application's encryption key material.

``status`` (the default) is read-only and prints no secrets -- it reports
presence, location and freshness so you can answer "where is it, has the
migration finished, and is my off-drive backup current?" without opening
anything that contains a key.

``backup`` writes a full copy, passphrase included, for the cases automatic
backup cannot cover: seeding a new machine, or capturing state before a
change. Routine backups happen on their own now, whenever the key store is
written (see AUTO_BACKUP_KEY_STORE in utils/encryptor.py).

Usage:
  python scripts/key_material.py                       # status
  python scripts/key_material.py status --include-legacy
  python scripts/key_material.py backup                # to the detected drive
  python scripts/key_material.py backup -o E:/keys.json
  python scripts/key_material.py backup --stdout       # print, write nothing
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(REPO_ROOT))

from sd_runner.globals import Globals  # noqa: E402
from lib.encryptor import (  # noqa: E402
    AUTO_BACKUP_KEY_STORE,
    ENCRYPTOR_TYPE_KEY,
    KEY_BACKUP_DIR_ENV_VAR,
    PasswordManager,
    available_external_drives,
    default_key_backup_path,
    export_key_material,
    get_key_base,
    has_prior_key_material,
    key_store_path,
    namespaced_key,
    peek_passphrase,
    read_key_store,
)
import keyring  # noqa: E402


def _identifiers(include_legacy: bool) -> list:
    """Current app identifier, plus the legacy ones when asked.

    A renamed app leaves key material filed under its old identifier, and that
    material stays load-bearing until everything encrypted under it has been
    migrated. This project has never renamed, so the list is empty and
    ``--include-legacy`` reports nothing extra -- it is kept so a future rename
    only has to add the old name to Globals.
    """
    identifiers = [Globals.APP_IDENTIFIER]
    if include_legacy:
        identifiers.extend(
            app_id for app_id in Globals.LEGACY_APP_IDENTIFIERS
            if app_id not in identifiers
        )
    return identifiers


def _mtime(path: str) -> str:
    try:
        stamp = datetime.datetime.fromtimestamp(os.path.getmtime(path))
        return stamp.strftime("%Y-%m-%d %H:%M:%S")
    except OSError:
        return "unknown"


def _stored_password_id() -> str:
    """The application password's id, from the auth layer that defines it.

    Imported lazily and guarded: this script must still run in a checkout
    where the auth module is unavailable or mid-edit.
    """
    try:
        from sd_runner.ui.auth.password_core import PasswordManager as AuthPasswordManager
        return AuthPasswordManager.PASSWORD_ID
    except Exception:
        return "base"


def _legacy_items_present(service_name: str, app_identifier: str) -> list:
    """Pre-consolidation keychain items still in place.

    Anything here means migration has not finished for this identifier -- the
    keys are still spread across one keychain item per component.
    """
    found = []
    for key in ("salt", "nonce", "tag", ENCRYPTOR_TYPE_KEY):
        if keyring.get_password(service_name, namespaced_key(app_identifier, key)):
            found.append(key)
    # Password chunks migrate lazily, on the first retrieve, so they can linger
    # after the keys themselves have moved. The id comes from the auth layer,
    # which is the only place that knows it.
    for base in ("encrypted_priv", "public_key", _stored_password_id()):
        count_key = namespaced_key(get_key_base(app_identifier, base), "count")
        count = keyring.get_password(service_name, count_key)
        if count:
            found.append(f"{base} ({count} chunks)")
    return found


def _report_identifier(service_name: str, app_identifier: str) -> None:
    print(f"\n--- {app_identifier} ---")
    if not has_prior_key_material(service_name, app_identifier):
        print("  No key material found for this identifier.")
        return

    store_path = key_store_path(service_name, app_identifier)
    store = read_key_store(service_name, app_identifier)
    print(f"  key store   : {store_path}")
    if store is None:
        print("                MISSING or unreadable -- the app will refuse to")
        print("                generate new keys and ask you to restore a backup.")
    else:
        passwords = sorted(store.get(PasswordManager.STORE_SECTION, {}))
        print(f"                present, {os.path.getsize(store_path)} bytes, "
              f"modified {_mtime(store_path)}")
        print(f"  encryptor   : {store.get(ENCRYPTOR_TYPE_KEY, 'unknown')}")
        print(f"  passwords   : {', '.join(passwords) if passwords else '(none stored)'}")

    print(f"  passphrase  : {'present in keychain' if peek_passphrase(service_name, app_identifier) else 'ABSENT'}")

    legacy = _legacy_items_present(service_name, app_identifier)
    if legacy:
        print(f"  legacy items: {', '.join(legacy)}")
        print("                migration has not completed for this identifier;")
        print("                starting the app should finish it.")
    else:
        print("  legacy items: none (migration complete)")

    backup = default_key_backup_path(service_name, app_identifier)
    if not backup:
        print("  backup      : no destination -- nothing is being backed up")
    elif not os.path.exists(backup):
        print(f"  backup      : {backup}")
        print("                NOT YET WRITTEN (auto-backup runs on the next")
        print("                key store write; 'backup' below writes one now)")
    else:
        print(f"  backup      : {backup}")
        print(f"                written {_mtime(backup)}")
        try:
            with open(backup, "r", encoding="utf-8") as handle:
                backed_up = json.load(handle)
            if backed_up.get("key_store") == store:
                print("                up to date with the key store")
            elif backed_up.get("key_store") is None:
                print("                PREDATES MIGRATION (holds legacy items, not a")
                print("                key store) -- still restorable, but stale")
            else:
                print("                STALE -- differs from the current key store")
        except Exception as e:
            print(f"                could not be read back: {e}")


def cmd_status(args: argparse.Namespace) -> int:
    print(f"Service        : {Globals.SERVICE_NAME}")
    print(f"Auto-backup    : {'on' if AUTO_BACKUP_KEY_STORE else 'off'}")
    print(f"{KEY_BACKUP_DIR_ENV_VAR:<15}: {os.environ.get(KEY_BACKUP_DIR_ENV_VAR) or '(unset)'}")
    print(f"SD_RUNNER_CACHE_DIR: {os.environ.get('SD_RUNNER_CACHE_DIR') or '(unset)'}")
    drives = available_external_drives()
    print(f"External drives: {', '.join(drives) if drives else '(none detected)'}")

    for app_identifier in _identifiers(args.include_legacy):
        _report_identifier(Globals.SERVICE_NAME, app_identifier)
    return 0


def _resolve_output(explicit: str | None, app_identifier: str) -> str | None:
    if explicit:
        # One file per identifier when several are exported to one path.
        stem, ext = os.path.splitext(explicit)
        return explicit if app_identifier == Globals.APP_IDENTIFIER else (
            f"{stem}__{app_identifier}{ext or '.json'}"
        )
    return default_key_backup_path(Globals.SERVICE_NAME, app_identifier)


def cmd_backup(args: argparse.Namespace) -> int:
    print(f"Service: {Globals.SERVICE_NAME}")
    written = []
    for app_identifier in _identifiers(args.include_legacy):
        print(f"\n--- {app_identifier} ---")
        if not has_prior_key_material(Globals.SERVICE_NAME, app_identifier):
            print("No key material found; nothing to back up.")
            continue

        if args.stdout:
            export_key_material(Globals.SERVICE_NAME, app_identifier)
            continue

        output = _resolve_output(args.output, app_identifier)
        if not output:
            print(
                "No external drive detected and no -o given. Re-run with "
                "-o <path on another drive>, or --stdout to print instead."
            )
            return 1

        directory = os.path.dirname(output)
        if directory:
            os.makedirs(directory, exist_ok=True)
        material = export_key_material(Globals.SERVICE_NAME, app_identifier, output)
        # Read back rather than trusting the write: an unreadable backup is
        # indistinguishable from no backup at the moment it is needed.
        with open(output, "r", encoding="utf-8") as handle:
            if json.load(handle) != material:
                print(f"WARNING: {output} did not read back intact -- do not rely on it.")
                return 1
        written.append(output)

    if written:
        print("\nVerified backups written:")
        for path in written:
            print(f"  {path}")
        print(
            "\nEach contains the keychain passphrase in the clear. Restore with:\n"
            "  from lib.encryptor import import_key_material\n"
            "  import_key_material(json.load(open(<path>)))"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    sub = parser.add_subparsers(dest="command")

    legacy_help = (
        f"Also cover legacy identifiers: "
        f"{', '.join(Globals.LEGACY_APP_IDENTIFIERS) or '(none)'}"
    )

    status = sub.add_parser("status", help="Report state; prints no secrets.")
    status.add_argument("--include-legacy", action="store_true", help=legacy_help)
    status.set_defaults(func=cmd_status)

    backup = sub.add_parser("backup", help="Write a full copy, passphrase included.")
    backup.add_argument("-o", "--output", help="File to write. Omit for the detected drive.")
    backup.add_argument("--stdout", action="store_true", help="Print instead of writing.")
    backup.add_argument("--include-legacy", action="store_true", help=legacy_help)
    backup.set_defaults(func=cmd_backup)

    args = parser.parse_args()
    if not getattr(args, "func", None):
        # Bare invocation reports state -- the harmless default.
        args = parser.parse_args(["status"])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
