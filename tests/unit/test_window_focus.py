"""Unit tests for ui_qt/window_focus.py helpers."""

import pytest
from unittest.mock import MagicMock

from ui_qt.window_focus import try_focus_existing_window, clear_class_ref_if_self


# ---------------------------------------------------------------------------
# try_focus_existing_window
# ---------------------------------------------------------------------------

class TestTryFocusExistingWindow:
    def test_none_returns_false(self):
        assert try_focus_existing_window(None) is False

    def test_visible_window_returns_true(self):
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.return_value = False
        assert try_focus_existing_window(win) is True

    def test_visible_window_raises_and_activates(self):
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.return_value = False
        try_focus_existing_window(win)
        win.raise_.assert_called_once()
        win.activateWindow.assert_called_once()

    def test_hidden_window_returns_false(self):
        win = MagicMock()
        win.isVisible.return_value = False
        assert try_focus_existing_window(win) is False

    def test_hidden_window_does_not_raise_or_activate(self):
        win = MagicMock()
        win.isVisible.return_value = False
        try_focus_existing_window(win)
        win.raise_.assert_not_called()
        win.activateWindow.assert_not_called()

    def test_minimized_window_calls_show_normal(self):
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.return_value = True
        try_focus_existing_window(win)
        win.showNormal.assert_called_once()

    def test_not_minimized_does_not_call_show_normal(self):
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.return_value = False
        try_focus_existing_window(win)
        win.showNormal.assert_not_called()

    def test_deleted_cpp_object_returns_false(self):
        """Simulates WA_DeleteOnClose: any method raises RuntimeError."""
        win = MagicMock()
        win.isVisible.side_effect = RuntimeError("Internal C++ object already deleted.")
        assert try_focus_existing_window(win) is False

    def test_runtime_error_on_minimized_check_returns_false(self):
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.side_effect = RuntimeError("Internal C++ object already deleted.")
        assert try_focus_existing_window(win) is False

    def test_minimized_returns_true(self):
        """A minimized but visible window is still successfully refocused."""
        win = MagicMock()
        win.isVisible.return_value = True
        win.isMinimized.return_value = True
        assert try_focus_existing_window(win) is True


# ---------------------------------------------------------------------------
# clear_class_ref_if_self
# ---------------------------------------------------------------------------

class TestClearClassRefIfSelf:
    def test_clears_when_same_object(self):
        class Owner:
            ref = None

        obj = object()
        Owner.ref = obj
        clear_class_ref_if_self(Owner, "ref", obj)
        assert Owner.ref is None

    def test_does_not_clear_when_different_object(self):
        class Owner:
            ref = None

        obj_a = object()
        obj_b = object()
        Owner.ref = obj_a
        clear_class_ref_if_self(Owner, "ref", obj_b)
        assert Owner.ref is obj_a

    def test_safe_when_attr_is_none(self):
        class Owner:
            ref = None

        obj = object()
        clear_class_ref_if_self(Owner, "ref", obj)  # should not raise
        assert Owner.ref is None

    def test_safe_when_attr_missing(self):
        class Owner:
            pass

        obj = object()
        clear_class_ref_if_self(Owner, "nonexistent", obj)  # should not raise

    def test_uses_identity_not_equality(self):
        """Two equal but distinct objects must not trigger a clear."""
        class Owner:
            ref = None

        class EqualToAll:
            def __eq__(self, other):
                return True

        stored = EqualToAll()
        closing = EqualToAll()
        Owner.ref = stored
        clear_class_ref_if_self(Owner, "ref", closing)
        assert Owner.ref is stored
