"""Application icon path resolution for the PySide6 UI."""

import os

APP_ICON_FILENAME = "app_icon_tableau_duotone_angled.png"
APP_ICON_FALLBACK_FILENAME = "icon.png"


def _assets_dir() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(__file__))), "assets")


def get_app_icon_path() -> str | None:
    """Return the path to the application icon PNG, or None if missing."""
    assets = _assets_dir()
    for name in (APP_ICON_FILENAME, APP_ICON_FALLBACK_FILENAME):
        path = os.path.join(assets, name)
        if os.path.isfile(path):
            return path
    return None


def apply_app_icon(qt_app) -> bool:
    """Set the QApplication window icon. Returns True if an icon was applied."""
    from PySide6.QtGui import QIcon

    icon_path = get_app_icon_path()
    if not icon_path:
        return False
    qt_app.setWindowIcon(QIcon(icon_path))
    return True
