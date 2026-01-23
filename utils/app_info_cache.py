import hashlib
import json
import os
import shutil

from lib.position_data import PositionData
from sd_runner.blacklist import Blacklist
from utils.config import config
from utils.globals import Globals, PromptMode, BlacklistPromptMode
from utils.encryptor import encrypt_data_to_file, decrypt_data_from_file
from utils.logging_setup import get_logger
from utils.runner_app_config import RunnerAppConfig

logger = get_logger("app_info_cache")

class AppInfoCache:
    CACHE_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.enc")
    JSON_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.json")
    INFO_KEY = "info"
    HISTORY_KEY = "run_history"
    PROMPT_HISTORY_KEY = "prompt_history"  # New key for prompt tag history
    MAX_HISTORY_ENTRIES = 1000
    MAX_PROMPT_HISTORY_ENTRIES = 5000  # Larger limit for prompt history
    DIRECTORIES_KEY = "directories"
    HISTORY_PURGE_CACHE_KEY = "history_purge_cache"  # Cache for history purge results
    NUM_BACKUPS = 4  # Number of backup files to maintain

    def __init__(self):
        self._cache = {
            AppInfoCache.INFO_KEY: {}, 
            AppInfoCache.HISTORY_KEY: [], 
            AppInfoCache.PROMPT_HISTORY_KEY: [],
            AppInfoCache.DIRECTORIES_KEY: {}
        }
        # Used to ensure post-init logic that depends on other subsystems
        # (like blacklist configuration) only runs once.
        self._post_init_done = False
        self.load()
        self.validate()

    def wipe_instance(self):
        self._cache = {
            AppInfoCache.INFO_KEY: {},
            AppInfoCache.HISTORY_KEY: [],
            AppInfoCache.PROMPT_HISTORY_KEY: [],
            AppInfoCache.DIRECTORIES_KEY: {},
            AppInfoCache.HISTORY_PURGE_CACHE_KEY: {}
        }

    def store(self):
        try:
            if config.purge_blacklisted_prompt_history:
                self._purge_blacklisted_history()
            cache_data = json.dumps(self._cache).encode('utf-8')
            encrypt_data_to_file(
                cache_data,
                Globals.SERVICE_NAME,
                Globals.APP_IDENTIFIER,
                AppInfoCache.CACHE_LOC
            )
        except Exception as e:
            logger.error(f"Error storing cache: {e}")
            raise e

    def _try_load_cache_from_file(self, path):
        """Attempt to load and decrypt the cache from the given file path. Raises on failure."""
        encrypted_data = decrypt_data_from_file(
            path,
            Globals.SERVICE_NAME,
            Globals.APP_IDENTIFIER
        )
        return json.loads(encrypted_data.decode('utf-8'))

    def load(self):
        try:
            if os.path.exists(AppInfoCache.JSON_LOC):
                logger.info(f"Removing old cache file: {AppInfoCache.JSON_LOC}")
                # Get the old data first
                with open(AppInfoCache.JSON_LOC, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self.store() # store encrypted cache
                os.remove(AppInfoCache.JSON_LOC)
                return

            # Try encrypted cache and backups in order
            cache_paths = [self.CACHE_LOC] + self._get_backup_paths()
            any_exist = any(os.path.exists(path) for path in cache_paths)
            if not any_exist:
                logger.info(f"No cache file found at {self.CACHE_LOC}, creating new cache")
                return

            for path in cache_paths:
                if os.path.exists(path):
                    try:
                        self._cache = self._try_load_cache_from_file(path)
                        # Only shift backups if we loaded from the main file
                        if path == self.CACHE_LOC:
                            message = f"Loaded cache from {self.CACHE_LOC}"
                            rotated_count = self._rotate_backups()
                            if rotated_count > 0:
                                message += f", rotated {rotated_count} backups"
                            logger.info(message)
                        else:
                            logger.warning(f"Loaded cache from backup: {path}")
                        return
                    except Exception as e:
                        logger.error(f"Failed to load cache from {path}: {e}")
                        continue
            # If we get here, all attempts failed (but at least one file existed)
            raise Exception(f"Failed to load cache from all locations: {cache_paths}")
        except Exception as e:
            logger.error(f"Error loading cache: {e}")
            pass

    def validate(self):
        pass

    def post_init(self):
        """Run initialization that depends on other subsystems having been configured.

        This is intended to be called once, after components like the blacklist
        window have been initialized and restored persisted blacklist settings.
        """
        if self._post_init_done:
            return
        self._post_init_done = True

        if config.purge_blacklisted_prompt_history:
            self._purge_blacklisted_history()

    def _purge_blacklisted_history(self):
        """Remove any history entries that contain blacklisted items in their prompts.
        
        Uses per-entry caching to avoid re-checking history entries that have already
        been checked. The cache is keyed by entry content hash and blacklist version
        to ensure consistency. Only clears cache when blacklist version changes.
        """
        if not self._cache.get(AppInfoCache.HISTORY_KEY):
            return

        prompt_mode = PromptMode.get(self.get("prompt_mode", default_val=PromptMode.SFW.name))
        if prompt_mode.is_nsfw() and Blacklist.get_blacklist_prompt_mode() == BlacklistPromptMode.ALLOW_IN_NSFW:
            return
        
        # Get current blacklist version
        current_version = Blacklist.get_version()
        
        # Initialize purge cache if it doesn't exist
        if AppInfoCache.HISTORY_PURGE_CACHE_KEY not in self._cache:
            self._cache[AppInfoCache.HISTORY_PURGE_CACHE_KEY] = {}
        
        purge_cache = self._cache[AppInfoCache.HISTORY_PURGE_CACHE_KEY]
        
        # Check if cache version matches, clear if not
        cached_version = purge_cache.get("_version", -1)
        if cached_version != current_version:
            # Version changed, clear the cache (but keep the markers)
            purge_cache.clear()
            purge_cache["_version"] = current_version
        
        filtered_history = []
        count_removed = 0

        for config_dict in self._cache[AppInfoCache.HISTORY_KEY]:
            config = RunnerAppConfig.from_dict(config_dict)
            if not config.positive_tags or not config.positive_tags.strip():
                filtered_history.append(config_dict)
                continue
            
            # Create cache key from entry content and blacklist version
            entry_content = config.positive_tags.strip()
            entry_hash = hashlib.md5(entry_content.encode('utf-8')).hexdigest()
            cache_key = f"{entry_hash}_{current_version}"
            
            # Check cache first
            if cache_key in purge_cache:
                # Use cached result
                is_blacklisted = purge_cache[cache_key]
            else:
                # Not in cache, perform the check
                # First do standard check, then detailed check if standard check passes
                blacklisted = Blacklist.find_blacklisted_items(config.positive_tags)
                if not blacklisted:
                    # Perform detailed check for filter evasion attempts
                    blacklisted = Blacklist.check_user_prompt_detailed(config.positive_tags)
                
                is_blacklisted = len(blacklisted) > 0
                # Cache the result
                purge_cache[cache_key] = is_blacklisted
            
            if not is_blacklisted:
                filtered_history.append(config_dict)
            else:
                count_removed += 1

        if count_removed > 0:
            logger.info(f"Removed {count_removed} history entries with blacklisted items.")
            logger.info(f"Remaining history entries: {len(filtered_history)}")
            
        # Ensure we don't exceed MAX_HISTORY_ENTRIES after filtering
        if len(filtered_history) > AppInfoCache.MAX_HISTORY_ENTRIES:
            filtered_history = filtered_history[:AppInfoCache.MAX_HISTORY_ENTRIES]
            logger.info(f"Truncated history to {AppInfoCache.MAX_HISTORY_ENTRIES} entries")
            
        self._cache[AppInfoCache.HISTORY_KEY] = filtered_history

    def _get_history(self) -> list:
        if AppInfoCache.HISTORY_KEY not in self._cache:
            self._cache[AppInfoCache.HISTORY_KEY] = {}
        return self._cache[AppInfoCache.HISTORY_KEY]

    def _get_prompt_history(self) -> list:
        """Get the prompt history list, creating it if it doesn't exist."""
        if AppInfoCache.PROMPT_HISTORY_KEY not in self._cache:
            self._cache[AppInfoCache.PROMPT_HISTORY_KEY] = []
        return self._cache[AppInfoCache.PROMPT_HISTORY_KEY]

    def _get_directory_info(self):
        if AppInfoCache.DIRECTORIES_KEY not in self._cache:
            self._cache[AppInfoCache.DIRECTORIES_KEY] = {}
        return self._cache[AppInfoCache.DIRECTORIES_KEY]

    def set(self, key, value):
        if AppInfoCache.INFO_KEY not in self._cache:
            self._cache[AppInfoCache.INFO_KEY] = {}
        self._cache[AppInfoCache.INFO_KEY][key] = value

    def get(self, key, default_val=None):
        if AppInfoCache.INFO_KEY not in self._cache or key not in self._cache[AppInfoCache.INFO_KEY]:
            return default_val
        return self._cache[AppInfoCache.INFO_KEY][key]

    def set_display_position(self, master):
        """Store the main window's display position and size."""
        self.set("display_position", PositionData.from_master(master).to_dict())

    def set_virtual_screen_info(self, master):
        """Store the virtual screen information."""
        try:
            self.set("virtual_screen_info", PositionData.from_master_virtual_screen(master).to_dict())
        except Exception as e:
            logger.warning(f"Failed to store virtual screen info: {e}")

    def get_virtual_screen_info(self):
        """Get the cached virtual screen info, returns None if not set or invalid."""
        virtual_screen_data = self.get("virtual_screen_info")
        if not virtual_screen_data:
            return None
        return PositionData.from_dict(virtual_screen_data)

    def get_display_position(self):
        """Get the cached display position, returns None if not set or invalid."""
        position_data = self.get("display_position")
        if not position_data:
            return None
        return PositionData.from_dict(position_data)

    def set_history(self, runner_app_config):
        history = self._get_history()
        if len(history) > 0 and runner_app_config == RunnerAppConfig.from_dict(history[0]):
            logger.debug("History already contains this config")
            return False
            
        config_dict = runner_app_config.to_dict()
        history.insert(0, config_dict)
        
        # Add to prompt history if there are positive tags
        if runner_app_config.positive_tags and runner_app_config.positive_tags.strip():
            prompt_history = self._get_prompt_history()
            prompt_entry = {
                "positive_tags": runner_app_config.positive_tags,
                "negative_tags": runner_app_config.negative_tags,
                "timestamp": config_dict.get("timestamp", "")  # Preserve timestamp if available
            }
            prompt_history.insert(0, prompt_entry)
            
            # Trim prompt history if needed
            while len(prompt_history) > AppInfoCache.MAX_PROMPT_HISTORY_ENTRIES:
                prompt_history.pop()
        
        # Remove the oldest entry from history if over the limit of entries
        while len(history) > AppInfoCache.MAX_HISTORY_ENTRIES:
            history.pop()
        return True

    def get_last_history_index(self):
        history = self._get_history()
        return len(history) - 1

    def get_history(self, _idx=0):
        history = self._get_history()
        if _idx >= len(history):
            raise Exception("Invalid history index " + str(_idx))
        return history[_idx]

    def get_prompt_tags_by_frequency(self, weighted=False) -> dict[str, int]:
        """Get frequency of prompt tags from the prompt history.
        
        Args:
            weighted: If True, weight tags by recency (newer tags count more)
            
        Returns:
            dict: Mapping of tags to their frequency counts
        """
        prompt_history = self._get_prompt_history()
        prompt_tags = {}
        
        for idx, entry in enumerate(prompt_history):
            if not entry.get("positive_tags"):
                continue
                
            # Calculate weight based on position if weighted
            weight = 1.0
            if weighted:
                # Newer entries get higher weights, decreasing exponentially
                weight = 1.0 / (1.0 + idx * 0.1)
                
            tags = entry["positive_tags"].split(",")
            for tag in tags:
                tag = tag.strip()
                if not tag:
                    continue
                    
                # Clean the tag by removing parentheses
                while tag.startswith('(') or tag.startswith('['):
                    tag = tag[1:].strip()
                while tag.endswith(')') or tag.endswith(']'):
                    tag = tag[:-1].strip()
                    
                if tag not in prompt_tags:
                    prompt_tags[tag] = weight
                else:
                    prompt_tags[tag] += weight
                    
        return prompt_tags

    def get_recent_prompts(self, limit=10) -> list[dict]:
        """Get the most recent prompts from the prompt history.
        
        Args:
            limit: Maximum number of prompts to return
            
        Returns:
            list: List of recent prompt entries, each containing positive_tags, negative_tags, and timestamp
        """
        prompt_history = self._get_prompt_history()
        return prompt_history[:limit]

    def set_directory(self, directory, key, value):
        directory = AppInfoCache.normalize_directory_key(directory)
        if directory is None or directory.strip() == "":
            raise Exception(f"Invalid directory provided to app_info_cache.set(). key={key} value={value}")
        directory_info = self._get_directory_info()
        if directory not in directory_info:
            directory_info[directory] = {}
        directory_info[directory][key] = value

    def get_directory(self, directory, key, default_val=None):
        directory = AppInfoCache.normalize_directory_key(directory)
        directory_info = self._get_directory_info()
        if directory not in directory_info or key not in directory_info[directory]:
            return default_val
        return directory_info[directory][key]

    @staticmethod
    def normalize_directory_key(directory):
        return os.path.normpath(os.path.abspath(directory))

    def export_as_json(self, json_path=None):
        """Export the current cache as a JSON file (not encrypted)."""
        if json_path is None:
            json_path = AppInfoCache.JSON_LOC
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(self._cache, f, ensure_ascii=False, indent=2)
        return json_path

    def _get_backup_paths(self):
        """Get list of backup file paths in order of preference"""
        backup_paths = []
        for i in range(1, self.NUM_BACKUPS + 1):
            index = "" if i == 1 else f"{i}"
            path = f"{self.CACHE_LOC}.bak{index}"
            backup_paths.append(path)
        return backup_paths

    def _rotate_backups(self):
        """Rotate backup files: move each backup to the next position, oldest gets overwritten"""
        backup_paths = self._get_backup_paths()
        rotated_count = 0
        
        # Remove the oldest backup if it exists
        if os.path.exists(backup_paths[-1]):
            os.remove(backup_paths[-1])
        
        # Shift backups: move each backup to the next position
        for i in range(len(backup_paths) - 1, 0, -1):
            if os.path.exists(backup_paths[i - 1]):
                shutil.copy2(backup_paths[i - 1], backup_paths[i])
                rotated_count += 1
        
        # Copy main cache to first backup position
        shutil.copy2(self.CACHE_LOC, backup_paths[0])
        
        return rotated_count


app_info_cache = AppInfoCache()
