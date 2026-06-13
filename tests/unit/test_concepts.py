import random
import pytest

from sd_runner.blacklist import Blacklist, BlacklistItem
from sd_runner.concepts import (
    ConceptConfiguration,
    ConceptsFile,
    Concepts,
    weighted_sample_without_replacement,
    sample,
)
from utils.globals import PromptMode


# ---------------------------------------------------------------------------
# ConceptConfiguration — data class
# ---------------------------------------------------------------------------

class TestConceptConfigurationGetAdjustedRange:
    def test_multiplier_one_returns_original(self):
        cc = ConceptConfiguration(low=2, high=5)
        assert cc.get_adjusted_range(1.0) == (2, 5)

    def test_multiplier_zero_returns_zero_zero(self):
        cc = ConceptConfiguration(low=2, high=5)
        assert cc.get_adjusted_range(0) == (0, 0)

    def test_multiplier_two_scales_up(self):
        cc = ConceptConfiguration(low=2, high=4)
        lo, hi = cc.get_adjusted_range(2.0)
        assert lo >= 2
        assert hi >= lo

    def test_multiplier_half_scales_down(self):
        cc = ConceptConfiguration(low=4, high=8)
        lo, hi = cc.get_adjusted_range(0.5)
        assert lo < 4
        assert hi <= 8

    def test_inverted_range_clamped_at_multiplier_one(self):
        cc = ConceptConfiguration(low=5, high=2)
        lo, hi = cc.get_adjusted_range(1.0)
        assert lo == hi == 5

    def test_nonzero_low_never_rounds_to_zero(self):
        cc = ConceptConfiguration(low=1, high=3)
        lo, hi = cc.get_adjusted_range(0.01)
        assert lo >= 1


class TestConceptConfigurationDefaults:
    def test_get_specific_inclusion_chance_default(self):
        cc = ConceptConfiguration(low=0, high=1)
        assert cc.get_specific_inclusion_chance() == 0.3

    def test_get_specific_inclusion_chance_explicit(self):
        cc = ConceptConfiguration(low=0, high=1, specific_chance=0.7)
        assert cc.get_specific_inclusion_chance() == 0.7

    def test_get_inclusion_chance_default(self):
        cc = ConceptConfiguration(low=0, high=1)
        assert cc.get_inclusion_chance() == 0.5

    def test_get_inclusion_chance_explicit(self):
        cc = ConceptConfiguration(low=0, high=1, inclusion_chance=0.8)
        assert cc.get_inclusion_chance() == 0.8

    def test_get_total_subcategory_weight_empty(self):
        cc = ConceptConfiguration(low=0, high=1)
        assert cc.get_total_subcategory_weight() == 0.0

    def test_get_total_subcategory_weight_sums_values(self):
        cc = ConceptConfiguration(low=0, high=1,
                                  subcategory_weights={"a.txt": 1.0, "b.txt": 2.0})
        assert cc.get_total_subcategory_weight() == 3.0


class TestConceptConfigurationFromTuple:
    def test_two_element_tuple(self):
        cc = ConceptConfiguration.from_tuple((2, 5))
        assert cc.low == 2 and cc.high == 5
        assert cc.specific_chance is None

    def test_three_element_tuple_uses_third_as_specific_chance(self):
        cc = ConceptConfiguration.from_tuple((2, 5, 0.4))
        assert cc.specific_chance == 0.4

    def test_three_element_tuple_kwarg_overrides(self):
        cc = ConceptConfiguration.from_tuple((2, 5, 0.4), specific_chance=0.9)
        assert cc.specific_chance == 0.9

    def test_invalid_tuple_length_raises(self):
        with pytest.raises((ValueError, Exception)):
            ConceptConfiguration.from_tuple((1,))


class TestConceptConfigurationFromSubcategoryList:
    def test_equal_weights_assigned(self):
        cc = ConceptConfiguration.from_subcategory_list(1, 3, ["a.txt", "b.txt"])
        assert cc.subcategory_weights == {"a.txt": 1.0, "b.txt": 1.0}
        assert cc.low == 1 and cc.high == 3


class TestConceptConfigurationDictRoundTrip:
    def test_basic_round_trip(self):
        cc = ConceptConfiguration(low=1, high=4)
        assert ConceptConfiguration.from_dict(cc.to_dict()) == cc

    def test_round_trip_with_optional_fields(self):
        cc = ConceptConfiguration(low=0, high=2, specific_chance=0.6, inclusion_chance=0.3)
        assert ConceptConfiguration.from_dict(cc.to_dict()) == cc

    def test_round_trip_with_subcategories(self):
        cc = ConceptConfiguration(low=1, high=3,
                                  subcategory_weights={"x.txt": 2.0, "y.txt": 1.0})
        assert ConceptConfiguration.from_dict(cc.to_dict()) == cc

    def test_from_dict_missing_keys_defaults_to_zero(self):
        cc = ConceptConfiguration.from_dict({})
        assert cc.low == 0 and cc.high == 0


class TestConceptConfigurationEqualityAndHash:
    def test_equal_configs(self):
        a = ConceptConfiguration(low=1, high=3)
        b = ConceptConfiguration(low=1, high=3)
        assert a == b

    def test_not_equal_different_low(self):
        assert ConceptConfiguration(low=1, high=3) != ConceptConfiguration(low=2, high=3)

    def test_not_equal_different_specific_chance(self):
        a = ConceptConfiguration(low=1, high=3, specific_chance=0.5)
        b = ConceptConfiguration(low=1, high=3, specific_chance=0.7)
        assert a != b

    def test_not_equal_to_other_type(self):
        assert ConceptConfiguration(low=1, high=2) != (1, 2)

    def test_hash_equal_for_equal_configs(self):
        a = ConceptConfiguration(low=2, high=4)
        b = ConceptConfiguration(low=2, high=4)
        assert hash(a) == hash(b)

    def test_update_changes_values(self):
        cc = ConceptConfiguration(low=1, high=3)
        cc.update(5, 10)
        assert cc.low == 5 and cc.high == 10


# ---------------------------------------------------------------------------
# Module-level functions: weighted_sample_without_replacement, sample
# ---------------------------------------------------------------------------

class TestWeightedSampleWithoutReplacement:
    def test_returns_k_items(self):
        pop = ["a", "b", "c", "d", "e"]
        weights = [1.0] * 5
        result = weighted_sample_without_replacement(pop, weights, k=3)
        assert len(result) == 3

    def test_no_duplicates(self):
        pop = list("abcdefghij")
        weights = [1.0] * 10
        for _ in range(50):
            result = weighted_sample_without_replacement(pop, weights, k=5)
            assert len(result) == len(set(result))

    def test_items_from_population(self):
        pop = ["cat", "dog", "fish"]
        result = weighted_sample_without_replacement(pop, [1.0, 1.0, 1.0], k=2)
        assert all(item in pop for item in result)

    def test_zero_weight_item_never_selected(self):
        pop = ["always", "never"]
        for _ in range(100):
            result = weighted_sample_without_replacement(pop, [1.0, 0.0], k=1)
            assert result == ["always"]

    def test_k_one_returns_single_item(self):
        pop = ["x", "y", "z"]
        result = weighted_sample_without_replacement(pop, [1.0, 1.0, 1.0], k=1)
        assert len(result) == 1 and result[0] in pop


class TestSampleFunction:
    def test_list_returns_k_items_in_range(self):
        lst = list(range(20))
        result = sample(lst, low=3, high=6)
        assert 3 <= len(result) <= 6

    def test_list_no_duplicates(self):
        lst = list(range(50))
        result = sample(lst, low=5, high=10)
        assert len(result) == len(set(result))

    def test_dict_returns_weighted_sample(self):
        d = {"a": 1.0, "b": 1.0, "c": 1.0}
        result = sample(d, low=2, high=2)
        assert len(result) == 2
        assert all(item in d for item in result)

    def test_high_clipped_to_population_size(self):
        lst = ["x", "y", "z"]
        result = sample(lst, low=1, high=100)
        assert len(result) <= len(lst)

    def test_invalid_type_raises(self):
        with pytest.raises(Exception):
            sample("not a list or dict", 1, 2)


# ---------------------------------------------------------------------------
# Concepts.sample_whitelisted — static method
# ---------------------------------------------------------------------------

class TestSampleWhitelisted:
    def test_zero_range_returns_empty(self):
        result = Concepts.sample_whitelisted(["a", "b", "c"], 0, 0, PromptMode.SFW)
        assert result == []

    def test_empty_list_with_zero_low_returns_empty(self):
        result = Concepts.sample_whitelisted([], 0, 3, PromptMode.SFW)
        assert result == []

    def test_empty_list_with_nonzero_low_raises(self):
        with pytest.raises(Exception):
            Concepts.sample_whitelisted([], 1, 3, PromptMode.SFW)

    def test_samples_from_list_when_no_blacklist(self):
        concepts = ["sun", "moon", "star", "cloud", "rain"]
        result = Concepts.sample_whitelisted(concepts, 2, 3, PromptMode.SFW)
        assert 2 <= len(result) <= 3
        assert all(c in concepts for c in result)

    def test_blacklisted_items_excluded(self):
        Blacklist.add_item(BlacklistItem("bad"))
        concepts = ["good", "bad", "neutral", "fine", "ok"]
        for _ in range(20):
            result = Concepts.sample_whitelisted(concepts, 1, 3, PromptMode.SFW)
            assert "bad" not in result

    def test_dict_input_weighted_sampling(self):
        d = {"alpha": 2.0, "beta": 1.0, "gamma": 1.0}
        result = Concepts.sample_whitelisted(d, 1, 2, PromptMode.SFW)
        assert 1 <= len(result) <= 2
        assert all(item in d for item in result)

    def test_dict_input_blacklisted_key_excluded(self):
        Blacklist.add_item(BlacklistItem("blocked"))
        d = {"safe": 1.0, "blocked": 1.0, "also_safe": 1.0}
        for _ in range(20):
            result = Concepts.sample_whitelisted(d, 1, 2, PromptMode.SFW)
            assert "blocked" not in result


# ---------------------------------------------------------------------------
# ConceptsFile.load — parses concepts and strips comments
# ---------------------------------------------------------------------------

class TestConceptsFileLoad:
    def test_loads_concepts_from_file(self, tmp_path):
        f = tmp_path / "test_concepts.txt"
        f.write_text("apple\nbanana\ncherry\n")
        cf = ConceptsFile(str(f))
        assert cf.concepts == ["apple", "banana", "cherry"]

    def test_strips_comment_lines(self, tmp_path):
        f = tmp_path / "test_concepts.txt"
        f.write_text("# this is a comment\napple\n# another comment\nbanana\n")
        cf = ConceptsFile(str(f))
        assert cf.concepts == ["apple", "banana"]

    def test_inline_comments_stripped(self, tmp_path):
        f = tmp_path / "test_concepts.txt"
        f.write_text("apple # juicy fruit\nbanana\n")
        cf = ConceptsFile(str(f))
        assert "apple" in cf.concepts
        assert not any("#" in c for c in cf.concepts)

    def test_blank_lines_ignored(self, tmp_path):
        f = tmp_path / "test_concepts.txt"
        f.write_text("apple\n\n\nbanana\n")
        cf = ConceptsFile(str(f))
        assert cf.concepts == ["apple", "banana"]

    def test_missing_file_gives_empty_lists(self, tmp_path):
        cf = ConceptsFile(str(tmp_path / "nonexistent.txt"))
        assert cf.concepts == []
        assert cf.lines == []

    def test_concept_indices_built(self, tmp_path):
        f = tmp_path / "test_concepts.txt"
        f.write_text("apple\nbanana\n")
        cf = ConceptsFile(str(f))
        assert "apple" in cf.concept_indices
        assert "banana" in cf.concept_indices
