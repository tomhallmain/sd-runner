"""Small helpers for re-focusing secondary windows that may already be open."""

from __future__ import annotations

from typing import Any


def try_focus_existing_window(window: Any) -> bool:
    """Raise and activate *window* if it is still visible.

    Returns True when the existing window was brought to the front.
    Returns False when *window* is None, hidden, or its C++ object was deleted.
    """
    if window is None:
        return False
    try:
        if not window.isVisible():
            return False
        if window.isMinimized():
            window.showNormal()
        window.raise_()
        window.activateWindow()
        return True
    except RuntimeError:
        return False


def clear_class_ref_if_self(owner_class: type, attr_name: str, obj: object) -> None:
    """Clear ``owner_class.attr_name`` when it still points at *obj*."""
    if getattr(owner_class, attr_name, None) is obj:
        setattr(owner_class, attr_name, None)
