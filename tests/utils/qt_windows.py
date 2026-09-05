"""Teardown helper for windows that may have closed themselves."""


def close_window(window) -> None:
    """Close *window* unless it is already gone.

    ``SmartDialog`` sets ``WA_DeleteOnClose``, so a window that closes itself --
    the models window on a selection, any dialog dismissed with Escape --
    destroys its C++ object. The Python wrapper survives and its own attributes
    still read fine, but calling a Qt method on it raises ``RuntimeError``, so a
    fixture that unconditionally closes what the test may already have closed
    fails in teardown rather than in the test.
    """
    try:
        window.close()
    except RuntimeError:
        pass
