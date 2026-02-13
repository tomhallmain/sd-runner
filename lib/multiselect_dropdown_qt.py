"""
Multi-select dropdown widget for PySide6.

Port of lib/multiselect_dropdown.py. Provides a QPushButton that opens a popup
QListWidget with multi-selection support. The button text shows the current
selection summary.
"""

from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


class MultiSelectDropdown(QWidget):
    """
    A button that opens a popup list with multi-selection.

    Mirrors the API of the tkinter ``MultiSelectDropdown``:
    ``options``, ``selected``, ``get_selected()``, ``set_options_and_selection()``.
    """

    selection_changed = Signal()  # emitted whenever selection changes

    def __init__(
        self,
        parent: QWidget,
        options: List[str],
        select_text: str = "Select...",
        width: int = 160,
        listbox_height: int = 5,
        selected: Optional[List[str]] = None,
        command: Optional[Callable] = None,
    ):
        super().__init__(parent)
        self._options: List[str] = list(options)
        self.selected: List[str] = [s for s in (selected or []) if s in self._options]
        self.select_text = select_text
        self._listbox_height = listbox_height

        if command is not None:
            self.selection_changed.connect(command)

        # Main button
        self.button = QPushButton(self._get_button_text(), self)
        self.button.setFixedWidth(width)
        self.button.clicked.connect(self.toggle_dropdown)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.button)

        # Popup management
        self._popup: Optional[_PopupList] = None

    # ------------------------------------------------------------------
    # Options property
    # ------------------------------------------------------------------
    @property
    def options(self) -> List[str]:
        return self._options

    @options.setter
    def options(self, value: List[str]):
        self._options = list(value)
        self._sync_options_with_ui()

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------
    def get_selected(self) -> List[str]:
        return list(self.selected)

    def set_options_and_selection(self, new_options: List[str], new_selection: List[str]):
        """Atomically update both options and selections with validation."""
        self._options = list(new_options)
        self.selected = [s for s in new_selection if s in self._options]
        self._sync_options_with_ui()

    def toggle_dropdown(self):
        if self._popup is not None and self._popup.isVisible():
            self._destroy_dropdown()
        else:
            self._create_dropdown()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _get_button_text(self) -> str:
        return ", ".join(self.selected) if self.selected else self.select_text

    def _sync_options_with_ui(self):
        self.selected = [s for s in self.selected if s in self._options]
        self.button.setText(self._get_button_text())
        if self._popup is not None and self._popup.isVisible():
            self._popup.refresh(self._options, self.selected)

    def _create_dropdown(self):
        self._popup = _PopupList(
            self, self._options, self.selected, self._listbox_height
        )
        self._popup.selection_updated.connect(self._on_popup_selection)
        self._popup.popup_closed.connect(self._on_popup_closed)

        # Position below the button
        global_pos = self.button.mapToGlobal(QPoint(0, self.button.height()))
        self._popup.move(global_pos)
        self._popup.setFixedWidth(max(self.button.width(), 120))
        self._popup.show()
        self._popup.activateWindow()

    def _destroy_dropdown(self):
        if self._popup is not None:
            self._popup.close()
            self._popup = None

    def _on_popup_selection(self, selected: list):
        self.selected = selected
        self.button.setText(self._get_button_text())
        self.selection_changed.emit()

    def _on_popup_closed(self):
        self._popup = None

    def destroy(self):
        """Explicit cleanup (mirrors tkinter API)."""
        self._destroy_dropdown()
        self.setParent(None)
        self.deleteLater()


class _PopupList(QWidget):
    """Frameless popup containing a multi-select QListWidget."""

    selection_updated = Signal(list)
    popup_closed = Signal()

    def __init__(
        self,
        parent: QWidget,
        options: List[str],
        selected: List[str],
        visible_rows: int,
    ):
        super().__init__(parent, Qt.WindowType.Popup)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.MultiSelection)
        layout.addWidget(self._list)

        self.refresh(options, selected)

        # Size hint: show *visible_rows* items
        row_h = self._list.sizeHintForRow(0) if self._list.count() else 20
        self._list.setFixedHeight(row_h * min(visible_rows, max(len(options), 1)) + 4)

        self._list.itemSelectionChanged.connect(self._emit_selection)

    def refresh(self, options: List[str], selected: List[str]):
        self._list.blockSignals(True)
        self._list.clear()
        for opt in options:
            item = QListWidgetItem(opt)
            self._list.addItem(item)
            if opt in selected:
                item.setSelected(True)
        self._list.blockSignals(False)

    def _emit_selection(self):
        selected = [item.text() for item in self._list.selectedItems()]
        self.selection_updated.emit(selected)

    def closeEvent(self, event):
        self.popup_closed.emit()
        super().closeEvent(event)
