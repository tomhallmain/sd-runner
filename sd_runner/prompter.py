from copy import deepcopy
import json
import random
import re
import subprocess

from sd_runner.blacklist import Blacklist
from sd_runner.concepts import ConceptConfiguration, Concepts
from ui.expansion import Expansion
from utils.config import config
from utils.globals import PromptMode
from utils.logging_setup import get_logger
from extensions.image_data_extractor import ImageDataExtractor

logger = get_logger("prompter")


class LegacyPrompterConfiguration:
    """Legacy prompter configuration class for backward compatibility.
    
    Handles loading old configuration formats and converting them to PrompterConfiguration.
    """
    def __init__(
        self,
        prompt_mode: PromptMode = PromptMode.SFW,
        concepts: tuple = (1, 3),
        positions: tuple = (0, 2),
        locations: tuple = (0, 1),
        animals: tuple = (0, 1, 0.1),
        colors: tuple = (0, 2),
        times: tuple = (0, 1),
        dress: tuple = (0, 2, 0.5),
        expressions: tuple = (1, 1),
        actions: tuple = (0, 2),
        descriptions: tuple = (0, 1),
        characters: tuple = (0, 1),
        random_words: tuple = (0, 5),
        nonsense: tuple = (0, 0),
        jargon: tuple = (0, 2),
        sayings: tuple = (0, 2),
        puns: tuple = (0, 1),
        witticisms: tuple = None,
        sayings_weight: float = 1.0,
        puns_weight: float = 0.5,
        art_styles_chance: float = 0.3,
        **kwargs
    ):
        self.prompt_mode = prompt_mode
        self.concepts = concepts
        self.positions = positions
        self.locations = locations
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
        self.jargon = jargon
        self.sayings = sayings
        self.puns = puns
        self.witticisms = witticisms
        self.sayings_weight = sayings_weight
        self.puns_weight = puns_weight
        self.art_styles_chance = art_styles_chance
        # Store any additional kwargs for compatibility
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def _handle_old_types(self) -> None:
        """Handle legacy type conversions and missing attributes."""
        # Handle boolean expressions (legacy)
        if isinstance(self.expressions, bool):
            self.expressions = (1, 1) if self.expressions else (0, 0)
        
        # Handle missing original tags keys
        if not hasattr(self, 'original_positive_tags'):
            self.original_positive_tags = ""
        if not hasattr(self, 'original_negative_tags'):
            self.original_negative_tags = ""
    
    def to_prompter_configuration(self) -> "PrompterConfiguration":
        """Convert legacy configuration to new PrompterConfiguration."""
        categories = {}
        
        # Convert all categories
        category_mappings = {
            "concepts": self.concepts,
            "positions": self.positions,
            "locations": self.locations,
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
            "jargon": self.jargon,
        }
        
        for name, value in category_mappings.items():
            if isinstance(value, bool):
                # Handle legacy bool expressions
                value = (1, 1) if value else (0, 0)
            # Determine what the third element represents based on category name
            if len(value) == 3:
                if name in ["dress", "animals"]:
                    categories[name] = ConceptConfiguration.from_tuple(value, inclusion_chance=value[2])
                elif name in ["locations", "times"]:
                    categories[name] = ConceptConfiguration.from_tuple(value, specific_chance=value[2])
                else:
                    # Default: assume specific_chance
                    categories[name] = ConceptConfiguration.from_tuple(value, specific_chance=value[2])
            else:
                # For 2-element tuples, set default inclusion_chance for dress and animals
                if name == "animals":
                    categories[name] = ConceptConfiguration.from_tuple(value, inclusion_chance=0.1)
                elif name == "dress":
                    categories[name] = ConceptConfiguration.from_tuple(value, inclusion_chance=0.5)
                else:
                    categories[name] = ConceptConfiguration.from_tuple(value)
        
        # Handle witticisms - if witticisms exists, use it; otherwise calculate from sayings+puns
        # Note: Old configs won't have witticisms, only sayings and puns separately
        if self.witticisms is not None:
            categories["witticisms"] = ConceptConfiguration(
                low=self.witticisms[0],
                high=self.witticisms[1],
                subcategory_weights={"sayings": self.sayings_weight, "puns": self.puns_weight}
            )
        else:
            # Calculate from sayings+puns (for old configs that don't have witticisms yet)
            categories["witticisms"] = ConceptConfiguration(
                low=max(self.sayings[0], self.puns[0]),
                high=self.sayings[1] + self.puns[1],
                subcategory_weights={"sayings": self.sayings_weight, "puns": self.puns_weight}
            )
        
        # Create new configuration
        new_config = PrompterConfiguration(
            prompt_mode=self.prompt_mode,
            categories=categories,
            art_styles_chance=getattr(self, 'art_styles_chance', 0.3)
        )
        
        # Copy additional attributes from legacy config
        for attr in ['concepts_dir', 'multiplier', 'specify_humans_chance',
                     'emphasis_chance', 'sparse_mixed_tags', 
                     'original_positive_tags', 'original_negative_tags']:
            if hasattr(self, attr):
                setattr(new_config, attr, getattr(self, attr))
        
        # Handle legacy specific chances - update category configs if they were set separately
        if hasattr(self, 'specific_locations_chance') and 'locations' in new_config.categories:
            new_config.categories['locations'].specific_chance = self.specific_locations_chance
        if hasattr(self, 'specific_times_chance') and 'times' in new_config.categories:
            new_config.categories['times'].specific_chance = self.specific_times_chance
        
        return new_config


class PrompterConfiguration:
    # Required category names
    REQUIRED_CATEGORIES = [
        "concepts", "positions", "locations", "animals", "colors", "times",
        "dress", "expressions", "actions", "descriptions", "characters",
        "random_words", "nonsense", "jargon", "witticisms"
    ]
    
    @staticmethod
    def _get_default_categories() -> dict[str, ConceptConfiguration]:
        """Get default category configurations."""
        return {
            "concepts": ConceptConfiguration(low=1, high=3),
            "positions": ConceptConfiguration(low=0, high=2),
            "locations": ConceptConfiguration(low=0, high=1, specific_chance=0.25),
            "animals": ConceptConfiguration(low=0, high=1, inclusion_chance=0.1),
            "colors": ConceptConfiguration(low=0, high=2),
            "times": ConceptConfiguration(low=0, high=1, specific_chance=0.25),
            "dress": ConceptConfiguration(low=0, high=2, inclusion_chance=0.5),
            "expressions": ConceptConfiguration(low=1, high=1),
            "actions": ConceptConfiguration(low=0, high=2),
            "descriptions": ConceptConfiguration(low=0, high=1),
            "characters": ConceptConfiguration(low=0, high=1),
            "random_words": ConceptConfiguration(low=0, high=5),
            "nonsense": ConceptConfiguration(low=0, high=0),
            "jargon": ConceptConfiguration(low=0, high=2),
            "witticisms": ConceptConfiguration(
                low=0, 
                high=3, 
                subcategory_weights={"sayings": 1.0, "puns": 0.5}
            ),
        }
    
    def __init__(
        self,
        prompt_mode: PromptMode = PromptMode.SFW,
        categories: dict[str, ConceptConfiguration] = None,
        art_styles_chance: float = 0.3,
        concepts_dir: str = None,
        multiplier: float = 1.0,
        emphasis_chance: float = 0.1,
        sparse_mixed_tags: bool = False,
        original_positive_tags: str = "",
        original_negative_tags: str = "",
        specify_humans_chance: float = 0.25
    ):
        self.prompt_mode = prompt_mode
        self.art_styles_chance = art_styles_chance
        self.concepts_dir = concepts_dir if concepts_dir is not None else config.concepts_dirs[config.default_concepts_dir]
        self.multiplier = multiplier
        self.emphasis_chance = emphasis_chance
        self.sparse_mixed_tags = sparse_mixed_tags
        self.original_positive_tags = original_positive_tags
        self.original_negative_tags = original_negative_tags
        self.specify_humans_chance = specify_humans_chance
        
        # Initialize categories dict
        if categories is not None:
            self.categories = deepcopy(categories)
        else:
            self.categories = self._get_default_categories()
        
        # Ensure all required categories exist
        self._ensure_required_categories()
    
    def _ensure_required_categories(self):
        """Ensure all required categories exist, using defaults if missing."""
        defaults = self._get_default_categories()
        for category_name in self.REQUIRED_CATEGORIES:
            if category_name not in self.categories:
                logger.warning(f"Category {category_name} not found in categories, using default")
                self.categories[category_name] = defaults[category_name]
    
    def get_specific_locations_chance(self) -> float:
        """Get specific locations chance from category config."""
        if 'locations' not in self.categories:
            raise ValueError("'locations' category not found in categories")
        if self.categories['locations'].specific_chance is None:
            raise ValueError("'locations' category has no specific_chance set")
        return self.categories['locations'].specific_chance
    
    def get_specific_times_chance(self) -> float:
        """Get specific times chance from category config."""
        if 'times' not in self.categories:
            raise ValueError("'times' category not found in categories")
        if self.categories['times'].specific_chance is None:
            raise ValueError("'times' category has no specific_chance set")
        return self.categories['times'].specific_chance
    
    def set_category(self, name: str, low: int, high: int, specific_chance: float = None, inclusion_chance: float = None):
        """Set category from low, high, specific_chance, and inclusion_chance.
        
        Preserves existing specific_chance, inclusion_chance, and subcategory_weights if the category already exists."""
        if name in self.categories:
            # Update existing configuration, preserving subcategory_weights and other fields
            self.categories[name].update(low=low, high=high, specific_chance=specific_chance, inclusion_chance=inclusion_chance)
        else:
            self.categories[name] = ConceptConfiguration(low=low, high=high, specific_chance=specific_chance, inclusion_chance=inclusion_chance)

    def get_category_config(self, name: str) -> ConceptConfiguration:
        """Get category configuration object."""
        return self.categories.get(name, ConceptConfiguration(0, 0))
    
    def set_category_config(self, name: str, config: ConceptConfiguration):
        """Set category configuration object."""
        self.categories[name] = config
    
    def get_witticisms_weights(self) -> tuple[float, float]:
        """Get witticisms subcategory weights as (sayings_weight, puns_weight)."""
        if 'witticisms' not in self.categories:
            raise ValueError("'witticisms' category not found in categories")
        witt = self.categories['witticisms']
        if not witt.subcategory_weights:
            raise ValueError("'witticisms' category has no subcategory_weights set")
        sayings_weight = witt.subcategory_weights.get("sayings")
        puns_weight = witt.subcategory_weights.get("puns")
        if sayings_weight is None:
            raise ValueError("'witticisms' subcategory_weights missing 'sayings' key")
        if puns_weight is None:
            raise ValueError("'witticisms' subcategory_weights missing 'puns' key")
        return (sayings_weight, puns_weight)
    
    def set_witticisms_weights(self, sayings_weight: float, puns_weight: float):
        """Set witticisms subcategory weights."""
        witt = self.categories.get("witticisms")
        if witt:
            if not witt.subcategory_weights:
                witt.subcategory_weights = {}
            witt.subcategory_weights["sayings"] = sayings_weight
            witt.subcategory_weights["puns"] = puns_weight
    
    def get_witticisms_ratio(self) -> float:
        """Get witticisms ratio (0.0 = all sayings, 0.5 = equal, 1.0 = all puns).
        
        Returns the ratio of puns_weight to total weight.
        """
        sayings_weight, puns_weight = self.get_witticisms_weights()
        total_weight = sayings_weight + puns_weight
        if total_weight > 0:
            return puns_weight / total_weight
        return 0.5  # Default to equal if both are 0
    
    def set_specific_locations_chance(self, chance: float):
        """Set specific locations chance (updates category config only)."""
        if 'locations' in self.categories:
            self.categories['locations'].specific_chance = chance
    
    def set_specific_times_chance(self, chance: float):
        """Set specific times chance (updates category config only)."""
        if 'times' in self.categories:
            self.categories['times'].specific_chance = chance
    
    def to_dict(self) -> dict:
        """Convert to dictionary in new format only."""
        result = {
            "concepts_dir": self.concepts_dir,
            "prompt_mode": self.prompt_mode.name,
            "multiplier": self.multiplier,
            "art_styles_chance": self.art_styles_chance,
            "specify_humans_chance": self.specify_humans_chance,
            "emphasis_chance": self.emphasis_chance,
            "sparse_mixed_tags": self.sparse_mixed_tags,
            "original_positive_tags": self.original_positive_tags,
            "original_negative_tags": self.original_negative_tags,
        }
        
        # Save categories in new format
        categories_dict = {}
        for name, config in self.categories.items():
            categories_dict[name] = config.to_dict()
        result["categories"] = categories_dict
        
        return result

    def set_from_dict(self, _dict: dict) -> None:
        """Load from dictionary, using LegacyPrompterConfiguration for old formats."""
        # Check if this is the new format
        if 'categories' in _dict:
            # New format
            self.prompt_mode = PromptMode[_dict["prompt_mode"]]
            self.concepts_dir = _dict.get('concepts_dir', self.concepts_dir)
            
            self.categories = {}
            for name, config_dict in _dict['categories'].items():
                self.categories[name] = ConceptConfiguration.from_dict(config_dict)
            
            # Ensure all required categories exist
            self._ensure_required_categories()
        else:
            # Legacy format - convert using LegacyPrompterConfiguration
            # Handle old type conversions first
            legacy_dict = {k: v for k, v in _dict.items() if k != 'prompt_mode'}
            legacy = LegacyPrompterConfiguration(**legacy_dict)
            legacy.prompt_mode = PromptMode[_dict["prompt_mode"]]
            # Handle old types in legacy config
            legacy._handle_old_types()
            converted = legacy.to_prompter_configuration()
            self.__dict__.update(converted.__dict__)
        
        # Load non-category configuration (may override defaults from __init__)
        self.multiplier = _dict.get("multiplier", self.multiplier)
        self.art_styles_chance = _dict.get('art_styles_chance', self.art_styles_chance)
        self.specify_humans_chance = _dict.get('specify_humans_chance', self.specify_humans_chance)
        self.emphasis_chance = _dict.get('emphasis_chance', self.emphasis_chance)
        self.sparse_mixed_tags = _dict.get('sparse_mixed_tags', self.sparse_mixed_tags)
        
        # Ensure missing original tags keys exist
        if not hasattr(self, 'original_positive_tags'):
            self.original_positive_tags = ""
        if not hasattr(self, 'original_negative_tags'):
            self.original_negative_tags = ""
        self.original_positive_tags = _dict.get('original_positive_tags', self.original_positive_tags)
        self.original_negative_tags = _dict.get('original_negative_tags', self.original_negative_tags)

    def set_from_other(self, other: "PrompterConfiguration") -> None:
        if not isinstance(other, PrompterConfiguration):
            raise TypeError("Can't set from non-PrompterConfiguration")
        self.__dict__ = deepcopy(other.__dict__)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, PrompterConfiguration):
            return False
        
        # Compare all attributes except original tags
        self_dict = {k: v for k, v in self.__dict__.items() 
                    if k not in ['original_positive_tags', 'original_negative_tags']}
        other_dict = {k: v for k, v in other.__dict__.items() 
                     if k not in ['original_positive_tags', 'original_negative_tags']}
        return self_dict == other_dict
    
    def __hash__(self) -> int:
        class PromptModeEncoder(json.JSONEncoder):
            def default(self, z):
                if isinstance(z, PromptMode):
                    return str(z.name)
                elif isinstance(z, ConceptConfiguration):
                    return z.to_dict()
                else:
                    return super().default(z)
        
        # Create dict excluding original tags for hashing
        # Convert categories dict to a serializable format
        hash_dict = {k: v for k, v in self.__dict__.items() 
                    if k not in ['original_positive_tags', 'original_negative_tags']}
        # Convert categories dict values to dicts for JSON serialization
        if 'categories' in hash_dict:
            hash_dict['categories'] = {k: v.to_dict() for k, v in hash_dict['categories'].items()}
        return hash(json.dumps(hash_dict, cls=PromptModeEncoder, sort_keys=True))


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
        get_specific_times: bool = False,
        prompt_list: list[str] = []
    ):
        self.reference_image_path = reference_image_path
        self.llava_path = llava_path
        self.prompter_config = prompter_config
        self.prompt_mode = prompter_config.prompt_mode
        self.concepts = Concepts(prompter_config.prompt_mode, get_specific_locations=get_specific_locations, get_specific_times=get_specific_times, concepts_dir=prompter_config.concepts_dir)
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
            positive = self.apply_expansions(positive, concepts=self.concepts, specific_locations_chance=self.prompter_config.get_specific_locations_chance())
        if Prompter.contains_expansion_var(negative):
            negative = self.apply_expansions(negative, concepts=self.concepts, specific_locations_chance=self.prompter_config.get_specific_locations_chance())
        if Prompter.contains_choice_set(positive):
            positive = self.apply_choices(positive)
        if Prompter.contains_choice_set(negative):
            negative = self.apply_choices(negative)
        
        # Validate final prompts against blacklist
        positive_concepts = [c.strip() for c in positive.split(',')]
        positive_whitelist, positive_filtered = Blacklist.filter_concepts(positive_concepts, prompt_mode=self.prompt_mode)
        
        # Reconstruct the prompts with only whitelisted concepts if needed
        if len(positive_filtered) > 0:
            positive = ', '.join(positive_whitelist)
            if config.debug:
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
        random_words = self.concepts.get_random_words(*self.prompter_config.get_category_config("random_words"), multiplier=self.prompter_config.multiplier)
        Prompter.emphasize(random_words, emphasis_chance=self.prompter_config.emphasis_chance)
        return ', '.join(random_words)

    def nonsense(self) -> str:
        nonsense = self.concepts.get_nonsense(*self.prompter_config.get_category_config("nonsense"), multiplier=self.prompter_config.multiplier)
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
        # Access categories directly from the categories dict
        mix.extend(self.concepts.get_concepts(self.prompter_config.get_category_config("concepts"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_positions(self.prompter_config.get_category_config("positions"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_locations(self.prompter_config.get_category_config("locations"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_animals(self.prompter_config.get_category_config("animals"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_colors(self.prompter_config.get_category_config("colors"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_times(self.prompter_config.get_category_config("times"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_dress(self.prompter_config.get_category_config("dress"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_expressions(self.prompter_config.get_category_config("expressions"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_actions(self.prompter_config.get_category_config("actions"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_descriptions(self.prompter_config.get_category_config("descriptions"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_characters(self.prompter_config.get_category_config("characters"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_random_words(self.prompter_config.get_category_config("random_words"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_nonsense(self.prompter_config.get_category_config("nonsense"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_jargon(self.prompter_config.get_category_config("jargon"), multiplier=self.prompter_config.multiplier))
        mix.extend(self.concepts.get_witticisms(self.prompter_config.get_category_config("witticisms"), multiplier=self.prompter_config.multiplier))
        # Humans might not always be desirable so only add some randomly
        if self.prompt_mode == PromptMode.SFW:
            if random.random() < humans_chance:
                humans_config = self.prompter_config.get_category_config("humans")
                mix.extend(self.concepts.get_humans(humans_config, multiplier=self.prompter_config.multiplier))
        # Small chance to add artist style
        if not self.concepts.is_art_style_prompt_mode() and random.random() < self.prompter_config.art_styles_chance:
            if config.debug:
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
        return ', '.join(self.concepts.get_colors(ConceptConfiguration(2, 5)))

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
                humans_config = ConceptConfiguration(1, 1)  # Default humans config
                mix.extend(self.concepts.get_humans(humans_config))
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
    def _find_matching_bracket(text: str, start_pos: int, open_char: str = "[", close_char: str = "]") -> int:
        """
        Finds the matching closing bracket for an opening bracket at start_pos.
        Returns the position of the matching closing bracket, or -1 if not found.
        """
        if start_pos >= len(text) or text[start_pos] != open_char:
            return -1
        
        depth = 0
        i = start_pos
        while i < len(text):
            if text[i] == open_char:
                depth += 1
            elif text[i] == close_char:
                depth -= 1
                if depth == 0:
                    return i
            i += 1
        return -1

    @staticmethod
    def _expand_nested_choices(text: str) -> list[tuple[str, float]]:
        """
        Recursively expands nested [choice1,choice2] patterns in text.
        Returns a list of (expansion, weight) tuples for all possible combinations.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.debug(f"Starting expansion with text: '{text}'")
        
        result = [(text, 1.0)]
        changed = True
        iteration = 0
        
        while changed:
            iteration += 1
            logger.debug(f"=== Starting iteration {iteration} ===")
            logger.debug(f"Current result count: {len(result)}")
            
            changed = False
            new_result = []
            
            for base_text, base_weight in result:
                logger.debug(f"Processing base_text: '{base_text}' with weight: {base_weight}")
                
                i = 0
                while i < len(base_text):
                    if base_text[i] == "[":
                        logger.debug(f"Found opening bracket at position {i}")
                        
                        # Find matching closing bracket
                        close_pos = Prompter._find_matching_bracket(base_text, i, "[", "]")
                        
                        if close_pos == -1:
                            logger.debug("No matching closing bracket found, skipping")
                            i += 1
                            continue
                        
                        logger.debug(f"Found matching closing bracket at position {close_pos}")
                        
                        # Extract the nested choice set content
                        nested_content = base_text[i + 1:close_pos]
                        logger.debug(f"Nested content: '{nested_content}'")
                        
                        # Split by top-level commas (respecting bracket depth)
                        options = []
                        current_option = ""
                        depth = 0
                        for char in nested_content:
                            if char == "[":
                                depth += 1
                                current_option += char
                            elif char == "]":
                                depth -= 1
                                current_option += char
                            elif char == "," and depth == 0:
                                if current_option.strip():
                                    options.append(current_option.strip())
                                current_option = ""
                            else:
                                current_option += char
                        if current_option.strip():
                            options.append(current_option.strip())
                        
                        # LOGGING POINT 5: Options found
                        logger.debug(f"Found {len(options)} options: {options}")
                        
                        # If no commas found, treat entire content as one option
                        if not options:
                            options = [nested_content]
                        
                        # Recursively expand each option
                        expanded_options = []
                        for option in options:
                            # Extract weight if present
                            weight = 1.0
                            option_text = option
                            if ":" in option:
                                # Check if colon is outside all brackets
                                colon_pos = -1
                                depth = 0
                                for j, char in enumerate(option):
                                    if char == "[":
                                        depth += 1
                                    elif char == "]":
                                        depth -= 1
                                    elif char == ":" and depth == 0:
                                        colon_pos = j
                                
                                if colon_pos != -1:
                                    try:
                                        weight = float(option[colon_pos + 1:])
                                        option_text = option[:colon_pos].strip()
                                        logger.debug(f"Found weight {weight} for option '{option_text}'")
                                    except ValueError:
                                        pass
                            
                            logger.debug(f"Recursively expanding option: '{option_text}'")
                            sub_expansions = Prompter._expand_nested_choices(option_text)
                            
                            # Add each expansion with its weight
                            for sub_exp, sub_weight in sub_expansions:
                                # Multiply weights (nested weight * parent weight)
                                expanded_options.append((sub_exp, weight * sub_weight))
                        
                        logger.debug(f"Generated {len(expanded_options)} expanded options")
                        
                        # Generate all combinations by replacing the nested pattern
                        for expanded_option, exp_weight in expanded_options:
                            new_text = base_text[:i] + expanded_option + base_text[close_pos + 1:]
                            # Multiply weights
                            new_result.append((new_text, base_weight * exp_weight))
                            logger.debug(f"Added new result: '{new_text}' with weight {base_weight * exp_weight}")
                        
                        changed = True
                        break  # Move to next base_text after processing this pattern
                    else:
                        i += 1
                
                if not changed:
                    new_result.append((base_text, base_weight))
            
            logger.debug(f"End of iteration {iteration}. Changed: {changed}, New result count: {len(new_result)}")
            
            if iteration > 20:  # Arbitrary limit to prevent infinite loops
                logger.warning(f"Stopping expansion after {iteration} iterations to prevent infinite loop")
                break
                
            result = new_result
        
        logger.debug(f"Final result count: {len(result)}")
        for i, (res_text, res_weight) in enumerate(result):
            logger.debug(f"Result {i+1}: '{res_text}' with weight {res_weight}")
        
        return result

    @staticmethod
    def contains_choice_set(text: str) -> bool:
        if "[[" not in text or "]]" not in text:
            return False
        # Check for [[...]] pattern (may contain nested brackets)
        i = 0
        while i < len(text) - 1:
            if text[i:i+2] == "[[":
                close_pos = Prompter._find_matching_bracket(text, i + 1, "[", "]")
                if close_pos != -1 and close_pos < len(text) - 1 and text[close_pos + 1] == "]":
                    return True
            i += 1
        return False

    @staticmethod
    def apply_choices(text: str) -> str:
        """
        Applies choice set expansion, supporting nested [choice1,choice2] patterns
        inside [[choice1,choice2]] choice sets.
        """
        import logging
        logger = logging.getLogger(__name__)
        
        offset = 0
        i = 0
        original_text = text
        max_iterations = len(text) * 10  # Arbitrary large number
        iteration = 0
        
        while i < len(original_text) - 1 and iteration < max_iterations:
            iteration += 1
            
            # Look for [[ pattern in the original text
            if original_text[i:i+2] == "[[":
                # Find the matching ]] bracket pair in the original text
                # First find the inner ] bracket
                inner_close = Prompter._find_matching_bracket(original_text, i + 1, "[", "]")
                if inner_close == -1:
                    i += 1
                    continue
                
                # Check if next character is ]
                if inner_close + 1 >= len(original_text) or original_text[inner_close + 1] != "]":
                    i += 1
                    continue
                
                # We have a valid [[...]] pattern
                outer_start = i
                outer_end = inner_close + 2
                
                # Extract the inner content (between the double brackets)
                inner_content = original_text[outer_start + 2:inner_close]
                
                # Split by top-level commas (respecting bracket depth)
                options = []
                current_option = ""
                depth = 0
                for char in inner_content:
                    if char == "[":
                        depth += 1
                        current_option += char
                    elif char == "]":
                        depth -= 1
                        current_option += char
                    elif char == "," and depth == 0:
                        if current_option.strip():
                            options.append(current_option.strip())
                        current_option = ""
                    else:
                        current_option += char
                if current_option.strip():
                    options.append(current_option.strip())
                
                # If no commas found, treat entire content as one option
                if not options:
                    options = [inner_content]
                
                # Expand nested choices in each option and build final population
                population = []
                weights = []
                
                for option in options:
                    # Extract weight if present (at the end, after any nested brackets)
                    weight = 1.0
                    option_text = option
                    
                    # Find weight (colon after the last bracket or at end)
                    if ":" in option:
                        # Check if colon is outside all brackets
                        colon_pos = -1
                        depth = 0
                        for j, char in enumerate(option):
                            if char == "[":
                                depth += 1
                            elif char == "]":
                                depth -= 1
                            elif char == ":" and depth == 0:
                                colon_pos = j
                        
                        if colon_pos != -1:
                            try:
                                weight = float(option[colon_pos + 1:])
                                option_text = option[:colon_pos].strip()
                            except ValueError:
                                pass
                    
                    # Expand nested [choice1,choice2] patterns in this option
                    expanded = Prompter._expand_nested_choices(option_text)
                    
                    # Add all expansions to population
                    # Multiply outer weight with nested weights
                    for exp, nested_weight in expanded:
                        population.append(exp)
                        weights.append(weight * nested_weight)
                
                # Randomly select one option
                if population:
                    choice = random.choices(population=population, weights=weights, k=1)[0]
                    
                    # Calculate the adjusted position in the current text with offset
                    adjusted_start = outer_start + offset
                    adjusted_end = outer_end + offset
                    
                    # Replace the pattern in the current text
                    text = text[:adjusted_start] + choice + text[adjusted_end:]
                    
                    # Update offset based on the length difference
                    offset += len(choice) - (outer_end - outer_start)
                    
                    # Continue from after the original position in the original text
                    i = outer_end
                else:
                    i += 1
            else:
                i += 1
        
        if iteration >= max_iterations:
            logger.warning(f"apply_choices stopped after {max_iterations} iterations to prevent infinite loop")
        
        return text

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
    def _select_concept(name: str, concepts: Concepts, specific_locations_chance: float = 0.3) -> str:
        concept = None
        if name.startswith("act"):
            concept = random.choice(concepts.get_actions(ConceptConfiguration(1, 1)))
        elif name.startswith("concept"):
            concept = random.choice(concepts.get_concepts(ConceptConfiguration(1, 1)))
        elif name == "dress":
            concept = random.choice(concepts.get_dress(ConceptConfiguration(1, 1, inclusion_chance=1.0)))
        elif name.startswith("time"):
            concept = random.choice(concepts.get_times(ConceptConfiguration(1, 1)))
        elif name.startswith("expr"):
            concept = random.choice(concepts.get_expressions(ConceptConfiguration(1, 1)))
        elif name.startswith("animal"):
            concept = random.choice(concepts.get_animals(ConceptConfiguration(1, 1, inclusion_chance=1.0)))
        elif name.startswith("desc"):
            concept = random.choice(concepts.get_descriptions(ConceptConfiguration(1, 1)))
        elif name == "random_word":
            concept = random.choice(concepts.get_random_words(ConceptConfiguration(1, 1)))
        elif name.startswith("nons"):
            concept = random.choice(concepts.get_nonsense(ConceptConfiguration(1, 1)))
        elif name.startswith("color"):
            concept = random.choice(concepts.get_colors(ConceptConfiguration(1, 1)))
        elif name.startswith("loc"):
            concept = random.choice(concepts.get_locations(ConceptConfiguration(1, 1, specific_chance=specific_locations_chance)))
        elif name.startswith("human"):
            concept = random.choice(concepts.get_humans(ConceptConfiguration(1, 1)))
        elif name.startswith("posit"):
            concept = random.choice(concepts.get_positions(ConceptConfiguration(1, 1)))
        elif name.startswith("witt"):
            concept = random.choice(concepts.get_witticisms(ConceptConfiguration.from_subcategory_list(1, 1, ["sayings", "puns"])))
        elif name.startswith("saying"):
            concept = random.choice(concepts.get_witticisms(ConceptConfiguration.from_subcategory_list(1, 1, ["sayings"])))
        elif name.startswith("pun"):
            concept = random.choice(concepts.get_witticisms(ConceptConfiguration.from_subcategory_list(1, 1, ["puns"])))
        elif name.startswith("jarg"):
            concept = random.choice(concepts.get_jargon(ConceptConfiguration(1, 1)))
        elif name.startswith("number"):
            concept = str(random.randint(1, 999))
        return concept

    @staticmethod
    def _get_concept_expansion(name: str, concepts: Concepts, specific_locations_chance: float = 0.3) -> str:
        concept = Prompter._select_concept(name, concepts, specific_locations_chance)
        if concept is None:
            return None
        elif "$$" in concept and random.random() < 0.5:
            # Slightly reduce chance of more prompt expansion nesting
            concept = Prompter._select_concept(name, concepts, specific_locations_chance)
        return concept

    @staticmethod
    def _expand_one_pass(
        text: str,
        from_ui: bool = False,
        concepts: Concepts = None,
        specific_locations_chance: float = 0.3
    ) -> tuple[str, bool]:
        """
        Performs a single pass of expansion on the text.
        Returns: (expanded_text, has_more_expansions)
        """
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
                replacement = Prompter._get_concept_expansion(name, concepts, specific_locations_chance)
            if replacement is None:
                logger.error(f"Invalid prompt replacement ID: \"{name}\"")
                continue
            text = left + replacement + right
            offset += len(replacement) - original_length
        
        # Check if the result still contains expansion variables
        has_more = Prompter.contains_expansion_var(text, from_ui=from_ui)
        return str(text), has_more

    @staticmethod
    def apply_expansions(
        text: str,
        from_ui: bool = False,
        concepts: Concepts = None,
        specific_locations_chance: float = 0.3
    ) -> str:
        """
        Applies prompt expansions recursively until no more expansion variables are found.
        When from_ui=False, converts $$var to $var before expanding.
        
        Note: Self-referencing (e.g., wildcard1 = "$wildcard1") or circular references
        (e.g., wildcard1 = "$wildcard2", wildcard2 = "$wildcard1") will cause the
        expansion to stop after max_iterations, with a warning logged. The maximum
        iteration limit prevents infinite loops in such cases.
        """
        max_iterations = 10
        iteration = 0
        current_text = text

        while Prompter.contains_expansion_var(current_text, from_ui=from_ui) and iteration < max_iterations:
            # Convert $$var to $var when not in UI mode (for final expansion)
            if not from_ui:
                current_text = re.sub(r'\$\$([A-Za-z_]+)', r'$\1', current_text)
            
            # Perform one expansion pass
            current_text, has_more = Prompter._expand_one_pass(
                current_text, 
                from_ui=from_ui, 
                concepts=concepts, 
                specific_locations_chance=specific_locations_chance
            )
            
            iteration += 1
            
            # If no expansions were made or no more expansions exist, break
            if not has_more:
                break

        if iteration >= max_iterations:
            logger.warning(f"Reached maximum expansion iterations ({max_iterations}). Some variables may not be expanded.")

        return str(current_text)


class GlobalPrompter:
    prompter_instance = Prompter()

    @classmethod
    def set_prompter(cls, prompter_config: PrompterConfiguration, get_specific_locations: bool, get_specific_times: bool = False, prompt_list: list[str] = []):
        cls.prompter_instance = Prompter(prompter_config=prompter_config, get_specific_locations=get_specific_locations, get_specific_times=get_specific_times, prompt_list=prompt_list)


if __name__ == "__main__":
    print(Prompter().generate_prompt())
