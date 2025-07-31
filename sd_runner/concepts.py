import os
from pathlib import Path
import random
import re
from typing import Dict, Set

from sd_runner.blacklist import Blacklist, BlacklistItem
from utils.config import config
from utils.globals import PromptMode

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))


def weighted_sample_without_replacement(population: list[str], weights: list[float], k: int = 1) -> list[str]:
    weights = list(weights)
    positions = range(len(population))
    indices = []
    while True:
        needed = k - len(indices)
        if needed == 0:
            break
        for i in random.choices(positions, weights, k=needed):
            if weights[i]:
                weights[i] = 0.0
                indices.append(i)
    return [population[i] for i in indices]


def sample(l: list[str] | dict[str, float], low: int, high: int) -> list[str]:
    if high > len(l):
        high = len(l) - 1
    k = high if low > high else random.randint(low, high)
    if isinstance(l, dict):
        return weighted_sample_without_replacement(list(l.keys()), l.values(), k)
    elif isinstance(l, list):
        return random.sample(l, k)
    raise Exception(f"{type(l)} is not a valid sample population type")


class ConceptsFile:
    def __init__(self, filename: str):
        self.filename = filename
        self.is_dictionary = filename == Concepts.ALL_WORDS_LIST_FILENAME
        self.lines = []  # Original lines with comments
        self.concepts = []  # Just the concept strings
        self.concept_indices = {}  # Map of concept -> line index
        self.load()

    def load(self) -> None:
        """Load the file while preserving structure and comments"""
        if os.path.isfile(self.filename):
            filepath = str(self.filename)
        else:
            filepath = os.path.join(Concepts.CONCEPTS_DIR, self.filename)
            
        try:
            with open(filepath, encoding="utf-8") as f:
                self.lines = f.readlines()
                
            # Process lines and build concept list
            self.concepts = []
            self.concept_indices = {}
            for i, line in enumerate(self.lines):
                val = ""
                for c in line:
                    if c == "#":
                        break
                    val += c
                val = val.strip()
                if len(val) > 0:
                    self.concepts.append(val)
                    self.concept_indices[val] = i
        except Exception as e:
            print(f"Failed to load concepts file: {filepath}")
            print(f"Error: {str(e)}")
            self.lines = []
            self.concepts = []
            self.concept_indices = {}

    def save(self) -> None:
        """Save the file while preserving structure and comments"""
        if os.path.isfile(self.filename):
            filepath = str(self.filename)
        else:
            filepath = os.path.join(Concepts.CONCEPTS_DIR, self.filename)
            
        try:
            with open(filepath, 'w', encoding="utf-8") as f:
                f.writelines(self.lines)
        except Exception as e:
            print(f"Failed to save concepts file: {filepath}")
            print(f"Error: {str(e)}")

    def add_concept(self, concept: str) -> bool:
        """Add a new concept to the file, maintaining alphabetical order when possible.
        
        The method will:
        1. Try to find the correct alphabetical position
        2. Allow for 4-5 consecutive out-of-order concepts before giving up
        3. If no suitable position is found, append to the end
        """
        print(f"\nAdding concept: {concept}")
        print(f"Number of lines: {len(self.lines)}")
        
        if concept in self.concepts:
            print("Concept already exists, returning False")
            return False
            
        # Find the first concept line to start our ordering from
        first_concept_idx = 0
        while first_concept_idx < len(self.lines):
            line = self.lines[first_concept_idx].strip()
            if not self.is_dictionary:
                print(f"Checking line {first_concept_idx}: '{line}'")
            # Only break if we find an actual concept (non-empty, non-comment line)
            if line and not line.startswith('#'):
                # Found a concept line
                print(f"Found first concept at index {first_concept_idx}: '{line}'")
                break
            first_concept_idx += 1

        if first_concept_idx >= len(self.lines):
            # No concepts found, append to end
            print("No concepts found, appending to end")
            self.lines.append(f"{concept}\n")
            self.concepts.append(concept)
            self.concept_indices[concept] = len(self.lines) - 1
            return True

        # Start from the first concept and look for insertion point
        current_idx = first_concept_idx
        consecutive_out_of_order = 0
        max_consecutive_out_of_order = 5  # Increased from 3 to 5

        if not self.is_dictionary:
            print(f"\nLooking for insertion point starting from index {current_idx}")
        while current_idx < len(self.lines):
            line = self.lines[current_idx].strip()
            if not self.is_dictionary:
                print(f"Checking line {current_idx}: '{line}'")
            
            # Skip comments and empty lines
            if not line or line.startswith('#'):
                if not self.is_dictionary:
                    print("Skipping comment/empty line")
                current_idx += 1
                continue
                
            # Compare with current concept
            if not self.is_dictionary:
                print(f"Comparing '{concept.lower()}' with '{line.lower()}'")
            if concept.lower() < line.lower():
                # Found insertion point
                print(f"Found insertion point at index {current_idx} (before line \"{line}\")")
                self.lines.insert(current_idx, f"{concept}\n")
                self.concepts.append(concept)
                self.concept_indices[concept] = current_idx
                
                # Update indices for concepts after insertion
                for c, i in self.concept_indices.items():
                    if i >= current_idx:
                        self.concept_indices[c] = i + 1
                return True
                
            # Check if we're out of order
            if current_idx > first_concept_idx:
                prev_line = self.lines[current_idx - 1].strip()
                if prev_line and not prev_line.startswith('#') and line.lower() < prev_line.lower():
                    consecutive_out_of_order += 1
                    print(f"Found consecutive out-of-order entry. Count: {consecutive_out_of_order}")
                    if consecutive_out_of_order >= max_consecutive_out_of_order:
                        # Too many consecutive out-of-order entries, append to end
                        print("Too many consecutive out-of-order entries, breaking")
                        break
                else:
                    # Reset counter if we find an in-order entry
                    consecutive_out_of_order = 0
                        
            current_idx += 1
            
        # If we get here, either we hit the end or found too many out-of-order entries
        # Find the last non-empty line to append after
        last_idx = len(self.lines) - 1
        while last_idx >= 0 and not self.lines[last_idx].strip():
            last_idx -= 1
            
        print(f"\nAppending concept after index {last_idx}")
        # Add new concept after the last non-empty line
        self.lines.insert(last_idx + 1, f"{concept}\n")
        self.concepts.append(concept)
        self.concept_indices[concept] = last_idx + 1
        return True

    def remove_concept(self, concept: str) -> bool:
        """Remove a concept from the file"""
        if concept not in self.concepts:
            return False
            
        idx = self.concept_indices[concept]
        del self.lines[idx]
        self.concepts.remove(concept)
        del self.concept_indices[concept]
        
        # Update indices for concepts after the removed one
        for c, i in self.concept_indices.items():
            if i > idx:
                self.concept_indices[c] = i - 1
        return True

    def get_concepts(self) -> list[str]:
        """Get the list of concepts"""
        return self.concepts.copy()


class Concepts:
    ALL_WORDS_LIST_FILENAME = "dictionary.txt"
    ALL_WORDS_LIST = []
    TAG_BLACKLIST = []
    ALPHABET = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m",
                "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"]
    CONCEPTS_DIR = os.path.join(BASE_DIR, "concepts") if config.default_concepts_dir == "concepts" else config.concepts_dir
    URBAN_DICTIONARY_CORPUS_PATH = os.path.join(BASE_DIR, "concepts", "temp", "urban_dictionary_additions.txt")
    URBAN_DICTIONARY_CORPUS = []

    @staticmethod
    def set_concepts_dir(path: str = "concepts") -> bool:
        old_path = Concepts.CONCEPTS_DIR
        if path == "concepts":
            Concepts.CONCEPTS_DIR = os.path.join(BASE_DIR, "concepts")
        elif not os.path.isdir(path):
            raise Exception(f"{path} is not a valid concepts directory")
        else:
            Concepts.CONCEPTS_DIR = path
        return old_path != Concepts.CONCEPTS_DIR

    @staticmethod
    def sample_whitelisted(concepts: list[str], low: int, high: int) -> list[str]:
        """Sample concepts while filtering out blacklisted items.
        
        Args:
            concepts: List or dict of concepts to sample from
            low: Minimum number of items to sample
            high: Maximum number of items to sample
            
        Returns:
            list[str]: Sampled concepts that passed the blacklist check
            
        Raises:
            Exception: If there are not enough non-blacklisted items to satisfy the range
        """
        if low == 0 and high == 0:
            return []
        if len(concepts) == 0:
            if low > 0:
                raise Exception("No concepts to sample")
            return []
        if Blacklist.is_empty():
            return sample(concepts, low, high)
            
        whitelist, filtered = Blacklist.filter_concepts(concepts, user_prompt=False)
        
        # Check if we have enough items after filtering
        if len(whitelist) < low:
            print(f"Warning: Not enough non-blacklisted items to satisfy range {low}-{high}. "
                  f"Got {len(whitelist)} items after filtering out {len(filtered)} blacklisted items.")
            if len(whitelist) == 0:
                raise Exception(f"No non-blacklisted items available. Filtered out {len(filtered)} blacklisted items.")
            # Adjust the range to what we can actually provide
            high = min(high, len(whitelist))
            low = min(low, high)
            
        return sample(whitelist, low, high)

    def __init__(self,
        prompt_mode: PromptMode,
        get_specific_locations: bool,
        concepts_dir: str = "concepts"
    ):
        if Concepts.set_concepts_dir(concepts_dir):
            Concepts.ALL_WORDS_LIST = Concepts.load(Concepts.ALL_WORDS_LIST_FILENAME)
            print(f"Reset all words list. Length: {len(Concepts.ALL_WORDS_LIST)}")
            if config.override_dictionary_path is not config.override_dictionary_path.strip() != "":
                if config.override_dictionary_append:
                    Concepts.ALL_WORDS_LIST.extend(Concepts.load(config.override_dictionary_path))
                    print(f"Added override dictionary words list. Length: {len(Concepts.ALL_WORDS_LIST)}")
                else:
                    Concepts.ALL_WORDS_LIST = Concepts.load(config.override_dictionary_path)
                    print(f"Overwrote dictionary words list. Length: {len(Concepts.ALL_WORDS_LIST)}")
        self.prompt_mode = prompt_mode
        self.get_specific_locations = get_specific_locations
        # Randomly select concepts from the lists

    def extend(self, l: list[str], nsfw_file: str, nsfw_repeats: int, nsfl_file: str, nsfl_repeats: int) -> None:
        nsfw = Concepts.load(nsfw_file)
        if self.prompt_mode == PromptMode.NSFL:
            nsfl = Concepts.load(nsfl_file)
            for i in range(nsfl_repeats):
                nsfw.extend(nsfl)
        for i in range(nsfw_repeats):
            l.extend(nsfw)

    def _adjust_range(self, low: int, high: int, multiplier: float = 1.0) -> tuple[int, int]:
        if multiplier == 0:
            return 0, 0
        if multiplier == 1:
            return low, high
        
        # Calculate the range size
        range_size = high - low
        # Scale the range size by the multiplier
        scaled_range = max(0, int(range_size * multiplier))
        # Calculate new low and high values
        new_low = max(0, int(low * multiplier))
        new_high = new_low + scaled_range
        
        # Ensure we don't return 0 if the original range was non-zero
        if new_low == 0 and low != 0:
            new_low = 1
        if new_high == 0 and high != 0:
            new_high = 1
            
        return new_low, new_high

    def get_concepts(self, low: int = 1, high: int = 3, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        concepts = Concepts.load(SFW.concepts)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        return Concepts.sample_whitelisted(concepts, low, high)

    def get_positions(self, low: int = 0, high: int = 2, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        positions = Concepts.load(SFW.positions)
        # if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
        #     self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        if len(positions) > 1 and random.random() > 0.4:
            del positions[1]
        return Concepts.sample_whitelisted(positions, low, high)

    def get_humans(self, low: int = 1, high: int = 1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        return Concepts.sample_whitelisted(Concepts.load(SFW.humans), low, high)

    def get_animals(self, low: int = 0, high: int = 2, inclusion_chance: float = 0.1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        if random.random() > inclusion_chance:
            return []
        return Concepts.sample_whitelisted(Concepts.load(SFW.animals), low, high)

    def get_locations(self, low: int = 0, high: int = 2, specific_inclusion_chance: float = 0.3, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        locations = Concepts.load(SFW.locations)
        if self.get_specific_locations:
            nonspecific_locations_chance = 1 - specific_inclusion_chance
            locations = {l: nonspecific_locations_chance for l in locations}
            for l in Concepts.load(SFW.locations_specific):
                locations[l] = specific_inclusion_chance
        return Concepts.sample_whitelisted(locations, low, high)

    def get_colors(self, low: int = 0, high: int = 3, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        colors = Concepts.sample_whitelisted(Concepts.load(SFW.colors), low, high)
        if "rainbow" in colors and random.random() > 0.5:
            colors.remove("rainbow")
        return colors

    def get_times(self, low: int = 0, high: int = 1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        return Concepts.sample_whitelisted(Concepts.load(SFW.times), low, high)

    def get_dress(self, low: int = 0, high: int = 2, inclusion_chance: float = 0.5, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        if random.random() > inclusion_chance:
            return []
        dress = Concepts.load(SFW.dress)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(dress, NSFW.dress, 3, NSFL.dress, 1)
        return Concepts.sample_whitelisted(dress, low, high)

    def get_expressions(self, low: int = 1, high: int = 1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        expressions = Concepts.load(SFW.expressions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(expressions, NSFW.expressions, 6, NSFL.expressions, 3)
        return Concepts.sample_whitelisted(expressions, low, high)

    def get_actions(self, low: int = 0, high: int = 2, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        actions = Concepts.load(SFW.actions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(actions, NSFW.actions, 8, NSFL.actions, 3)
        return Concepts.sample_whitelisted(actions, low, high)

    def get_descriptions(self, low: int = 0, high: int = 1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        descriptions = Concepts.load(SFW.descriptions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(descriptions, NSFW.descriptions, 3, NSFL.descriptions, 2)
        return Concepts.sample_whitelisted(descriptions, low, high)

    def get_characters(self, low: int = 0, high: int = 1, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        characters = Concepts.load(SFW.characters)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(characters, NSFW.characters, 3, NSFL.characters, 2)
        return Concepts.sample_whitelisted(characters, low, high)

    def get_random_words(self, low: int = 0, high: int = 9, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        if len(Concepts.ALL_WORDS_LIST) == 0:
            print("For some reason, all words list was empty.")
            Concepts.ALL_WORDS_LIST = Concepts.load(Concepts.ALL_WORDS_LIST_FILENAME)
            if config.override_dictionary_path is not None and config.override_dictionary_path.strip() != "":
                if config.override_dictionary_append:
                    Concepts.ALL_WORDS_LIST.extend(Concepts.load(config.override_dictionary_path))
                    print(f"Added override dictionary words list. Length: {len(Concepts.ALL_WORDS_LIST)}")
                else:
                    Concepts.ALL_WORDS_LIST = Concepts.load(config.override_dictionary_path)
                    print(f"Overwrote dictionary words list. Length: {len(Concepts.ALL_WORDS_LIST)}")
        
        # Get initial whitelisted words and load extra words as needed
        all_words = Concepts.ALL_WORDS_LIST.copy()
        if len(Concepts.URBAN_DICTIONARY_CORPUS) == 0 and self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            try:
                Concepts.URBAN_DICTIONARY_CORPUS = Concepts.load(Concepts.URBAN_DICTIONARY_CORPUS_PATH)
            except Exception as e:
                pass
        if len(Concepts.URBAN_DICTIONARY_CORPUS) > 0:
            all_words.extend(Concepts.URBAN_DICTIONARY_CORPUS)
            # random_urban_dictionary_words = Concepts.sample_whitelisted(Concepts.URBAN_DICTIONARY_CORPUS, low, high)
            # random_words.extend(random_urban_dictionary_words)
        random_words = Concepts.sample_whitelisted(all_words, low, high)
        
        # Generate combinations and filter out blacklisted combinations
        random_word_strings = []
        blacklisted_combination_counts = {}
        def is_blacklisted(combination, combination_counts, current_count):
            if current_count > 1:
                return False
            if Blacklist.get_violation_item(combination) is None:
                # Only combinations need to be tested, because the sample 
                # is already composed of whitelisted words
                return False
            combination_counts[combination] = current_count
            return True
        def combine_words(words, combination_counts, chance_to_combine=0.25):
            current_count = 0
            word_string = ""
            for word in words:
                if random.random() < chance_to_combine:
                    if word_string != "":
                        combination = word_string.strip()
                        if not is_blacklisted(combination, combination_counts, current_count):
                            random_word_strings.append(combination)
                    word_string = ""
                    current_count = 0
                word_string += word + " "
                current_count += 1
            if word_string != "" and not word_string.strip() in random_word_strings:
                combination = word_string.strip()
                if not is_blacklisted(combination, combination_counts, current_count):
                    random_word_strings.append(combination)

        combine_words(random_words, blacklisted_combination_counts)
        attempts = 0
        while len(blacklisted_combination_counts) > 0 and attempts < 10:
            print(f"Hit {len(blacklisted_combination_counts)} blacklist violations on attempt {attempts} to combine words")
            attempts += 1
            number_required = sum(blacklisted_combination_counts.values())
            # There may be duplication in this resampling but very unlikely for lists of tens of thousands of words
            random_words = Concepts.sample_whitelisted(all_words, number_required, number_required)
            new_chance_to_combine = 0.75 # we know these failures came from combinations, try to combine their replacements
            combine_words(random_words, blacklisted_combination_counts, new_chance_to_combine)
        return random_word_strings

    def get_nonsense(self, low: int = 0, high: int = 2, multiplier: float = 1.0) -> list[str]:
        low, high = self._adjust_range(low, high, multiplier)
        nonsense_words = [self.get_nonsense_word() for _ in range(high)]
        return Concepts.sample_whitelisted(nonsense_words, low, high)

    def is_art_style_prompt_mode(self) -> bool:
        return self.prompt_mode in (PromptMode.ANY_ART, PromptMode.PAINTERLY, PromptMode.ANIME, PromptMode.GLITCH)

    def get_art_styles(self, max_styles: int = -1, multiplier: float = 1.0) -> list[str]:
        m = {PromptMode.ANIME: (ArtStyles.anime, "anime"),
             PromptMode.GLITCH: (ArtStyles.glitch, "glitch"),
             PromptMode.PAINTERLY: (ArtStyles.painters, "painting")}
        if self.prompt_mode in m:
            art_styles = Concepts.load(m[self.prompt_mode][0])
            style_tag = m[self.prompt_mode][1]
        else:
            art_styles = []
            art_styles.extend(Concepts.load(ArtStyles.anime))
            art_styles.extend(Concepts.load(ArtStyles.glitch))
            art_styles.extend(Concepts.load(ArtStyles.painters))
            art_styles.extend(Concepts.load(ArtStyles.artists))
            style_tag = None            
        if max_styles == -1:
            max_styles = min(8, len(art_styles)) if self.prompt_mode in (PromptMode.ANY_ART, PromptMode.GLITCH) else 2
        low = 1
        high = random.randint(1, max_styles)
        low, high = self._adjust_range(low, high, multiplier=multiplier)
        out = sample(art_styles, low, high)
        append = style_tag + " art by " if style_tag else "art by "
        for i in range(len(out)):
            out[i] = append + out[i]
        return out

    def get_nonsense_word(self) -> str:
        # TODO check other language lists as well
        # TODO check other concept lists
        length = random.randint(3, 15)
        word = ''.join([random.choice(Concepts.ALPHABET) for i in range(length)])
        counter = 0
        while word in Concepts.ALL_WORDS_LIST and Blacklist.get_violation_item(word) is not None:
            if counter > 100:
                print("Failed to generate a nonsense word!")
                break
            word = ''.join([random.choice(Concepts.ALPHABET) for i in range(length)])
            counter += 1
        return word

    @staticmethod
    def load(filename: str) -> list[str]:
        # Keeping this separate from the ConceptsFile class to minimize memory
        # usage as this is called every time there's a prompt generation for every file.
        l = []
        if os.path.isfile(filename):
            filepath = str(filename)
        else:
            filepath = os.path.join(Concepts.CONCEPTS_DIR, filename)
        try:
            with open(filepath, encoding="utf-8") as f:
                for line in f:
                    val = ""
                    for c in line:
                        if c == "#":
                            break
                        val += c
                    val = val.strip()
                    if len(val) > 0:
                        l.append(val)
        except Exception:
            print("Failed to load concepts file: " + filepath)
        return l

    @staticmethod
    def save(filename: str, concepts: list[str]) -> None:
        """Save concepts to a file"""
        file = ConceptsFile(filename)
        current_concepts = set(file.get_concepts())
        new_concepts = set(concepts)
        
        # Remove concepts that are no longer present
        for concept in current_concepts - new_concepts:
            file.remove_concept(concept)
            
        # Add new concepts
        for concept in new_concepts - current_concepts:
            file.add_concept(concept)
            
        # Save the file
        file.save()

    @staticmethod
    def get_concept_files(category_states: dict[str, bool]) -> list[str]:
        """Get concept files based on category states.
        
        Args:
            category_states: Dictionary mapping category names to their enabled state
            
        Returns:
            List of concept file paths
        """
        files = []
        
        # Add files from each category based on enabled state
        if category_states.get("SFW", True):
            for attr_name in dir(SFW):
                if not attr_name.startswith('_'):
                    attr_value = getattr(SFW, attr_name)
                    if isinstance(attr_value, str) and attr_value.endswith('.txt'):
                        files.append(attr_value)
                        
        if category_states.get("NSFW", False):
            for attr_name in dir(NSFW):
                if not attr_name.startswith('_'):
                    attr_value = getattr(NSFW, attr_name)
                    if isinstance(attr_value, str) and attr_value.endswith('.txt'):
                        files.append(attr_value)
                        
        if category_states.get("NSFL", False):
            for attr_name in dir(NSFL):
                if not attr_name.startswith('_'):
                    attr_value = getattr(NSFL, attr_name)
                    if isinstance(attr_value, str) and attr_value.endswith('.txt'):
                        files.append(attr_value)
                        
        if category_states.get("Art Styles", True):
            for attr_name in dir(ArtStyles):
                if not attr_name.startswith('_'):
                    attr_value = getattr(ArtStyles, attr_name)
                    if isinstance(attr_value, str) and attr_value.endswith('.txt'):
                        files.append(attr_value)
                        
        if category_states.get("Dictionary", False):
            files.append(Concepts.ALL_WORDS_LIST_FILENAME)
            
        return sorted(files)

    @staticmethod
    def get_concepts_map(category_states: dict[str, bool] = {}) -> dict[str, set[str]]:
        """Get a map of all concept categories to their concepts.
        If category_states is provided, only include enabled categories."""
        existing_concepts = {}
        
        # Use default category states if none provided
        if len(category_states) == 0:
            category_states = {
                "SFW": True,
                "NSFW": True,
                "NSFL": True,
                "Art Styles": True,
                "Dictionary": True
            }
        
        # Get all files and load their concepts
        for filename in Concepts.get_concept_files(category_states):
            concepts = Concepts.load(filename)
            existing_concepts[filename] = set(concepts)
                    
        return existing_concepts

    @staticmethod
    def add_concept_to_category(concept: str, target_category: str) -> bool:
        """Add a concept to a category if it doesn't already exist.
        
        Args:
            concept: The concept to add
            target_category: The category file to add it to
            
        Returns:
            bool: True if the concept was added, False if it already existed
        """
        current_concepts = Concepts.load(target_category)
        if concept not in current_concepts:
            current_concepts.append(concept)
            current_concepts.sort()
            Concepts.save(target_category, current_concepts)
            return True
        return False

    @staticmethod
    def _check_concept_exists(
        concept: str,
        existing_concepts: Dict[str, Set[str]]
    ) -> list[tuple[str, str]]:
        """Check if concept exists in any category, including as part of other concepts."""
        matches = []
        concept_lower = concept.lower()
        
        # Create pattern that matches at word boundary or start of string
        pattern = re.compile(rf'(\b|^){re.escape(concept_lower)}')
        
        for category, concepts in existing_concepts.items():
            for existing in concepts:
                existing_lower = existing.lower()
                if pattern.search(existing_lower):
                    matches.append((existing, category))
                    
        return matches
    
    @staticmethod
    def import_concepts(
        import_file: str,
        target_category: str,
        category_states: dict[str, bool] = None
    ) -> tuple[list[str], list[str]]:
        """
        Import concepts from a file into a target category.
        Returns (imported_concepts, failed_concepts)
        
        Concepts can be force-imported by prefixing them with '!'
        
        Args:
            import_file: Path to file containing concepts to import
            target_category: Category to import concepts into
            category_states: Dict mapping category names to their enabled state
        """
        # Reset found concepts for this import
        found_concepts: dict[str, list[tuple[str, str]]] = {}
        
        # Read and deduplicate concepts from import file
        with open(import_file, 'r', encoding='utf-8') as f:
            concepts = set()
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    # Check for force-import prefix
                    force_import = line.startswith('!')
                    if force_import:
                        line = line[1:].strip()
                    concepts.add((force_import, line))
            
        # Get all existing concepts
        existing_concepts = Concepts.get_concepts_map(category_states)

        if not target_category in existing_concepts:
            raise Exception(f"Target category \"{target_category}\" not found in existing concepts")
        
        imported = []
        failed = []
        
        # Process each concept
        for force_import, concept in concepts:
            # First check if concept exists in target category
            if concept in existing_concepts[target_category]:
                # Concept already exists in target, consider it "imported" but don't add to list
                continue
                
            # Skip existence check for force-imported concepts
            if force_import:
                if Concepts.add_concept_to_category(concept, target_category):
                    imported.append(concept)
                continue
                
            # Check if concept exists anywhere
            matches = Concepts._check_concept_exists(concept, existing_concepts)
            
            if matches:
                # Concept exists somewhere, add to found concepts
                found_concepts[concept] = matches
                failed.append(concept)
            else:
                # Concept doesn't exist, import it
                if Concepts.add_concept_to_category(concept, target_category):
                    imported.append(concept)
        
        # Write failed imports to file if any
        if failed:
            failed_file = str(Path(import_file).with_suffix('')) + '_failed_import.txt'
            with open(failed_file, 'w', encoding='utf-8') as f:
                for concept in failed:
                    matches = found_concepts[concept]
                    match_str = " | ".join(f"{match} ({category})" for match, category in matches)
                    f.write(f"{concept} -> {match_str}\n")
        
        return imported, failed

    @staticmethod
    def get_filtered_concepts_for_preview(
        blacklist_item: BlacklistItem = None,
        category_states: dict[str, bool] = None
    ) -> list[str]:
        """Get concepts that would be filtered by blacklist items for preview purposes.
        
        Args:
            blacklist_item: Specific blacklist item to check against, or None for all items
            category_states: Dictionary mapping category names to their enabled state
            
        Returns:
            List of concepts that would be filtered out
        """
        # Use default category states if none provided
        if category_states is None:
            category_states = {
                "SFW": True,
                "NSFW": True,
                "NSFL": True,
                "Art Styles": True,
                "Dictionary": True
            }
        
        # Get all concepts from enabled categories
        all_concepts = []
        for filename in Concepts.get_concept_files(category_states):
            concepts = Concepts.load(filename)
            if concepts:
                all_concepts.extend(concepts)
        
        if blacklist_item:
            # Filter for specific blacklist item
            filtered_concepts = []
            for concept in all_concepts:
                if blacklist_item.matches_tag(concept):
                    filtered_concepts.append(concept)
            return filtered_concepts
        else:
            # Use the actual blacklist filtering logic
            whitelist, filtered = Blacklist.filter_concepts(all_concepts, user_prompt=False)
            return list(filtered.keys())


class HardConcepts:
    hard_concepts = Concepts.load("hard_concepts.txt")
    exclusionary_concepts = Concepts.load("exclusionary_concepts.txt")
    boring_concepts = Concepts.load("boring_concepts.txt")

# Below files are reloaded every time there's a prompt generation to enable quick swapping
class SFW:
    actions = "sfw_actions.txt"
    animals = "animals.txt"
    characters = "sfw_characters.txt"
    colors = "colors.txt"
    concepts = "sfw_concepts.txt"
    descriptions = "sfw_descriptions.txt"
    dress = "sfw_dress.txt"
    expressions = "sfw_expressions.txt"
    humans = "humans.txt"
    lighting = "lighting.txt"
    locations = "locations.txt"
    locations_specific = "locations_specific.txt"
    positions = "positions.txt"
    times = "times.txt"

class NSFW:
    characters = "nsfw_characters.txt"
    concepts = "nsfw_concepts.txt"
    dress = "nsfw_dress.txt"
    descriptions = "nsfw_descriptions.txt"
    expressions = "nsfw_expressions.txt"
    actions = "nsfw_actions.txt"

class NSFL:
    characters = "nsfl_characters.txt"
    concepts = "nsfl_concepts.txt"
    dress = "nsfl_dress.txt"
    descriptions = "nsfl_descriptions.txt"
    expressions = "nsfl_expressions.txt"
    actions = "nsfl_actions.txt"


class ArtStyles:
    artists = "artists.txt"
    anime = "mangakas.txt"
    painters = "painters.txt"
    glitch = "glitch.txt"

