"""Capturing log output from the project's own loggers.

``lib.logging_setup.get_logger`` sets ``propagate = False`` on every logger it
builds, so records go to the project's own handler and never reach the root
handler ``caplog`` installs. A test that just uses ``caplog.at_level(...)`` sees
an empty ``caplog.text`` while the message is plainly visible in captured
stderr, which is a confusing way to spend twenty minutes.
"""

import logging
from contextlib import contextmanager


@contextmanager
def captured_logs(caplog, logger, level: int | str = logging.ERROR):
    """Make *logger*'s records visible to *caplog* for the duration.

        with captured_logs(caplog, some_module.logger):
            do_the_thing()
        assert "expected message" in caplog.text

    *logger* may be the logger object or its name. Propagation is restored on
    exit whether or not the body raised, so a logger is never left propagating
    into later tests.
    """
    if isinstance(logger, str):
        logger = logging.getLogger(logger)
    previous = logger.propagate
    logger.propagate = True
    try:
        with caplog.at_level(level, logger=logger.name):
            yield caplog
    finally:
        logger.propagate = previous
