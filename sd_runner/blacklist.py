import csv
import json
import re

class BlacklistItem:
    def __init__(self, string: str, enabled: bool = True, use_regex: bool = False):
        self.string = string.lower()
        self.string_plural = (self.string + 's').lower()
        self.string_plural_es = (self.string + 'es').lower()
        self.enabled = enabled
        # Store pre-compiled regex pattern if using regex, otherwise None
        self.regex_pattern = re.compile(self._glob_to_regex(self.string)) if use_regex else None

    def to_dict(self):
        return {
            "string": self.string,
            "enabled": self.enabled,
            "use_regex": self.regex_pattern is not None
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
        return cls(data["string"], enabled, use_regex)

    def matches_tag(self, tag: str) -> bool:
        """Check if a tag matches this blacklist item.
        
        Args:
            tag: The tag to check against this blacklist item
            
        Returns:
            bool: True if the tag matches this blacklist item, False otherwise
        """
        tag = tag.lower()
        blacklist_str = self.string.lower()
        
        # If regex pattern is available, use regex matching
        if self.regex_pattern is not None:
            return bool(self.regex_pattern.search(tag))
        
        # Original exact match behavior for non-regex patterns
        if tag.startswith(blacklist_str) or re.search(r'(^|\W)' + re.escape(blacklist_str), tag):
            return True
        if tag.startswith(self.string_plural) or re.search(r'(^|\W)' + re.escape(self.string_plural), tag):
            return True
        if tag.startswith(self.string_plural_es) or re.search(r'(^|\W)' + re.escape(self.string_plural_es), tag):
            return True
                
        return False

    def _glob_to_regex(self, pattern: str) -> str:
        """Convert a glob pattern to a regex pattern with word start boundary matching.
        
        Args:
            pattern: The glob pattern to convert
            
        Returns:
            str: The regex pattern with word start boundary matching
        """
        # Escape regex special characters except *
        regex_pattern = re.escape(pattern)
        
        # Replace escaped asterisks with .* for wildcard matching
        regex_pattern = regex_pattern.replace(r'\*', '.*')
        
        # Add word boundary matching: (^|\W) at start only.
        # This ensures the pattern matches at the start of a word.
        # If the user wants to add boundary matching to the end,
        # they can do this by adding (\W|$) to the end of the pattern.
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

    @staticmethod
    def is_empty():
        return len(Blacklist.TAG_BLACKLIST) == 0

    @staticmethod
    def add_item(item: BlacklistItem):
        Blacklist.TAG_BLACKLIST.append(item)

    @staticmethod
    def remove_item(item: BlacklistItem):
        """Remove a BlacklistItem from the blacklist."""
        try:
            Blacklist.TAG_BLACKLIST.remove(item)
            return True
        except ValueError:
            return False

    @staticmethod
    def get_items():
        return Blacklist.TAG_BLACKLIST

    @staticmethod
    def clear():
        Blacklist.TAG_BLACKLIST.clear()

    @staticmethod
    def set_blacklist(blacklist):
        """Set the blacklist to a list of BlacklistItem objects."""
        Blacklist.TAG_BLACKLIST = list(blacklist)
    
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
        Blacklist.TAG_BLACKLIST.append(tag)
        Blacklist.TAG_BLACKLIST.sort(key=lambda x: x.string)

    @staticmethod
    def filter_concepts(concepts, filtered_dict=None) -> tuple[list[str], dict[str, str]]:
        """Filter a list of concepts against the blacklist.
        
        Args:
            concepts: List of concepts to filter
            filtered_dict: Optional dict to store filtered items. If None, a new dict is created.
            
        Returns:
            tuple: (whitelist, filtered_dict) where:
                - whitelist is a list of concepts that passed the blacklist check
                - filtered_dict maps filtered concepts to their blacklist items
        """
        whitelist = []
        filtered = {} if filtered_dict is None else filtered_dict
        
        for concept_cased in concepts:
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

        # Uncomment to see filtered concepts                    
        # if len(filtered) != 0:
            # print(f"Filtered concepts from blacklist tags: {filtered}")

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

