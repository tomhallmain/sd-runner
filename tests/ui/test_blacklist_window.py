"""Blacklist item CRUD through the widgets.

The window is the only way a user edits the blacklist, and every editing action
on it sits behind ``@require_password``. Both halves are asserted here: that the
action reaches ``Blacklist.TAG_BLACKLIST``, and that it does not when the gate
refuses.

Adding goes through ``BlacklistModifyWindow`` -- the parent window only opens
it, and the item is built and handed back on save -- so an add test drives both
windows. Removing and toggling act on the table selection, which exists only
after the concepts are revealed, itself a gated action.

``Blacklist`` matching, backup and persistence are unit-tested elsewhere; what
is exercised here is the path a user takes to reach them.
"""

from types import SimpleNamespace

import pytest

from sd_runner.prompts.blacklist import Blacklist, BlacklistItem
from sd_runner.ui.prompts.blacklist_window import BlacklistWindow
from tests.utils import close_window, install_password_bypass


class RecordingAppActions:
    """AppActions stand-in that records toasts and answers confirmations."""

    def __init__(self, confirm=True):
        self.toasts = []
        self.alerts = []
        self._confirm = confirm

    def toast(self, message, *args, **kwargs):
        self.toasts.append(message)

    def alert(self, title, message, kind=None, master=None, **kwargs):
        self.alerts.append((title, message, kind))
        return self._confirm

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


def open_window(monkeypatch, granted=True):
    crossings = install_password_bypass(monkeypatch, granted=granted)
    actions = RecordingAppActions()
    window = BlacklistWindow(None, actions)
    window._test_actions = actions
    window._test_crossings = crossings
    return window


@pytest.fixture
def window(qapp, monkeypatch):
    """An open blacklist window with the password gate answering yes."""
    win = open_window(monkeypatch)
    try:
        yield win
    finally:
        close_window(win)


@pytest.fixture
def gated_window(qapp, monkeypatch):
    """The same window with the gate refusing, to prove the gate is enforced."""
    win = open_window(monkeypatch, granted=False)
    try:
        yield win
    finally:
        close_window(win)


def add_item(window, string):
    """Add one item the way a user does: open the editor, type, save."""
    window._add_new_item()
    modify = BlacklistWindow._modify_window
    modify._string_entry.setText(string)
    modify._finalize()


def reveal(window):
    """Show the item table. Selection-based actions need it to exist."""
    window._reveal_concepts()


def strings(items=None):
    return [item.string for item in (items if items is not None else Blacklist.get_items())]


# ---------------------------------------------------------------------------
# Opening
# ---------------------------------------------------------------------------

class TestOpening:
    def test_it_starts_with_the_concepts_hidden(self, window):
        """The list is offensive by construction, so it is not shown until
        asked for."""
        assert window._concepts_revealed is False

    def test_no_table_exists_before_the_reveal(self, window):
        Blacklist.add_item(BlacklistItem("forbidden"))
        window._refresh()
        assert window._tag_table is None

    def test_revealing_builds_the_table(self, window):
        Blacklist.add_item(BlacklistItem("forbidden"))
        window._refresh()
        reveal(window)
        assert window._tag_table is not None

    def test_the_reveal_is_behind_the_password_gate(self, window):
        reveal(window)
        assert window._test_crossings, "_reveal_concepts ran without crossing the gate"

    def test_a_refused_reveal_keeps_the_concepts_hidden(self, gated_window):
        reveal(gated_window)
        assert gated_window._concepts_revealed is False


# ---------------------------------------------------------------------------
# Add
# ---------------------------------------------------------------------------

class TestAddItem:
    def test_the_item_reaches_the_blacklist(self, window):
        add_item(window, "forbidden")
        assert "forbidden" in strings()

    def test_an_empty_string_adds_nothing(self, window):
        window._add_new_item()
        modify = BlacklistWindow._modify_window
        modify._string_entry.setText("   ")
        modify._finalize()
        assert Blacklist.is_empty()

    def test_adding_is_behind_the_password_gate(self, window):
        add_item(window, "forbidden")
        assert window._test_crossings, "_add_new_item ran without crossing the gate"

    def test_a_refused_gate_opens_no_editor(self, gated_window):
        gated_window._add_new_item()
        assert BlacklistWindow._modify_window is None

    def test_the_added_item_is_recorded_in_history(self, window):
        add_item(window, "forbidden")
        assert strings(BlacklistWindow.item_history) == ["forbidden"]

    def test_two_items_both_survive(self, window):
        add_item(window, "forbidden")
        add_item(window, "banned")
        assert set(strings()) == {"forbidden", "banned"}


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

class TestToggleItem:
    def _select_first(self, window):
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(0, 0)

    def test_toggling_disables_an_enabled_item(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._toggle_selected_tag()
        assert Blacklist.get_items()[0].enabled is False

    def test_toggling_twice_returns_it_to_enabled(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._toggle_selected_tag()
        window._toggle_selected_tag()
        assert Blacklist.get_items()[0].enabled is True

    def test_a_disabled_item_stops_matching(self, window):
        """Disabling is the point of the toggle: the item stays on the list and
        stops filtering."""
        add_item(window, "forbidden")
        self._select_first(window)
        window._toggle_selected_tag()
        assert Blacklist.get_violation_item("forbidden") is None

    def test_the_item_is_not_removed(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._toggle_selected_tag()
        assert strings() == ["forbidden"]

    def test_nothing_selected_changes_nothing(self, window):
        add_item(window, "forbidden")
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(-1, -1)
        window._toggle_selected_tag()
        assert Blacklist.get_items()[0].enabled is True

    def test_toggling_is_behind_the_password_gate(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._test_crossings.clear()
        window._toggle_selected_tag()
        assert window._test_crossings, "_toggle_item ran without crossing the gate"


# ---------------------------------------------------------------------------
# Remove
# ---------------------------------------------------------------------------

class TestRemoveItem:
    def _select_first(self, window):
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(0, 0)

    def test_the_item_leaves_the_blacklist(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._remove_selected_tag()
        assert Blacklist.is_empty()

    def test_the_other_items_are_untouched(self, window):
        add_item(window, "forbidden")
        add_item(window, "banned")
        window._refresh()
        reveal(window)
        row = strings(window._filtered_items).index("forbidden")
        window._tag_table.setCurrentCell(row, 0)
        window._remove_selected_tag()
        assert strings() == ["banned"]

    def test_the_removed_item_stops_matching(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._remove_selected_tag()
        assert Blacklist.get_violation_item("forbidden") is None

    def test_nothing_selected_removes_nothing(self, window):
        add_item(window, "forbidden")
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(-1, -1)
        window._remove_selected_tag()
        assert strings() == ["forbidden"]

    def test_removing_is_behind_the_password_gate(self, window):
        add_item(window, "forbidden")
        self._select_first(window)
        window._test_crossings.clear()
        window._remove_selected_tag()
        assert window._test_crossings, "_remove_item ran without crossing the gate"


# ---------------------------------------------------------------------------
# Add, toggle, remove in sequence
# ---------------------------------------------------------------------------

class TestTheFullSequence:
    def test_the_blacklist_ends_where_it_started(self, window):
        add_item(window, "forbidden")
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(0, 0)
        window._toggle_selected_tag()
        window._remove_selected_tag()
        assert Blacklist.is_empty()

    def test_a_stale_row_index_would_show_here(self, window):
        """Each action rebuilds the table from the filtered list, so a removal
        that did not refresh would leave the next action pointed at a row that
        no longer means what it did."""
        add_item(window, "forbidden")
        add_item(window, "banned")
        window._refresh()
        reveal(window)
        window._tag_table.setCurrentCell(0, 0)
        first = window._filtered_items[0].string
        window._remove_selected_tag()
        assert first not in strings()


# ---------------------------------------------------------------------------
# Escape closes without releasing the singleton twice
# ---------------------------------------------------------------------------

class TestDismissal:
    def test_escape_clears_the_singleton(self, qapp, monkeypatch):
        """Escape reaches reject(), which does not fire closeEvent -- so the
        release has to be reachable from both."""
        win = open_window(monkeypatch)
        win.reject()
        try:
            assert BlacklistWindow._instance is None
        finally:
            close_window(win)

    def test_the_release_is_idempotent(self, qapp, monkeypatch):
        """Both paths can run for a single dismissal, so the second must not
        fail on what the first already let go of."""
        win = open_window(monkeypatch)
        try:
            win._release()
            win._release()
            assert BlacklistWindow._instance is None
        finally:
            close_window(win)

    def test_the_release_closes_an_open_editor(self, qapp, monkeypatch):
        """Otherwise the class reference outlives the window that owns it.

        A stand-in rather than a real editor: driving this with two live
        dialogs and letting the parent be destroyed under the child is what the
        app itself does on Escape, but reproducing it here brings down the
        interpreter during Qt's deferred deletion rather than failing.
        """
        win = open_window(monkeypatch)
        try:
            closed = []
            BlacklistWindow._modify_window = SimpleNamespace(
                _saved=False, close=lambda: closed.append(True),
            )
            win._release()
            assert closed == [True]
            assert BlacklistWindow._modify_window is None
        finally:
            BlacklistWindow._modify_window = None
            close_window(win)
