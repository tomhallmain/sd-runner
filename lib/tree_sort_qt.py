"""Header-click sorting for a ``QTreeWidget`` that leaves sorting disabled."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget


def toggle_sort(tree: QTreeWidget, col: int) -> None:
    """Sort *tree* by *col*, alternating direction on each call.

    The first call sorts descending. The direction is kept on the tree itself,
    so it is shared across columns: a click on a new column sorts it opposite
    to the previous click.
    """
    reverse = not getattr(tree, "_sort_reverse", False)
    tree._sort_reverse = reverse
    order = Qt.SortOrder.DescendingOrder if reverse else Qt.SortOrder.AscendingOrder
    tree.sortItems(col, order)
