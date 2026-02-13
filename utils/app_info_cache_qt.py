"""
PySide6 adapter for the application info cache.

Wraps the existing ``app_info_cache`` singleton from ``utils.app_info_cache``
so that display-position storage and retrieval use
``lib.position_data_qt.PositionData`` (PySide6-aware) instead of the
tkinter-based ``lib.position_data.PositionData``.

All other cache functionality (encryption, backup rotation, inflation
monitoring, directory / meta storage) delegates unchanged to the underlying
singleton -- there is only **one** in-memory cache, avoiding write conflicts.

Usage::

    from utils.app_info_cache_qt import app_info_cache

    # Meta / directory operations -- identical to the base cache:
    app_info_cache.get_meta("key")
    app_info_cache.set_meta("key", value)

    # Position operations -- use PySide6 PositionData:
    app_info_cache.set_display_position(qt_main_window)
    pos = app_info_cache.get_display_position()   # returns position_data_qt.PositionData
"""

from lib.position_data_qt import PositionData
from utils.app_info_cache import app_info_cache as _base_cache
from utils.logging_setup import get_logger

logger = get_logger(__name__)


class _AppInfoCacheQtAdapter:
    """
    Thin proxy around the base ``AppInfoCache`` singleton.

    Delegates every attribute access to the underlying cache.  Only the
    four display-position helpers are overridden to use the Qt-aware
    ``PositionData``.
    """

    def __init__(self, base):
        # Use object.__setattr__ to avoid triggering our own __setattr__
        object.__setattr__(self, "_base", base)

    # ------------------------------------------------------------------
    # Overridden position helpers (Qt PositionData)
    # ------------------------------------------------------------------
    def set_display_position(self, master):
        """Store the main window's display position and size (PySide6 QWidget)."""
        self._base.set_meta(
            "display_position",
            PositionData.from_master(master).to_dict(),
        )

    def set_virtual_screen_info(self, master):
        """Store virtual screen information (PySide6 QWidget)."""
        try:
            self._base.set_meta(
                "virtual_screen_info",
                PositionData.from_master_virtual_screen(master).to_dict(),
            )
        except Exception as e:
            logger.warning(f"Failed to store virtual screen info: {e}")

    def get_display_position(self):
        """Get the cached display position as a Qt-aware PositionData (or None)."""
        data = self._base.get_meta("display_position")
        if not data:
            return None
        return PositionData.from_dict(data)

    def get_virtual_screen_info(self):
        """Get the cached virtual screen info as a Qt-aware PositionData (or None)."""
        data = self._base.get_meta("virtual_screen_info")
        if not data:
            return None
        return PositionData.from_dict(data)

    # ------------------------------------------------------------------
    # Transparent delegation for everything else
    # ------------------------------------------------------------------
    def __getattr__(self, name):
        return getattr(self._base, name)

    def __setattr__(self, name, value):
        if name == "_base":
            object.__setattr__(self, name, value)
        else:
            setattr(self._base, name, value)


# The module-level singleton: same on-disk cache, Qt-aware position methods.
app_info_cache = _AppInfoCacheQtAdapter(_base_cache)
