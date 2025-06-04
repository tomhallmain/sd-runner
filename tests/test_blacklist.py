import unittest
from sd_runner.blacklist import Blacklist, BlacklistItem
from sd_runner.concepts import Concepts

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

if __name__ == '__main__':
    unittest.main() 