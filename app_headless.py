"""
SD Runner -- headless entry point.

Serves the request front ends with no window: the same servers over the same
run path, driven by ``HeadlessApp`` in place of ``AppWindow``. Requests that
carry their own parameters are served; the two that mean "reuse what the user
has on screen" are refused, because here there is no screen.

Deliberately imports no Qt, and neither does anything it constructs -- so this
runs on a machine with no display and no PySide6 installed. It is a separate
script rather than a flag on ``app_qt`` for that reason: a flag would still
have imported the toolkit before reading it.
"""

import atexit
import os
import signal
import sys
import threading
import time
import traceback

from utils.config import config
from utils.logging_setup import get_logger
from utils.translations import I18N
from utils.utils import Utils

_ = I18N._
logger = get_logger("app_headless")


def main():
    lock_file, cleanup_lock = Utils.check_single_instance("SDRunner")

    I18N.install_locale(config.locale, verbose=config.print_settings)

    from sd_runner.generators.base import BaseImageGenerator
    from sd_runner.runs.headless_app import HeadlessApp

    BaseImageGenerator.cleanup_image_converter()

    app = HeadlessApp()

    # The same emergency-store hooks the windowed entry point installs, for the
    # same reason: the signal handlers below cover a polite kill, and an
    # unhandled exception raises no signal, so without these a crash loses
    # everything since the last write.
    emergency_store_done = [False]

    def _emergency_store(reason: str) -> None:
        if emergency_store_done[0]:
            return
        emergency_store_done[0] = True
        try:
            logger.error(f"Emergency cache store ({reason})")
            app.cache_ctrl.store_info_cache()
        except Exception as store_error:
            logger.error(f"Emergency cache store failed: {store_error}")

    def _handle_uncaught(exc_type, exc_value, exc_traceback):
        if not issubclass(exc_type, KeyboardInterrupt):
            _emergency_store(f"unhandled {exc_type.__name__}")
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    def _handle_uncaught_in_thread(args):
        if not issubclass(args.exc_type, SystemExit):
            _emergency_store(f"unhandled {args.exc_type.__name__} in thread")
        threading.__excepthook__(args)

    sys.excepthook = _handle_uncaught
    threading.excepthook = _handle_uncaught_in_thread
    atexit.register(lambda: _emergency_store("interpreter exit"))

    def graceful_shutdown(signum, frame):
        logger.info("Caught signal, shutting down gracefully...")
        try:
            app.on_closing()
        finally:
            cleanup_lock()
        os._exit(0)

    signal.signal(signal.SIGINT, graceful_shutdown)
    signal.signal(signal.SIGTERM, graceful_shutdown)

    app.start_servers()
    if app.server is None and app.mcp_server is None:
        logger.error("No server started; there is nothing for this process to do")
        cleanup_lock()
        return 1

    logger.info("SD Runner is serving headless")
    try:
        # The servers run on their own threads, so this one only has to stay
        # alive and interruptible. Sleeping in short spans rather than one long
        # one is what lets a signal be handled promptly on Windows, where a
        # sleeping main thread is not interrupted by one.
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("Interrupted, shutting down")
    finally:
        app.on_closing()
        cleanup_lock()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()
        sys.exit(1)
