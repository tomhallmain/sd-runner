from collections import OrderedDict
import os
import pickle
import sys

class PicklableCache:
    """A pickleable LRU cache with integrated file persistence."""
    def __init__(self, maxsize=128, filename=None):
        self.maxsize = maxsize
        self.filename = filename
        self.cache = OrderedDict()

    def get(self, key):
        """Retrieve value from cache while updating access order."""
        if key in self.cache:
            self.cache.move_to_end(key)
            return self.cache[key]
        return None

    def put(self, key, value):
        """Add/update value in cache while maintaining size limit."""
        # Handle disabled cache scenario
        if self.maxsize <= 0:
            if key in self.cache:
                self.cache.pop(key)
            return
        
        # Update existing key
        if key in self.cache:
            self.cache[key] = value
            self.cache.move_to_end(key)
        # Insert new key
        else:
            # Evict least recently used item if needed
            if len(self.cache) >= self.maxsize:
                self.cache.popitem(last=False)
            self.cache[key] = value

    def clear(self):
        """Clear all items from cache."""
        self.cache.clear()

    def __len__(self):
        return len(self.cache)
    
    def save(self, filename=None):
        """
        Persist cache to disk using pickle.
        
        Args:
            filename: Override default filename if provided
        """
        save_filename = filename or self.filename
        if not save_filename:
            raise ValueError("No filename specified for saving")
        
        with open(save_filename, 'wb') as f:
            pickle.dump(self, f)
        
        # Update default filename if new one was provided
        if filename and filename != self.filename:
            self.filename = filename

    @classmethod
    def load(cls, filename):
        """
        Load cache from pickled file.
        
        Args:
            filename: File to load from
            
        Returns:
            PicklableCache instance
            
        Raises:
            FileNotFoundError: If specified file doesn't exist
        """
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Cache file not found: {filename}")
            
        with open(filename, 'rb') as f:
            return pickle.load(f)
    
    @classmethod
    def load_or_create(cls, filename, maxsize=128):
        """
        Safely load cache or create new if file doesn't exist.
        
        Args:
            filename: File to attempt loading from
            maxsize: Cache size if new cache is created
            
        Returns:
            PicklableCache instance
        """
        try:
            return cls.load(filename)
        except FileNotFoundError:
            return cls(maxsize, filename)


from collections import OrderedDict
import os
import pickle
import sys

class SizeAwarePicklableCache:
    """LRU cache with size-aware eviction and file persistence."""
    
    def __init__(self, maxsize=128, filename=None, large_threshold=1024 * 1024, max_large_items=1):
        """
        Initialize a size-aware cache.
        
        Args:
            maxsize: Maximum number of items in cache
            filename: Default persistence file path
            large_threshold: Minimum size (bytes) to consider an item "very large"
            max_large_items: Maximum number of large items to retain
        """
        self.maxsize = maxsize
        self.filename = filename
        self.large_threshold = large_threshold
        self.max_large_items = max_large_items
        self.cache = OrderedDict()  # key: (value, size)
        self.large_count = 0  # Track number of large items
        self.total_size = 0

    def get(self, key):
        """Retrieve item from cache, updating access order."""
        if key in self.cache:
            value, size = self.cache.pop(key)
            self.cache[key] = (value, size)  # Move to MRU position
            return value
        return None

    def put(self, key, value):
        """Add/update item in cache with size tracking."""
        # Calculate item size
        new_size = self._calculate_size(value)
        is_large = new_size >= self.large_threshold
        
        # Handle existing item
        old_large = False
        if key in self.cache:
            _, old_size = self.cache.pop(key)
            self.total_size -= old_size
            old_large = old_size >= self.large_threshold
            if old_large:
                self.large_count -= 1
        
        # Add/update the item
        self.cache[key] = (value, new_size)
        self.total_size += new_size
        
        # Update large count if new item is large
        if is_large:
            self.large_count += 1
        
        # Enforce large item limit if needed
        if is_large and self.large_count > self.max_large_items:
            self._evict_oldest_large_item(key)
        
        # Enforce maxsize using standard LRU eviction
        while len(self.cache) > self.maxsize:
            oldest_key, (_, oldest_size) = self.cache.popitem(last=False)
            self.total_size -= oldest_size
            if oldest_size >= self.large_threshold:
                self.large_count -= 1
    
    def _evict_oldest_large_item(self, current_key):
        """Evict the oldest large item that isn't the current key."""
        # Find first large item that's not the current key
        for key in list(self.cache.keys()):
            if key == current_key:
                continue
            value, size = self.cache[key]
            if size >= self.large_threshold:
                # Found candidate - remove it
                del self.cache[key]
                self.total_size -= size
                self.large_count -= 1
                return
    
    def _calculate_size(self, value):
        """Calculate memory footprint of an item."""
        if isinstance(value, (list, tuple, set)):
            return sys.getsizeof(value) + sum(sys.getsizeof(v) for v in value)
        if isinstance(value, dict):
            return (sys.getsizeof(value) + 
                    sum(sys.getsizeof(k) + sys.getsizeof(v) 
                    for k, v in value.items()))
        return sys.getsizeof(value)

    def clear(self):
        """Clear all cached items and reset state."""
        self.cache.clear()
        self.large_count = 0
        self.total_size = 0

    def __len__(self):
        return len(self.cache)
    
    def save(self, filename=None):
        """Persist cache to file using pickle."""
        save_file = filename or self.filename
        if not save_file:
            raise ValueError("Missing filename for cache persistence")
            
        with open(save_file, 'wb') as f:
            pickle.dump(self, f)
            
        if filename and filename != self.filename:
            self.filename = filename

    @classmethod
    def load(cls, filename):
        """Load cache from pickle file."""
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Cache file not found: {filename}")
            
        with open(filename, 'rb') as f:
            return pickle.load(f)
    
    @classmethod
    def load_or_create(cls, filename, maxsize=128, large_threshold=1024, max_large_items=1):
        """Load cache or create new if file doesn't exist."""
        try:
            return cls.load(filename)
        except FileNotFoundError:
            return cls(
                maxsize=maxsize,
                filename=filename,
                large_threshold=large_threshold,
                max_large_items=max_large_items
            )
