"""
Autocomplete QLineEdit for PySide6.

Port of lib/autocomplete_entry.py.  Provides a text entry with a dropdown
completion list that supports custom matching and selection functions.  This
enables multi-tag autocomplete (e.g. comma- or plus-separated values) when
the caller supplies appropriate *matches_function* and *set_function*
callbacks.

Modified from source: https://gist.github.com/uroshekic/11078820
"""

import re

from PySide6.QtWidgets import QListWidget, QListWidgetItem
from PySide6.QtCore import Qt, QPoint, QTimer
from PySide6.QtGui import QFocusEvent

from lib.aware_entry_qt import AwareEntry


def default_matches(field_value: str, ac_list_entry: str) -> bool:
    """Default case-insensitive substring match."""
    if not field_value:
        return False
    pattern = re.compile(".*" + re.escape(field_value) + ".*", re.IGNORECASE)
    return bool(pattern.match(ac_list_entry))


class AutocompleteEntry(AwareEntry):
    """AwareEntry subclass with a popup autocomplete list.

    Parameters
    ----------
    autocomplete_list : list[str]
        The full list of possible completions.
    parent : QWidget | None
        Parent widget.
    listbox_length : int
        Maximum number of visible rows in the popup (default ``8``).
    matches_function : callable | None
        ``(field_value, ac_list_entry) -> bool``.  Called for each item
        in *autocomplete_list* to decide whether it matches the current
        text.  Defaults to case-insensitive substring matching.  For
        multi-tag fields the caller can split on a separator and match
        only the rightmost segment.
    set_function : callable | None
        ``(current_value, new_value) -> str``.  Controls how a selected
        completion is merged into the current text.  Defaults to
        replacing the entire text.  For multi-tag fields the caller can
        append the new value after the last separator instead.
    """

    def __init__(
        self,
        autocomplete_list: list[str] | None = None,
        parent=None,
        *,
        listbox_length: int = 8,
        matches_function=None,
        set_function=None,
    ):
        super().__init__(parent)
        self.autocomplete_list: list[str] = autocomplete_list or []
        self.listbox_length = listbox_length
        self.matches_function = matches_function or default_matches
        self.set_function = set_function or (lambda _cur, new: new)

        self._popup: _CompletionPopup | None = None
        self._popup_visible = False

        # Suppress popup updates triggered by programmatic setText() inside
        # _accept_completion to avoid a re-entrant popup refresh.
        self._suppress_changes = False

        self.textChanged.connect(self._on_text_changed)

    # ------------------------------------------------------------------
    # Public helpers
    # ------------------------------------------------------------------

    def set_autocomplete_list(self, items: list[str]) -> None:
        """Replace the completion list at runtime."""
        self.autocomplete_list = items
        if self._popup_visible:
            self._refresh_popup()

    def close_listbox(self) -> None:
        """Programmatically dismiss the completion popup."""
        if self._popup is not None:
            self._popup.close()
            self._popup.deleteLater()
            self._popup = None
            self._popup_visible = False

    # Alias used by external code (matches plan wording).
    closeListbox = close_listbox

    # ------------------------------------------------------------------
    # Internal -- text change handling
    # ------------------------------------------------------------------

    def _matching_words(self) -> list[str]:
        text = self.text()
        return [w for w in self.autocomplete_list if self.matches_function(text, w)]

    def _on_text_changed(self, text: str) -> None:
        if self._suppress_changes:
            return
        if not text:
            self.close_listbox()
            return
        words = self._matching_words()
        if words:
            self._show_popup(words)
        else:
            self.close_listbox()

    # ------------------------------------------------------------------
    # Internal -- popup management
    # ------------------------------------------------------------------

    def _show_popup(self, words: list[str]) -> None:
        if not self._popup_visible:
            self._popup = _CompletionPopup(owner=self)
            self._popup.itemClicked.connect(self._on_item_clicked)
            self._popup_visible = True

        self._fill_popup(words)
        self._position_popup()
        self._popup.show()

    def _refresh_popup(self) -> None:
        words = self._matching_words()
        if words and self._popup is not None:
            self._fill_popup(words)
        else:
            self.close_listbox()

    def _fill_popup(self, words: list[str]) -> None:
        popup = self._popup
        popup.clear()
        for w in words:
            popup.addItem(w)
        visible = min(len(words), self.listbox_length)
        row_h = popup.sizeHintForRow(0) if popup.count() else 20
        popup.setFixedHeight(row_h * visible + 2 * popup.frameWidth())

    def _position_popup(self) -> None:
        """Place the popup directly below this entry, left-aligned."""
        popup = self._popup
        bottom_left = self.mapToGlobal(QPoint(0, self.height()))
        popup.setFixedWidth(self.width())
        popup.move(bottom_left)

    # ------------------------------------------------------------------
    # Internal -- selection
    # ------------------------------------------------------------------

    def _on_item_clicked(self, item: QListWidgetItem) -> None:
        self._accept_completion(item.text())

    def _accept_completion(self, value: str) -> None:
        new_text = self.set_function(self.text(), value)
        self._suppress_changes = True
        self.setText(new_text)
        self._suppress_changes = False
        self.setCursorPosition(len(new_text))
        self.close_listbox()
        self.setFocus()

    # ------------------------------------------------------------------
    # Keyboard handling
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = event.key()

        if self._popup_visible and self._popup is not None:
            if key == Qt.Key.Key_Up:
                self._move_selection(-1)
                return
            if key == Qt.Key.Key_Down:
                self._move_selection(1)
                return
            if key in (
                Qt.Key.Key_Right,
                Qt.Key.Key_Return,
                Qt.Key.Key_Enter,
                Qt.Key.Key_Tab,
            ):
                current = self._popup.currentItem()
                if current is not None:
                    self._accept_completion(current.text())
                    return
                # No selection — let the event propagate normally
            if key == Qt.Key.Key_Escape:
                self.close_listbox()
                return

        super().keyPressEvent(event)

    def _move_selection(self, delta: int) -> None:
        popup = self._popup
        row = popup.currentRow()
        new_row = max(0, min(row + delta, popup.count() - 1))
        popup.setCurrentRow(new_row)
        popup.scrollToItem(popup.item(new_row))

    # ------------------------------------------------------------------
    # Focus handling
    # ------------------------------------------------------------------

    def focusOutEvent(self, event: QFocusEvent) -> None:  # noqa: N802
        # Delay so that a click on the popup is processed before we close.
        QTimer.singleShot(150, self._maybe_close_on_focus_loss)
        super().focusOutEvent(event)

    def _maybe_close_on_focus_loss(self) -> None:
        if not self.hasFocus():
            if self._popup is None or not self._popup.isActiveWindow():
                self.close_listbox()


# ======================================================================
# Popup widget
# ======================================================================

class _CompletionPopup(QListWidget):
    """Frameless top-level popup list used by :class:`AutocompleteEntry`."""

    def __init__(self, owner: AutocompleteEntry):
        # Top-level (no Qt parent) so it isn't clipped by the entry's container.
        super().__init__(parent=None)
        self._owner = owner
        self.setWindowFlags(
            Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
        )
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
