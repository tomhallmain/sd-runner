"""
SD Runner -- PySide6 entry point.

Creates the QApplication, handles startup authentication, signal handlers,
single-instance locking, and launches the main AppWindow.
"""

import atexit
import os
import signal
import sys
import threading
import traceback

from PySide6.QtWidgets import QApplication

from sd_runner.ui.app_style import AppStyle
from utils.app_icon import apply_app_icon
from utils.config import config
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("app_qt")


def main():
    # Single instance check -- prevent multiple instances from running
    lock_file, cleanup_lock = Utils.check_single_instance("SDRunner")

    I18N.install_locale(config.locale, verbose=config.print_settings)

    # Apply UI scale factor (must be set before QApplication is created)
    if config.ui_scale_factor != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(config.ui_scale_factor)

    # Create QApplication (must exist before any widgets)
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(_(" SD Runner "))
    qt_app.setStyleSheet(AppStyle.get_stylesheet())

    apply_app_icon(qt_app)

    # ------------------------------------------------------------------
    # Graceful shutdown handler
    # ------------------------------------------------------------------
    app_window = None  # will be set after startup auth succeeds

    def graceful_shutdown(signum, frame):
        logger.info("Caught signal, shutting down gracefully...")
        if app_window is not None:
            app_window.on_closing()
        cleanup_lock()
        os._exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    # ------------------------------------------------------------------
    # Emergency cache save
    #
    # The signal handlers above cover a polite kill and Ctrl-C. They do not
    # cover a crash: an unhandled exception never raises a signal, so without
    # the hooks below the process dies with everything since the last save
    # still only in memory. See _emergency_store for what each hook catches.
    # ------------------------------------------------------------------
    emergency_store_done = [False]

    def _emergency_store(reason: str) -> None:
        """Best-effort cache write from a failure path.

        Deliberately does the minimum: one store, guarded, never raising. The
        process is already in an unknown state, so this must not turn a crash
        into a hang or mask the original traceback.
        """
        if emergency_store_done[0] or app_window is None:
            return
        emergency_store_done[0] = True
        try:
            logger.error(f"Emergency cache store ({reason})")
            app_window.cache_ctrl.store_info_cache()
        except Exception as store_error:
            # Never let the rescue attempt replace the failure being reported.
            logger.error(f"Emergency cache store failed: {store_error}")

    def _handle_uncaught(exc_type, exc_value, exc_traceback):
        # KeyboardInterrupt reaches here when it lands outside the signal
        # handler; it is an orderly exit, not a crash worth a rescue write.
        if not issubclass(exc_type, KeyboardInterrupt):
            _emergency_store(f"unhandled {exc_type.__name__}")
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _handle_uncaught_in_thread(args):
        if not issubclass(args.exc_type, SystemExit):
            _emergency_store(f"unhandled {args.exc_type.__name__} in thread")
        threading.__excepthook__(args)

    sys.excepthook = _handle_uncaught
    threading.excepthook = _handle_uncaught_in_thread
    # Covers the orderly-exit paths that bypass on_closing (a stray sys.exit, or
    # the interpreter simply running out of main). Does not run on os._exit,
    # which the paths above use once they have already saved. Safe to run after
    # a normal shutdown because AppInfoCache.store refuses once the instance has
    # been wiped, so this cannot write an emptied cache over the saved one.
    atexit.register(lambda: _emergency_store("interpreter exit"))

    # Periodically yield to the Python interpreter so that signal handlers
    # (SIGINT, SIGTERM) can fire.  Without this, Qt's C++ event loop never
    # gives Python a chance to process pending signals.
    from PySide6.QtCore import QTimer
    _signal_timer = QTimer()
    _signal_timer.start(500)
    _signal_timer.timeout.connect(lambda: None)

    # ------------------------------------------------------------------
    # Startup authentication callback
    # ------------------------------------------------------------------
    def startup_callback(result: bool) -> None:
        nonlocal app_window

        if not result:
            logger.info("User cancelled password dialog, exiting application")
            cleanup_lock()
            sys.exit(0)

        # Password verified or not required -- create the main window
        from sd_runner.ui.app_window.app_window import AppWindow

        # Clean up any old image converter temporary files on startup
        from sd_runner.generators.base import BaseImageGenerator
        BaseImageGenerator.cleanup_image_converter()

        try:
            app_window = AppWindow()
            app_window.show()

            # Bring window to front and give it focus
            app_window.raise_()
            app_window.activateWindow()
        except Exception as e:
            logger.critical(f"Failed to create main window: {e}", exc_info=True)
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(
                None, _("Startup Error"),
                _("Failed to create main window:") + f"\n\n{e}"
            )
            cleanup_lock()
            os._exit(1)

    # ------------------------------------------------------------------
    # Check if startup password is required
    # ------------------------------------------------------------------
    from sd_runner.ui.auth.app_startup_auth_qt import check_startup_password_required
    check_startup_password_required(callback=startup_callback)

    # ------------------------------------------------------------------
    # Run the event loop
    # ------------------------------------------------------------------
    try:
        exit_code = qt_app.exec()
    except KeyboardInterrupt:
        exit_code = 0
    finally:
        cleanup_lock()

    # Hard exit -- sys.exit() can hang if non-daemon threads are still
    # alive (e.g. server listener blocking on accept(), websocket loops).
    # All critical state was already persisted in on_closing().
    os._exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
