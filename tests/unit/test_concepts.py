import random
import pytest

from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.prompts.concepts import (
    ConceptConfiguration,
    ConceptsFile,
    Concepts,
    weighted_sample_without_replacement,
    sample,
)
from sd_runner.globals import PromptMode


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

    def test_empty_list_with_nonzero_low_is_skipped_not_fatal(self):
        """A category with no source is inert, not an error.

        This used to raise. A concepts directory is not required to carry
        every file -- a translated set may simply not have one yet -- and
        raising failed the whole generation over a category the user could not
        have known was missing.
        """
        assert Concepts.sample_whitelisted([], 1, 3, PromptMode.SFW) == []

    def test_a_fully_blacklisted_list_still_raises(self):
        """Different case, deliberately kept: the user did that to themselves.

        Nothing available because it was all blocked is actionable; nothing
        available because the file is absent is not.
        """
        Blacklist.add_item(BlacklistItem("blocked"))
        with pytest.raises(Exception):
            Concepts.sample_whitelisted(["blocked"], 1, 1, PromptMode.SFW)

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


# ---------------------------------------------------------------------------
# Concepts.get_with_subcategories — proportional sampling across weighted files
#
# Backs get_witticisms(), whose category config carries
# {"sayings": 1.0, "puns": 0.5}. A subcategory whose file fails to load is
# skipped with a warning, which can leave the result short or empty -- the case
# that used to reach random.choice() in Prompter._select_concept.
# ---------------------------------------------------------------------------

class TestGetWithSubcategories:
    FILES = {
        "sayings.txt": [f"saying_{i}" for i in range(40)],
        "puns.txt": [f"pun_{i}" for i in range(40)],
    }

    @pytest.fixture(autouse=True)
    def subcategory_files(self, monkeypatch):
        monkeypatch.setattr(Concepts, "ensure_dictionary_loaded", staticmethod(lambda: None))
        monkeypatch.setattr(
            Concepts, "load",
            staticmethod(lambda filename: list(TestGetWithSubcategories.FILES.get(filename, []))),
        )

    def _concepts(self):
        return Concepts(PromptMode.SFW, get_specific_locations=False)

    def _config(self, low, high, weights=None):
        return ConceptConfiguration(
            low=low, high=high,
            subcategory_weights=weights if weights is not None else {"sayings.txt": 1.0, "puns.txt": 0.5},
        )

    def test_zero_range_returns_empty(self):
        assert self._concepts().get_with_subcategories(self._config(0, 0)) == []

    def test_zero_total_weight_returns_empty(self):
        config = self._config(2, 4, weights={"sayings.txt": 0.0, "puns.txt": 0.0})
        assert self._concepts().get_with_subcategories(config) == []

    def test_no_subcategories_returns_empty(self):
        assert self._concepts().get_with_subcategories(self._config(2, 4, weights={})) == []

    def test_count_within_requested_range(self):
        concepts = self._concepts()
        for _ in range(25):
            assert 2 <= len(concepts.get_with_subcategories(self._config(2, 5))) <= 5

    def test_fixed_range_returns_exactly_that_many(self):
        concepts = self._concepts()
        for _ in range(25):
            assert len(concepts.get_with_subcategories(self._config(4, 4))) == 4

    def test_all_items_come_from_the_subcategory_files(self):
        concepts = self._concepts()
        allowed = set(self.FILES["sayings.txt"]) | set(self.FILES["puns.txt"])
        for _ in range(25):
            assert set(concepts.get_with_subcategories(self._config(3, 6))) <= allowed

    def test_heavier_weight_contributes_more(self):
        """sayings is weighted 1.0 against puns at 0.5, so it should dominate."""
        concepts = self._concepts()
        sayings = puns = 0
        for _ in range(80):
            for item in concepts.get_with_subcategories(self._config(6, 6)):
                if item.startswith("saying_"):
                    sayings += 1
                else:
                    puns += 1
        assert sayings > puns

    def test_single_subcategory_supplies_everything(self):
        config = self._config(5, 5, weights={"puns.txt": 1.0})
        result = self._concepts().get_with_subcategories(config)
        assert len(result) == 5
        assert all(item.startswith("pun_") for item in result)

    def test_missing_file_is_skipped_not_fatal(self, monkeypatch):
        """An unreadable subcategory file warns and is skipped rather than raising."""
        monkeypatch.setattr(
            Concepts, "load",
            staticmethod(lambda filename: [] if filename == "puns.txt"
                         else list(TestGetWithSubcategories.FILES[filename])),
        )
        result = self._concepts().get_with_subcategories(self._config(4, 4))
        assert all(item.startswith("saying_") for item in result)

    def test_every_file_failing_yields_empty_rather_than_raising(self, monkeypatch):
        monkeypatch.setattr(Concepts, "load", staticmethod(lambda filename: []))
        assert self._concepts().get_with_subcategories(self._config(4, 4)) == []

    def test_raising_loader_is_caught(self, monkeypatch):
        def boom(filename):
            raise OSError("unreadable")
        monkeypatch.setattr(Concepts, "load", staticmethod(boom))
        # ensure_dictionary_loaded is already stubbed, so construction is safe.
        assert self._concepts().get_with_subcategories(self._config(4, 4)) == []

    def test_multiplier_scales_the_range(self):
        concepts = self._concepts()
        base = self._config(2, 2)
        assert len(concepts.get_with_subcategories(base, multiplier=0)) == 0
        assert len(concepts.get_with_subcategories(base, multiplier=1)) == 2

    @pytest.mark.parametrize("total", [1, 2, 3, 4, 5, 6, 7])
    def test_equal_weights_never_over_allocate(self, total):
        """Regression: the per-subcategory cap compared against the full total.

        With equal weights each subcategory rounds the same way, so an odd total
        allocated one extra item per subcategory that rounded up (3 -> 2 + 2).
        """
        config = self._config(total, total, weights={"sayings.txt": 1.0, "puns.txt": 1.0})
        assert len(self._concepts().get_with_subcategories(config)) == total

    @pytest.mark.parametrize("total", [1, 2, 3, 4, 5, 6, 7])
    def test_three_equal_weights_never_over_allocate(self, total):
        weights = {"sayings.txt": 1.0, "puns.txt": 1.0, "extra.txt": 1.0}
        config = self._config(total, total, weights=weights)
        assert len(self._concepts().get_with_subcategories(config)) <= total


# ---------------------------------------------------------------------------
# Affix categories, and a missing category file
# ---------------------------------------------------------------------------

class TestAffixCategories:
    """Prefixes and suffixes attach to a word; they are not concepts alone."""

    def _concepts(self):
        return Concepts(PromptMode.SFW, get_specific_locations=False)

    def test_prefixes_are_sampled_from_the_file(self):
        result = self._concepts().get_prefixes(ConceptConfiguration(low=2, high=2))
        assert len(result) == 2

    def test_suffixes_are_sampled_from_the_file(self):
        result = self._concepts().get_suffixes(ConceptConfiguration(low=2, high=2))
        assert len(result) == 2

    def test_entries_carry_their_own_joining_hyphen(self):
        """Attaching is concatenation, so the file decides how to join."""
        prefixes = self._concepts().get_prefixes(ConceptConfiguration(low=5, high=5))
        suffixes = self._concepts().get_suffixes(ConceptConfiguration(low=5, high=5))
        assert all(p.endswith("-") for p in prefixes)
        assert all(s.startswith("-") for s in suffixes)

    def test_they_are_off_by_default(self):
        """They would be nonsense in a prompt until something attaches them."""
        from sd_runner.prompts.prompter_configuration import PrompterConfiguration

        config = PrompterConfiguration()
        for name in ("prefixes", "suffixes"):
            assert config.get_category_config(name).low == 0
            assert config.get_category_config(name).high == 0

    def test_the_sample_is_a_request_not_a_result(self):
        """Sampling does not know how many hosts exist; the prompter caps it."""
        result = self._concepts().get_prefixes(ConceptConfiguration(low=8, high=8))
        assert len(result) == 8


class TestMissingCategoryFile:
    """A concepts directory need not carry every file.

    The German set has no prefixes.txt or suffixes.txt, and a translated set
    may lack any category. That has to be inert rather than fatal.
    """

    def _concepts(self):
        return Concepts(PromptMode.SFW, get_specific_locations=False)

    def test_a_missing_file_loads_as_empty(self):
        assert Concepts.load("definitely_not_a_concepts_file.txt") == []

    def test_a_missing_file_does_not_break_sampling(self):
        concepts = Concepts.load("definitely_not_a_concepts_file.txt")
        assert Concepts.sample_whitelisted(concepts, 2, 4, PromptMode.SFW) == []

    def test_the_absence_is_reported_once(self, caplog):
        """Every prompt generation loads every file; warning each time is noise."""
        from sd_runner.prompts import concepts as concepts_module
        from tests.utils import captured_logs

        concepts_module.Concepts._missing_files_reported.clear()
        with captured_logs(caplog, concepts_module.logger, level="WARNING"):
            for _ in range(3):
                Concepts.load("definitely_not_a_concepts_file.txt")
        assert caplog.text.count("definitely_not_a_concepts_file") == 1
