import json
import os

from utils.runner_app_config import RunnerAppConfig
from sd_runner.blacklist import Blacklist

# TODO add a second history cache for only the positive and negative prompt tags, or perhaps for the final prompts.
# This list should have a longer length of say 5000, and perhaps it should be its own file as well.
# This would enable the get_prompt_tags_by_frequency functionality to be used.

class AppInfoCache:
    CACHE_LOC = os.path.join(os.path.dirname(os.path.abspath(os.path.dirname(__file__))), "app_info_cache.json")
    INFO_KEY = "info"
    HISTORY_KEY = "run_history"
    MAX_HISTORY_ENTRIES = 1000
    DIRECTORIES_KEY = "directories"

    def __init__(self):
        self._cache = {AppInfoCache.INFO_KEY: {}, AppInfoCache.HISTORY_KEY: [], AppInfoCache.DIRECTORIES_KEY: {}}
        self.load()
        self.validate()

    def store(self):
        self._purge_blacklisted_history()
        with open(AppInfoCache.CACHE_LOC, "w") as f:
            json.dump(self._cache, f, indent=4)

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

    def load(self):
        try:
            with open(AppInfoCache.CACHE_LOC, "r") as f:
                self._cache = json.load(f)
        except FileNotFoundError:
            pass

    def validate(self):
        pass

    def _get_history(self) -> list:
        if AppInfoCache.HISTORY_KEY not in self._cache:
            self._cache[AppInfoCache.HISTORY_KEY] = {}
        return self._cache[AppInfoCache.HISTORY_KEY]

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
        history = self._get_history()
        prompts = []
        prompt_tags = {}
        for config in history:
            prompt = RunnerAppConfig.from_dict(config).positive_tags
            if prompt is not None and prompt != "" and prompt not in prompts:
                prompts.append(str(prompt))
        for prompt in prompts:
            tags = prompt.split(",")
            for tag in tags:
                tag = tag.strip()
                if tag not in prompt_tags:
                    prompt_tags[tag] = 1
                else:
                    prompt_tags[tag] += 1
        return prompt_tags

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

app_info_cache = AppInfoCache()
