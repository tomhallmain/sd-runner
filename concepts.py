from enum import Enum
import os
import random

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class PromptMode(Enum):
    FIXED = "FIXED"
    SFW = "SFW"
    NSFW = "NSFW"
    NSFL = "NSFL"
    RANDOM = "RANDOM"
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


def sample(l, low, high):
    if low > high:
        return random.sample(l, high)
    return random.sample(l, random.randint(low, high))


class Concepts:
    ENGLISH_WORDS = "english_words.txt"

    def __init__(self, prompt_mode, get_specific_locations):
        self.prompt_mode = prompt_mode
        self.get_specific_locations = get_specific_locations
        self.english_words = Concepts.load(Concepts.ENGLISH_WORDS)
        # Randomly select concepts from the lists

    def extend(self, l, nsfw_file, nsfw_repeats, nsfl_file, nsfl_repeats):
        nsfw = Concepts.load(nsfw_file)
        if self.prompt_mode == PromptMode.NSFL:
            nsfl = Concepts.load(nsfl_file)
            for i in range(nsfl_repeats):
                nsfw.extend(nsfl)
        for i in range(nsfw_repeats):
            l.extend(nsfw)

    def get_concepts(self, low=1, high=3):
        concepts = Concepts.load(SFW.concepts)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        return sample(concepts, low, high)

    def get_positions(self, low=0, high=2):
        positions = Concepts.load(SFW.positions)
        # if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
        #     self.extend(concepts, NSFW.concepts, 5, NSFL.concepts, 3)
        if len(positions) > 1 and random.random() > 0.4:
            del positions[1]
        return sample(positions, low, high)

    def get_humans(self):
        return sample(Concepts.load(SFW.humans), 1, 1)

    def get_animals(self, low=0, high=2, inclusion_chance=0.1):
        if random.random() > inclusion_chance:
            return []
        return sample(Concepts.load(SFW.animals), low, high)

    def get_locations(self, low=0, high=2):
        locations = Concepts.load(SFW.locations)
        if self.get_specific_locations and random.random() > 0.5:
            locations.extend(Concepts.load(SFW.locations_specific))
        if random.random() > 0.4:
            return []
        return sample(locations, low, high)

    def get_colors(self, low=0, high=3):
        colors = sample(Concepts.load(SFW.colors), low, high)
        if "rainbow" in colors and random.random() > 0.5:
            colors.remove("rainbow")
        return colors

    def get_times(self, low=0, high=1):
        return sample(Concepts.load(SFW.times), low, high)

    def get_dress(self, low=0, high=2, inclusion_chance=0.5):
        if random.random() > inclusion_chance:
            return []
        dress = Concepts.load(SFW.dress)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(dress, NSFW.dress, 8, NSFL.dress, 1)
        return sample(dress, low, high)

    def get_expressions(self):
        expressions = Concepts.load(SFW.expressions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(expressions, NSFW.expressions, 6, NSFL.expressions, 3)
        return sample(expressions, 1, 1)

    def get_actions(self, low=0, high=2):
        actions = Concepts.load(SFW.actions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(actions, NSFW.actions, 8, NSFL.actions, 3)
        return sample(actions, low, high)

    def get_descriptions(self, low=0, high=1):
        descriptions = Concepts.load(SFW.descriptions)
        if self.prompt_mode in (PromptMode.NSFW, PromptMode.NSFL):
            self.extend(descriptions, NSFW.descriptions, 3, NSFL.descriptions, 2)
        return sample(descriptions, low, high)

    def get_random_words(self, low=0, high=9):
        random_words = sample(self.english_words, low, high)
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

    def get_art_styles(self):
        if self.prompt_mode == PromptMode.ANY_ART:
            art_styles = []
            art_styles.extend(Concepts.load(ArtSyles.anime))
            art_styles.extend(Concepts.load(ArtSyles.glitch))
            art_styles.extend(Concepts.load(ArtSyles.painters))
            style_tag = None
        else:
            m = {PromptMode.ANIME: (ArtSyles.anime, "anime"),
                 PromptMode.GLITCH: (ArtSyles.glitch, "glitch"),
                 PromptMode.PAINTERLY: (ArtSyles.painters, "painting")}
            art_styles = Concepts.load(m[self.prompt_mode][0])
            style_tag = m[self.prompt_mode][1]
        max_styles = min(8, len(art_styles)) if self.prompt_mode in (PromptMode.ANY_ART, PromptMode.GLITCH) else 2
        out = sample(art_styles, 1, random.randint(1, max_styles))
        append = style_tag + " art by " if style_tag else "art by "
        for i in range(len(out)):
            out[i] = append + out[i]
        return out

    @staticmethod
    def load(filename):
        l = []
        filepath = os.path.join(os.path.join(BASE_DIR, "concepts"), filename)
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
        return l

class HardConcepts:
    hard_concepts = Concepts.load("hard_concepts.txt")
    exclusionary_concepts = Concepts.load("exclusionary_concepts.txt")
    boring_concepts = Concepts.load("boring_concepts.txt")

# Below files are reloaded every time there's a prompt generation to enable quick swapping
class SFW:
    concepts = "sfw_concepts.txt"
    positions = "positions.txt"
    lighting = "lighting.txt"
    humans = "humans.txt"
    locations = "locations.txt"
    locations_specific = "locations_specific.txt"
    colors = "colors.txt"
    times = "times.txt"
    dress = "sfw_dress.txt"
    descriptions = "sfw_descriptions.txt"
    expressions = "sfw_expressions.txt"
    actions = "sfw_actions.txt"
    animals = "animals.txt"

class NSFW:
    concepts = "nsfw_concepts.txt"
    dress = "nsfw_dress.txt"
    descriptions = "nsfw_descriptions.txt"
    expressions = "nsfw_expressions.txt"
    actions = "nsfw_actions.txt"

class NSFL:
    concepts = "nsfl_concepts.txt"
    dress = "nsfl_dress.txt"
    descriptions = "nsfl_descriptions.txt"
    expressions = "nsfl_expressions.txt"
    actions = "nsfl_actions.txt"


class ArtSyles:
    anime = "mangakas.txt"
    painters = "painters.txt"
    glitch = "glitch.txt"
