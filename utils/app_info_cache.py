import json
import os
import shutil

from sd_runner.blacklist import Blacklist
from utils.globals import Globals
from utils.encryptor import encrypt_data_to_file, decrypt_data_from_file
from utils.runner_app_config import RunnerAppConfig

class AppInfoCache:
    CACHE_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.enc")
    JSON_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.json")
    INFO_KEY = "info"
    HISTORY_KEY = "run_history"
    PROMPT_HISTORY_KEY = "prompt_history"  # New key for prompt tag history
    MAX_HISTORY_ENTRIES = 1000
    MAX_PROMPT_HISTORY_ENTRIES = 5000  # Larger limit for prompt history
    DIRECTORIES_KEY = "directories"

    def __init__(self):
        self._cache = {
            AppInfoCache.INFO_KEY: {}, 
            AppInfoCache.HISTORY_KEY: [], 
            AppInfoCache.PROMPT_HISTORY_KEY: [],
            AppInfoCache.DIRECTORIES_KEY: {}
        }
        self.load()
        self.validate()

    def wipe_instance(self):
        self._cache = {
            AppInfoCache.INFO_KEY: {},
            AppInfoCache.HISTORY_KEY: [],
            AppInfoCache.PROMPT_HISTORY_KEY: [],
            AppInfoCache.DIRECTORIES_KEY: {}
        }

    def store(self):
        try:
            self._purge_blacklisted_history()
            cache_data = json.dumps(self._cache).encode('utf-8')
            encrypt_data_to_file(
                cache_data,
                Globals.SERVICE_NAME,
                Globals.APP_IDENTIFIER,
                AppInfoCache.CACHE_LOC
            )
        except Exception as e:
            print(f"Error storing cache: {e}")
            raise e

    def load(self):
        try:
            if os.path.exists(AppInfoCache.JSON_LOC):
                print(f"Removing old cache file: {AppInfoCache.JSON_LOC}")
                # Get the old data first
                with open(AppInfoCache.JSON_LOC, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self.store() # store encrypted cache
                os.remove(AppInfoCache.JSON_LOC)
            elif os.path.exists(AppInfoCache.CACHE_LOC):
                decrypted_data = decrypt_data_from_file(
                    AppInfoCache.CACHE_LOC,
                    Globals.SERVICE_NAME,
                    Globals.APP_IDENTIFIER
                )
                self._cache = json.loads(decrypted_data.decode('utf-8'))
                # The encrypted file did not fail to decrypt, so preserve a backup
                backup_loc = AppInfoCache.CACHE_LOC + ".bak"
                backup_loc2 = AppInfoCache.CACHE_LOC + ".bak2"
                text = f"Loaded cache from {AppInfoCache.CACHE_LOC}, shifted backups to {backup_loc}"
                if os.path.exists(backup_loc):
                    shutil.copy2(backup_loc, backup_loc2)
                    text += f" and {backup_loc2}"
                shutil.copy2(AppInfoCache.CACHE_LOC, backup_loc)
                print(text)
            else:
                print(f"No cache file found at {AppInfoCache.CACHE_LOC}, creating new cache")
        except Exception as e:
            print(f"Error loading cache: {e}")
            pass

    def validate(self):
        pass

    def _purge_blacklisted_history(self):
        """Remove any history entries that contain blacklisted items in their prompts."""
        if not self._cache.get(AppInfoCache.HISTORY_KEY):
            return
            
        filtered_history = []
        count_removed = 0

        for config_dict in self._cache[AppInfoCache.HISTORY_KEY]:
            config = RunnerAppConfig.from_dict(config_dict)
            if not config.positive_tags or not config.positive_tags.strip():
                filtered_history.append(config_dict)
                continue
                
            # Check if any tags in the prompt are blacklisted
            blacklisted = Blacklist.find_blacklisted_items(config.positive_tags)
            if not blacklisted:
                filtered_history.append(config_dict)
            else:
                count_removed += 1

        if count_removed > 0:
            print(f"Removed {count_removed} history entries with blacklisted items.")
            print(f"Remaining history entries: {len(filtered_history)}")
            
        # Ensure we don't exceed MAX_HISTORY_ENTRIES after filtering
        if len(filtered_history) > AppInfoCache.MAX_HISTORY_ENTRIES:
            filtered_history = filtered_history[:AppInfoCache.MAX_HISTORY_ENTRIES]
            print(f"Truncated history to {AppInfoCache.MAX_HISTORY_ENTRIES} entries")
            
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

    def set_history(self, runner_config):
        history = self._get_history()
        if len(history) > 0 and runner_config == RunnerAppConfig.from_dict(history[0]):
            return False
            
        config_dict = runner_config.to_dict()
        history.insert(0, config_dict)
        
        # Add to prompt history if there are positive tags
        if runner_config.positive_tags and runner_config.positive_tags.strip():
            prompt_history = self._get_prompt_history()
            prompt_entry = {
                "positive_tags": runner_config.positive_tags,
                "negative_tags": runner_config.negative_tags,
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

app_info_cache = AppInfoCache()
