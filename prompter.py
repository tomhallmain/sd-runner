import json
import random
import subprocess

from concepts import Concepts, PromptMode
from config import config


class PrompterConfiguration:
    def __init__(self, concepts_config=(1,3), positions_config=(0,2), locations_config=(0,1),
                 animals_config=(0,1,0.1), colors_config=(0,2), times_config=(0,1),
                 dress_config=(0,2,0.5), expressions=True, actions=(0,2), descriptions=(0,1),
                 random_words_config=(0,5)) -> None:
        self.concepts = concepts_config
        self.positions = positions_config
        self.locations = locations_config
        self.animals = animals_config
        self.colors = colors_config
        self.times = times_config
        self.dress = dress_config
        self.expressions = expressions
        self.actions = actions
        self.descriptions = descriptions
        self.random_words = random_words_config


PROMPTER_CONFIG = PrompterConfiguration()

class Prompter:
    # Set these to include constant detail in all prompts
    POSITIVE_TAGS = config.dict["default_positive_tags"]
    NEGATIVE_TAGS = config.dict["default_negative_tags"]

    """
    Has various functions for generating stable diffusion image generation prompts.
    """
    def __init__(self, reference_image_path="", llava_path="", prompt_mode=PromptMode.SFW, get_specific_locations=False, prompt_list=[]):
        self.reference_image_path = reference_image_path
        self.llava_path = llava_path
        self.prompt_mode = prompt_mode
        self.concepts = Concepts(prompt_mode, get_specific_locations=get_specific_locations)
        self.count = 0
        self.prompt_list = prompt_list
        self.last_prompt = ""

        if prompt_mode == PromptMode.LIST and len(prompt_list) == 0:
            raise Exception("No list items to iterate for prompting.")

    def set_prompt_mode(self, prompt_mode):
        self.prompt_mode = prompt_mode
        self.concepts.prompt_mode = prompt_mode

    @classmethod
    def set_positive_tags(cls, tags):
        cls.POSITIVE_TAGS = tags

    @classmethod
    def set_negative_tags(cls, tags):
        cls.NEGATIVE_TAGS = tags

    def generate_prompt(self, positive="", negative=""):
        if self.prompt_mode in (PromptMode.SFW, PromptMode.NSFW, PromptMode.NSFL):
            positive = self.mix_concepts()
        elif PromptMode.RANDOM == self.prompt_mode:
            positive = self.random()
            negative += " boring, dull"
        elif self.concepts.is_art_style_prompt_mode():
            print(positive)
            print(len(positive))
            positive += self.get_artistic_prompt(len(positive) == 0)
        elif PromptMode.LIST == self.prompt_mode:
            positive = self.prompt_list[self.count % len(self.prompt_list)]
        elif PromptMode.IMPROVE == self.prompt_mode:
            data = self.gather_data()
            positive = self.transform_result(data)
        self.count += 1
        if Prompter.POSITIVE_TAGS and Prompter.POSITIVE_TAGS != "" and not positive.startswith(Prompter.POSITIVE_TAGS):
            positive = Prompter.POSITIVE_TAGS + positive
        if Prompter.NEGATIVE_TAGS and Prompter.NEGATIVE_TAGS != "" and not negative.startswith(Prompter.NEGATIVE_TAGS):
            negative = Prompter.NEGATIVE_TAGS + negative
        self.last_prompt = positive
        return (positive, negative)

    def gather_data(self):
        # Use subprocess to call local LLaVA installation and gather data about the image
        # Assuming LLaVA outputs JSON data about the image
        result = subprocess.run([self.llava_path, self.reference_image_path], capture_output=True)
        return json.loads(result.stdout)

    def transform_result(self, data):
        print(self.last_prompt)
        # Transform the result into a new prompt based on the original
        # This is a placeholder as the transformation will depend on the specific requirements
        return "New prompt based on original image: " + str(data)

    def random(self, emphasis_threshold=0.9):
        random_words = self.concepts.get_random_words(*PROMPTER_CONFIG.random_words)
        Prompter.emphasize(random_words, emphasis_threshold=emphasis_threshold)
        return ', '.join(random_words)

    def _mix_concepts(self, humans_threshold=0.75, emphasis_threshold=0.9, art_styles_chance=0.3):
        mix = []
        mix.extend(self.concepts.get_concepts(*PROMPTER_CONFIG.concepts))
        mix.extend(self.concepts.get_positions(*PROMPTER_CONFIG.positions))
        mix.extend(self.concepts.get_locations(*PROMPTER_CONFIG.locations))
        mix.extend(self.concepts.get_animals(*PROMPTER_CONFIG.animals))
        mix.extend(self.concepts.get_colors(*PROMPTER_CONFIG.colors))
        mix.extend(self.concepts.get_times(*PROMPTER_CONFIG.times))
        mix.extend(self.concepts.get_dress(*PROMPTER_CONFIG.dress))
        if PROMPTER_CONFIG.expressions:
            mix.extend(self.concepts.get_expressions())
        mix.extend(self.concepts.get_actions(*PROMPTER_CONFIG.actions))
        mix.extend(self.concepts.get_descriptions(*PROMPTER_CONFIG.descriptions))
        mix.extend(self.concepts.get_random_words(*PROMPTER_CONFIG.random_words))
        # Humans might not always be desirable so only add some randomly
        if self.prompt_mode == PromptMode.SFW:
            if random.random() > humans_threshold:
                mix.extend(self.concepts.get_humans())
        # Small chance to add artist style
        if not self.concepts.is_art_style_prompt_mode() and random.random() < art_styles_chance:
            print("Adding art styles")
            mix.extend(self.concepts.get_art_styles(max_styles=2))
        random.shuffle(mix)
        Prompter.emphasize(mix, emphasis_threshold=emphasis_threshold)
        # Extra concepts for NSFW
        self.add_presets(mix)
        return mix

    def mix_concepts(self, humans_threshold=0.75, emphasis_threshold=0.9):
        return ', '.join(self._mix_concepts(humans_threshold=humans_threshold, emphasis_threshold=emphasis_threshold))

    def mix_colors(self):
        return ', '.join(self.concepts.get_colors(low=2, high=5))

    def add_presets(self, mix=[]):
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

    def get_artistic_prompt(self, add_concepts, humans_threshold=0.75, emphasis_threshold=0.9):
        mix = []
        mix.extend(self.concepts.get_art_styles())
        if add_concepts:
            mix.extend(self._mix_concepts(humans_threshold=humans_threshold, emphasis_threshold=emphasis_threshold))
        # Humans might not always be desirable so only add some randomly
        if self.prompt_mode == PromptMode.SFW:
            if random.random() > humans_threshold:
                mix.extend(self.concepts.get_humans())
        random.shuffle(mix)
        Prompter.emphasize(mix, emphasis_threshold=emphasis_threshold)
        return ', '.join(mix)

    @staticmethod
    def emphasize(mix, emphasis_threshold=0.9):
        # Randomly boost some concepts
        for i in range(len(mix)):
            if random.random() > emphasis_threshold and len(mix[i]) > 0:
                if random.random() < emphasis_threshold:
                    mix[i] = "(" + mix[i] + ")"
                else:
                    random_deemphasis = random.random()
                    if random.random() > emphasis_threshold:
                        random_deemphasis *= random.randint(2, 10)
                    if random_deemphasis >= 0.1:
                        deemphasis_str = str(random_deemphasis)[:3]
                        if random_deemphasis > 1.5:
                            deemphasis_str = "1.1"
                        mix[i] = f"({mix[i]}:{deemphasis_str})"


if __name__ == "__main__":
    print(Prompter().generate_prompt())
