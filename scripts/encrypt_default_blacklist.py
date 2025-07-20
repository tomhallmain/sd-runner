import os
import sys

from sd_runner.blacklist import Blacklist
from ui.tags_blacklist_window import BlacklistWindow

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)


def main():
    # First, check the number of items in the existing encrypted blacklist
    try:
        Blacklist.decrypt_blacklist()
        items_in_encrypted = len(Blacklist.get_items())
        print(f"Number of items in existing encrypted blacklist: {items_in_encrypted}")
    except Exception as e:
        print(f"No existing encrypted blacklist found or error reading it: {e}")
        items_in_encrypted = 0
    
    # Now load the current blacklist
    BlacklistWindow.set_blacklist()
    print("Blacklist loaded from current")
    
    # Print the current number of items in the blacklist before encryption
    items_before = len(Blacklist.get_items())
    print(f"Number of items in blacklist before encryption: {items_before}")
    
    Blacklist.encrypt_blacklist()
    print("Default blacklist encrypted: " + Blacklist.DEFAULT_BLACKLIST_FILE_LOC)
    
    # Decrypt the blacklist and print the number of items after
    Blacklist.decrypt_blacklist()
    items_after = len(Blacklist.get_items())
    print(f"Number of items in blacklist after decryption: {items_after}")
    
    # Verify the counts match
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


if __name__ == "__main__":
    main()
