"""
SD Runner -- headless entry point.

Serves the request front ends with no window: the same servers over the same
run path, driven by ``HeadlessApp`` in place of ``AppWindow``. Requests that
carry their own parameters are served; the two that mean "reuse what the user
has on screen" are refused, because here there is no screen.

Deliberately imports no Qt, and neither does anything it constructs -- so this
runs on a machine with no display and no PySide6 installed. It is a separate
script rather than a flag on ``app_gui`` for that reason: a flag would still
have imported the toolkit before reading it.
"""

import atexit
import os
import signal
import sys
import threading
import time
import traceback

from sd_runner.runtime.oqs_path import point_oqs_at_bundled_library

point_oqs_at_bundled_library()

from sd_runner.config import config
from sd_runner.runtime.crash_log import enable_fault_log
from sd_runner.runtime.unpack_cleanup import remove_stale_unpack_dirs
from sd_runner.runtime.version import describe as describe_version, source_drift
from lib.logging_setup import get_logger
from lib.translations import I18N
from lib.utils import Utils

_ = I18N._
logger = get_logger("app_headless")


def _report_source_drift():
    """In a build, log whether the source checkout it was built from has changed since."""
    try:
        result = source_drift()
    except Exception as e:
        logger.error(f"Could not compare this build with its source checkout: {e}")
        return
    if result:
        drifted, message = result
        (logger.warning if drifted else logger.info)(message)


def _smoke_test(expect_oqs: bool = False) -> int:
    """Check that a build can serve, without binding a port. Returns an exit code."""
    from sd_runner.runtime.smoke_test import SmokeTest

    smoke = SmokeTest()
    smoke.run_common(expect_oqs=expect_oqs)

    def servers():
        from extensions.mcp_server import MCPServerExtension
        from extensions.sd_runner_server import SDRunnerServer
        from sd_runner.runs.headless_app import HeadlessApp

        app = HeadlessApp()
        run_ctrl = app.run_ctrl
        callbacks = (
            run_ctrl.server_run_callback,
            run_ctrl.cancel,
            run_ctrl.server_revert_to_simple_gen,
            run_ctrl.server_batch_enqueue,
            run_ctrl.server_health_check,
        )
        # Constructed only; start() is what binds.
        SDRunnerServer(*callbacks)
        MCPServerExtension(*callbacks, run_ctrl.run_status, run_ctrl.server_resource)

    smoke.check_call("headless application and servers", servers)
    return smoke.result()


def main():
    if "--smoke-test" in sys.argv[1:]:
        # Before the single-instance check: a running app must not block it,
        # and it must not take the lock.
        try:
            return _smoke_test(expect_oqs="--expect-oqs" in sys.argv[1:])
        except BaseException:
            # An error outside a check must fail the smoke test, not end it with status 0.
            logger.error(f"smoke test: unexpected error:\n{traceback.format_exc()}")
            return 1

    lock_file, cleanup_lock = Utils.check_single_instance("SDRunner")
    logger.info(describe_version())
    try:
        enable_fault_log()
    except Exception as e:
        logger.error(f"Could not open the fault log: {e}")

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
    atexit.register(lambda: _emergency_store("interpreter exit"))
    # Runs first (registered last); an exit without this line ended in native code.
    atexit.register(lambda: logger.info("Python interpreter exiting"))

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
    threading.Thread(target=remove_stale_unpack_dirs, name="unpack-cleanup", daemon=True).start()
    threading.Thread(target=_report_source_drift, name="source-drift", daemon=True).start()
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
