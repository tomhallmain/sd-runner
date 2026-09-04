"""Building the whole headless application, and serving a request through it.

Constructing it is most of the assertion: it wires ``AppActions``, which refuses
to build with a required action missing, and it loads the cache, which is where
a window import would be reached. What follows checks the pieces that a missing
window changes rather than removes, and then drives one request end to end.

The generator is stubbed, as it is everywhere else: what is worth covering here
is that the run path reaches ``Run.execute`` at all with no window behind it --
the progress sink, the thread bridge and ``post_run`` are the parts that differ
-- not that a backend produces an image.
"""

import pytest

from extensions.sd_runner_server import CommandType
from sd_runner.globals import WorkflowType
from sd_runner.runs.headless_app import HeadlessApp
from sd_runner.runs.job_queue import SDRunsQueue, ServerStagingQueue
from sd_runner.runs.run_controller import SERVER_ORIGIN


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


class TestAServedRequestRunsWithNoWindow:
    """One request, end to end, with nothing but the headless application.

    Everything the run path reports through differs here -- the progress sink
    logs instead of writing labels, ``DirectBridge`` calls instead of
    marshalling, ``job_queue_preset_schedules`` is None where the window has a
    queue -- so reaching ``Run.execute`` is the assertion.
    """

    def test_a_parameterized_request_reaches_a_run(self, headless_app, run_stubs, executed):
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert len(executed) == 1
        assert executed[0].args.workflow_tag == WorkflowType.RENOISER.name

    def test_the_run_carries_the_requests_image(self, headless_app, run_stubs, executed):
        headless_app.run_ctrl.server_run_callback(
            CommandType.CONTROL_NET, {"image": "remote.png"}
        )
        assert executed[0].args.control_nets == "remote.png"

    def test_the_run_is_marked_with_the_requesting_client(self, headless_app, run_stubs, executed):
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        assert executed[0].args.run_origin == "weidr"

    def test_an_unidentified_client_falls_back_to_the_server_origin(
        self, headless_app, run_stubs, executed
    ):
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_the_settings_come_from_the_stored_config(self, headless_app, run_stubs, executed):
        """No sidebar to read, so the stored config is the whole source."""
        headless_app.runner_app_config.model_tags = "stored_model"
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert executed[0].args.model_tags == "stored_model"

    def test_the_queue_is_empty_afterwards(self, headless_app, run_stubs, executed):
        """post_run has to complete without a window: it is bridged through
        AppActions, and the window's version of every action it calls writes a
        widget."""
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert headless_app.job_queue.has_pending() is False
        assert headless_app.job_queue.job_running is False

    def test_a_contextual_request_is_refused_rather_than_run(
        self, headless_app, run_stubs, executed
    ):
        resp = headless_app.run_ctrl.server_run_callback(CommandType.LAST_SETTINGS, {})
        assert resp["error"] == "no user interface"
        assert executed == []

    def test_run_status_reports_the_finished_run(self, headless_app, run_stubs, executed):
        headless_app.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        status = headless_app.run_ctrl.run_status(origin="weidr")
        assert status["queued"] == 0
        assert status["staged"] == 0


class TestPasswordGateWithNothingToPromptFrom:
    """A protected action reached with no window refuses rather than proceeds.

    The gate used to run the function when it could not resolve a parent window
    for the dialog, which would let the absence of a display stand in for a
    correct password.
    """

    def test_the_handler_is_installed_by_construction(self, headless_app):
        """Its own handler, not merely the default -- both refuse, so asserting
        the answer would pass with nothing installed at all."""
        from sd_runner.ui.auth import password_core
        from sd_runner.globals import ProtectedActions

        assert password_core._unprompted_gate_handler is not None
        assert password_core.answer_unprompted_gate(
            ProtectedActions.EDIT_BLACKLIST
        ) is False

    def test_a_gate_with_no_window_does_not_call_through(self, headless_app):
        from sd_runner.globals import ProtectedActions
        from sd_runner.ui.auth.password_utils import require_password

        called = []

        class NoWindow:
            @require_password(ProtectedActions.EDIT_BLACKLIST)
            def protected(self):
                called.append(True)
                return "ran"

        assert NoWindow().protected() is None
        assert called == []
