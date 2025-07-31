from copy import deepcopy
import json
import random
import re
import subprocess

from sd_runner.blacklist import Blacklist
from sd_runner.concepts import Concepts
from ui.expansion import Expansion
from utils.config import config
from utils.globals import PromptMode
from extensions.image_data_extractor import ImageDataExtractor


class PrompterConfiguration:
    def __init__(
        self,
        prompt_mode: PromptMode = PromptMode.SFW,
        concepts: tuple[int, int] = (1, 3),
        positions: tuple[int, int] = (0, 2),
        locations: tuple[int, int] = (0, 1),
        animals: tuple[int, int, float] = (0, 1, 0.1),
        colors: tuple[int, int] = (0, 2),
        times: tuple[int, int] = (0, 1),
        dress: tuple[int, int, float] = (0, 2, 0.5),
        expressions: tuple[int, int] = (1, 1),
        actions: tuple[int, int] = (0, 2),
        descriptions: tuple[int, int] = (0, 1),
        characters: tuple[int, int] = (0, 1),
        random_words: tuple[int, int] = (0, 5),
        nonsense: tuple[int, int] = (0, 0),
        art_styles_chance: float = 0.3
    ):
        self.concepts_dir = config.concepts_dirs[config.default_concepts_dir]
        self.prompt_mode = prompt_mode
        self.concepts = concepts
        self.positions = positions
        self.locations = locations
        self.specific_locations_chance = 0.25
        self.animals = animals
        self.colors = colors
        self.times = times
        self.dress = dress
        self.expressions = expressions
        self.actions = actions
        self.descriptions = descriptions
        self.characters = characters
        self.random_words = random_words
        self.nonsense = nonsense
        self.multiplier = 1
        self.art_styles_chance = art_styles_chance
        self.specify_humans_chance = 0.25
        self.emphasis_chance = 0.1
        self.sparse_mixed_tags = False

    def to_dict(self) -> dict:
        return {
            "concepts_dir": self.concepts_dir,
            "prompt_mode": self.prompt_mode.name,
            "concepts": self.concepts,
            "positions": self.positions,
            "locations": self.locations,
            "specific_locations_chance": self.specific_locations_chance,
            "animals": self.animals,
            "colors": self.colors,
            "times": self.times,
            "dress": self.dress,
            "expressions": self.expressions,
            "actions": self.actions,
            "descriptions": self.descriptions,
            "characters": self.characters,
            "random_words": self.random_words,
            "nonsense": self.nonsense,
            "multiplier": self.multiplier,
            "art_styles_chance": self.art_styles_chance,
            "specify_humans_chance": self.specify_humans_chance,
            "emphasis_chance": self.emphasis_chance,
            "sparse_mixed_tags": self.sparse_mixed_tags,
        }

    def set_from_dict(self, _dict: dict) -> None:
        self.prompt_mode = PromptMode[_dict["prompt_mode"]]
        self.concepts_dir = _dict['concepts_dir'] if 'concepts_dir' in _dict else self.concepts_dir
        self.concepts = _dict['concepts'] if 'concepts' in _dict else self.concepts
        self.positions = _dict['positions'] if 'positions' in _dict else self.positions
        self.locations = _dict['locations'] if 'locations' in _dict else self.locations
        self.specific_locations_chance = _dict['specific_locations_chance'] if 'specific_locations_chance' in _dict else self.specific_locations_chance
        self.animals = _dict['animals'] if 'animals' in _dict else self.animals
        self.colors = _dict['colors'] if 'colors' in _dict else self.colors
        self.times = _dict['times'] if 'times' in _dict else self.times
        self.dress = _dict['dress'] if 'dress' in _dict else self.dress
        self.expressions = _dict['expressions'] if 'expressions' in _dict else self.expressions
        self.actions = _dict['actions'] if 'actions' in _dict else self.actions
        self.descriptions = _dict['descriptions'] if 'descriptions' in _dict else self.descriptions
        self.characters = _dict["characters"] if "characters" in _dict else self.characters
        self.random_words = _dict['random_words'] if 'random_words' in _dict else self.random_words
        self.nonsense = _dict['nonsense'] if 'nonsense' in _dict else self.nonsense
        self.multiplier = _dict["multiplier"] if "multiplier" in _dict else self.multiplier
        self.art_styles_chance = _dict['art_styles_chance'] if 'art_styles_chance' in _dict else self.art_styles_chance
        self.specify_humans_chance = _dict['specify_humans_chance'] if'specify_humans_chance' in  _dict else self.specify_humans_chance
        self.emphasis_chance = _dict['emphasis_chance'] if 'emphasis_chance' in _dict else self.emphasis_chance
        self.sparse_mixed_tags = _dict['sparse_mixed_tags'] if 'sparse_mixed_tags' in _dict else self.sparse_mixed_tags
        self._handle_old_types()

    def set_from_other(self, other: "PrompterConfiguration") -> None:
        if not isinstance(other, PrompterConfiguration):
            raise TypeError("Can't set from non-PrompterConfiguration")
        self.__dict__ = deepcopy(other.__dict__)
        self._handle_old_types()

    def _handle_old_types(self) -> None:
        if type(self.expressions) == bool:
            if self.expressions:
                self.expressions = (1, 1)
            else:
                self.expressions = (0, 0)

    def __eq__(self, other: object) -> bool:
        return self.__dict__ == other.__dict__
    
    def __hash__(self) -> int:
        class PromptModeEncoder(json.JSONEncoder):
            def default(self, z):
                if isinstance(z, PromptMode):
                    return (str(z.name))
                else:
                    return super().default(z)
        return hash(json.dumps(self, cls=PromptModeEncoder, sort_keys=True))


class Prompter:
    # Set these to include constant detail in all prompts
    POSITIVE_TAGS = config.dict["default_positive_tags"]
    NEGATIVE_TAGS = config.dict["default_negative_tags"]
    TAGS_APPLY_TO_START = True
    IMAGE_DATA_EXTRACTOR = None

    """
    Has various functions for generating stable diffusion image generation prompts.
    """
    def __init__(
        self,
        reference_image_path: str = "",
        llava_path: str = "",
        prompter_config: PrompterConfiguration = PrompterConfiguration(),
        get_specific_locations: bool = False,
        prompt_list: list[str] = []
    ):
        self.reference_image_path = reference_image_path
        self.llava_path = llava_path
        self.prompter_config = prompter_config
        self.prompt_mode = prompter_config.prompt_mode
        self.concepts = Concepts(prompter_config.prompt_mode, get_specific_locations=get_specific_locations, concepts_dir=prompter_config.concepts_dir)
        self.count = 0
        self.prompt_list = prompt_list
        self.last_prompt = ""

        if prompter_config == PromptMode.LIST and len(prompt_list) == 0:
            raise Exception("No list items to iterate for prompting.")

    def set_prompt_mode(self, prompt_mode: PromptMode) -> None:
        self.prompt_mode = prompt_mode
        self.concepts.prompt_mode = prompt_mode

    @classmethod
    def set_positive_tags(cls, tags: str) -> None:
        cls.POSITIVE_TAGS = tags

    @classmethod
    def set_negative_tags(cls, tags: str) -> None:
        cls.NEGATIVE_TAGS = tags

    @classmethod
    def set_tags_apply_to_start(cls, apply: bool) -> None:
        cls.TAGS_APPLY_TO_START = apply

    def generate_prompt(
        self,
        positive: str = "",
        negative: str = "",
        related_image_path: str = ""
    ) -> tuple[str, str]:
        if self.prompt_mode in (PromptMode.SFW, PromptMode.NSFW, PromptMode.NSFL):
            positive = self.mix_concepts()
        elif PromptMode.RANDOM == self.prompt_mode:
            positive = self.random()
            negative += ", boring, dull"
        elif PromptMode.NONSENSE == self.prompt_mode:
            positive = self.nonsense()
            negative += ", boring, dull"
        elif self.concepts.is_art_style_prompt_mode():
            # print(positive)
            # print(len(positive))
            positive += self.get_artistic_prompt(len(positive) == 0)
        elif PromptMode.TAKE == self.prompt_mode:
            if related_image_path == "":
                raise Exception("No related image path provided to take prompt from")
            positive, negative = Prompter.take_prompt_from_image(related_image_path)
        elif PromptMode.LIST == self.prompt_mode:
            positive = self.prompt_list[self.count % len(self.prompt_list)]
        elif PromptMode.IMPROVE == self.prompt_mode:
            data = self.gather_data()
            positive = self.transform_result(data)
        self.count += 1
        if Prompter.POSITIVE_TAGS and Prompter.POSITIVE_TAGS.strip() != "":
            if self.prompter_config.sparse_mixed_tags:
                positive = self._mix_sparse_tags(positive)
            elif Prompter.TAGS_APPLY_TO_START:
                if not positive.startswith(Prompter.POSITIVE_TAGS):
                    positive = Prompter.POSITIVE_TAGS + positive
            elif not positive.endswith(Prompter.POSITIVE_TAGS):
                positive += ", " + Prompter.POSITIVE_TAGS
        if Prompter.NEGATIVE_TAGS and Prompter.NEGATIVE_TAGS != "":
            if self.prompter_config.sparse_mixed_tags:
                negative = self._mix_sparse_tags(negative)
            elif Prompter.TAGS_APPLY_TO_START:
                if not negative.startswith(Prompter.NEGATIVE_TAGS):
                    negative = Prompter.NEGATIVE_TAGS + negative
            elif not negative.endswith(Prompter.NEGATIVE_TAGS):
                negative += ", " + Prompter.NEGATIVE_TAGS
        if Prompter.contains_expansion_var(positive):
            positive = self.apply_expansions(positive, concepts=self.concepts, specific_locations_chance=self.prompter_config.specific_locations_chance)
        if Prompter.contains_expansion_var(negative):
            negative = self.apply_expansions(negative, concepts=self.concepts, specific_locations_chance=self.prompter_config.specific_locations_chance)
        if Prompter.contains_choice_set(positive):
            positive = self.apply_choices(positive)
        if Prompter.contains_choice_set(negative):
            negative = self.apply_choices(negative)
        
        # Validate final prompts against blacklist
        positive_concepts = [c.strip() for c in positive.split(',')]
        positive_whitelist, positive_filtered = Blacklist.filter_concepts(positive_concepts)
        
        # Reconstruct the prompts with only whitelisted concepts if needed
        if len(positive_filtered) > 0:
            positive = ', '.join(positive_whitelist)
            print(f"Filtered concepts from blacklist tags: {positive_filtered}")
        
        self.last_prompt = positive
        return (positive, negative)

    def gather_data(self) -> dict:
        # Use subprocess to call local LLaVA installation and gather data about the image
        # Assuming LLaVA outputs JSON data about the image
        result = subprocess.run([self.llava_path, self.reference_image_path], capture_output=True)
        return json.loads(result.stdout)

    def transform_result(self, data: dict) -> str:
        print(self.last_prompt)
        # Transform the result into a new prompt based on the original
        # This is a placeholder as the transformation will depend on the specific requirements
        return "New prompt based on original image: " + str(data)

    def random(self) -> str:
        random_words = self.concepts.get_random_words(*self.prompter_config.random_words)
        Prompter.emphasize(random_words, emphasis_chance=self.prompter_config.emphasis_chance)
        return ', '.join(random_words)

    def nonsense(self) -> str:
        nonsense = self.concepts.get_nonsense(*self.prompter_config.nonsense)
        Prompter.emphasize(nonsense, emphasis_chance=self.prompter_config.emphasis_chance)
        return ', '.join(nonsense)

    def _mix_sparse_tags(self, text: str) -> str:
        if not Prompter.POSITIVE_TAGS or Prompter.POSITIVE_TAGS.strip() == '' or text is None or text.strip() == "":
            return str(text)
        positive_tags = Prompter._get_discretely_emphasized_prompt(Prompter.POSITIVE_TAGS)
        # print(positive_tags)
        if len(positive_tags) > 1:
            random.shuffle(positive_tags)
            min_chance = 0.5
            max_chance = 1
            proportion_to_keep = random.random() * (max_chance - min_chance) + min_chance
            positive_tags = positive_tags[:int(len(positive_tags) * proportion_to_keep)]
        full_prompt = [w.strip() for w in text.split(',')]
        full_prompt.extend(positive_tags)
        random.shuffle(full_prompt)
        return ', '.join(full_prompt)

    @staticmethod
    def _get_discretely_emphasized_prompt(text: str) -> list[str]:
        assert isinstance(text, str) and len(text) > 0, "Text must be a non-empty string."
        prompt_part = ""
        just_closed = 0
        emphasis_level = 0
        positive_tags = []
        for i in range(len(text)):
            c = text[i]
            if c == "(":
                emphasis_level += 1
            elif c == ")":
                emphasis_level -= 1
                if emphasis_level == 0:
                    just_closed += 1
            elif c == ",":
                emphasis_left = "(" * (emphasis_level + just_closed)
                emphasis_right = ")" * (emphasis_level + just_closed)
                positive_tags.append(emphasis_left + prompt_part.strip() + emphasis_right)
                prompt_part = ""
                just_closed = 0
            else:
                prompt_part += c
        return positive_tags

    def _mix_concepts(self, humans_chance: float = 0.25) -> list[str]:
        mix = []
        mix.extend(self.concepts.get_concepts(*self.prompter_config.concepts, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_positions(*self.prompter_config.positions, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_locations(*self.prompter_config.locations, specific_inclusion_chance=self.prompter_config.specific_locations_chance, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_animals(*self.prompter_config.animals, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_colors(*self.prompter_config.colors, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_times(*self.prompter_config.times, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_dress(*self.prompter_config.dress, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_expressions(*self.prompter_config.expressions, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_actions(*self.prompter_config.actions, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_descriptions(*self.prompter_config.descriptions, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_characters(*self.prompter_config.characters, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_random_words(*self.prompter_config.random_words, multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_nonsense(*self.prompter_config.nonsense, multiplier=self.prompter_config.multiplier))
        # Humans might not always be desirable so only add some randomly
        if self.prompt_mode == PromptMode.SFW:
            if random.random() < humans_chance:
                mix.extend(self.concepts.get_humans(multiplier=self.prompter_config.multiplier))
        # Small chance to add artist style
        if not self.concepts.is_art_style_prompt_mode() and random.random() < self.prompter_config.art_styles_chance:
            print("Adding art styles")
            mix.extend(self.concepts.get_art_styles(max_styles=2, multiplier=self.prompter_config.multiplier))
        random.shuffle(mix)
        Prompter.emphasize(mix, emphasis_chance=self.prompter_config.emphasis_chance)
        # Extra concepts for NSFW
        self.add_presets(mix)
        return mix

    def mix_concepts(self, emphasis_threshold: float = 0.9) -> str:
        return ', '.join(self._mix_concepts(humans_chance=self.prompter_config.specify_humans_chance))

    def mix_colors(self) -> str:
        return ', '.join(self.concepts.get_colors(low=2, high=5))

    def add_presets(self, mix: list[str] = []) -> None:
        for preset in config.prompt_presets:
            for prompt_mode_name in preset["prompt_modes"]:
                if prompt_mode_name in PromptMode.__members__.keys():
                    preset_prompt_mode = PromptMode[prompt_mode_name]
                    if self.prompt_mode == preset_prompt_mode:
                        if "chance" not in preset or random.random() < preset["chance"]:
                            if "prepend_prompt" in preset:
                                mix.insert(0, preset["prepend_prompt"])
                            if "append_prompt" in preset:
                                mix.append(preset["append_prompt"])
                else:
                    raise Exception(f"Invalid prompt mode: {prompt_mode_name}")

    def get_artistic_prompt(self, add_concepts: bool, emphasis_threshold: float = 0.9) -> str:
        mix = []
        mix.extend(self.concepts.get_art_styles())
        if add_concepts:
            mix.extend(self._mix_concepts(humans_chance=0))
        # Humans might not always be desirable so only add some randomly
        if self.prompt_mode == PromptMode.SFW:
            if random.random() < (self.prompter_config.specify_humans_chance * 0.5):
                mix.extend(self.concepts.get_humans())
        random.shuffle(mix)
        Prompter.emphasize(mix)
        return ', '.join(mix)

    @staticmethod
    def take_prompt_from_image(related_image_path: str) -> tuple[str, str]:
        if Prompter.IMAGE_DATA_EXTRACTOR is None:
            Prompter.IMAGE_DATA_EXTRACTOR = ImageDataExtractor()
        return Prompter.IMAGE_DATA_EXTRACTOR.extract(related_image_path)

    @staticmethod
    def emphasize(mix: list[str], emphasis_chance: float = 0.1) -> None:
        # Randomly boost some concepts
        for i in range(len(mix)):
            if random.random() < emphasis_chance and len(mix[i]) > 0:
                if random.random() < 0.9:
                    mix[i] = "(" + mix[i] + ")"
                else:
                    random_deemphasis = random.random()
                    if random.random() > 0.9:
                        random_deemphasis *= random.randint(2, 10)
                    if random_deemphasis >= 0.1:
                        deemphasis_str = str(random_deemphasis)[:3]
                        if random_deemphasis > 1.5:
                            deemphasis_str = "1.1"
                        mix[i] = f"({mix[i]}:{deemphasis_str})"

    @staticmethod
    def contains_choice_set(text: str) -> bool:
        if "[[" not in text or "]]" not in text:
            return False
        return re.search(r"\[\[[^\[\]]*\]\]", text) is not None

    @staticmethod
    def apply_choices(text: str) -> str:
        offset = 0
        for match in re.finditer(r"\[\[[^\[\]]*\]\]", text):
            left = text[:match.start() + offset]
            right = text[match.end() + offset:]
            original_len = len(match.group())
            choice_set_str = match.group()[2:-2].split(",")
            population = []
            weights = []
            for choice in choice_set_str:
                if ":" in choice:
                    chance_weight = float(choice[choice.rfind(":") + 1:])
                    choice = choice[:choice.rfind(":")]
                else:
                    chance_weight = 1
                population.append(choice.strip())
                weights.append(chance_weight)
            choice = random.choices(population=population, weights=weights, k=1)[0]
            text = left + choice + right
            offset += len(choice) - original_len
        return str(text)

    @staticmethod
    def _expansion_var_pattern(from_ui: bool = False) -> str:
        if from_ui:
            return r"(\$)[A-Za-z_]+|(\$)?\{[A-Za-z_]+\}"
        else:
            return r"(\$)(\$)?[A-Za-z_]+|(\$)?\{[A-Za-z_]+\}"

    @staticmethod
    def contains_expansion_var(text: str, from_ui: bool = False) -> bool:
        # if "*" in text or "?" in text:
        #     return True
        if re.search(Prompter._expansion_var_pattern(from_ui), text):
            return True
        return False

    @staticmethod
    def apply_expansions(
        text: str,
        from_ui: bool = False,
        concepts: Concepts = None,
        specific_locations_chance: float = 0.3
    ) -> str:
        # TODO enable recursive expansions
#        text += " ${}"
        offset = 0
        for match in re.finditer(Prompter._expansion_var_pattern(from_ui), text):
            left = text[:match.start() + offset]
            right = text[match.end() + offset:]
            name = match.group().lower()
            if from_ui and name[0] == "$" and match.start() > 0 and text[match.start()-1] == "$":
                continue
            original_length = len(name)
            if "$" in name:
                name = name.replace("$", "")
            if "{" in name:
                name = name.replace("{", "")
            if "}" in name:
                name = name.replace("}", "")
            replacement = None
            if name in config.wildcards:
                replacement = config.wildcards[name]
            elif Expansion.contains_expansion(name):
                replacement = Expansion.get_expansion_text_by_id(name)
            elif name == "random" and len(config.wildcards) > 0:
                name = random.choice(list(config.wildcards))
                replacement = config.wildcards[name]
                print(f"Using random prompt replacement ID: {name}")
            elif concepts is not None:
                if name.startswith("action"):
                    replacement = random.choice(concepts.get_actions(low=1, high=1))
                elif name.startswith("concept"):
                    replacement = random.choice(concepts.get_concepts(low=1, high=1))
                elif name == "dress":
                    replacement = random.choice(concepts.get_dress(low=1, high=1))
                elif name.startswith("time"):
                    replacement = random.choice(concepts.get_times(low=1, high=1))
                elif name.startswith("expression"):
                    replacement = random.choice(concepts.get_expressions(low=1, high=1))
                elif name.startswith("animal"):
                    replacement = random.choice(concepts.get_animals(low=1, high=1, inclusion_chance=1.0))
                elif name.startswith("description"):
                    replacement = random.choice(concepts.get_descriptions(low=1, high=1))
                elif name == "random_word":
                    replacement = random.choice(concepts.get_random_words(low=1, high=1))
                elif name == "nonsense":
                    replacement = random.choice(concepts.get_nonsense(low=1, high=1))
                elif name.startswith("color"):
                    replacement = random.choice(concepts.get_colors(low=1, high=1))
                elif name.startswith("location"):
                    replacement = random.choice(concepts.get_locations(low=1, high=1, specific_inclusion_chance=specific_locations_chance))
                elif name.startswith("human"):
                    replacement = random.choice(concepts.get_humans(low=1, high=1))
                elif name.startswith("position"):
                    replacement = random.choice(concepts.get_positions(low=1, high=1))
                elif name.startswith("number"):
                    replacement = str(random.randint(1, 999))
            if replacement is None:
                print(f"Invalid prompt replacement ID: \"{name}\"")
                continue
            text = left + replacement + right
            offset += len(replacement) - original_length
        return str(text)


class GlobalPrompter:
    prompter_instance = Prompter()

    @classmethod
    def set_prompter(cls, prompter_config: PrompterConfiguration, get_specific_locations: bool, prompt_list: list[str]):
        cls.prompter_instance = Prompter(prompter_config=prompter_config, get_specific_locations=get_specific_locations, prompt_list=prompt_list)


if __name__ == "__main__":
    print(Prompter().generate_prompt())
