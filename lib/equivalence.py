"""Value comparison for change detection.

Used by AppInfoCache to decide whether a write actually changes anything, so a
periodic store can be skipped when nothing has moved.

The bias is deliberate and one-directional: when in doubt, report *not*
equivalent. A false "not equivalent" costs one unnecessary write; a false
"equivalent" silently drops a change the user made.
"""


def are_equivalent(first, second) -> bool:
    """True if *first* and *second* represent the same cached value.

    Container contents are compared structurally, with dict key order ignored
    and list order significant. Anything that raises during comparison is
    reported as not equivalent rather than propagating.
    """
    try:
        if first is second:
            return True
        # bool is a subclass of int, so compare types before falling through to
        # ==: True == 1 must not read as an unchanged value.
        if isinstance(first, bool) != isinstance(second, bool):
            return False
        if isinstance(first, dict) and isinstance(second, dict):
            if len(first) != len(second) or set(first.keys()) != set(second.keys()):
                return False
            return all(are_equivalent(first[key], second[key]) for key in first)
        if isinstance(first, (list, tuple)) and isinstance(second, (list, tuple)):
            if len(first) != len(second):
                return False
            return all(are_equivalent(a, b) for a, b in zip(first, second))
        return bool(first == second)
    except Exception:
        return False
