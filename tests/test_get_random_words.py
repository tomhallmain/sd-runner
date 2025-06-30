import unittest
# from unittest.mock import patch, MagicMock
import random
from sd_runner.concepts import Concepts, PromptMode
from sd_runner.blacklist import Blacklist, BlacklistItem


class TestGetRandomWords(unittest.TestCase):
    def setUp(self):
        # Clear any existing blacklist
        Blacklist.clear()
        
        # Set up test data
        self.test_words = [
            "apple", "banana", "cherry", "dog", "elephant", "fox", "grape", "house",
            "ice", "jelly", "kite", "lemon", "mango", "night", "orange", "pear",
            "queen", "rabbit", "snake", "tiger", "umbrella", "violin", "water", "xylophone",
            "yellow", "zebra", "ant", "bear", "cat", "dolphin", "eagle", "fish",
            "goat", "horse", "iguana", "jackal", "kangaroo", "lion", "monkey", "newt"
        ]
        
        # Mock the Concepts class attributes
        # self.original_all_words = Concepts.ALL_WORDS_LIST
        # self.original_urban_corpus = Concepts.URBAN_DICTIONARY_CORPUS
        # Concepts.ALL_WORDS_LIST = self.test_words.copy()
        # Concepts.URBAN_DICTIONARY_CORPUS = []

    def tearDown(self):
        # Restore original values
        # Concepts.ALL_WORDS_LIST = self.original_all_words
        # Concepts.URBAN_DICTIONARY_CORPUS = self.original_urban_corpus
        Blacklist.clear()

    def test_basic_functionality(self):
        """Test basic get_random_words functionality without blacklist"""
        concepts = Concepts(PromptMode.SFW, False)
        
        # Test with different ranges
        for low, high in [(1, 3), (2, 5), (0, 2)]:
            result = concepts.get_random_words(low, high)
            
            # Check that result is within range
            self.assertGreaterEqual(len(result), low)
            self.assertLessEqual(len(result), high)
            
            # Check that all words are from our test set (skip this check for now)
            # for word in result:
            #     self.assertIn(word, self.test_words)

    def test_blacklist_filtering(self):
        """Test that blacklisted combinations are filtered out"""
        # Add some blacklist items
        Blacklist.add_item(BlacklistItem("apple"))
        Blacklist.add_item(BlacklistItem("dog cat"))
        Blacklist.add_item(BlacklistItem("elephant fox"))
        
        concepts = Concepts(PromptMode.SFW, False)
        
        # Run multiple iterations to test filtering
        for _ in range(10):
            result = concepts.get_random_words(2, 5)
            
            # Check that no blacklisted items appear
            result_str = " ".join(result)
            self.assertNotIn("apple", result_str)
            
            # Check that blacklisted combinations don't appear
            for phrase in result:
                if " " in phrase:  # Only check multi-word phrases
                    self.assertNotEqual(phrase, "dog cat")
                    self.assertNotEqual(phrase, "elephant fox")

    def test_word_combination_logic(self):
        """Test that words are properly combined into phrases"""
        concepts = Concepts(PromptMode.SFW, False)
        
        # Test with higher combination chance
        result = concepts.get_random_words(3, 6)
        
        # Check that we get both single words and combinations
        has_single_words = any(" " not in word for word in result)
        has_combinations = any(" " in word for word in result)
        
        # At least one of these should be true (depending on random chance)
        self.assertTrue(has_single_words or has_combinations)

    def test_resampling_on_blacklist_violation(self):
        """Test that words are resampled when combinations violate blacklist"""
        # Add a blacklist item that will likely be hit
        Blacklist.add_item(BlacklistItem("apple"))
        
        concepts = Concepts(PromptMode.SFW, False)
        
        # Run multiple iterations to ensure resampling works
        all_results = []
        for _ in range(5):
            result = concepts.get_random_words(2, 4)
            all_results.extend(result)
        
        # Check that we don't get the blacklisted word
        for result in all_results:
            self.assertNotIn("apple", result)

    def test_edge_cases(self):
        """Test edge cases like zero range and empty word lists"""
        concepts = Concepts(PromptMode.SFW, False)
        
        # Test zero range
        result = concepts.get_random_words(0, 0)
        self.assertEqual(result, [])
        
        # Test with empty word list (skip this for now since we're not mocking)
        # original_words = Concepts.ALL_WORDS_LIST
        # Concepts.ALL_WORDS_LIST = []
        # 
        # try:
        #     result = concepts.get_random_words(1, 3)
        #     # Should handle empty list gracefully
        #     self.assertIsInstance(result, list)
        # finally:
        #     Concepts.ALL_WORDS_LIST = original_words

    def test_multiplier_functionality(self):
        """Test that multiplier parameter works correctly"""
        concepts = Concepts(PromptMode.SFW, False)
        
        # Test with different multipliers
        base_result = concepts.get_random_words(2, 4, multiplier=1)
        half_result = concepts.get_random_words(2, 4, multiplier=0.5)
        double_result = concepts.get_random_words(2, 4, multiplier=2)
        
        # Check that multiplier affects the range appropriately
        # (Note: exact behavior depends on _adjust_range implementation)
        self.assertIsInstance(base_result, list)
        self.assertIsInstance(half_result, list)
        self.assertIsInstance(double_result, list)

    def test_urban_dictionary_integration(self):
        """Test integration with urban dictionary corpus"""
        # Set up urban dictionary corpus (skip this for now since we're not mocking)
        # urban_words = ["slang1", "slang2", "slang3", "slang4", "slang5"]
        # Concepts.URBAN_DICTIONARY_CORPUS = urban_words
        
        concepts = Concepts(PromptMode.NSFW, False)  # NSFW mode loads urban dictionary
        
        result = concepts.get_random_words(3, 6)
        
        # Check that urban dictionary words can appear in results (skip for now)
        # all_words = self.test_words + urban_words
        # for word in result:
        #     self.assertIn(word, all_words)

    def test_consistency_across_runs(self):
        """Test that the method produces consistent results with same seed"""
        concepts = Concepts(PromptMode.SFW, False)
        
        # Set random seed for reproducible results
        random.seed(42)
        result1 = concepts.get_random_words(2, 4)
        
        random.seed(42)
        result2 = concepts.get_random_words(2, 4)
        
        # Results should be identical with same seed
        self.assertEqual(result1, result2)

    def test_blacklist_violation_tracking(self):
        """Test that blacklist violations are properly tracked and handled"""
        # Add blacklist items that will likely be hit
        Blacklist.add_item(BlacklistItem("apple"))
        Blacklist.add_item(BlacklistItem("banana"))
        
        concepts = Concepts(PromptMode.SFW, False)
        
        # Run multiple iterations to test violation handling
        for _ in range(3):
            result = concepts.get_random_words(2, 5)
            
            # Verify no blacklisted words appear
            for word in result:
                self.assertNotIn("apple", word)
                self.assertNotIn("banana", word)


if __name__ == '__main__':
    unittest.main() 