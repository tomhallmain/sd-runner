"""
SD Runner -- PySide6 entry point.

Creates the QApplication, handles startup authentication, signal handlers,
single-instance locking, and launches the main AppWindow.
"""

import os
import signal
import sys
import traceback

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon

from ui_qt.app_style import AppStyle
from utils.config import config
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("app_qt")


def main():
    # Single instance check -- prevent multiple instances from running
    lock_file, cleanup_lock = Utils.check_single_instance("SD Runner")

    I18N.install_locale(config.locale, verbose=config.print_settings)

    # Create QApplication (must exist before any widgets)
    qt_app = QApplication(sys.argv)
    qt_app.setApplicationName(" SD Runner ")
    qt_app.setStyleSheet(AppStyle.get_stylesheet())

    # Application icon
    assets = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")
    icon_path = os.path.join(assets, "icon.png")
    if os.path.isfile(icon_path):
        qt_app.setWindowIcon(QIcon(icon_path))

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
    # Startup authentication callback
    # ------------------------------------------------------------------
    def startup_callback(result: bool) -> None:
        nonlocal app_window

        if not result:
            logger.info("User cancelled password dialog, exiting application")
            cleanup_lock()
            sys.exit(0)

        # Password verified or not required -- create the main window
        from ui_qt.app_window.app_window import AppWindow

        # Clean up any old image converter temporary files on startup
        from sd_runner.base_image_generator import BaseImageGenerator
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
    from ui_qt.auth.app_startup_auth_qt import check_startup_password_required
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

    sys.exit(exit_code)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
