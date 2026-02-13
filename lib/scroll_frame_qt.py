"""
Scrollable frame widget for PySide6.

Port of lib/tk_scroll_demo.py (ScrollFrame). In PySide6, QScrollArea already
provides native scroll support with automatic scroll-bar management and mouse
wheel forwarding, so the heavy lifting that the tkinter version does manually
is unnecessary.

This module provides a thin convenience wrapper so that consumer code has a
consistent API: add child widgets to ``scroll_frame.viewPort`` (a QWidget with
a QVBoxLayout), and pack/add the ``ScrollFrame`` itself into your layout.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget


class ScrollFrame(QScrollArea):
    """
    A QScrollArea pre-configured with an inner viewport widget.

    Usage::

        sf = ScrollFrame(parent)
        # Add children to the viewport:
        sf.viewPort.layout().addWidget(some_label)
        sf.viewPort.layout().addWidget(some_button)
        # Then add the ScrollFrame itself to your layout:
        parent_layout.addWidget(sf)

    The viewport layout has a stretch at the bottom by default so that
    content is top-aligned. Call ``sf.set_bottom_stretch(False)`` if you
    want content to fill the entire height instead.
    """

    def __init__(self, parent: QWidget = None, bg_color: str | None = None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self.viewPort = QWidget()
        self._layout = QVBoxLayout(self.viewPort)
        self._layout.setContentsMargins(4, 4, 4, 4)
        self._layout.setSpacing(2)
        self._layout.addStretch()  # keeps content top-aligned

        self.setWidget(self.viewPort)

        if bg_color:
            self.setStyleSheet(f"QScrollArea {{ background-color: {bg_color}; }}")
            self.viewPort.setStyleSheet(f"background-color: {bg_color};")

    def add_widget(self, widget: QWidget):
        """Convenience: insert a widget above the bottom stretch."""
        count = self._layout.count()
        # Insert before the trailing stretch
        self._layout.insertWidget(count - 1, widget)

    def set_bottom_stretch(self, enabled: bool = True):
        """Enable or disable the bottom stretch that top-aligns content."""
        last = self._layout.itemAt(self._layout.count() - 1)
        if enabled:
            if last is None or last.widget() is not None:
                self._layout.addStretch()
        else:
            if last is not None and last.widget() is None:
                self._layout.removeItem(last)
