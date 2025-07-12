import os
import sys

from sd_runner.blacklist import Blacklist
from ui.tags_blacklist_window import BlacklistWindow

# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)

if __name__ == "__main__":
    BlacklistWindow.set_blacklist()
    print("Default blacklist loaded")
    Blacklist.encrypt_blacklist()
    print("Default blacklist encrypted: " + Blacklist.DEFAULT_BLACKLIST_FILE_LOC)
