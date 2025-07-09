from collections import OrderedDict
import os
import pickle
import sys
import threading

class PicklableCache:
    """Thread-safe pickleable LRU cache with file persistence."""
    def __init__(self, maxsize=128, filename=None):
        self.maxsize = maxsize
        self.filename = filename
        self.cache = OrderedDict()
        self.version = 2
        self._lock = threading.Lock()

    def verify_cache_version(self, version=1):
        # Legacy support for old cache versions
        if not hasattr(self, 'version'):
            self.version = 1
        return self.version == version

    def get(self, key):
        """Retrieve value from cache while updating access order."""
        with self._lock:
            if key in self.cache:
                self.cache.move_to_end(key)
                return self.cache[key]
            return None

    def put(self, key, value):
        """Add or update an item in the cache while maintaining size limits."""
        with self._lock:
            if self.maxsize <= 0:
                if key in self.cache:
                    self.cache.pop(key)
                return
            
            if key in self.cache:
                self.cache[key] = value
                self.cache.move_to_end(key)
            else:
                if len(self.cache) >= self.maxsize:
                    self.cache.popitem(last=False)
                self.cache[key] = value

    def clear(self):
        """Clear all items from cache."""
        with self._lock:
            self.cache.clear()

    def __len__(self):
        with self._lock:
            return len(self.cache)

    def __getstate__(self):
        """Prepare object for pickling by removing non-picklable attributes."""
        state = self.__dict__.copy()
        # Remove the lock as it's not picklable
        del state['_lock']
        return state
        
    def __setstate__(self, state):
        """Restore state after unpickling and initialize a new lock."""
        self.__dict__.update(state)
        # Reinitialize the lock after unpickling
        self._lock = threading.Lock()

    def save(self, filename=None):
        """
        Persist cache to disk using pickle.
        
        Args:
            filename: Override default filename if provided
        """
        save_filename = filename or self.filename
        if not save_filename:
            raise ValueError("Missing filename for saving")
        
        with self._lock:
            # Atomic state capture
            state = (self.maxsize, save_filename, OrderedDict(self.cache))
        
        # Create temporary object for serialization
        temp_cache = PicklableCache(state[0], state[1])
        temp_cache.cache = state[2]
        
        with open(save_filename, 'wb') as f:
            pickle.dump(temp_cache, f)
        
        # Update filename only if saving succeeded
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
            pickle.UnpicklingError: If file is corrupted
        """
        if not os.path.exists(filename):
            raise FileNotFoundError(f"Cache file not found: {filename}")
        with open(filename, 'rb') as f:
            return pickle.load(f)
    
    @classmethod
    def load_or_create(cls, filename, maxsize=128):
        """
        Load cache from pickled file or create new cache if file doesn't exist.
        
        Args:
            filename: File to load from
            maxsize: Maximum size of the cache

        Returns:
            PicklableCache instance
        """
        try:
            cache = cls.load(filename)
            if not cache.verify_cache_version(version=2):
                # Cache is outdated, create a new one
                cache = cls(maxsize, filename)
            return cache
        except (FileNotFoundError, EOFError):
            return cls(maxsize, filename)


class SizeAwarePicklableCache:
    """Thread-safe size-aware LRU cache with file persistence."""
    def __init__(self, maxsize=128, filename=None, large_threshold=1024*1024, max_large_items=1):
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
        self.cache = OrderedDict()
        self.large_count = 0
        self.total_size = 0
        self.version = 2
        self._lock = threading.Lock()

    def verify_cache_version(self, version=1):
        # Legacy support for old cache versions
        if not hasattr(self, 'version'):
            self.version = 1
        return self.version == version

    def get(self, key):
        """Retrieve item from cache, updating access order."""
        with self._lock:
            if key in self.cache:
                value, size = self.cache.pop(key)
                self.cache[key] = (value, size)
                return value
            return None

    def put(self, key, value):
        """Add or update an item in the cache with size tracking."""
        with self._lock:
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
            
            # Add/update item
            self.cache[key] = (value, new_size)
            self.total_size += new_size
            
            if is_large:
                self.large_count += 1
            
            # Enforce large item limit
            if is_large and self.large_count > self.max_large_items:
                self._evict_oldest_large_item(key)
            
            # Enforce maxsize
            while len(self.cache) > self.maxsize:
                oldest_key, (_, oldest_size) = self.cache.popitem(last=False)
                self.total_size -= oldest_size
                if oldest_size >= self.large_threshold:
                    self.large_count -= 1
    
    def _evict_oldest_large_item(self, current_key):
        """Thread-safe oldest large item eviction."""
        # Protected by caller's lock
        for key in list(self.cache.keys()):  # Safe: using snapshot
            if key == current_key:
                continue
            value, size = self.cache[key]
            if size >= self.large_threshold:
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
        """Clear all items from cache."""
        with self._lock:
            self.cache.clear()
            self.large_count = 0
            self.total_size = 0

    def __len__(self):
        with self._lock:
            return len(self.cache)

    def __getstate__(self):
        """Prepare object for pickling by removing non-picklable attributes."""
        state = self.__dict__.copy()
        # Remove the lock as it's not picklable
        del state['_lock']
        return state
        
    def __setstate__(self, state):
        """Restore state after unpickling and initialize a new lock."""
        self.__dict__.update(state)
        # Reinitialize the lock after unpickling
        self._lock = threading.Lock()

    def save(self, filename=None):
        """Persist cache to file using pickle."""
        save_file = filename or self.filename
        if not save_file:
            raise ValueError("Missing filename for persistence")
        
        with self._lock:
            # Atomic state capture
            state = (
                self.maxsize,
                save_file,
                self.large_threshold,
                self.max_large_items,
                OrderedDict(self.cache),  # OrderedDict copy
                self.large_count,
                self.total_size
            )
        
        # Create temporary object
        temp_cache = SizeAwarePicklableCache(
            state[0], state[1], state[2], state[3]
        )
        temp_cache.cache = state[4]
        temp_cache.large_count = state[5]
        temp_cache.total_size = state[6]
        
        with open(save_file, 'wb') as f:
            pickle.dump(temp_cache, f)
        
        # Update filename only after successful save
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
        """Load cache or create new if file doesn't exist or is corrupted."""
        try:
            cache = cls.load(filename)
            if not cache.verify_cache_version(version=2):
                # Cache is outdated, create a new one
                cache = cls(
                    maxsize=maxsize,
                    filename=filename,
                    large_threshold=large_threshold,
                    max_large_items=max_large_items
                )
            return cache
        except (FileNotFoundError, EOFError):
            return cls(
                maxsize=maxsize,
                filename=filename,
                large_threshold=large_threshold,
                max_large_items=max_large_items
            )
