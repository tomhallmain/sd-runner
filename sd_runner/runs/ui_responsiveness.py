"""Keeping a user interface responsive during long synchronous work.

Work running on the thread that draws the window freezes the display until it
finishes. Two things relieve that: pumping pending events between iterations of
a loop, or moving the slow part onto a worker thread and waiting on a nested
event loop. Both are properties of having a window, not of the work.

As a port, the code doing the work names neither. A package that has to stay
free of PySide6 can keep a window alive through it, and a caller with no event
loop supplies the implementation that does nothing, because there is nothing to
keep responsive.

Two operations, matching the two situations:

- yield_to_ui() -- let the display catch up mid-loop.
- run_off_thread(func) -- run func elsewhere, block until it returns, and keep
  the interface alive meanwhile.

run_off_thread reports a failure as None rather than raising, and both
implementations log it. An exception inside a worker thread does not reach the
caller, so the Qt implementation cannot propagate one; this implementation
could, and matches the contract instead of diverging from it.
"""

from __future__ import annotations

from typing import Any, Callable

from lib.logging_setup import get_logger

logger = get_logger("runs.ui_responsiveness")


class NullResponsiveness:
    """For callers with no event loop: nothing to yield to, nothing to unblock.

    run_off_thread runs the callable inline. A thread would add nothing here --
    its only purpose in the Qt path is to leave the drawing thread free.
    """

    def yield_to_ui(self) -> None:
        return None

    def run_off_thread(self, func: Callable[[], Any]) -> Any:
        try:
            return func()
        except Exception:
            logger.exception("Background work failed.")
            return None
