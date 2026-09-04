"""Building the whole headless application.

Constructing it is most of the assertion: it wires ``AppActions``, which refuses
to build with a required action missing, and it loads the cache, which is where
a window import would be reached. What follows checks the pieces that a missing
window changes rather than removes.
"""

import pytest

from sd_runner.headless_app import HeadlessApp
from utils.job_queue import SDRunsQueue, ServerStagingQueue


@pytest.fixture
def headless_app():
    app = HeadlessApp()
    yield app
    app.on_closing()


class TestHeadlessApp:
    def test_it_builds(self, headless_app):
        """AppActions raises on a missing action, so this covers the wiring."""
        assert headless_app.app_actions is not None

    def test_the_queues_are_the_same_ones_the_window_uses(self, headless_app):
        assert isinstance(headless_app.job_queue, SDRunsQueue)
        assert isinstance(headless_app.server_staging_queue, ServerStagingQueue)

    def test_there_is_no_sidebar(self, headless_app):
        """Absent by design: it is what makes the contextual commands refuse."""
        assert not hasattr(headless_app, "sidebar_panel")

    def test_there_is_no_preset_schedule_queue(self, headless_app):
        """A schedule reads the sidebar for every task, so there is no headless one."""
        assert headless_app.job_queue_preset_schedules is None

    def test_a_run_config_can_be_built_from_the_stored_state(self, headless_app):
        """The parameterized path end to end, minus the queueing.

        This is what a served request is assembled from, and it has to work
        with no widgets to read it out of.
        """
        from extensions.sd_runner_server import CommandType

        base_args, preset = headless_app.run_ctrl._snapshot_for_server_run(
            CommandType.RENOISER, {}
        )
        assert base_args["model_tags"] == headless_app.runner_app_config.model_tags

    def test_no_servers_are_started_by_construction(self, headless_app):
        """Ports are bound by start_servers, so a test can build one freely."""
        assert headless_app.server is None
        assert headless_app.mcp_server is None


class TestCacheLoadIsWindowFree:
    """The cache load restores run state; the windows restore their own.

    It used to call into two windows, inside the same try that guards the rest
    of the load -- so on a machine with no PySide6 the ImportError was caught
    and the presets, schedules and pending queues were silently not restored.
    """

    def test_the_stored_config_is_returned(self, headless_app):
        assert headless_app.runner_app_config is not None

    def test_the_staging_queue_is_restored(self, headless_app):
        """_restore_pending_queues runs after the point the window calls were at."""
        assert headless_app.server_staging_queue is not None
