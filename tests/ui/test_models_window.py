"""Model browser: what it lists, and what a selection does.

The window does not own the models -- it reads ``Model.CHECKPOINTS`` and
``Model.LORAS`` and hands a chosen name back through
``set_model_from_models_window``, so the assertions here are on the list it
builds and the call it makes.

Two things are easy to get wrong and are pinned. The scan result is cached on
the class rather than the instance, so anything that changes what should be
listed has to invalidate it. And blacklisted models are filtered out of that
list, with the reveal behind the same password gate as the blacklist's own.
"""

import pytest

from sd_runner.models.model import Model
from sd_runner.prompts.blacklist import Blacklist, ModelBlacklistItem
from sd_runner.ui.models.models_window import ModelsWindow
from tests.utils import close_window, install_password_bypass, make_model


CHECKPOINTS = ["alpha.safetensors", "beta.safetensors", "gamma.safetensors"]
LORAS = ["detail.safetensors", "style.safetensors"]


class RecordingAppActions:
    """AppActions stand-in that records the selection callback."""

    def __init__(self):
        self.selections = []
        self.alerts = []

    def set_model_from_models_window(self, name, is_lora=False, replace=True):
        self.selections.append((name, is_lora, replace))

    def alert(self, title, message, kind=None, master=None, **kwargs):
        self.alerts.append((title, message, kind))
        return True

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


@pytest.fixture
def models():
    """A known set of models, so no scan of the developer's models_dir runs.

    ``load_all_if_unloaded`` scans only when ``CHECKPOINTS`` is empty, so
    filling it is what keeps the window off the filesystem.
    """
    Model.CHECKPOINTS = {name: make_model(id=name) for name in CHECKPOINTS}
    Model.LORAS = {name: make_model(id=name, is_lora=True) for name in LORAS}
    return Model.CHECKPOINTS


def open_window(monkeypatch, granted=True):
    crossings = install_password_bypass(monkeypatch, granted=granted)
    actions = RecordingAppActions()
    window = ModelsWindow(None, actions)
    window._test_actions = actions
    window._test_crossings = crossings
    return window


@pytest.fixture
def window(qapp, models, monkeypatch):
    win = open_window(monkeypatch)
    try:
        yield win
    finally:
        close_window(win)


def listed(tree):
    return [tree.topLevelItem(i).text(0) for i in range(tree.topLevelItemCount())]


def select(tree, name):
    for i in range(tree.topLevelItemCount()):
        item = tree.topLevelItem(i)
        if item.text(0) == name:
            tree.setCurrentItem(item)
            item.setSelected(True)
            return item
    raise AssertionError(f"{name} is not listed")


def select_nothing(tree):
    tree.clearSelection()
    tree.setCurrentItem(None)


# ---------------------------------------------------------------------------
# Listing
# ---------------------------------------------------------------------------

class TestListing:
    def test_checkpoints_are_listed(self, window):
        assert set(listed(window._cp_tree)) == set(CHECKPOINTS)

    def test_adapters_are_listed_separately(self, window):
        assert set(listed(window._ad_tree)) == set(LORAS)

    def test_a_checkpoint_is_not_listed_as_an_adapter(self, window):
        assert not set(listed(window._ad_tree)) & set(CHECKPOINTS)

    def test_every_row_carries_its_architecture(self, window):
        row = window._cp_tree.topLevelItem(0)
        assert row.text(1)


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

class TestFilter:
    def test_typing_narrows_the_list(self, window):
        window._cp_filter.setText("alpha")
        assert listed(window._cp_tree) == ["alpha.safetensors"]

    def test_the_filter_is_case_insensitive(self, window):
        window._cp_filter.setText("ALPHA")
        assert listed(window._cp_tree) == ["alpha.safetensors"]

    def test_it_matches_anywhere_in_the_name(self, window):
        window._cp_filter.setText("safetensors")
        assert set(listed(window._cp_tree)) == set(CHECKPOINTS)

    def test_clearing_it_restores_the_list(self, window):
        window._cp_filter.setText("alpha")
        window._cp_filter.setText("")
        assert set(listed(window._cp_tree)) == set(CHECKPOINTS)

    def test_no_match_lists_nothing(self, window):
        window._cp_filter.setText("not_a_model")
        assert listed(window._cp_tree) == []

    def test_the_adapter_filter_is_independent(self, window):
        window._cp_filter.setText("alpha")
        assert set(listed(window._ad_tree)) == set(LORAS)


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

class TestSelectingACheckpoint:
    def test_the_name_goes_back_to_the_app(self, window):
        select(window._cp_tree, "beta.safetensors")
        window._select_checkpoint()
        assert window._test_actions.selections == [("beta.safetensors", False, True)]

    def test_add_rather_than_replace_is_passed_through(self, window):
        select(window._cp_tree, "beta.safetensors")
        window._select_checkpoint(replace=False)
        assert window._test_actions.selections[0][2] is False

    def test_nothing_selected_calls_nothing(self, window):
        select_nothing(window._cp_tree)
        window._select_checkpoint()
        assert window._test_actions.selections == []

    def test_a_filtered_list_still_selects_the_right_row(self, window):
        """The tree is rebuilt on filter, so a row index kept across the
        rebuild would point at a different model."""
        window._cp_filter.setText("gamma")
        select(window._cp_tree, "gamma.safetensors")
        window._select_checkpoint()
        assert window._test_actions.selections[0][0] == "gamma.safetensors"


class TestSelectingAnAdapter:
    def test_it_is_reported_as_a_lora(self, window):
        select(window._ad_tree, "style.safetensors")
        window._select_adapter()
        assert window._test_actions.selections == [("style.safetensors", True, False)]

    def test_adding_one_leaves_the_window_open(self, window):
        """Adapters stack, so the window stays up for the next pick."""
        select(window._ad_tree, "style.safetensors")
        window._select_adapter(replace=False)
        assert window.isVisible()

    def test_replacing_closes_it(self, window):
        """Asserted through the singleton the close clears rather than through
        the widget: WA_DeleteOnClose means asking a closed window anything
        reaches a destroyed C++ object."""
        select(window._ad_tree, "style.safetensors")
        window._select_adapter(replace=True)
        assert ModelsWindow._instance is None

    def test_nothing_selected_calls_nothing(self, window):
        select_nothing(window._ad_tree)
        window._select_adapter()
        assert window._test_actions.selections == []


# ---------------------------------------------------------------------------
# Blacklisted models
# ---------------------------------------------------------------------------

BLOCKED = "beta.safetensors"


def block_beta(window):
    """Blacklist one model and rebuild the list around it.

    The refresh is explicit because the filter is applied when the scan cache
    is built: blacklisting after a window is open does not change what it is
    already showing.
    """
    Blacklist.add_model_item(ModelBlacklistItem("beta"))
    window._refresh_cache()


class TestBlacklistedModels:
    def test_a_blacklisted_model_is_hidden(self, window):
        block_beta(window)
        assert BLOCKED not in listed(window._cp_tree)

    def test_the_others_are_still_listed(self, window):
        block_beta(window)
        assert set(listed(window._cp_tree)) == set(CHECKPOINTS) - {BLOCKED}

    def test_revealing_lists_it(self, window):
        block_beta(window)
        window._toggle_blacklisted()
        assert BLOCKED in listed(window._cp_tree)

    def test_revealing_is_behind_the_password_gate(self, window):
        window._toggle_blacklisted()
        assert window._test_crossings, "_toggle_blacklisted ran without the gate"

    def test_a_refused_gate_keeps_it_hidden(self, qapp, models, monkeypatch):
        win = open_window(monkeypatch, granted=False)
        try:
            block_beta(win)
            win._toggle_blacklisted()
            assert BLOCKED not in listed(win._cp_tree)
        finally:
            close_window(win)

    def test_toggling_back_hides_it_again(self, window):
        block_beta(window)
        window._toggle_blacklisted()
        window._toggle_blacklisted()
        assert BLOCKED not in listed(window._cp_tree)

    def test_the_button_says_which_way_it_will_go(self, window):
        before = window._cp_blacklist_btn.text()
        window._toggle_blacklisted()
        assert window._cp_blacklist_btn.text() != before


# ---------------------------------------------------------------------------
# The scan cache, which lives on the class
# ---------------------------------------------------------------------------

class TestTheScanCache:
    def test_it_is_filled_on_open(self, window):
        assert ModelsWindow._checkpoints_cache is not None

    def test_a_second_window_reuses_it(self, window, monkeypatch):
        """Held on the class, so reopening does not rescan."""
        cached = ModelsWindow._checkpoints_cache
        second = open_window(monkeypatch)
        try:
            assert ModelsWindow._checkpoints_cache is cached
        finally:
            close_window(second)

    def test_refreshing_rebuilds_it(self, window):
        cached = ModelsWindow._checkpoints_cache
        window._refresh_cache()
        assert ModelsWindow._checkpoints_cache is not cached

    def test_a_new_model_appears_only_after_a_refresh(self, window):
        """What the cache costs: the list is stale until asked to rescan."""
        Model.CHECKPOINTS["delta.safetensors"] = make_model(id="delta.safetensors")
        window._refresh_checkpoint_list()
        assert "delta.safetensors" not in listed(window._cp_tree)
        window._refresh_cache()
        assert "delta.safetensors" in listed(window._cp_tree)

    def test_revealing_blacklisted_models_invalidates_it(self, window):
        """The filter is applied when the cache is built, so a reveal that left
        it in place would show the same list."""
        Blacklist.add_model_item(ModelBlacklistItem("beta"))
        window._refresh_cache()
        assert "beta.safetensors" not in listed(window._cp_tree)
        window._toggle_blacklisted()
        assert "beta.safetensors" in listed(window._cp_tree)


# ---------------------------------------------------------------------------
# Dismissal
# ---------------------------------------------------------------------------

class TestDismissal:
    def test_closing_clears_the_singleton(self, qapp, models, monkeypatch):
        win = open_window(monkeypatch)
        close_window(win)
        assert ModelsWindow._instance is None
