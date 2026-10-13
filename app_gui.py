"""
SD Runner -- PySide6 entry point.

Creates the QApplication, handles startup authentication, signal handlers,
single-instance locking, and launches the main AppWindow.
"""

import atexit
import logging
import os
import signal
import sys
import threading
import traceback

from sd_runner.runtime.console_streams import make_console_streams_byte_safe
from sd_runner.runtime.oqs_path import point_oqs_at_bundled_library

_byte_safe_fds = make_console_streams_byte_safe()
point_oqs_at_bundled_library()

from PySide6.QtCore import QtMsgType, qInstallMessageHandler
from PySide6.QtWidgets import QApplication

from sd_runner.ui.app_style import AppStyle
from sd_runner.ui.app_icon import apply_app_icon
from sd_runner.app_paths import resource_path
from sd_runner.config import config
from sd_runner.runtime.crash_log import enable_fault_log
from sd_runner.runtime.unpack_cleanup import remove_stale_unpack_dirs
from sd_runner.runtime.version import describe as describe_version, source_drift
from lib.logging_setup import get_logger
from lib.translations import I18N
from lib.utils import Utils

_ = I18N._
logger = get_logger("app_gui")


_QT_MSG_LOG_LEVELS = {
    QtMsgType.QtDebugMsg: logging.DEBUG,
    QtMsgType.QtInfoMsg: logging.INFO,
    QtMsgType.QtWarningMsg: logging.WARNING,
    QtMsgType.QtCriticalMsg: logging.ERROR,
    QtMsgType.QtFatalMsg: logging.CRITICAL,
}


def _log_qt_message(msg_type, context, message):
    logger.log(_QT_MSG_LOG_LEVELS.get(msg_type, logging.WARNING), "Qt: %s", message)


def _route_qt_messages_to_logger():
    """Send Qt's own warnings and errors through the app logger.

    Qt's default handler writes byte strings to the C-level stderr. A Nuitka
    build with --windows-console-mode=attach puts that stream in wide-character
    (_O_U8TEXT) mode, and the C runtime aborts the process (0xc0000409 in
    ucrtbase.dll) on a byte write to it, so any Qt warning would kill the app.
    """
    qInstallMessageHandler(_log_qt_message)


def _report_source_drift(app_window):
    """In a build, log whether the source checkout it was built from has
    changed since, and tell the user with a toast when it has."""
    try:
        result = source_drift()
    except Exception as e:
        logger.error(f"Could not compare this build with its source checkout: {e}")
        return
    if result:
        drifted, message = result
        if drifted:
            logger.warning(message)
            # Through AppActions, which marshals onto the GUI thread.
            app_window.app_actions.toast(_("This build no longer matches its source code. See the log for details."))
        else:
            logger.info(message)


def _smoke_test(expect_oqs: bool = False) -> int:
    """Check that a build can start, without opening a window. Returns an exit code."""
    import importlib

    from sd_runner.runtime.smoke_test import SmokeTest

    smoke = SmokeTest()
    smoke.run_common(expect_oqs=expect_oqs)

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    _route_qt_messages_to_logger()
    from PySide6.QtGui import QImageReader
    from PySide6.QtMultimedia import QSoundEffect

    qt_app = QApplication([])
    reader = QImageReader(resource_path("assets", "icon.png"))
    can_read = reader.canRead()
    smoke.check("app icon (PNG image plugin)", can_read, "" if can_read else reader.errorString())
    smoke.check_call("sound effect (Qt Multimedia)", lambda: QSoundEffect() and None)
    smoke.check_call(
        "main window modules",
        lambda: importlib.import_module("sd_runner.ui.app_window.app_window") and None,
    )
    qt_app.quit()
    return smoke.result()


def main():
    if "--smoke-test" in sys.argv[1:]:
        # Before the single-instance check: a running app must not block it,
        # and it must not take the lock.
        try:
            exit_code = _smoke_test(expect_oqs="--expect-oqs" in sys.argv[1:])
        except BaseException:
            # An error outside a check must fail the smoke test, not end it with status 0.
            logger.error(f"smoke test: unexpected error:\n{traceback.format_exc()}")
            exit_code = 1
        sys.exit(exit_code)

    # Single instance check -- prevent multiple instances from running
    lock_file, cleanup_lock = Utils.check_single_instance("SDRunner")
    logger.info("SD Runner starting")
    logger.info(describe_version())
    if _byte_safe_fds:
        logger.info(f"Console streams {_byte_safe_fds} switched from wide-character to binary mode")
    try:
        enable_fault_log()
    except Exception as e:
        logger.error(f"Could not open the fault log: {e}")

    I18N.install_locale(config.locale, verbose=config.print_settings)

    # Apply UI scale factor (must be set before QApplication is created)
    if config.ui_scale_factor != 1.0:
        os.environ["QT_SCALE_FACTOR"] = str(config.ui_scale_factor)

    # Create QApplication (must exist before any widgets)
    _route_qt_messages_to_logger()
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
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return
        # Through the logger, so the traceback also reaches the log file.
        logger.critical("Unhandled exception", exc_info=(exc_type, exc_value, exc_traceback))
        _emergency_store(f"unhandled {exc_type.__name__}")

    def _handle_uncaught_in_thread(args):
        if issubclass(args.exc_type, SystemExit):
            return
        thread_name = args.thread.name if args.thread else "unknown"
        logger.critical(
            f"Unhandled exception in thread {thread_name}",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
        _emergency_store(f"unhandled {args.exc_type.__name__} in thread")

    sys.excepthook = _handle_uncaught
    threading.excepthook = _handle_uncaught_in_thread
    # Covers the orderly-exit paths that bypass on_closing (a stray sys.exit, or
    # the interpreter simply running out of main). Does not run on os._exit,
    # which the paths above use once they have already saved. Safe to run after
    # a normal shutdown because AppInfoCache.store refuses once the instance has
    # been wiped, so this cannot write an emptied cache over the saved one.
    atexit.register(lambda: _emergency_store("interpreter exit"))
    # Registered after the line above, so it runs first. An exit that reaches
    # neither this line nor "SD Runner exiting" ended in native code: see
    # faults.log, or for a fast-fail abort the system's application event log.
    atexit.register(lambda: logger.info("Python interpreter exiting"))

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
        logger.info("Creating the main window")
        try:
            from sd_runner.ui.app_window.app_window import AppWindow

            # Clean up any old image converter temporary files on startup
            from sd_runner.generators.base import BaseImageGenerator
            BaseImageGenerator.cleanup_image_converter()

            app_window = AppWindow()
            app_window.show()

            # Bring window to front and give it focus
            app_window.raise_()
            app_window.activateWindow()
            logger.info("Main window opened")
            threading.Thread(target=remove_stale_unpack_dirs, name="unpack-cleanup", daemon=True).start()
            # Runs git, which can take a moment.
            threading.Thread(
                target=_report_source_drift, args=(app_window,), name="source-drift", daemon=True,
            ).start()
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
    from sd_runner.ui.auth.app_startup_auth import check_startup_password_required
    logger.debug("Checking whether the start needs a password")
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
    logger.info(f"SD Runner exiting with code {exit_code}")

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
