from enum import Enum
import os
import random

from utils.config import config

BASE_DIR = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))

class PromptMode(Enum):
    FIXED = "FIXED"
    SFW = "SFW"
    NSFW = "NSFW"
    NSFL = "NSFL"
    TAKE = "TAKE"
    RANDOM = "RANDOM"
    NONSENSE = "NONSENSE"
    ANY_ART = "ANY_ART"
    PAINTERLY = "PAINTERLY"
    ANIME = "ANIME"
    GLITCH = "GLITCH"
    LIST = "LIST"
    IMPROVE = "IMPROVE"

    def __str__(self):
        return self.value

    @staticmethod
    def get(name):
        for key, value in PromptMode.__members__.items():
            if key == name:
                return value
        
        raise Exception(f"Not a valid prompt mode: {name}")

def weighted_sample_without_replacement(population, weights, k=1) -> list:
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


def sample(l, low, high) -> list:
    if high > len(l):
        high = len(l) - 1
    k = high if low > high else random.randint(low, high)
    if isinstance(l, dict):
        return weighted_sample_without_replacement(list(l.keys()), l.values(), k)
    elif isinstance(l, list):
        return random.sample(l, k)
    raise Exception(f"{type(l)} is not a valid sample population type")


class ConceptsFile:
    def __init__(self, filename):
        self.filename = filename
        self.is_dictionary = filename == Concepts.ALL_WORDS_LIST_FILENAME
        self.lines = []  # Original lines with comments
        self.concepts = []  # Just the concept strings
        self.concept_indices = {}  # Map of concept -> line index
        self.load()

    def load(self):
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

    def save(self):
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

    def add_concept(self, concept):
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

    def remove_concept(self, concept):
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

    def get_concepts(self):
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
    def set_concepts_dir(path="concepts"):
        old_path = Concepts.CONCEPTS_DIR
        if path == "concepts":
            Concepts.CONCEPTS_DIR = os.path.join(BASE_DIR, "concepts")
        elif not os.path.isdir(path):
            raise Exception(f"{path} is not a valid concepts directory")
        else:
            Concepts.CONCEPTS_DIR = path
        return old_path != Concepts.CONCEPTS_DIR

    @staticmethod
    def set_blacklist(blacklist):
        Concepts.TAG_BLACKLIST = list(blacklist)
    
    @staticmethod
    def add_to_blacklist(tag):
        Concepts.TAG_BLACKLIST.append(tag)
        Concepts.TAG_BLACKLIST.sort()

    @staticmethod
    def remove_from_blacklist(tag):
        try:
            Concepts.TAG_BLACKLIST.remove(tag)
            return True
        except ValueError as e:
            return False

    @staticmethod
    def clear_blacklist():
        Concepts.TAG_BLACKLIST = []

    @staticmethod
    def sample_whitelisted(concepts, low, high) -> list:
        # TODO technically inefficient to rebuild the whitelist each time
        # TODO blacklist concepts from the negative prompt
        if low == 0 and high == 0:
            return []
        if len(concepts) == 0:
            if low > 0:
                raise Exception("No concepts to sample")
            return []
        if len(Concepts.TAG_BLACKLIST) == 0:
            return sample(concepts, low, high)
        ### TODO fix this case as it is broken
        sampled = []
        count = 0
        min_needed = min(low, high)
        while len(sampled) < min_needed:
            count += 1
            if count > 100:
                raise Exception(f"Failed to generate a sample list for concepts. Concepts len {len(concepts)} Low {low} High {high}")
            sampled = Concepts._sample_whitelisted(concepts, low, high)
        return sampled

    @staticmethod
    def _sample_whitelisted(concepts, low, high):
        is_dict = isinstance(concepts, dict)
        whitelist = {} if is_dict else []
        filtered = {}
        for concept_cased in concepts:
            match_found = False
            for tag in Concepts.TAG_BLACKLIST:
                concept = concept_cased.lower()
                tag = tag.lower()
                if concept.startswith(tag + " ") or concept.startswith(tag + "-") or (" " + tag) in concept:
                    filtered[concept_cased] = tag
                    match_found = True
                    break
            if not match_found:
                if is_dict:
                    whitelist[concept_cased] = concepts[concept_cased]
                else:
                    whitelist.append(concept_cased)
        if len(filtered)!= 0:
            print(f"Filtered concepts from blacklist tags: {filtered}")
        return sample(whitelist, low, high)

    def __init__(self, prompt_mode, get_specific_locations, concepts_dir="concepts"):
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

    def extend(self, l, nsfw_file, nsfw_repeats, nsfl_file, nsfl_repeats):
        nsfw = Concepts.load(nsfw_file)
        if self.prompt_mode == PromptMode.NSFL:
            nsfl = Concepts.load(nsfl_file)
            for i in range(nsfl_repeats):
                nsfw.extend(nsfl)
        for i in range(nsfw_repeats):
            l.extend(nsfw)

    def _adjust_range(self, low, high, multiplier=1):
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

    def get_concepts(self, low=1, high=3, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        concepts = Concepts.load(SFW.concepts)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        return Concepts.sample_whitelisted(concepts, low, high)

    def get_positions(self, low=0, high=2, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        positions = Concepts.load(SFW.positions)
        # if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
        #     self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        if len(positions) > 1 and random.random() > 0.4:
            del positions[1]
        return Concepts.sample_whitelisted(positions, low, high)

    def get_humans(self, low=1, high=1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        return Concepts.sample_whitelisted(Concepts.load(SFW.humans), low, high)

    def get_animals(self, low=0, high=2, inclusion_chance=0.1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        if random.random() > inclusion_chance:
            return []
        return Concepts.sample_whitelisted(Concepts.load(SFW.animals), low, high)

    def get_locations(self, low=0, high=2, specific_inclusion_chance=0.3, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        locations = Concepts.load(SFW.locations)
        if self.get_specific_locations:
            nonspecific_locations_chance = 1 - specific_inclusion_chance
            locations = {l: nonspecific_locations_chance for l in locations}
            for l in Concepts.load(SFW.locations_specific):
                locations[l] = specific_inclusion_chance
        return Concepts.sample_whitelisted(locations, low, high)

    def get_colors(self, low=0, high=3, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        colors = Concepts.sample_whitelisted(Concepts.load(SFW.colors), low, high)
        if "rainbow" in colors and random.random() > 0.5:
            colors.remove("rainbow")
        return colors

    def get_times(self, low=0, high=1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        return Concepts.sample_whitelisted(Concepts.load(SFW.times), low, high)

    def get_dress(self, low=0, high=2, inclusion_chance=0.5, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        if random.random() > inclusion_chance:
            return []
        dress = Concepts.load(SFW.dress)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(dress, NSFW.dress, 3, NSFL.dress, 1)
        return Concepts.sample_whitelisted(dress, low, high)

    def get_expressions(self, low=1, high=1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        expressions = Concepts.load(SFW.expressions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(expressions, NSFW.expressions, 6, NSFL.expressions, 3)
        return Concepts.sample_whitelisted(expressions, low, high)

    def get_actions(self, low=0, high=2, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        actions = Concepts.load(SFW.actions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(actions, NSFW.actions, 8, NSFL.actions, 3)
        return Concepts.sample_whitelisted(actions, low, high)

    def get_descriptions(self, low=0, high=1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        descriptions = Concepts.load(SFW.descriptions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(descriptions, NSFW.descriptions, 3, NSFL.descriptions, 2)
        return Concepts.sample_whitelisted(descriptions, low, high)

    def get_characters(self, low=0, high=1, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        characters = Concepts.load(SFW.characters)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(characters, NSFW.characters, 3, NSFL.characters, 2)
        return Concepts.sample_whitelisted(characters, low, high)

    def get_random_words(self, low=0, high=9, multiplier=1):
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
        random_words = Concepts.sample_whitelisted(Concepts.ALL_WORDS_LIST, low, high)
        if len(Concepts.URBAN_DICTIONARY_CORPUS) == 0 and self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            try:
                Concepts.URBAN_DICTIONARY_CORPUS = Concepts.load(Concepts.URBAN_DICTIONARY_CORPUS_PATH)
            except Exception as e:
                pass
        if len(Concepts.URBAN_DICTIONARY_CORPUS) > 0:
            random_urban_dictionary_words = Concepts.sample_whitelisted(Concepts.URBAN_DICTIONARY_CORPUS, low, high)
            random_words.extend(random_urban_dictionary_words)
            random_words = Concepts.sample_whitelisted(random_words, low, high)
        random.shuffle(random_words)
        random_word_strings = []
        word_string = ""
        for word in random_words:
            if random.random() < 0.25:
                if word_string != "":
                    random_word_strings.append(word_string.strip())
                word_string = ""
            word_string += word + " "
        if word_string != "" and not word_string.strip() in random_word_strings:
            random_word_strings.append(word_string.strip())
        return random_word_strings

    def get_nonsense(self, low=0, high=2, multiplier=1):
        low, high = self._adjust_range(low, high, multiplier)
        nonsense_words = [self.get_nonsense_word() for _ in range(high)]
        return Concepts.sample_whitelisted(nonsense_words, low, high)

    def is_art_style_prompt_mode(self):
        return self.prompt_mode in (PromptMode.ANY_ART, PromptMode.PAINTERLY, PromptMode.ANIME, PromptMode.GLITCH)

    def get_art_styles(self, max_styles=None, multiplier=1):
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
        if max_styles is None:
            max_styles = min(8, len(art_styles)) if self.prompt_mode in (PromptMode.ANY_ART, PromptMode.GLITCH) else 2
        low = 1
        high = random.randint(1, max_styles)
        low, high = self._adjust_range(low, high, multiplier=multiplier)
        out = sample(art_styles, low, high)
        append = style_tag + " art by " if style_tag else "art by "
        for i in range(len(out)):
            out[i] = append + out[i]
        return out

    def get_nonsense_word(self):
        # TODO check other language lists as well
        # TODO check other concept lists
        length = random.randint(3, 15)
        word = ''.join([random.choice(Concepts.ALPHABET) for i in range(length)])
        counter = 0
        while word in Concepts.ALL_WORDS_LIST:
            if counter > 100:
                print("Failed to generate a nonsense word!")
                break
            word = ''.join([random.choice(Concepts.ALPHABET) for i in range(length)])
            counter += 1
        return word

    @staticmethod
    def load(filename):
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
    def save(filename, concepts):
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


def is_in_existing_concepts(parts_to_check=[]):
    is_in_existing = {}
    all_words_list = []
    for filename in [
            SFW.actions,
            SFW.animals,
            SFW.characters,
            SFW.colors,
            SFW.concepts,
            SFW.descriptions,
            SFW.dress,
            SFW.expressions,
            SFW.humans,
            SFW.lighting,
            SFW.locations,
            SFW.locations_specific,
            SFW.positions,
            SFW.times,
            NSFW.characters,
            NSFW.concepts,
            NSFW.dress,
            NSFW.descriptions,
            NSFW.expressions,
            NSFW.actions,
            NSFL.characters,
            NSFL.concepts,
            NSFL.dress,
            NSFL.descriptions,
            NSFL.expressions,
            NSFL.actions,
            ArtStyles.artists,
            ArtStyles.anime,
            ArtStyles.painters,
            ArtStyles.glitch,
            ]:
        l = Concepts.load(filename)
        for s in l:
            all_words_list.append(s.lower())
    for part in parts_to_check:
        is_in_existing[part] = part.lower() in all_words_list
    return is_in_existing
