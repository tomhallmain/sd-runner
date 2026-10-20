import argparse
import os
import sys

from sd_runner.prompts.blacklist import Blacklist
from sd_runner.prompts import blacklist_state

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

#: Label -> getter for each list the default blacklist file carries.
LISTS = {
    "tag": Blacklist.get_items,
    "model": Blacklist.get_model_items,
}


def _item_dicts() -> dict[str, dict[str, dict]]:
    """Each list's items as string -> to_dict(), so a change to any field shows."""
    return {label: {item.string: item.to_dict() for item in getter()} for label, getter in LISTS.items()}


def _load_encrypted_items() -> dict[str, dict[str, dict]]:
    """The items currently in the encrypted default blacklist, per list."""
    # Emptied first: a file written before model items were included leaves
    # the model list untouched, and that must not read as its contents.
    Blacklist.TAG_BLACKLIST = []
    Blacklist.MODEL_BLACKLIST = []
    try:
        Blacklist.decrypt_blacklist()
        items = _item_dicts()
        for label, entries in items.items():
            print(f"Number of {label} items in existing encrypted blacklist: {len(entries)}")
        return items
    except Exception as e:
        print(f"No existing encrypted blacklist found or error reading it: {e}")
        return {label: {} for label in LISTS}


def _load_current_items() -> dict[str, dict[str, dict]]:
    """The items in the current user blacklist cache, per list."""
    blacklist_state.set_blacklist()
    print("Blacklist loaded from current cache")
    return _item_dicts()


def _changed_fields(old: dict, new: dict) -> str:
    return ", ".join(f"{key}: {old.get(key)!r} -> {new.get(key)!r}"
                     for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key))


def dry_run():
    """Print what would change without writing anything."""
    encrypted = _load_encrypted_items()
    current = _load_current_items()

    changed = False
    for label in LISTS:
        old, new = encrypted[label], current[label]
        added = new.keys() - old.keys()
        removed = old.keys() - new.keys()
        modified = {s for s in new.keys() & old.keys() if new[s] != old[s]}
        unchanged = len(new.keys() & old.keys()) - len(modified)

        print(f"\n--- Dry Run Summary: {label} blacklist ---")
        print(f"Unchanged : {unchanged}")
        print(f"Modified  : {len(modified)}")
        print(f"To add    : {len(added)}")
        print(f"To remove : {len(removed)}")

        if modified:
            print(f"\n{label.capitalize()} items that would be MODIFIED ({len(modified)}):")
            for s in sorted(modified):
                print(f"  ~ {s}  ({_changed_fields(old[s], new[s])})")
        if added:
            print(f"\n{label.capitalize()} items that would be ADDED ({len(added)}):")
            for s in sorted(added):
                print(f"  + {s}")
        if removed:
            print(f"\n{label.capitalize()} items that would be REMOVED ({len(removed)}):")
            for s in sorted(removed):
                print(f"  - {s}")
        changed = changed or bool(added or removed or modified)

    if not changed:
        print("\nNo changes -- encrypted blacklist is already up to date.")


def encrypt():
    """Encrypt the tag and model blacklists into one file, then verify the round trip."""
    encrypted = _load_encrypted_items()
    current = _load_current_items()
    counts_before = {label: len(getter()) for label, getter in LISTS.items()}
    for label, count in counts_before.items():
        print(f"Number of {label} items in blacklist before encryption: {count}")

    Blacklist.encrypt_blacklist()
    print("Default blacklist encrypted: " + Blacklist.DEFAULT_BLACKLIST_FILE_LOC)

    # Verify round-trip
    Blacklist.TAG_BLACKLIST = []
    Blacklist.MODEL_BLACKLIST = []
    Blacklist.decrypt_blacklist()
    counts_after = {label: len(getter()) for label, getter in LISTS.items()}
    for label, count in counts_after.items():
        print(f"Number of {label} items in blacklist after decryption: {count}")

    if counts_before == counts_after:
        print("✓ Blacklist encryption/decryption successful - item counts match")
    else:
        print(f"⚠ Warning: Item count mismatch - before: {counts_before}, after: {counts_after}")

    # Show the change from the previous encrypted version
    for label in LISTS:
        if not encrypted[label]:
            continue
        change = len(current[label]) - len(encrypted[label])
        if change > 0:
            print(f"📈 Added {change} {label} items to the blacklist")
        elif change < 0:
            print(f"📉 Removed {abs(change)} {label} items from the blacklist")
        else:
            print(f"📊 No change in {label} item count from previous encrypted version")


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt the default tag and model blacklists from the current user cache."
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be added, removed or modified without writing the encrypted file.",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    else:
        encrypt()


if __name__ == "__main__":
    main()
