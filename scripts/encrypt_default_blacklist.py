import argparse
import os
import sys

from sd_runner.blacklist import Blacklist
from ui.tags_blacklist_window import BlacklistWindow

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)


def _load_encrypted_items():
    """Load and return the items currently in the encrypted default blacklist."""
    try:
        Blacklist.decrypt_blacklist()
        items = [item.string for item in Blacklist.get_items()]
        print(f"Number of items in existing encrypted blacklist: {len(items)}")
        return set(items)
    except Exception as e:
        print(f"No existing encrypted blacklist found or error reading it: {e}")
        return set()


def _load_current_items():
    """Load the current user blacklist from cache and return item strings."""
    BlacklistWindow.set_blacklist()
    print("Blacklist loaded from current cache")
    return {item.string for item in Blacklist.get_items()}


def dry_run():
    """Print what would change without writing anything."""
    encrypted_strings = _load_encrypted_items()
    current_strings = _load_current_items()

    added = current_strings - encrypted_strings
    removed = encrypted_strings - current_strings
    unchanged = current_strings & encrypted_strings

    print(f"\n--- Dry Run Summary ---")
    print(f"Unchanged : {len(unchanged)}")
    print(f"To add    : {len(added)}")
    print(f"To remove : {len(removed)}")

    if added:
        print(f"\nConcepts that would be ADDED ({len(added)}):")
        for s in sorted(added):
            print(f"  + {s}")
    if removed:
        print(f"\nConcepts that would be REMOVED ({len(removed)}):")
        for s in sorted(removed):
            print(f"  - {s}")
    if not added and not removed:
        print("\nNo changes -- encrypted blacklist is already up to date.")


def encrypt():
    """Full encrypt run (original behaviour)."""
    encrypted_strings = _load_encrypted_items()
    items_in_encrypted = len(encrypted_strings)

    current_strings = _load_current_items()
    items_before = len(current_strings)
    print(f"Number of items in blacklist before encryption: {items_before}")

    Blacklist.encrypt_blacklist()
    print("Default blacklist encrypted: " + Blacklist.DEFAULT_BLACKLIST_FILE_LOC)

    # Verify round-trip
    Blacklist.decrypt_blacklist()
    items_after = len(Blacklist.get_items())
    print(f"Number of items in blacklist after decryption: {items_after}")

    if items_before == items_after:
        print("✓ Blacklist encryption/decryption successful - item counts match")
    else:
        print(f"⚠ Warning: Item count mismatch - before: {items_before}, after: {items_after}")
    
    # Show the change from the previous encrypted version
    if items_in_encrypted > 0:
        change = items_before - items_in_encrypted
        if change > 0:
            print(f"📈 Added {change} items to the blacklist")
        elif change < 0:
            print(f"📉 Removed {abs(change)} items from the blacklist")
        else:
            print("📊 No change in item count from previous encrypted version")


def main():
    parser = argparse.ArgumentParser(
        description="Encrypt the default blacklist from the current user cache."
    )
    parser.add_argument(
        "--dry-run", "-n",
        action="store_true",
        help="Show what would be added/removed without writing the encrypted file.",
    )
    args = parser.parse_args()

    if args.dry_run:
        dry_run()
    else:
        encrypt()


if __name__ == "__main__":
    main()
