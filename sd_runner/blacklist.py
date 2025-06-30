import csv
import json
import os
import re

from utils.pickleable_cache import SizeAwarePicklableCache
from utils.translations import I18N

_ = I18N._

# Define cache file path
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "configs")
BLACKLIST_CACHE_FILE = os.path.join(CACHE_DIR, "blacklist_filter_cache.pkl")


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
    

class Blacklist:
    TAG_BLACKLIST: list[BlacklistItem] = []
    CACHE_MAXSIZE = 64
    CACHE_LARGE_THRESHOLD = 1024 * 1024 * 8
    CACHE_MAX_LARGE_ITEMS = 4
    _ui_callbacks = None  # Static variable to store UI callbacks
    _filter_cache = SizeAwarePicklableCache.load_or_create(
        BLACKLIST_CACHE_FILE, maxsize=CACHE_MAXSIZE,
        max_large_items=CACHE_MAX_LARGE_ITEMS, large_threshold=CACHE_LARGE_THRESHOLD)

    @staticmethod
    def _filter_concepts_cached(concepts_tuple, do_cache=True):
        # Check cache first - use just the concepts tuple as key (no version needed)
        cached_result = Blacklist._filter_cache.get(concepts_tuple)
        if cached_result is not None:
            return cached_result
        
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
        concepts = list(concepts_tuple)
        whitelist = []
        filtered = {}
        
        # Call progress update at the beginning (0)
        do_update_progress(0)
        
        print(f"Filtering concepts for blacklist: {concepts_count}")
        for i, concept_cased in enumerate(concepts):
            match_found = False
            for blacklist_item in Blacklist.TAG_BLACKLIST:
                if not blacklist_item.enabled:
                    continue
                if blacklist_item.matches_tag(concept_cased):
                    filtered[concept_cased] = blacklist_item.string
                    match_found = True
                    break
            if not match_found:
                whitelist.append(concept_cased)
            
            # Call progress update every 5000 concepts
            if (i + 1) % 5000 == 0:
                do_update_progress(i + 1)
        
        # Call progress update at the end
        do_update_progress(concepts_count)
        print(f"Filtered {len(filtered)} concepts for blacklist")

        # Uncomment to see filtered concepts                    
        # if len(filtered) != 0:
            # print(f"Filtered concepts from blacklist tags: {filtered}")

        result = (whitelist, filtered)
        
        # Cache the result
        if do_cache:
            Blacklist._filter_cache.put(concepts_tuple, result)
        
        return result

    @staticmethod
    def is_empty():
        return len(Blacklist.TAG_BLACKLIST) == 0

    @staticmethod
    def add_item(item: BlacklistItem):
        Blacklist.TAG_BLACKLIST.append(item)
        Blacklist.sort()
        Blacklist._filter_cache.clear()
        Blacklist._filter_cache.save()

    @staticmethod
    def remove_item(item: BlacklistItem, do_save=True):
        """Remove a BlacklistItem from the blacklist."""
        try:
            Blacklist.TAG_BLACKLIST.remove(item)
            Blacklist._filter_cache.clear()
            if do_save:
                Blacklist._filter_cache.save()
            return True
        except ValueError:
            return False

    @staticmethod
    def get_items():
        return Blacklist.TAG_BLACKLIST

    @staticmethod
    def clear():
        Blacklist.TAG_BLACKLIST.clear()
        Blacklist._filter_cache.clear()
        Blacklist._filter_cache.save()

    @staticmethod
    def set_blacklist(blacklist, clear_cache=False):
        """Set the blacklist to a list of BlacklistItem objects.
        
        Args:
            blacklist: List of BlacklistItem objects to set
            clear_cache: Whether to clear and save the cache (default: False)
        """
        Blacklist.TAG_BLACKLIST = list(blacklist)
        if clear_cache:
            Blacklist._filter_cache.clear()
        Blacklist._filter_cache.save()
    
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
    def sort():
        Blacklist.TAG_BLACKLIST.sort(key=lambda x: x.string)

    @staticmethod
    def filter_concepts(concepts, filtered_dict=None, do_cache=True) -> tuple[list[str], dict[str, str]]:
        """Filter a list of concepts against the blacklist.
        
        Args:
            concepts: List of concepts to filter
            filtered_dict: Optional dict to store filtered items. If None, a new dict is created.
            
        Returns:
            tuple: (whitelist, filtered_dict) where:
                - whitelist is a list of concepts that passed the blacklist check
                - filtered_dict maps filtered concepts to their blacklist items
        """
        # Use the LRU cache for filtering
        concepts_tuple = tuple(concepts)
        whitelist, filtered = Blacklist._filter_concepts_cached(concepts_tuple, do_cache)
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
        Blacklist._filter_cache.save()

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

