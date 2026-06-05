from typing import Callable, TypeVar, List, Any, Generic

T = TypeVar('T')


# TODO: Add handling for image-like files (videos, PDFs, HTML, etc.) to extract frames
# - Extract first frame or random frame from videos (mp4, avi, mov, etc.)
# - Extract first page as image from PDFs
# - Extract screenshot from HTML files
# - Create temporary directory to hold extracted reference images
# - Maintain frame/page information for EXIF data inclusion
# - Ensure temporary files persist for duration of API calls


class LazyAdapterList(Generic[T]):
    """List-compatible wrapper that defers adapter object construction until first access.

    Paths are sorted upfront (required for recency ordering) but adapter objects are
    only constructed on demand and cached so each path pays the factory cost once.
    """

    def __init__(self, sorted_paths: List[str], factory: Callable[[str], T]):
        self._paths = sorted_paths
        self._factory = factory
        self._cache: dict[int, T] = {}

    def _get(self, index: int) -> T:
        if index not in self._cache:
            self._cache[index] = self._factory(self._paths[index])
        return self._cache[index]

    def __len__(self) -> int:
        return len(self._paths)

    def __bool__(self) -> bool:
        return len(self._paths) > 0

    def __iter__(self):
        for i in range(len(self._paths)):
            yield self._get(i)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._get(i) for i in range(*index.indices(len(self._paths)))]
        if index < 0:
            index = len(self._paths) + index
        return self._get(index)

    def __repr__(self) -> str:
        return f"LazyAdapterList({len(self._paths)} items, {len(self._cache)} constructed)"


def _sort_adapters_by_recency(
    adapter_files: List[str],
    random_sort: bool,
    app_actions: Any,
    adapter_factory: Callable[[str], T]
) -> LazyAdapterList[T]:
    """
    Centralized sorting logic for adapters by recency with optional jitter.

    Paths are sorted upfront (recency sort requires the full list), but adapter
    objects are not constructed until first access on the returned LazyAdapterList.

    Args:
        adapter_files: List of file paths to process
        random_sort: Whether to apply jitter to the sorting
        app_actions: App actions object for recent file checking
        adapter_factory: Function to create adapter objects from file paths

    Returns:
        LazyAdapterList of adapter objects sorted by recency (least recent first)
    """
    non_recent_paths = []
    recent_paths = []  # (path, recent_index, original_position)

    # Order adapters by recency - most recent first, then non-recent items
    for i, path in enumerate(adapter_files):
        if app_actions is not None:
            recent_index = app_actions.contains_recent_adapter_file(path)
            if recent_index >= 0:
                # Store with index for sorting (lower index = more recent) and original position for jitter
                recent_paths.append((path, recent_index, i))
            else:
                non_recent_paths.append(path)
        else:
            non_recent_paths.append(path)

    # Sort recent paths by recency with optional jitter
    if random_sort and len(adapter_files) > 1:
        # Add jitter based on original position (normalized by file list size)
        jitter_weight = 0.1  # Adjust this to control jitter strength
        max_position = len(adapter_files) - 1
        recent_paths.sort(key=lambda x: -x[1] * (x[2] / max_position * jitter_weight))
    else:
        # Pure recency sorting (lower index = more recent)
        recent_paths.sort(key=lambda x: -x[1])

    # Combine: non-recent items first, then recent items in order of least recent to most recent
    sorted_paths = non_recent_paths + [item[0] for item in recent_paths]
    return LazyAdapterList(sorted_paths, adapter_factory)
