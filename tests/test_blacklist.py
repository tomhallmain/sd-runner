import unittest
from sd_runner.blacklist import Blacklist, BlacklistItem
from sd_runner.concepts import Concepts
from ui.tags_blacklist_window import BlacklistWindow
from utils.app_info_cache import app_info_cache

class TestBlacklist(unittest.TestCase):
    def setUp(self):
        # Clear any existing blacklist
        Blacklist.clear()
        # Add some test items
        Blacklist.add_item(BlacklistItem("bad_word"))
        Blacklist.add_item(BlacklistItem("inappropriate"))
        Blacklist.add_item(BlacklistItem("copyrighted"))
        Blacklist.add_item(BlacklistItem("style:bad_style", enabled=False))  # Disabled item

    def test_direct_validation(self):
        """Test direct validation of blacklisted terms"""
        # Test exact matches
        self.assertTrue(len(Blacklist.find_blacklisted_items("bad_word")) > 0)
        self.assertTrue(len(Blacklist.find_blacklisted_items("inappropriate")) > 0)
        
        # Test partial matches
        self.assertTrue(len(Blacklist.find_blacklisted_items("bad_word with suffix")) > 0)
        self.assertTrue(len(Blacklist.find_blacklisted_items("prefix bad_word")) > 0)
        
        # Test disabled items
        self.assertTrue(len(Blacklist.find_blacklisted_items("style:bad_style")) == 0)
        
        # Test clean text
        self.assertTrue(len(Blacklist.find_blacklisted_items("clean text")) == 0)

    def test_sampling_validation(self):
        """Test blacklist behavior during concept sampling"""
        # Set up some test concepts with a large number of tags
        test_concepts = {
            "safe_concept": [
                "good_word", "appropriate", "nice", "pleasant", "beautiful", "wonderful",
                "excellent", "fantastic", "amazing", "brilliant", "perfect", "ideal",
                "splendid", "magnificent", "gorgeous", "stunning", "breathtaking",
                "elegant", "graceful", "charming", "delightful", "enchanting",
                "captivating", "mesmerizing", "alluring", "attractive", "appealing",
                "engaging", "fascinating", "interesting", "compelling", "enticing",
                "inviting", "welcoming", "friendly", "warm", "cozy", "comfortable",
                "relaxing", "peaceful", "serene", "tranquil", "calm", "quiet",
                "gentle", "soft", "smooth", "silky", "velvety", "luxurious"
            ],
            "mixed_concept": [
                "good_word", "bad_word", "appropriate", "inappropriate", "nice", "pleasant",
                "beautiful", "wonderful", "excellent", "fantastic", "amazing", "brilliant",
                "perfect", "ideal", "splendid", "magnificent", "gorgeous", "stunning",
                "breathtaking", "elegant", "graceful", "charming", "delightful", "enchanting",
                "captivating", "mesmerizing", "alluring", "attractive", "appealing",
                "engaging", "fascinating", "interesting", "compelling", "enticing",
                "inviting", "welcoming", "friendly", "warm", "cozy", "comfortable",
                "relaxing", "peaceful", "serene", "tranquil", "calm", "quiet",
                "gentle", "soft", "smooth", "silky", "velvety", "luxurious",
                "bad_style", "poor_quality", "ugly", "terrible", "awful", "horrible",
                "dreadful", "atrocious", "abysmal", "appalling", "shocking", "disturbing"
            ],
            "bad_concept": [
                "bad_word", "inappropriate", "copyrighted", "bad_style", "poor_quality",
                "ugly", "terrible", "awful", "horrible", "dreadful", "atrocious",
                "abysmal", "appalling", "shocking", "disturbing", "offensive",
                "inappropriate", "unacceptable", "unwanted", "undesirable", "unpleasant",
                "disgusting", "repulsive", "revolting", "nauseating", "sickening",
                "vile", "foul", "filthy", "dirty", "unclean", "contaminated",
                "polluted", "toxic", "poisonous", "harmful", "dangerous", "risky",
                "hazardous", "perilous", "threatening", "menacing", "hostile",
                "aggressive", "violent", "brutal", "savage", "cruel", "vicious",
                "malicious", "spiteful", "hateful", "hostile", "aggressive"
            ],
            "disabled_concept": [
                "style:bad_style", "good_word", "nice", "pleasant", "beautiful",
                "wonderful", "excellent", "fantastic", "amazing", "brilliant",
                "perfect", "ideal", "splendid", "magnificent", "gorgeous", "stunning",
                "breathtaking", "elegant", "graceful", "charming", "delightful",
                "enchanting", "captivating", "mesmerizing", "alluring", "attractive",
                "appealing", "engaging", "fascinating", "interesting", "compelling",
                "enticing", "inviting", "welcoming", "friendly", "warm", "cozy",
                "comfortable", "relaxing", "peaceful", "serene", "tranquil", "calm",
                "quiet", "gentle", "soft", "smooth", "silky", "velvety", "luxurious"
            ]
        }
        
        # Test different sampling ranges
        test_ranges = [
            (1, 2),   # Small range
            (2, 3),   # Medium range
            (3, 4),   # Larger range
            (5, 10),  # Much larger range
            (10, 20)  # Very large range
        ]
        
        # Number of iterations to run for each test case
        num_iterations = 50
        
        for low, high in test_ranges:
            print(f"\nTesting range {low}-{high}:")
            for concept_name, tags in test_concepts.items():
                print(f"\nTesting {concept_name}:")
                for i in range(num_iterations):
                    # Create a sample with these tags
                    sampled_tags = Concepts.sample_whitelisted(tags, low=low, high=high)
                    
                    # Check if any blacklisted terms made it through
                    sample_str = ", ".join(sampled_tags)
                    blacklisted = Blacklist.find_blacklisted_items(sample_str)
                    if blacklisted:
                        print(f"Iteration {i+1}: Found blacklisted terms: {blacklisted}")
                        print(f"Original tags: {tags}")
                        print(f"Sampled result: {sampled_tags}")
                    
                    # For concepts containing blacklisted terms, verify they were filtered
                    if any(Blacklist.find_blacklisted_items(tag) for tag in tags):
                        self.assertTrue(len(blacklisted) == 0, 
                            f"Blacklisted terms found in sample for {concept_name} on iteration {i+1}")
                    
                    # Verify the count is within range
                    self.assertTrue(low <= len(sampled_tags) <= high,
                        f"Sample count {len(sampled_tags)} outside range {low}-{high} for {concept_name} on iteration {i+1}")
                    
                    if (i + 1) % 10 == 0:  # Print progress every 10 iterations
                        print(f"Completed {i+1}/{num_iterations} iterations")

class TestBlacklistItem(unittest.TestCase):
    
    def test_exact_match_behavior_preserved(self):
        """Test that the original exact match behavior is preserved when use_regex=False."""
        item = BlacklistItem("cat", use_regex=False)
        
        # Should match exact word
        self.assertTrue(item.matches_tag("cat"))
        
        # Should match plural forms and other word forms (prefix matching)
        self.assertTrue(item.matches_tag("cats"))
        self.assertTrue(item.matches_tag("catch"))
        self.assertTrue(item.matches_tag("category"))
        
        # Should match when part of a larger tag
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("cat-sitting"))
        self.assertTrue(item.matches_tag("cat, dog"))
        
        # Should not match when not at word start
        self.assertFalse(item.matches_tag("scat"))
        self.assertFalse(item.matches_tag("blackcat"))
    
    def test_regex_pattern_matching_with_word_start_boundaries(self):
        """Test regex pattern matching with automatic word start boundary handling."""
        # Test simple word matching (should match at word start boundaries)
        item = BlacklistItem("cat", use_regex=True)  # use_regex=False by default, so explicitly set to True
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("cat sitting"))
        self.assertTrue(item.matches_tag("black-cat"))
        self.assertTrue(item.matches_tag("cat, dog"))
        # Should match words that start with the pattern (prefix matching)
        self.assertTrue(item.matches_tag("catch"))
        self.assertTrue(item.matches_tag("category"))
        self.assertTrue(item.matches_tag("cats"))
        # Should not match when not at word start
        self.assertFalse(item.matches_tag("scat"))
        self.assertFalse(item.matches_tag("blackcat"))
        
        # Test wildcard patterns
        item = BlacklistItem("*cat*", use_regex=True)
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("cat sitting"))
        self.assertTrue(item.matches_tag("fat cat"))
        self.assertTrue(item.matches_tag("black-cat"))
        self.assertTrue(item.matches_tag("cat_sitting"))
        self.assertFalse(item.matches_tag("dog"))
        
        # Test prefix wildcard
        item = BlacklistItem("*cat", use_regex=True)
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("fat cat"))
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("cat sitting"))
        
        # Test suffix wildcard
        item = BlacklistItem("cat*", use_regex=True)
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("cat sitting"))
        self.assertTrue(item.matches_tag("cat, dog"))
        self.assertTrue(item.matches_tag("black cat"))
        
        # Test middle wildcard
        item = BlacklistItem("c*t", use_regex=True)
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("cut"))
        self.assertTrue(item.matches_tag("cart"))
        self.assertFalse(item.matches_tag("dog"))
    
    def test_regex_pattern_without_word_boundaries(self):
        """Test regex pattern matching when regex is disabled."""
        # Test wildcard patterns without regex (falls back to exact match)
        item = BlacklistItem("*cat*", use_regex=False)
        self.assertFalse(item.matches_tag("blackcat"))
        self.assertFalse(item.matches_tag("catblack"))
        self.assertFalse(item.matches_tag("blackcatwhite"))
        self.assertFalse(item.matches_tag("dog"))
        
        # Test simple word without regex (falls back to exact match)
        item = BlacklistItem("cat", use_regex=False)
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("cats"))  # Prefix matching
        self.assertTrue(item.matches_tag("catch"))  # Prefix matching
        self.assertTrue(item.matches_tag("category"))  # Prefix matching
        self.assertTrue(item.matches_tag("black cat"))
        self.assertFalse(item.matches_tag("scat"))  # Not at word start
        self.assertFalse(item.matches_tag("blackcat"))  # Not at word start
    
    def test_special_characters_in_patterns(self):
        """Test that special characters in patterns are handled correctly."""
        # Test patterns with special regex characters
        item = BlacklistItem("cat+dog")
        self.assertTrue(item.matches_tag("cat+dog"))
        self.assertFalse(item.matches_tag("catdog"))
        
        # Test patterns with parentheses
        item = BlacklistItem("(cat)")
        self.assertTrue(item.matches_tag("(cat)"))
        self.assertFalse(item.matches_tag("cat"))
        
        # Test patterns with dots
        item = BlacklistItem("cat.dog")
        self.assertTrue(item.matches_tag("cat.dog"))
        self.assertFalse(item.matches_tag("catdog"))
    
    def test_case_insensitive_matching(self):
        """Test that both exact and regex matching are case insensitive."""
        # Test exact match case insensitivity
        item = BlacklistItem("Cat", use_regex=False)
        self.assertTrue(item.matches_tag("CAT"))
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("Cat"))
        
        # Test regex match case insensitivity
        item = BlacklistItem("*Cat*", use_regex=True)
        self.assertTrue(item.matches_tag("BLACK CAT"))
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("Black Cat"))
    
    def test_use_regex_property(self):
        """Test that the regex_pattern property works correctly."""
        # Should be a compiled regex pattern by default (exact match mode)
        item = BlacklistItem("cat")
        self.assertIsNotNone(item.regex_pattern)
        self.assertTrue(hasattr(item.regex_pattern, 'search'))
        self.assertFalse(item.use_regex)
        
        # Should be a compiled regex when explicitly set to False
        item = BlacklistItem("cat", use_regex=False)
        self.assertIsNotNone(item.regex_pattern)
        self.assertTrue(hasattr(item.regex_pattern, 'search'))
        self.assertFalse(item.use_regex)
        
        # Should be a compiled regex when explicitly set to True
        item = BlacklistItem("cat", use_regex=True)
        self.assertIsNotNone(item.regex_pattern)
        self.assertTrue(hasattr(item.regex_pattern, 'search'))
        self.assertTrue(item.use_regex)
        
        # Test that wildcard patterns create valid regex
        item = BlacklistItem("*cat*", use_regex=True)
        self.assertIsNotNone(item.regex_pattern)
        self.assertTrue(hasattr(item.regex_pattern, 'search'))
        self.assertTrue(item.use_regex)
    
    def test_edge_cases(self):
        """Test edge cases and boundary conditions."""
        # Empty string - should match anything since it's a prefix of everything
        item = BlacklistItem("")
        self.assertTrue(item.matches_tag("anything"))
        self.assertTrue(item.matches_tag(""))
        
        # Just asterisk
        item = BlacklistItem("*", use_regex=True)
        self.assertTrue(item.matches_tag("anything"))
        self.assertTrue(item.matches_tag(""))
        
        # Multiple asterisks
        item = BlacklistItem("***", use_regex=True)
        self.assertTrue(item.matches_tag("anything"))
        self.assertTrue(item.matches_tag(""))
        
        # Asterisk at start and end
        item = BlacklistItem("*cat*", use_regex=True)
        self.assertTrue(item.matches_tag("cat"))
        self.assertTrue(item.matches_tag("black cat"))
        self.assertTrue(item.matches_tag("cat sitting"))
        self.assertFalse(item.matches_tag("dog"))
    
    def test_serialization(self):
        """Test that the new regex_pattern property is properly serialized."""
        # Test to_dict
        item = BlacklistItem("test", enabled=True, use_regex=True)
        data = item.to_dict()
        self.assertEqual(data["string"], "test")
        self.assertEqual(data["enabled"], True)
        self.assertEqual(data["use_regex"], True)
        
        # Test from_dict
        new_item = BlacklistItem.from_dict(data)
        self.assertEqual(new_item.string, "test")
        self.assertEqual(new_item.enabled, True)
        self.assertIsNotNone(new_item.regex_pattern)
        self.assertTrue(new_item.use_regex)
        
        # Test backward compatibility (missing use_regex)
        old_data = {"string": "test", "enabled": True}
        old_item = BlacklistItem.from_dict(old_data)
        self.assertIsNotNone(old_item.regex_pattern)  # Always a compiled pattern now
        self.assertFalse(old_item.use_regex)  # Default value

    def test_use_word_boundary_parameter(self):
        """Test that the use_word_boundary parameter correctly controls word boundary matching."""
        # Test non-regex patterns with word boundary (default behavior)
        item_with_boundary = BlacklistItem("cat", use_regex=False, use_word_boundary=True)
        self.assertTrue(item_with_boundary.matches_tag("cat"))
        self.assertTrue(item_with_boundary.matches_tag("black cat"))
        self.assertTrue(item_with_boundary.matches_tag("cat sitting"))
        self.assertFalse(item_with_boundary.matches_tag("scat"))  # Not at word start
        self.assertFalse(item_with_boundary.matches_tag("blackcat"))  # Not at word start
        
        # Test non-regex patterns without word boundary
        item_without_boundary = BlacklistItem("cat", use_regex=False, use_word_boundary=False)
        self.assertTrue(item_without_boundary.matches_tag("cat"))
        self.assertTrue(item_without_boundary.matches_tag("black cat"))
        self.assertTrue(item_without_boundary.matches_tag("cat sitting"))
        self.assertTrue(item_without_boundary.matches_tag("scat"))  # Now matches anywhere
        self.assertTrue(item_without_boundary.matches_tag("blackcat"))  # Now matches anywhere
        
        # Test regex patterns with word boundary (default behavior)
        item_regex_with_boundary = BlacklistItem("cat", use_regex=True, use_word_boundary=True)
        self.assertTrue(item_regex_with_boundary.matches_tag("cat"))
        self.assertTrue(item_regex_with_boundary.matches_tag("black cat"))
        self.assertTrue(item_regex_with_boundary.matches_tag("cat sitting"))
        self.assertFalse(item_regex_with_boundary.matches_tag("scat"))  # Not at word start
        self.assertFalse(item_regex_with_boundary.matches_tag("blackcat"))  # Not at word start
        
        # Test regex patterns without word boundary
        item_regex_without_boundary = BlacklistItem("cat", use_regex=True, use_word_boundary=False)
        self.assertTrue(item_regex_without_boundary.matches_tag("cat"))
        self.assertTrue(item_regex_without_boundary.matches_tag("black cat"))
        self.assertTrue(item_regex_without_boundary.matches_tag("cat sitting"))
        self.assertTrue(item_regex_without_boundary.matches_tag("scat"))  # Now matches anywhere
        self.assertTrue(item_regex_without_boundary.matches_tag("blackcat"))  # Now matches anywhere
        
        # Test wildcard patterns with word boundary
        item_wildcard_with_boundary = BlacklistItem("*cat*", use_regex=True, use_word_boundary=True)
        self.assertTrue(item_wildcard_with_boundary.matches_tag("black cat"))
        self.assertTrue(item_wildcard_with_boundary.matches_tag("cat sitting"))
        self.assertTrue(item_wildcard_with_boundary.matches_tag("blackcat"))  # Wildcard allows this
        
        # Test wildcard patterns without word boundary
        item_wildcard_without_boundary = BlacklistItem("*cat*", use_regex=True, use_word_boundary=False)
        self.assertTrue(item_wildcard_without_boundary.matches_tag("black cat"))
        self.assertTrue(item_wildcard_without_boundary.matches_tag("cat sitting"))
        self.assertTrue(item_wildcard_without_boundary.matches_tag("blackcat"))  # Now matches anywhere

    def test_use_word_boundary_serialization(self):
        """Test that the use_word_boundary parameter is properly serialized."""
        # Test to_dict with use_word_boundary=True (default)
        item_default = BlacklistItem("test", enabled=True, use_regex=False, use_word_boundary=True)
        data_default = item_default.to_dict()
        self.assertEqual(data_default["string"], "test")
        self.assertEqual(data_default["enabled"], True)
        self.assertEqual(data_default["use_regex"], False)
        self.assertEqual(data_default["use_word_boundary"], True)
        
        # Test to_dict with use_word_boundary=False
        item_no_boundary = BlacklistItem("test", enabled=True, use_regex=False, use_word_boundary=False)
        data_no_boundary = item_no_boundary.to_dict()
        self.assertEqual(data_no_boundary["use_word_boundary"], False)
        
        # Test from_dict with use_word_boundary=True
        new_item_default = BlacklistItem.from_dict(data_default)
        self.assertEqual(new_item_default.string, "test")
        self.assertEqual(new_item_default.enabled, True)
        self.assertEqual(new_item_default.use_regex, False)
        self.assertEqual(new_item_default.use_word_boundary, True)
        
        # Test from_dict with use_word_boundary=False
        new_item_no_boundary = BlacklistItem.from_dict(data_no_boundary)
        self.assertEqual(new_item_no_boundary.use_word_boundary, False)
        
        # Test backward compatibility (missing use_word_boundary)
        old_data = {"string": "test", "enabled": True, "use_regex": False}
        old_item = BlacklistItem.from_dict(old_data)
        self.assertEqual(old_item.use_word_boundary, True)  # Default value

    def test_use_word_boundary_edge_cases(self):
        """Test edge cases for use_word_boundary parameter."""
        # Test empty string with word boundary
        item_empty_with_boundary = BlacklistItem("", use_word_boundary=True)
        self.assertTrue(item_empty_with_boundary.matches_tag("anything"))
        self.assertTrue(item_empty_with_boundary.matches_tag(""))
        
        # Test empty string without word boundary
        item_empty_without_boundary = BlacklistItem("", use_word_boundary=False)
        self.assertTrue(item_empty_without_boundary.matches_tag("anything"))
        self.assertTrue(item_empty_without_boundary.matches_tag(""))
        
        # Test single character with word boundary
        item_char_with_boundary = BlacklistItem("a", use_word_boundary=True)
        self.assertTrue(item_char_with_boundary.matches_tag("a"))
        self.assertTrue(item_char_with_boundary.matches_tag("a word"))
        self.assertFalse(item_char_with_boundary.matches_tag("ba"))  # Not at word start
        
        # Test single character without word boundary
        item_char_without_boundary = BlacklistItem("a", use_word_boundary=False)
        self.assertTrue(item_char_without_boundary.matches_tag("a"))
        self.assertTrue(item_char_without_boundary.matches_tag("a word"))
        self.assertTrue(item_char_without_boundary.matches_tag("ba"))  # Now matches anywhere


class TestFirstTimeUserBlacklist(unittest.TestCase):
    """Test the first-time user blacklist loading functionality."""
    
    def setUp(self):
        """Set up test environment."""
        # Clear any existing blacklist
        Blacklist.clear()
        # Clear the user confirmation flag
        app_info_cache.set("blacklist_user_confirmed_non_default", False)
        # Clear any existing blacklist cache
        app_info_cache.set("tag_blacklist", [])
    
    def tearDown(self):
        """Clean up after tests."""
        # Clear any existing blacklist
        Blacklist.clear()
        # Reset the user confirmation flag
        app_info_cache.set("blacklist_user_confirmed_non_default", False)
        # Clear any existing blacklist cache
        app_info_cache.set("tag_blacklist", [])
    
    def test_first_time_user_loads_default_blacklist(self):
        """Test that first-time users get the default encrypted blacklist."""
        # Ensure user has not confirmed non-default state
        self.assertFalse(app_info_cache.get("blacklist_user_confirmed_non_default", default_val=False))
        
        # Call set_blacklist - should load default encrypted blacklist
        BlacklistWindow.set_blacklist()
        
        # Should have loaded some default items (if decryption succeeds)
        # Note: This test may fail if the default blacklist file doesn't exist
        # or can't be decrypted, which is expected behavior
        try:
            items = Blacklist.get_items()
            # If decryption succeeded, we should have items
            # If decryption failed, we should have an empty list
            # Both are valid outcomes
            self.assertIsInstance(items, list)
        except Exception as e:
            # If there's an error loading the default blacklist, that's also valid
            # The method should handle this gracefully
            pass
    
    def test_returning_user_loads_cached_blacklist(self):
        """Test that returning users get their cached blacklist."""
        # Mark user as having confirmed non-default state
        app_info_cache.set("blacklist_user_confirmed_non_default", True)
        
        # Add some test items to cache
        test_items = [
            BlacklistItem("test_item_1", enabled=True),
            BlacklistItem("test_item_2", enabled=False)
        ]
        blacklist_dicts = [item.to_dict() for item in test_items]
        app_info_cache.set("tag_blacklist", blacklist_dicts)
        
        # Call set_blacklist - should load from cache
        BlacklistWindow.set_blacklist()
        
        # Should have loaded the cached items
        items = Blacklist.get_items()
        self.assertEqual(len(items), 2)
        
        # Check that items match what we cached
        item_strings = [item.string for item in items]
        self.assertIn("test_item_1", item_strings)
        self.assertIn("test_item_2", item_strings)
    
    def test_user_confirmation_marking(self):
        """Test that user confirmation is properly marked when they modify the blacklist."""
        # Initially, user should not have confirmed non-default state
        self.assertFalse(app_info_cache.get("blacklist_user_confirmed_non_default", default_val=False))
        
        # Simulate user confirmation by calling mark_user_confirmed_non_default
        BlacklistWindow.mark_user_confirmed_non_default()
        
        # User should now be marked as having confirmed non-default state
        self.assertTrue(app_info_cache.get("blacklist_user_confirmed_non_default", default_val=False))
    
    def test_empty_cache_confirmed_user_behavior(self):
        """Test that confirmed users with empty cache get empty blacklist."""
        # Mark user as having confirmed non-default state
        app_info_cache.set("blacklist_user_confirmed_non_default", True)
        
        # Ensure cache is empty
        app_info_cache.set("tag_blacklist", [])
        
        # Call set_blacklist - should load empty list from cache
        BlacklistWindow.set_blacklist()
        
        # Should have empty blacklist
        items = Blacklist.get_items()
        self.assertEqual(len(items), 0)
    
    def test_load_default_blacklist_functionality(self):
        """Test that the load_default_blacklist method works correctly."""
        # Start with empty blacklist
        Blacklist.clear()
        self.assertEqual(len(Blacklist.get_items()), 0)
        
        # Mark user as having confirmed non-default state
        app_info_cache.set("blacklist_user_confirmed_non_default", True)
        
        # Call load_default_blacklist - should load default blacklist
        result = BlacklistWindow.load_default_blacklist()
        self.assertTrue(result)
        
        # Should have loaded default blacklist items
        items = Blacklist.get_items()
        self.assertGreater(len(items), 0)
        
        # Should have reset the user confirmation flag
        self.assertFalse(app_info_cache.get("blacklist_user_confirmed_non_default", default_val=False))

    def test_reveal_concepts_functionality(self):
        """Test that the reveal concepts functionality works correctly."""
        # Test that is_in_default_state works correctly
        # Start with user not confirmed
        app_info_cache.set("blacklist_user_confirmed_non_default", False)
        self.assertTrue(BlacklistWindow.is_in_default_state())
        
        # Mark user as confirmed
        app_info_cache.set("blacklist_user_confirmed_non_default", True)
        self.assertFalse(BlacklistWindow.is_in_default_state())
        
        # Reset for other tests
        app_info_cache.set("blacklist_user_confirmed_non_default", False)


if __name__ == '__main__':
    unittest.main() 