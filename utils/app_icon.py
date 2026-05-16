"""Application icon path resolution for the PySide6 UI."""

import os

APP_ICON_FILENAME = "icon.png"


def _assets_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "assets")


def get_app_icon_path() -> str | None:
    """Return the path to the application icon PNG, or None if missing."""
    path = os.path.join(_assets_dir(), APP_ICON_FILENAME)
    return path if os.path.isfile(path) else None


def apply_app_icon(qt_app) -> bool:
    """Set the QApplication window icon. Returns True if an icon was applied."""
    from PySide6.QtGui import QIcon

    icon_path = get_app_icon_path()
    if not icon_path:
        return False
    qt_app.setWindowIcon(QIcon(icon_path))
    return True
