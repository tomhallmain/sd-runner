from typing import Callable, TypeVar, List, Any

T = TypeVar('T')


# TODO: Add handling for image-like files (videos, PDFs, HTML, etc.) to extract frames
# - Extract first frame or random frame from videos (mp4, avi, mov, etc.)
# - Extract first page as image from PDFs
# - Extract screenshot from HTML files
# - Create temporary directory to hold extracted reference images
# - Maintain frame/page information for EXIF data inclusion
# - Ensure temporary files persist for duration of API calls


def _sort_adapters_by_recency(
    adapter_files: List[str], 
    random_sort: bool, 
    app_actions: Any,
    adapter_factory: Callable[[str], T]
) -> List[T]:
    """
    Centralized sorting logic for adapters by recency with optional jitter.
    
    Args:
        adapter_files: List of file paths to process
        random_sort: Whether to apply jitter to the sorting
        app_actions: App actions object for recent file checking
        adapter_factory: Function to create adapter objects from file paths
        
    Returns:
        List of adapter objects sorted by recency (least recent first)
    """
    adapters = []
    recent_adapters = []
    
    # Order adapters by recency - most recent first, then non-recent items
    for i, path in enumerate(adapter_files):
        if app_actions is not None:
            recent_index = app_actions.contains_recent_adapter_file(path)
            if recent_index >= 0:
                # Store with index for sorting (lower index = more recent) and original position for jitter
                recent_adapters.append((adapter_factory(path), recent_index, i))
            else:
                adapters.append(adapter_factory(path))
        else:
            adapters.append(adapter_factory(path))
    
    # Sort recent adapters by recency with optional jitter
    if random_sort and len(adapter_files) > 1:
        # Add jitter based on original position (normalized by file list size)
        jitter_weight = 0.1  # Adjust this to control jitter strength
        max_position = len(adapter_files) - 1
        recent_adapters.sort(key=lambda x: -x[1] * (x[2] / max_position * jitter_weight))
    else:
        # Pure recency sorting (lower index = more recent)
        recent_adapters.sort(key=lambda x: -x[1])
    recent_adapters_only = [item[0] for item in recent_adapters]
    
    # Combine: non-recent items first, then recent items in order of least recent to most recent
    return adapters + recent_adapters_only
