"""
Focus-aware QLineEdit for PySide6.

Port of lib/aware_entry.py. Provides a class-level flag that tracks whether
any AwareEntry instance currently has keyboard focus. This is used by the
main application window to suppress single-key shortcuts while the user is
typing in a text field.
"""

from PySide6.QtWidgets import QLineEdit


class AwareEntry(QLineEdit):
    """QLineEdit subclass that maintains a class-level focus flag."""

    an_entry_has_focus: bool = False

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def focusInEvent(self, event):
        AwareEntry.an_entry_has_focus = True
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        AwareEntry.an_entry_has_focus = False
        super().focusOutEvent(event)
