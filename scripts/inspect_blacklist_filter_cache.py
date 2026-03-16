import argparse
import datetime
import hashlib
import os
import pickle
import sys


# Ensure we are running from the project root for imports and relative paths
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(PROJECT_ROOT)
sys.path.insert(0, PROJECT_ROOT)


DEFAULT_CACHE_PATH = os.path.join("configs", "blacklist_filter_cache.pkl")


def _human_bytes(num_bytes: int) -> str:
    units = ["B", "KB", "MB", "GB", "TB"]
    value = float(num_bytes)
    for unit in units:
        if value < 1024.0 or unit == units[-1]:
            return f"{value:.2f} {unit}"
        value /= 1024.0
    return f"{num_bytes} B"


def _safe_len(value) -> int:
    try:
        return len(value)
    except Exception:
        return -1


def _key_signature(key) -> str:
    if isinstance(key, tuple):
        key_len = len(key)
        if key_len == 0:
            return "tuple(len=0)"
        first = str(key[0])[:60]
        digest = hashlib.md5(str(key[: min(5, key_len)]).encode("utf-8")).hexdigest()[:10]
        return f"tuple(len={key_len}, first='{first}', md5[:10]={digest})"
    return f"{type(key).__name__}"


def _entry_summary(raw_entry):
    """
    SizeAwarePicklableCache stores entries as (value, stored_size).
    """
    if isinstance(raw_entry, tuple) and len(raw_entry) == 2 and isinstance(raw_entry[1], int):
        value, stored_size = raw_entry
    else:
        value = raw_entry
        stored_size = None

    whitelist_count = -1
    filtered_count = -1
    if isinstance(value, tuple) and len(value) == 2:
        whitelist_count = _safe_len(value[0])
        filtered_count = _safe_len(value[1])

    return whitelist_count, filtered_count, stored_size


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect blacklist filter cache contents in a readable summary."
    )
    parser.add_argument(
        "--cache-path",
        default=DEFAULT_CACHE_PATH,
        help=f"Path to cache pickle file (default: {DEFAULT_CACHE_PATH})",
    )
    parser.add_argument(
        "--show-top",
        type=int,
        default=10,
        help="How many largest stored entries to print",
    )
    parser.add_argument(
        "--show-sample",
        type=int,
        default=5,
        help="How many first entries to print as samples",
    )
    args = parser.parse_args()

    cache_path = os.path.abspath(args.cache_path)
    if not os.path.exists(cache_path):
        print(f"Cache file not found: {cache_path}")
        return

    file_size = os.path.getsize(cache_path)
    modified_ts = datetime.datetime.fromtimestamp(os.path.getmtime(cache_path)).isoformat(sep=" ", timespec="seconds")
    print("=== Blacklist Filter Cache File ===")
    print(f"Path          : {cache_path}")
    print(f"File size     : {_human_bytes(file_size)} ({file_size} bytes)")
    print(f"Last modified : {modified_ts}")

    try:
        with open(cache_path, "rb") as f:
            cache_obj = pickle.load(f)
    except Exception as e:
        print(f"\nFailed to unpickle cache: {e}")
        return

    cache_data = getattr(cache_obj, "cache", None)
    if cache_data is None:
        print("\nUnpickled object does not have a 'cache' attribute.")
        print(f"Object type: {type(cache_obj).__name__}")
        return

    print("\n=== Cache Metadata ===")
    print(f"Object type       : {type(cache_obj).__name__}")
    print(f"Version           : {getattr(cache_obj, 'version', 'unknown')}")
    print(f"Max size          : {getattr(cache_obj, 'maxsize', 'unknown')}")
    print(f"Large threshold   : {getattr(cache_obj, 'large_threshold', 'n/a')}")
    print(f"Max large items   : {getattr(cache_obj, 'max_large_items', 'n/a')}")
    print(f"Protected large   : {getattr(cache_obj, 'protected_large_items', 'n/a')}")
    print(f"Large count       : {getattr(cache_obj, 'large_count', 'n/a')}")
    print(f"Total size tracked: {getattr(cache_obj, 'total_size', 'n/a')}")
    print(f"Version cache     : {getattr(cache_obj, 'version_cache', None)}")
    print(f"Entry count       : {len(cache_data)}")

    if len(cache_data) == 0:
        print("\nCache is empty.")
        return

    entries = list(cache_data.items())

    # Show aggregate stats
    key_lengths = []
    whitelist_lengths = []
    filtered_lengths = []
    stored_sizes = []

    for key, raw_entry in entries:
        if isinstance(key, tuple):
            key_lengths.append(len(key))
        wl_count, fl_count, stored_size = _entry_summary(raw_entry)
        if wl_count >= 0:
            whitelist_lengths.append(wl_count)
        if fl_count >= 0:
            filtered_lengths.append(fl_count)
        if stored_size is not None:
            stored_sizes.append(stored_size)

    def _range(values):
        if not values:
            return "n/a"
        return f"min={min(values)}, max={max(values)}, avg={sum(values)/len(values):.2f}"

    print("\n=== Aggregate Stats ===")
    print(f"Key tuple lengths : {_range(key_lengths)}")
    print(f"Whitelist lengths : {_range(whitelist_lengths)}")
    print(f"Filtered lengths  : {_range(filtered_lengths)}")
    if stored_sizes:
        print(f"Stored sizes      : min={_human_bytes(min(stored_sizes))}, max={_human_bytes(max(stored_sizes))}, avg={_human_bytes(int(sum(stored_sizes)/len(stored_sizes)))}")
    else:
        print("Stored sizes      : n/a")

    # Show top entries by stored size
    if stored_sizes:
        top_n = max(0, args.show_top)
        print(f"\n=== Top {top_n} Largest Entries ===")
        sized_entries = []
        for key, raw_entry in entries:
            wl_count, fl_count, stored_size = _entry_summary(raw_entry)
            if stored_size is not None:
                sized_entries.append((stored_size, key, wl_count, fl_count))
        sized_entries.sort(key=lambda x: x[0], reverse=True)
        for idx, (stored_size, key, wl_count, fl_count) in enumerate(sized_entries[:top_n], start=1):
            print(
                f"{idx:>2}. size={_human_bytes(stored_size):>10} | "
                f"wl={wl_count:>8} | filtered={fl_count:>8} | {_key_signature(key)}"
            )

    # Show first sample entries in LRU order
    sample_n = max(0, args.show_sample)
    print(f"\n=== First {sample_n} Entry Samples (LRU order) ===")
    for idx, (key, raw_entry) in enumerate(entries[:sample_n], start=1):
        wl_count, fl_count, stored_size = _entry_summary(raw_entry)
        size_text = _human_bytes(stored_size) if stored_size is not None else "n/a"
        print(
            f"{idx:>2}. size={size_text:>10} | wl={wl_count:>8} | filtered={fl_count:>8} | {_key_signature(key)}"
        )


if __name__ == "__main__":
    main()
