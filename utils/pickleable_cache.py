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
    
    def __init__(self, maxsize=128, filename=None, large_threshold=1024, max_large_items=1):
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
        self.large_items = OrderedDict()  # Tracks large items in LRU order
        self.total_size = 0

    def get(self, key):
        """Retrieve item from cache, updating access order."""
        if key in self.cache:
            value, size = self.cache.pop(key)
            self.cache[key] = (value, size)  # Move to MRU position
            
            # Update LRU position for large items
            if size >= self.large_threshold:
                if key in self.large_items:
                    self.large_items.move_to_end(key)
                else:
                    # Shouldn't happen normally, but handle inconsistency
                    self.large_items[key] = None
            return value
        return None

    def put(self, key, value):
        """Add/update item in cache with size tracking."""
        # Calculate item size
        new_size = self._calculate_size(value)
        is_large = new_size >= self.large_threshold
        
        # Handle existing item
        if key in self.cache:
            _, old_size = self.cache.pop(key)
            self.total_size -= old_size
            
            # Remove from large items if it was large
            if old_size >= self.large_threshold and key in self.large_items:
                del self.large_items[key]
        
        # Add/update the item
        self.cache[key] = (value, new_size)
        self.total_size += new_size
        
        # Update large items tracking
        if is_large:
            if type(key) == tuple:
                print(f"Adding large item: {len(key)}, size: {new_size}")
            # Add or move to MRU position in large items
            self.large_items[key] = None
            self.large_items.move_to_end(key)
            
            # Enforce large item limit (evict oldest large item if needed)
            if len(self.large_items) > self.max_large_items:
                oldest_large_key, _ = self.large_items.popitem(last=False)
                self._remove_item(oldest_large_key)
        
        # Enforce maxsize using standard LRU eviction
        while len(self.cache) > self.maxsize:
            oldest_key, _ = self.cache.popitem(last=False)
            self._remove_item(oldest_key)
    
    def _calculate_size(self, value):
        """Calculate memory footprint of an item."""
        if isinstance(value, (list, tuple, set, dict)):
            container_size = sys.getsizeof(value)
            if isinstance(value, dict):
                return container_size + sum(
                    sys.getsizeof(k) + sys.getsizeof(v)
                    for k, v in value.items()
                )
            else:
                return container_size + sum(sys.getsizeof(v) for v in value)
        return sys.getsizeof(value)
    
    def _remove_item(self, key):
        """Remove item from all tracking structures."""
        if key in self.cache:
            _, size = self.cache.pop(key)
            self.total_size -= size
        if key in self.large_items:
            del self.large_items[key]

    def clear(self):
        """Clear all cached items and reset state."""
        self.cache.clear()
        self.large_items.clear()
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
