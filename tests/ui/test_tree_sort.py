"""``toggle_sort``: header clicks alternate the sort direction of a tree."""

from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from lib.tree_sort_qt import toggle_sort


def make_tree(qapp, names):
    tree = QTreeWidget()
    tree.setColumnCount(2)
    for name in names:
        QTreeWidgetItem(tree, [name, name.upper()])
    return tree


def first_column(tree):
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def test_first_call_sorts_descending(qapp):
    tree = make_tree(qapp, ["b", "c", "a"])
    toggle_sort(tree, 0)
    assert first_column(tree) == ["c", "b", "a"]


def test_second_call_reverses(qapp):
    tree = make_tree(qapp, ["b", "c", "a"])
    toggle_sort(tree, 0)
    toggle_sort(tree, 0)
    assert first_column(tree) == ["a", "b", "c"]


def test_direction_is_shared_across_columns(qapp):
    tree = make_tree(qapp, ["b", "c", "a"])
    toggle_sort(tree, 0)
    toggle_sort(tree, 1)
    assert first_column(tree) == ["a", "b", "c"]


def test_trees_keep_their_own_direction(qapp):
    first = make_tree(qapp, ["a", "b"])
    second = make_tree(qapp, ["a", "b"])
    toggle_sort(first, 0)
    toggle_sort(second, 0)
    assert first_column(first) == first_column(second) == ["b", "a"]
