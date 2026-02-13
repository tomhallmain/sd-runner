"""
KeyBindingManager -- owns all QShortcut creation.

Extracted from the key-binding block in App.__init__.
Each shortcut is guarded by a focus check so that single-key shortcuts
are suppressed while the user is typing in an AwareEntry.

Tkinter key syntax → Qt key syntax mapping:
    <Control-Return>    → Ctrl+Return
    <Shift-R>           → Shift+R
    <Prior>             → PgUp  (Qt uses "Prior")
    <Next>              → PgDown (Qt uses "Next")
    <Home>              → Home
    <End>               → End
    <Control-b>         → Ctrl+B
    <Control-q>         → Ctrl+Q
    <Control-p>         → Ctrl+P
    <Control-d>         → Ctrl+D
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Callable

from PySide6.QtGui import QKeySequence, QShortcut

from lib.aware_entry_qt import AwareEntry
from utils.logging_setup import get_logger

if TYPE_CHECKING:
    from ui_qt.app_window.app_window import AppWindow

logger = get_logger("ui_qt.key_binding_manager")


class KeyBindingManager:
    """
    Creates all keyboard shortcuts for the main AppWindow.

    Shortcuts that conflict with text entry (single-character keys,
    Shift+<letter>) are wrapped in a guard that checks
    ``AwareEntry.an_entry_has_focus``.
    """

    def __init__(self, app_window: AppWindow):
        self._app = app_window
        self._shortcuts: list[QShortcut] = []
        self._bind_all()

    # ------------------------------------------------------------------
    # Guard wrapper
    # ------------------------------------------------------------------
    @staticmethod
    def _guarded(func: Callable) -> Callable:
        """Wrap *func* so it only fires when no AwareEntry has focus."""
        def wrapper():
            if not AwareEntry.an_entry_has_focus:
                func()
        return wrapper

    # ------------------------------------------------------------------
    # Shortcut helper
    # ------------------------------------------------------------------
    def _bind(self, key: str, func: Callable, guarded: bool = True) -> None:
        """Create a QShortcut, optionally guarded against text entry focus."""
        target = self._guarded(func) if guarded else func
        shortcut = QShortcut(QKeySequence(key), self._app)
        shortcut.activated.connect(target)
        self._shortcuts.append(shortcut)

    # ------------------------------------------------------------------
    # All bindings -- ported from App.__init__
    # ------------------------------------------------------------------
    def _bind_all(self) -> None:
        """Register all keyboard shortcuts."""
        app = self._app

        # ==============================================================
        # Run / cancel
        # ==============================================================
        self._bind("Ctrl+Return", app.run_ctrl.run, guarded=False)
        self._bind("Shift+R", app.run_ctrl.run)
        self._bind("Shift+N", app.sidebar_panel.next_preset)

        # ==============================================================
        # Config history navigation
        # ==============================================================
        self._bind("Prior", lambda: app.one_config_away(change=1))
        self._bind("Next", lambda: app.one_config_away(change=-1))
        self._bind("Home", lambda: app.first_config())
        self._bind("End", lambda: app.first_config(end=True))

        # ==============================================================
        # Window launchers (Ctrl+<key>)
        # ==============================================================
        self._bind("Ctrl+B", app.window_launcher.show_tag_blacklist, guarded=False)
        self._bind("Ctrl+P", app.window_launcher.open_password_admin_window, guarded=False)

        # ==============================================================
        # Application control
        # ==============================================================
        self._bind("Ctrl+Q", app.quit, guarded=False)
        self._bind("Ctrl+D", app.toggle_debug, guarded=False)
