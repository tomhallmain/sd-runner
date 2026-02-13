"""
RunController -- image generation execution, queuing, and progress.

Owns the run lifecycle: validation, execution (via ``Run``), job queue
management, progress updates, cancellation, and time estimation.
"""

import datetime
from copy import deepcopy
from typing import Optional

from PySide6.QtCore import QTimer

from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._
logger = get_logger("ui_qt.run_controller")


class RunController:
    """Manages image generation runs and job queuing.

    Parameters
    ----------
    app_window : AppWindow
        The parent window providing access to sidebar widgets and
        notification controller.
    """

    def __init__(self, app_window):
        self._app = app_window

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------
    def run(self, event=None) -> None:
        """Start an image generation run (or enqueue it).

        Ported from ``App.run``.  The heavy lifting runs on a background
        thread; UI updates are marshalled to the main thread via
        ``_MainThreadBridge``-wrapped ``AppActions``.
        """
        # TODO: full port of App.run() logic
        logger.info("run() called -- not yet fully implemented")
        self._app.notification_ctrl.toast(_("Run triggered (not yet wired)."))

    def cancel(self, event=None, reason: str | None = None) -> None:
        """Cancel the current run."""
        if hasattr(self._app, "current_run") and self._app.current_run is not None:
            self._app.current_run.cancel(reason=reason)
        self.clear_progress()

    # ------------------------------------------------------------------
    # Progress
    # ------------------------------------------------------------------
    def update_progress(
        self,
        current_index: int = 0,
        total: int = 0,
        pending_adapters: int = 0,
        prepend_text: str = "",
        batch_current: int = 0,
        batch_limit: int = 0,
        override_text: str = "",
        adapter_current: int = 0,
        adapter_total: int = 0,
    ) -> None:
        """Update progress labels on the sidebar.

        Ported from ``App.update_progress``.
        """
        # TODO: wire to sidebar progress labels
        if override_text:
            logger.debug(f"Progress: {override_text}")
        elif total > 0:
            logger.debug(f"Progress: {current_index}/{total}")

    def update_pending(self, count_pending: int = 0) -> None:
        """Update the pending-generations label.

        Ported from ``App.update_pending``.
        """
        # TODO: wire to sidebar pending label
        pass

    def update_time_estimation(self, *args, **kwargs) -> None:
        """Update the time-estimation label.

        Ported from ``App.update_time_estimation``.
        """
        # TODO: wire to sidebar time-est label
        pass

    def clear_progress(self) -> None:
        """Clear all progress / time-estimation labels."""
        # TODO: wire to sidebar labels
        pass

    # ------------------------------------------------------------------
    # Server callback
    # ------------------------------------------------------------------
    def server_run_callback(self, workflow_type, args: dict):
        """Called by ``SDRunnerServer`` when a remote run request arrives.

        Ported from ``App.server_run_callback``.
        """
        # TODO: full port
        logger.info(f"Server run callback: {workflow_type}")
        return {}
