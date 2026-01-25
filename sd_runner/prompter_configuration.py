from copy import deepcopy

import json

from sd_runner.concepts import ConceptConfiguration
from utils.config import config
from utils.globals import PromptMode


class LegacyPrompterConfiguration:
    """Legacy prompter configuration class for backward compatibility.
    
    Handles loading old configuration formats and converting them to PrompterConfiguration.
    """
    def __init__(
        self,
        prompt_mode: PromptMode = PromptMode.SFW,
        concepts: tuple = (1, 3),
        positions: tuple = (0, 2),
        locations: tuple = (0, 1, 0.3),
        animals: tuple = (0, 1, 0.1),
        colors: tuple = (0, 2),
        times: tuple = (0, 1, 0.3),
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
            "locations": ConceptConfiguration(low=0, high=1, specific_chance=0.3),
            "animals": ConceptConfiguration(low=0, high=1, inclusion_chance=0.1),
            "colors": ConceptConfiguration(low=0, high=2),
            "times": ConceptConfiguration(low=0, high=1, specific_chance=0.3),
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
            # Return default value from default category configurations
            try:
                return self.get_default_categories()['locations'].specific_chance
            except KeyError:
                return 0.3
        return self.categories['locations'].specific_chance
    
    def get_specific_times_chance(self) -> float:
        """Get specific times chance from category config."""
        if 'times' not in self.categories:
            raise ValueError("'times' category not found in categories")
        if self.categories['times'].specific_chance is None:
            # Return default value from default category configurations
            try:
                return self.get_default_categories()['times'].specific_chance
            except KeyError:
                return 0.3
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
        # Sort category keys for consistent hashing
        if 'categories' in hash_dict:
            hash_dict['categories'] = {k: v.to_dict() for k, v in sorted(hash_dict['categories'].items())}
        return hash(json.dumps(hash_dict, cls=PromptModeEncoder, sort_keys=True))


