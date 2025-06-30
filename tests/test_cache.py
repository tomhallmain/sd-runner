import unittest


from utils.pickleable_cache import SizeAwarePicklableCache


class TestCache(unittest.TestCase):
    def test_cache(self):

        # Initialize cache with custom size constraints
        cache = SizeAwarePicklableCache(
            maxsize=100,             # Max 100 items
            large_threshold=1024 * 80,    # 80KB threshold for large items
            max_large_items=2,       # Max 2 large items
            filename="data.cache"
        )

        # Add mixed-size items
        cache.put("small1", [i for i in range(100)])    # ~0.8KB
        cache.put("small2", [i for i in range(200)])    # ~1.6KB
        cache.put("large1", [i for i in range(10000)])  # ~80KB
        cache.put("large2", [i for i in range(15000)])  # ~120KB

        # Verify all items are in cache
        cache_keys = list(cache.cache.keys())
        self.assertIn("small1", cache_keys)
        self.assertIn("small2", cache_keys)
        self.assertIn("large1", cache_keys)
        self.assertIn("large2", cache_keys)

        # Adding third large item triggers size-aware eviction
        cache.put("large3", [i for i in range(20000)])  # ~160KB
        # "large1" (smallest large item) will be evicted

        # Verify large1 was evicted (smallest large item)
        cache_keys = list(cache.cache.keys())
        self.assertNotIn("large1", cache_keys)
        # Verify other items are still there
        self.assertIn("small1", cache_keys)
        self.assertIn("small2", cache_keys)
        self.assertIn("large2", cache_keys)
        self.assertIn("large3", cache_keys)

        # Adding 101st item triggers LRU eviction (started with 4 items, 100 max size)
        for i in range(97):
            cache.put(f"item_{i}", [j for j in range(100)])
        # Oldest non-large item ("small1") will be evicted

        # Verify small1 was evicted (oldest non-large item)
        cache_keys = list(cache.cache.keys())
        self.assertNotIn("small1", cache_keys)
        # Verify small2 is still there (more recent than small1)
        self.assertIn("small2", cache_keys)
        # Verify large items are still there
        self.assertIn("large2", cache_keys)
        self.assertIn("large3", cache_keys)


if __name__ == '__main__':
    unittest.main()
