import csv
import json
import os
import re

from utils.globals import Globals, BlacklistMode, ModelBlacklistMode
from utils.encryptor import symmetric_encrypt_data_to_file, symmetric_decrypt_data_from_file
from utils.pickleable_cache import SizeAwarePicklableCache
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._

# Define cache file path
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
BLACKLIST_CACHE_FILE = os.path.join(CACHE_DIR, "blacklist_filter_cache.pkl")

class BlacklistException(Exception):
    def __init__(self, message, whitelist, filtered):
        self.message = message
        self.whitelist = whitelist
        self.filtered = filtered
        super().__init__(self.message)


class BlacklistItem:
    def __init__(self, string: str, enabled: bool = True, use_regex: bool = False, use_word_boundary: bool = True):
        self.enabled = enabled
        self.use_regex = use_regex
        self.use_word_boundary = use_word_boundary
        
        if use_regex:
            # For regex patterns, store the original string and compile with case-insensitive flag
            self.string = string  # Keep original case for regex patterns
            # Use glob-to-regex conversion for regex mode with case-insensitive flag
            self.regex_pattern = re.compile(self._glob_to_regex(string), re.IGNORECASE)
        else:
            # For non-regex patterns, convert to lowercase and use simple word boundary pattern
            self.string = string.lower()
            # Use simple word boundary pattern for exact match mode
            if use_word_boundary:
                self.regex_pattern = re.compile(r'(^|\W)' + re.escape(self.string))
            else:
                self.regex_pattern = re.compile(re.escape(self.string))

    def to_dict(self):
        return {
            "string": self.string,
            "enabled": self.enabled,
            "use_regex": self.use_regex,
            "use_word_boundary": self.use_word_boundary
        }

    @classmethod
    def from_dict(cls, data: dict):
        if not isinstance(data, dict):
            return None
        if "string" not in data or not isinstance(data["string"], str):
            return None
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        use_regex = data.get("use_regex", False)
        if not isinstance(use_regex, bool):
            use_regex = False
        use_word_boundary = data.get("use_word_boundary", True)
        if not isinstance(use_word_boundary, bool):
            use_word_boundary = True
        return cls(data["string"], enabled, use_regex, use_word_boundary)

    def matches_tag(self, tag: str) -> bool:
        """Check if a tag matches this blacklist item.
        
        Args:
            tag: The tag to check against this blacklist item
            
        Returns:
            bool: True if the tag matches this blacklist item, False otherwise
        """
        if not self.use_regex:
            # For regex patterns, use the original tag (case-insensitive matching is handled by the regex)
            # For non-regex patterns, convert tag to lowercase
            tag = tag.lower()
            
        # Always use the compiled regex pattern for the base string
        if self.regex_pattern.search(tag):
            return True
                
        return False

    def _glob_to_regex(self, pattern: str) -> str:
        """Convert a glob pattern to a regex pattern with optional word start boundary matching.
        
        Args:
            pattern: The glob pattern to convert
            
        Returns:
            str: The regex pattern with optional word start boundary matching
        """
        regex_pattern = ''
        prev_char = None
        two_prev_char = None
        for char in pattern:
            if char == '*':
                if two_prev_char == '\\' and prev_char == '.':
                    regex_pattern += '*'
                else:
                    regex_pattern += '.*'
            elif char != '.':
                if prev_char == '.':
                    regex_pattern += '.'
                regex_pattern += char
            prev_char = char
            two_prev_char = prev_char
        
        # Add word boundary matching: (^|\W) at start only if requested.
        # This ensures the pattern matches at the start of a word.
        # If the user wants to add boundary matching to the end,
        # they can do this by adding (\W|$) to the end of the pattern.
        if self.use_word_boundary:
            regex_pattern = r'(^|\W)' + regex_pattern
        
        return regex_pattern

    def remove_blacklisted_content(self, tag: str) -> str:
        """Remove blacklisted content from a tag.
        
        Args:
            tag: The tag to process
            
        Returns:
            str: The tag with blacklisted content removed
        """
        # Remove the matched pattern from the tag (works for both regex and non-regex)
        cleaned_tag = re.sub(self.regex_pattern, '', tag)
        # Clean up extra whitespace
        cleaned_tag = re.sub(r'\s+', ' ', cleaned_tag).strip()
        return cleaned_tag

    def __eq__(self, other):
        if isinstance(other, BlacklistItem):
            return self.string == other.string
        if isinstance(other, str):
            return self.string == other
        return False

    def __hash__(self):
        return hash(self.string)

    def __str__(self):
        return self.string
    

class ModelBlacklistItem(BlacklistItem):
    def __init__(self, string: str, enabled: bool = True, use_regex: bool = False):
        # For models, word boundary is not relevant
        super().__init__(string, enabled, use_regex, use_word_boundary=False)

    @classmethod
    def from_dict(cls, data: dict):
        # Ignore use_word_boundary for models
        if not isinstance(data, dict):
            return None
        if "string" not in data or not isinstance(data["string"], str):
            return None
        enabled = data.get("enabled", True)
        if not isinstance(enabled, bool):
            enabled = True
        use_regex = data.get("use_regex", False)
        if not isinstance(use_regex, bool):
            use_regex = False
        return cls(data["string"], enabled, use_regex)


class Blacklist:
    TAG_BLACKLIST: list[BlacklistItem] = []
    MODEL_BLACKLIST: list[ModelBlacklistItem] = []
    CACHE_MAXSIZE = 64
    CACHE_LARGE_THRESHOLD = 1024 * 1024 * 8
    CACHE_MAX_LARGE_ITEMS = 4
    DEFAULT_BLACKLIST_FILE_LOC = os.path.join(os.path.dirname(__file__), "data", "blacklist_default.enc")
    _ui_callbacks = None  # Static variable to store UI callbacks
    _filter_cache = SizeAwarePicklableCache.load_or_create(
        BLACKLIST_CACHE_FILE, maxsize=CACHE_MAXSIZE,
        max_large_items=CACHE_MAX_LARGE_ITEMS, large_threshold=CACHE_LARGE_THRESHOLD)

    blacklist_mode = BlacklistMode.REMOVE_ENTIRE_TAG
    model_blacklist_mode = ModelBlacklistMode.ALLOW_IN_NSFW
    blacklist_silent_removal = False
    model_blacklist_all_prompt_modes = False

    @staticmethod
    def get_blacklist_mode():
        return Blacklist.blacklist_mode

    @staticmethod
    def set_blacklist_mode(mode):
        Blacklist.blacklist_mode = mode

    @staticmethod
    def get_model_blacklist_mode():
        return Blacklist.model_blacklist_mode

    @staticmethod
    def set_model_blacklist_mode(mode):
        Blacklist.model_blacklist_mode = mode

    @staticmethod
    def get_blacklist_silent_removal():
        return Blacklist.blacklist_silent_removal

    @staticmethod
    def set_blacklist_silent_removal(silent):
        Blacklist.blacklist_silent_removal = silent

    @staticmethod
    def get_model_blacklist_all_prompt_modes():
        return Blacklist.model_blacklist_all_prompt_modes

    @staticmethod
    def set_model_blacklist_all_prompt_modes(all_prompt_modes):
        Blacklist.model_blacklist_all_prompt_modes = all_prompt_modes

    @staticmethod
    def _filter_concepts_cached(concepts_tuple, do_cache=True, user_prompt=True):
        # Check cache first - use just the concepts tuple as key (no version needed)
        try:
            cached_result = Blacklist._filter_cache.get(concepts_tuple)
            if cached_result is not None:
                return cached_result
        except Exception as e:
            raise Exception(f"Error accessing blacklist cache: {e}", e)
        
        concepts_count = len(concepts_tuple)

        def do_update_progress(current_concept_index):
            if concepts_count < 20000 or Blacklist._ui_callbacks is None:
                return
            # Notify UI that filtering is starting
            try:
                Blacklist._ui_callbacks.update_progress(current_index=current_concept_index, total=concepts_count,
                                                        prepend_text=_("Filtering concepts for blacklist: "))
            except Exception:
                pass  # Ignore any errors in UI callback
        
        # Convert tuple back to list for processing
        mode = Blacklist.get_blacklist_mode() if user_prompt else BlacklistMode.REMOVE_ENTIRE_TAG
        concepts = list(concepts_tuple)
        whitelist = []
        filtered = {}
        
        # Call progress update at the beginning (0)
        do_update_progress(0)
        
        print(f"Filtering concepts for blacklist: {concepts_count} - {mode}")
        
        # Single loop with different behaviors based on mode
        for i, concept_cased in enumerate(concepts):
            match_found = False
            for blacklist_item in Blacklist.TAG_BLACKLIST:
                if not blacklist_item.enabled:
                    continue
                if blacklist_item.matches_tag(concept_cased):
                    filtered[concept_cased] = blacklist_item.string
                    match_found = True
                    break
            
            # Handle different modes
            if mode == BlacklistMode.REMOVE_WORD_OR_PHRASE and match_found:
                # Try to remove the blacklisted content from the concept
                cleaned_concept = blacklist_item.remove_blacklisted_content(concept_cased)
                if cleaned_concept and cleaned_concept.strip():
                    whitelist.append(cleaned_concept)
            elif not match_found or mode == BlacklistMode.LOG_ONLY:
                # Default behavior: add to whitelist if no blacklist match found
                whitelist.append(concept_cased)
            
            # Call progress update every 5000 concepts
            if (i + 1) % 5000 == 0:
                do_update_progress(i + 1)
        
        # # Handle FAIL_PROMPT mode: clear whitelist if any violations were found
        # if mode == BlacklistMode.FAIL_PROMPT and filtered:
        #     whitelist = []
        if mode == BlacklistMode.LOG_ONLY:
            print(f"Concepts would have been filtered:")
            for filtered_concept, blacklist_item in filtered.items():
                print(f"  {filtered_concept} -> {blacklist_item}")
            
        # Call progress update at the end
        do_update_progress(concepts_count)
        print(f"Filtered {len(filtered)} concepts for blacklist")

        # Uncomment to see filtered concepts                    
        # if len(filtered) != 0:
            # print(f"Filtered concepts from blacklist tags: {filtered}")

        result = (whitelist, filtered)
        
        # Cache the result
        if do_cache:
            try:
                Blacklist._filter_cache.put(concepts_tuple, result)
            except Exception as e:
                raise Exception(f"Error caching blacklist result: {e}", e)
        
        return result

    @staticmethod
    def is_empty():
        return len(Blacklist.TAG_BLACKLIST) == 0

    @staticmethod
    def is_model_empty():
        return len(Blacklist.MODEL_BLACKLIST) == 0

    @staticmethod
    def add_item(item: BlacklistItem):
        Blacklist.TAG_BLACKLIST.append(item)
        Blacklist.sort()
        try:
            Blacklist._filter_cache.clear()
            Blacklist._filter_cache.save()
        except Exception as e:
            raise Exception(f"Error clearing/saving blacklist cache: {e}", e)

    @staticmethod
    def remove_item(item: BlacklistItem, do_save=True):
        """Remove a BlacklistItem from the blacklist."""
        try:
            Blacklist.TAG_BLACKLIST.remove(item)
            try:
                Blacklist._filter_cache.clear()
                if do_save:
                    Blacklist._filter_cache.save()
            except Exception as e:
                raise Exception(f"Error clearing/saving blacklist cache: {e}", e)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_items():
        return Blacklist.TAG_BLACKLIST

    @staticmethod
    def clear():
        Blacklist.TAG_BLACKLIST.clear()
        try:
            Blacklist._filter_cache.clear()
            Blacklist._filter_cache.save()
        except Exception as e:
            raise Exception(f"Error clearing/saving blacklist cache: {e}", e)

    @staticmethod
    def sort():
        Blacklist.TAG_BLACKLIST.sort(key=lambda x: x.string.lower())

    @staticmethod
    def set_blacklist(blacklist, clear_cache=False):
        """Set the blacklist to a list of BlacklistItem objects.
        
        Args:
            blacklist: List of BlacklistItem objects to set
            clear_cache: Whether to clear and save the cache (default: False)
        """
        validated_blacklist = []
        
        # Convert each item to a BlacklistItem
        for item in blacklist:
            if isinstance(item, dict):
                blacklist_item = BlacklistItem.from_dict(item)
                if blacklist_item:
                    validated_blacklist.append(blacklist_item)
            elif isinstance(item, str):
                validated_blacklist.append(BlacklistItem(item))
            elif isinstance(item, BlacklistItem):
                validated_blacklist.append(item)
            else:
                print(f"Invalid blacklist item type: {type(item)}")
        
        Blacklist.TAG_BLACKLIST = validated_blacklist
        try:
            if clear_cache:
                Blacklist._filter_cache.clear()
            Blacklist._filter_cache.save()
        except Exception as e:
            raise Exception(f"Error clearing/saving blacklist cache: {e}", e)
    
    @staticmethod
    def add_to_blacklist(tag, enabled: bool = True, use_regex: bool = False):
        """Add a tag to the blacklist. If tag is a string, convert to BlacklistItem.
        
        Args:
            tag: The tag string or BlacklistItem to add
            enabled: Whether the item should be enabled (default: True)
            use_regex: Whether to use regex matching (default: False)
        """
        if isinstance(tag, str):
            tag = BlacklistItem(tag, enabled=enabled, use_regex=use_regex)
        Blacklist.add_item(tag)

    @staticmethod
    def filter_concepts(concepts, filtered_dict=None, do_cache=True, user_prompt=True) -> tuple[list[str], dict[str, str]]:
        """Filter a list of concepts against the blacklist.
        
        Args:
            concepts: List of concepts to filter
            filtered_dict: Optional dict to store filtered items. If None, a new dict is created.
            do_cache: Whether to use caching for filtering
            user_prompt: Whether this is a user-provided prompt (True) or internal prompt (False)
            
        Returns:
            tuple: (whitelist, filtered_dict) where:
                - whitelist is a list of concepts that passed the blacklist check
                - filtered_dict maps filtered concepts to their blacklist items
        """
        # Use the LRU cache for filtering
        concepts_tuple = tuple(concepts)
        whitelist, filtered = Blacklist._filter_concepts_cached(concepts_tuple, do_cache, user_prompt)
        # If a filtered_dict is provided, update it
        if filtered_dict is not None:
            filtered_dict.update(filtered)
        return whitelist, filtered

    @staticmethod
    def find_blacklisted_items(text: str) -> dict:
        """Find any blacklisted items in the given text.
        
        Args:
            text: The text to check for blacklisted items
            
        Returns:
            dict: A dictionary mapping found blacklisted tags to their blacklist items.
                 Empty if no blacklisted items are found.
        """
        filtered = {}
        user_tags = text.split(',')
        
        for tag in user_tags:
            # Clean the tag by removing parentheses and extra whitespace
            tag = tag.strip()
            if not tag:
                continue
                
            # Remove outer parentheses if they exist
            while tag.startswith('(') or tag.startswith('['):
                tag = tag[1:].strip()
            while tag.endswith(')') or tag.endswith(']'):
                tag = tag[:-1].strip()
                
            for blacklist_item in Blacklist.TAG_BLACKLIST:
                if not blacklist_item.enabled:
                    continue
                if blacklist_item.matches_tag(tag):
                    filtered[tag] = blacklist_item.string
                    break
                    
        return filtered

    @staticmethod
    def get_violation_item(string: str) -> BlacklistItem:
        """Check if a single string violates any blacklist items.
        
        Args:
            string: The string to check against the blacklist
            
        Returns:
            BlacklistItem: The first blacklist item that matches the string, or None if no violations
        """
        for blacklist_item in Blacklist.TAG_BLACKLIST:
            if blacklist_item.enabled and blacklist_item.matches_tag(string):
                return blacklist_item
        return None

    @staticmethod
    def import_blacklist_csv(filename):
        """Import blacklist from a CSV file.
        
        Expected format:
        string
        tag1
        tag2
        
        Or with optional enabled state:
        string,enabled
        tag1,true
        tag2,false
        """
        with open(filename, 'r', encoding='utf-8') as f:
            # Read first line to determine format
            first_line = f.readline().strip()
            f.seek(0)  # Reset file pointer to start
            
            if ',' in first_line:
                # Two-column format with headers
                reader = csv.DictReader(f)
                for row in reader:
                    enabled = True
                    if 'enabled' in row:
                        enabled_str = row['enabled'].lower()
                        enabled = enabled_str == 'true' or enabled_str == 't' or enabled_str == '1'
                    Blacklist.add_to_blacklist(BlacklistItem(row['string'].strip(), enabled))
            else:
                # Single-column format
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        Blacklist.add_to_blacklist(BlacklistItem(row[0].strip()))

    @staticmethod
    def import_blacklist_json(filename):
        """Import blacklist from a JSON file.
        
        Expected format:
        ["tag1", "tag2", "tag3"]
        
        Or with optional enabled state:
        [
            {"string": "tag1", "enabled": true},
            {"string": "tag2", "enabled": false}
        ]
        """
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        Blacklist.add_to_blacklist(BlacklistItem(item))
                    elif isinstance(item, dict) and 'string' in item:
                        enabled = item.get('enabled', True)
                        Blacklist.add_to_blacklist(BlacklistItem(item['string'], enabled))
                    else:
                        print(f"Invalid item type in JSON blacklist import: {type(item)}")
            else:
                raise ValueError("Invalid JSON format for blacklist import")

    @staticmethod
    def import_blacklist_txt(filename):
        """Import blacklist from a text file.
        
        Expected format:
        tag1
        tag2
        # Comment line
        tag3
        """
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    Blacklist.add_to_blacklist(BlacklistItem(line))

    @staticmethod
    def export_blacklist_csv(filename):
        """Export blacklist to a CSV file."""
        with open(filename, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['string', 'enabled'])
            writer.writeheader()
            for item in Blacklist.TAG_BLACKLIST:
                writer.writerow(item.to_dict())

    @staticmethod
    def export_blacklist_json(filename):
        """Export blacklist to a JSON file."""
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump([item.to_dict() for item in Blacklist.TAG_BLACKLIST], f, indent=2)

    @staticmethod
    def export_blacklist_txt(filename):
        """Export blacklist to a text file."""
        with open(filename, 'w', encoding='utf-8') as f:
            for item in Blacklist.TAG_BLACKLIST:
                if item.enabled:
                    f.write(f"{item.string}\n")
                else:
                    f.write(f"# {item.string}\n")

    @staticmethod
    def set_ui_callbacks(ui_callbacks):
        """Set the UI callbacks to be used for notifications during filtering."""
        Blacklist._ui_callbacks = ui_callbacks

    @staticmethod
    def save_cache():
        """Explicitly save the cache to disk."""
        try:
            Blacklist._filter_cache.save()
        except Exception as e:
            raise Exception(f"Error saving blacklist cache: {e}", e)

    @staticmethod
    def encrypt_blacklist():
        """Encrypt the default blacklist items."""
        try:
            blacklist_dicts = [item.to_dict() for item in Blacklist.get_items()]
            blacklist_json = json.dumps(blacklist_dicts)
            encoded_data = Utils.preprocess_data_for_encryption(blacklist_json)
            symmetric_encrypt_data_to_file(encoded_data, Blacklist.DEFAULT_BLACKLIST_FILE_LOC, (Globals.APP_IDENTIFIER + "_blacklist").encode("utf-8"))
        except Exception as e:
            raise Exception(f"Error encrypting blacklist: {e}", e)

    @staticmethod
    def decrypt_blacklist():
        """Decrypt the default blacklist items."""
        try:
            encoded_data = symmetric_decrypt_data_from_file(Blacklist.DEFAULT_BLACKLIST_FILE_LOC, (Globals.APP_IDENTIFIER + "_blacklist").encode("utf-8"))
            blacklist_json = Utils.postprocess_data_from_decryption(encoded_data)
            blacklist_dicts = json.loads(blacklist_json)
            Blacklist.set_blacklist([BlacklistItem.from_dict(item) for item in blacklist_dicts])
        except Exception as e:
            raise Exception(f"Error decrypting blacklist: {e}", e)

    @staticmethod
    def clear_cache_file():
        """Clear the cache file and reload the cache."""
        try:
            if os.path.exists(BLACKLIST_CACHE_FILE):
                os.remove(BLACKLIST_CACHE_FILE)
            Blacklist._filter_cache = SizeAwarePicklableCache.load_or_create(
                BLACKLIST_CACHE_FILE, maxsize=Blacklist.CACHE_MAXSIZE,
                max_large_items=Blacklist.CACHE_MAX_LARGE_ITEMS, large_threshold=Blacklist.CACHE_LARGE_THRESHOLD)
        except Exception as e:
            print(f"Error clearing cache file: {e}")
            # Fallback to creating a new cache
            Blacklist._filter_cache = SizeAwarePicklableCache.load_or_create(
                BLACKLIST_CACHE_FILE, maxsize=Blacklist.CACHE_MAXSIZE,
                max_large_items=Blacklist.CACHE_MAX_LARGE_ITEMS, large_threshold=Blacklist.CACHE_LARGE_THRESHOLD)

    @staticmethod
    def add_model_item(item: ModelBlacklistItem):
        if not isinstance(item, ModelBlacklistItem):
            # Convert if needed
            item = ModelBlacklistItem(item.string, item.enabled, item.use_regex)
        Blacklist.MODEL_BLACKLIST.append(item)
        Blacklist.sort_model_blacklist()

    @staticmethod
    def add_to_model_blacklist(tag, enabled: bool = True, use_regex: bool = False):
        if isinstance(tag, str):
            tag = ModelBlacklistItem(tag, enabled=enabled, use_regex=use_regex)
        elif not isinstance(tag, ModelBlacklistItem):
            tag = ModelBlacklistItem(tag.string, tag.enabled, tag.use_regex)
        Blacklist.add_model_item(tag)

    @staticmethod
    def remove_model_item(item: ModelBlacklistItem):
        try:
            Blacklist.MODEL_BLACKLIST.remove(item)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_model_items():
        return Blacklist.MODEL_BLACKLIST

    @staticmethod
    def clear_model_blacklist():
        Blacklist.MODEL_BLACKLIST.clear()

    @staticmethod
    def sort_model_blacklist():
        Blacklist.MODEL_BLACKLIST.sort(key=lambda x: x.string.lower())

    @staticmethod
    def set_model_blacklist(blacklist):
        # Accepts a list of ModelBlacklistItem or dicts
        items = []
        for item in blacklist:
            if isinstance(item, ModelBlacklistItem):
                items.append(item)
            elif isinstance(item, dict):
                mb = ModelBlacklistItem.from_dict(item)
                if mb:
                    items.append(mb)
        Blacklist.MODEL_BLACKLIST = items

    @staticmethod
    def get_model_blacklist_violations(model_id):
        violations = []
        for item in Blacklist.MODEL_BLACKLIST:
            if item.enabled and item.matches_tag(model_id):
                return True
        return False

    @staticmethod
    def import_model_blacklist_csv(filename):
        """Import model blacklist from a CSV file.
        
        Expected format:
        string
        tag1
        tag2
        
        Or with optional enabled state:
        string,enabled
        tag1,true
        tag2,false
        """
        with open(filename, 'r', encoding='utf-8') as f:
            # Read first line to determine format
            first_line = f.readline().strip()
            f.seek(0)  # Reset file pointer to start
            
            if ',' in first_line:
                # Two-column format with headers
                reader = csv.DictReader(f)
                for row in reader:
                    enabled = True
                    if 'enabled' in row:
                        enabled_str = row['enabled'].lower()
                        enabled = enabled_str == 'true' or enabled_str == 't' or enabled_str == '1'
                    Blacklist.add_to_model_blacklist(ModelBlacklistItem(row['string'].strip(), enabled))
            else:
                # Single-column format
                reader = csv.reader(f)
                for row in reader:
                    if row and row[0].strip():
                        Blacklist.add_to_model_blacklist(ModelBlacklistItem(row[0].strip()))

    @staticmethod
    def import_model_blacklist_json(filename):
        """Import model blacklist from a JSON file.
        
        Expected format:
        ["tag1", "tag2", "tag3"]
        
        Or with optional enabled state:
        [
            {"string": "tag1", "enabled": true},
            {"string": "tag2", "enabled": false}
        ]
        """
        with open(filename, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, str):
                        Blacklist.add_to_model_blacklist(item)
                    elif isinstance(item, dict) and 'string' in item:
                        enabled = item.get('enabled', True)
                        Blacklist.add_to_model_blacklist(ModelBlacklistItem(item['string'], enabled=enabled))
                    else:
                        print(f"Invalid item type in JSON model blacklist import: {type(item)}")
            else:
                raise ValueError("Invalid JSON format for model blacklist import")

    @staticmethod
    def import_model_blacklist_txt(filename):
        """Import model blacklist from a text file.
        
        Expected format:
        tag1
        tag2
        # Comment line
        tag3
        """
        with open(filename, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    Blacklist.add_to_model_blacklist(ModelBlacklistItem(line))

    @staticmethod
    def export_model_blacklist_json(filename):
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump([item.to_dict() for item in Blacklist.MODEL_BLACKLIST], f, indent=2)

