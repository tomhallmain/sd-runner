"""Shared helpers for the test suite.

Import from here rather than redefining per-module factories:

    from tests.utils import make_prompter, make_model, make_run_config

Nothing in this package is collected by pytest -- ``pytest.ini`` sets
``python_files = test_*.py``, which no module here matches.

Note this is ``tests.utils``, distinct from the project's top-level ``utils``
package. Absolute imports keep them apart, so a test module can import from both.
"""

from tests.utils.auth_bypass import install_password_bypass
from tests.utils.factories import (
    FakeServerConn,
    make_app_actions,
    make_gen_config,
    make_model,
    make_prompter,
    make_prompter_config,
    make_resolution,
    make_run_config,
    make_schedule,
)

__all__ = [
    "FakeServerConn",
    "install_password_bypass",
    "make_app_actions",
    "make_gen_config",
    "make_model",
    "make_prompter",
    "make_prompter_config",
    "make_resolution",
    "make_run_config",
    "make_schedule",
]
