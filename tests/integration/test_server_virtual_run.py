"""Server requests build a run without disturbing the sidebar.

A remote request used to be executed by writing its values into the sidebar
widgets and reading them straight back out, so it changed the workflow dropdown
and adapter fields the user might be mid-edit of, and persisted its own values
as their saved settings. These assert the widgets and the stored config come out
of a server run exactly as they went in, while the run still carries the
request's parameters.

The run machinery is stubbed the same way as test_run_dispatch: no backend, and
start_thread runs synchronously so the effects are visible on return.
"""

import time as time_module
import pytest

from extensions.sd_runner_server import CommandType, SDRunnerServer
from sd_runner.runs.run import Run
from sd_runner.models.model import Model
from sd_runner.models.resolution import Resolution
from sd_runner.runs.run_config import RunConfig
from sd_runner.presets.timed_schedules_manager import timed_schedules_manager
from tests.utils import FakeServerConn
from sd_runner.runs.run_controller import SERVER_ORIGIN
from utils.globals import WorkflowType
from utils.time_estimator import TimeEstimator
from utils.utils import Utils


class _FakeModel:
    architecture_type = None

    def __str__(self):
        return "fake"


@pytest.fixture
def executed():
    return []


@pytest.fixture
def run_stubs(monkeypatch, executed):
    def fake_execute(self):
        executed.append(self)
        self.is_complete = True

    monkeypatch.setattr(Run, "execute", fake_execute)
    monkeypatch.setattr(
        Utils, "start_thread", lambda fn, use_asyncio=False, args=[]: fn(*args)
    )
    monkeypatch.setattr(
        Model, "get_models",
        lambda tags, default_tag=None, inpainting=False, **kw: [_FakeModel()],
    )
    monkeypatch.setattr(
        Resolution, "get_resolutions",
        lambda tags, architecture_type=None, resolution_group=None: [object()],
    )
    monkeypatch.setattr(RunConfig, "validate", lambda self: True)
    # Both estimate entry points, or a run long enough to cross
    # TIME_ESTIMATION_CONFIRMATION_THRESHOLD_SECONDS would raise a modal.
    # latents is optional on the real signature; callers pass either shape.
    monkeypatch.setattr(TimeEstimator, "estimate_queue_time", lambda images, latents=1.0: 0)
    monkeypatch.setattr(TimeEstimator, "estimate_run_seconds", lambda gen_config, images: 0)
    monkeypatch.setattr(time_module, "sleep", lambda s: None)
    monkeypatch.setattr(timed_schedules_manager, "check_for_shutdown_request", lambda dt: None)


def sidebar_snapshot(sp) -> dict:
    """The fields a server request used to overwrite."""
    return {
        "workflow": sp.workflow_combo.currentText(),
        "control_net": sp.controlnet_file_entry.text(),
        "ip_adapter": sp.ipadapter_file_entry.text(),
        "source_prompt": sp.source_prompt_file_entry.text(),
        "target_dir": sp.target_dir_entry.text(),
        "edit_suffix": sp.edit_suffix_entry.text(),
        "positive_tags": sp.positive_tags_box.toPlainText(),
        "negative_tags": sp.negative_tags_box.toPlainText(),
    }


# ---------------------------------------------------------------------------
# Isolation
# ---------------------------------------------------------------------------

class TestSidebarIsUntouched:
    def test_control_net_request_leaves_every_field_alone(self, app_window, run_stubs):
        sp = app_window.sidebar_panel
        sp.controlnet_file_entry.setText("user_was_editing.png")
        before = sidebar_snapshot(sp)

        app_window.run_ctrl.server_run_callback(
            CommandType.CONTROL_NET, {"image": "remote.png"}
        )

        assert sidebar_snapshot(sp) == before

    def test_workflow_dropdown_does_not_move(self, app_window, run_stubs):
        sp = app_window.sidebar_panel
        before = sp.workflow_combo.currentText()
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert sp.workflow_combo.currentText() == before

    def test_target_dir_is_not_written_to_the_field(self, app_window, run_stubs):
        sp = app_window.sidebar_panel
        app_window.run_ctrl.server_run_callback(
            CommandType.IP_ADAPTER, {"image": "a.png", "target_dir": "/remote/out"}
        )
        assert sp.target_dir_entry.text() != "/remote/out"

    def test_stored_config_is_not_overwritten(self, app_window, run_stubs):
        """run() persists its args as the user's settings; the virtual path must not.

        The user's own value is set through the widget, which is where it lives
        while they work: the build writes the widgets through to the config
        before reading it, so establishing it on the config alone would prove
        nothing about what the request did.
        """
        cfg = app_window.runner_app_config
        app_window.sidebar_panel.controlnet_file_entry.setText("user_value.png")
        app_window.run_ctrl.server_run_callback(
            CommandType.CONTROL_NET, {"image": "remote.png"}
        )
        assert cfg.control_net_file == "user_value.png"

    def test_stored_workflow_is_not_overwritten(self, app_window, run_stubs):
        cfg = app_window.runner_app_config
        before = cfg.workflow_type
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert cfg.workflow_type == before


# ---------------------------------------------------------------------------
# The run still carries the request
# ---------------------------------------------------------------------------

class TestRequestReachesTheRun:
    def test_run_uses_the_commands_workflow(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert len(executed) == 1
        assert executed[0].args.workflow_tag == WorkflowType.RENOISER.name

    def test_run_uses_the_requests_image(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.CONTROL_NET, {"image": "remote.png"}
        )
        assert executed[0].args.control_nets == "remote.png"

    def test_run_uses_the_requests_target_dir(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.IP_ADAPTER, {"image": "a.png", "target_dir": "/remote/out"}
        )
        assert executed[0].args.target_dir == "/remote/out"

    def test_the_run_is_marked_with_the_requesting_client(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        assert executed[0].args.run_origin == "weidr"

    def test_an_unidentified_client_falls_back_to_the_server_origin(
        self, app_window, run_stubs, executed
    ):
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert executed[0].args.run_origin == SERVER_ORIGIN


# ---------------------------------------------------------------------------
# last_settings stays on the widget-backed path by design
# ---------------------------------------------------------------------------

class TestLastSettingsStillReadsTheUI:
    def test_last_settings_runs_from_current_widget_state(self, app_window, run_stubs, executed):
        sp = app_window.sidebar_panel
        sp.model_tags_entry.setText("user_model_choice")
        app_window.run_ctrl.server_run_callback(CommandType.LAST_SETTINGS, {})
        assert len(executed) == 1
        assert executed[0].args.model_tags == "user_model_choice"

    def test_last_settings_is_still_marked_with_its_origin(self, app_window, run_stubs, executed):
        """The marker is about origin, not configuration.

        This run's settings are the user's own -- that is the command -- but
        they did not press Run, so the progress label still has to say which
        client started it.
        """
        app_window.run_ctrl.server_run_callback(CommandType.LAST_SETTINGS, {}, "weidr")
        assert executed[0].args.run_origin == "weidr"

    def test_an_unidentified_client_still_marks_the_run(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(CommandType.LAST_SETTINGS, {})
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_a_run_from_the_run_button_has_no_origin(self, app_window, run_stubs, executed):
        app_window.run_ctrl.run()
        assert executed[0].args.run_origin == ""


# ---------------------------------------------------------------------------
# revert_to_simple_gen — a STATE command that still ends in a run
# ---------------------------------------------------------------------------

class TestRevertToSimpleGenOrigin:
    def test_the_server_entry_point_marks_the_run(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_revert_to_simple_gen("weidr")
        assert executed[0].args.run_origin == "weidr"

    def test_an_unidentified_client_is_named_like_every_other_path(
        self, app_window, run_stubs, executed
    ):
        app_window.run_ctrl.server_revert_to_simple_gen()
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_the_ui_entry_point_leaves_the_run_unmarked(self, app_window, run_stubs, executed):
        """Reachable through AppActions, where nobody asked remotely."""
        app_window.run_ctrl.revert_to_simple_gen()
        assert executed[0].args.run_origin == ""


# ---------------------------------------------------------------------------
# From the socket to the run — the seam the origin defect hid in
# ---------------------------------------------------------------------------

class TestOriginFromAnActualMessage:
    """Both halves of client identity were covered; the join was not.

    ``client_id()`` and ``origin_for_client()`` each looked correct in
    isolation, and the run-path tests call ``server_run_callback`` directly with
    whatever id they please. Nothing drove a message through the server into a
    run, so nothing noticed that a real connection could never produce the
    unidentified case those tests were asserting on -- the listener binds
    loopback, so every peer host was 127.0.0.1 and no run was ever labelled
    ``server``.
    """

    def serve(self, app_window, messages, peer=("127.0.0.1", 54321)):
        server = SDRunnerServer(
            run_callback=app_window.run_ctrl.server_run_callback,
            cancel_callback=app_window.run_ctrl.cancel,
            revert_callback=app_window.run_ctrl.server_revert_to_simple_gen,
            batch_enqueue_callback=app_window.run_ctrl.server_batch_enqueue,
            host="127.0.0.1",
            port=0,
        )
        server._adopt_peer(peer)
        server._conn = FakeServerConn(messages)
        server._handle_connection()
        return server

    def run_message(self, **extra):
        return {"command": "run", "type": "renoiser", "args": {"image": "a.png"}, **extra}

    def test_a_named_client_reaches_the_run(self, app_window, run_stubs, executed):
        self.serve(app_window, [self.run_message(client_id="weidr")])
        assert executed[0].args.run_origin == "weidr"

    def test_a_local_client_that_sends_no_id_is_labelled_server(
        self, app_window, run_stubs, executed
    ):
        """Not 127.0.0.1: loopback is the address of everyone who can connect."""
        self.serve(app_window, [self.run_message()])
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_a_remote_client_that_sends_no_id_is_labelled_by_host(
        self, app_window, run_stubs, executed
    ):
        """A host only says something once someone binds a wider address."""
        self.serve(app_window, [self.run_message()], peer=("192.168.1.50", 54321))
        assert executed[0].args.run_origin == "192.168.1.50"

    def test_last_settings_is_labelled_the_same_way(self, app_window, run_stubs, executed):
        """The widget-backed path names an unidentified client identically."""
        self.serve(app_window, [{"command": "run", "type": "last_settings", "args": {}}])
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_revert_to_simple_gen_is_labelled_the_same_way(
        self, app_window, run_stubs, executed
    ):
        self.serve(
            app_window,
            [{"command": "run", "type": "revert_to_simple_gen", "args": {}}],
        )
        assert executed[0].args.run_origin == SERVER_ORIGIN

    def test_a_batch_carries_its_client_into_the_promoted_run(
        self, app_window, run_stubs, executed
    ):
        """A batch item is staged first, so its origin has to survive the queue."""
        self.serve(app_window, [{
            "command": "run_batch",
            "client_id": "weidr",
            "requests": [{"type": "renoiser", "args": {"image": "a.png"}}],
        }])
        assert executed[0].args.run_origin == "weidr"


# ---------------------------------------------------------------------------
# Prompt text and run size
# ---------------------------------------------------------------------------

class TestPromptTagsTravelOnTheRun:
    """Tags reach generation via process globals, so each run must carry its own.

    Applying them at execution rather than at enqueue is what stops a queued run
    generating with tags a later run pushed while it waited.
    """

    def test_a_user_run_carries_its_tags(self, app_window, run_stubs, executed):
        sp = app_window.sidebar_panel
        sp.positive_tags_box.setPlainText("user tags")
        app_window.run_ctrl.run()
        assert executed[0].args.positive_tags == "user tags"

    def test_a_server_run_carries_the_stored_tags(self, app_window, run_stubs, executed):
        app_window.runner_app_config.positive_tags = "stored tags"
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert executed[0].args.positive_tags == "stored tags"

    def test_tags_reach_the_prompter_when_the_run_starts(self, app_window, run_stubs, monkeypatch):
        """Not at enqueue: Prompter state must hold this run's tags as it begins."""
        from sd_runner.prompter import Prompter

        seen = []

        def capture(self):
            seen.append(Prompter.POSITIVE_TAGS)
            self.is_complete = True

        monkeypatch.setattr(Run, "execute", capture)
        app_window.runner_app_config.positive_tags = "applied at start"
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert seen == ["applied at start"]


class TestPresetScheduleDiversion:
    """A request handed to a running preset schedule is never built as a run.

    The schedule owns the adapter fields for its duration, so the request's
    image goes to it instead. Settling that before the build is what keeps a
    diverted request from being estimated -- and possibly refused over the size
    ceiling -- for a run that was never going to be queued.
    """

    def arm_schedule(self, app_window):
        app_window.sidebar_panel.run_preset_schedule_check.setChecked(True)
        app_window.job_queue_preset_schedules.add({"placeholder": True})

    def test_image_goes_to_the_schedule_instead_of_a_run(self, app_window, run_stubs, executed):
        self.arm_schedule(app_window)
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert resp == {}
        assert executed == []
        assert {"control_net": "remote.png"} in app_window.job_queue_preset_schedules.pending_jobs

    def test_the_run_is_never_built_when_diverting(self, app_window, run_stubs, monkeypatch):
        import sd_runner.runs.virtual_run_config as vrc

        def fail(*a, **kw):
            raise AssertionError("a diverted request must not be built")

        monkeypatch.setattr(vrc, "build_from_base_args", fail)
        self.arm_schedule(app_window)
        assert app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        ) == {}

    def test_a_diverted_request_is_not_refused_by_the_ceiling(
        self, app_window, run_stubs, executed, monkeypatch
    ):
        from utils.config import config
        monkeypatch.setattr(config, "server_run_max_seconds", 10)
        monkeypatch.setattr(
            app_window.run_ctrl, "_estimate_run", lambda args: (9999, 500)
        )
        self.arm_schedule(app_window)
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert "error" not in resp
        assert executed == []


# ---------------------------------------------------------------------------
# last_settings carries no workflow, so workflow-specific args cannot apply
# ---------------------------------------------------------------------------

class TestLastSettingsIgnoresWorkflowArgs:
    def test_an_image_does_not_reach_the_adapter_fields(self, app_window, run_stubs, executed):
        """An image names the input of a particular workflow; last_settings
        selects none, so there is nowhere correct to put it."""
        sp = app_window.sidebar_panel
        sp.controlnet_file_entry.setText("user_value.png")
        sp.ipadapter_file_entry.setText("user_ip.png")

        app_window.run_ctrl.server_run_callback(
            CommandType.LAST_SETTINGS, {"image": "remote.png"}
        )

        assert sp.controlnet_file_entry.text() == "user_value.png"
        assert sp.ipadapter_file_entry.text() == "user_ip.png"
        assert len(executed) == 1

    def test_a_control_net_does_not_reach_the_field(self, app_window, run_stubs, executed):
        sp = app_window.sidebar_panel
        sp.controlnet_file_entry.setText("user_value.png")
        app_window.run_ctrl.server_run_callback(
            CommandType.LAST_SETTINGS, {"control_net": "remote.png"}
        )
        assert sp.controlnet_file_entry.text() == "user_value.png"
        assert len(executed) == 1

    def test_the_args_it_can_honour_still_apply(self, app_window, run_stubs, executed):
        sp = app_window.sidebar_panel
        app_window.run_ctrl.server_run_callback(
            CommandType.LAST_SETTINGS,
            {"source_prompt": "take_from.png", "target_dir": "/remote/out"},
        )
        assert sp.source_prompt_file_entry.text() == "take_from.png"
        assert sp.target_dir_entry.text() == "/remote/out"
        assert len(executed) == 1

    def test_append_extends_the_source_prompt_field(self, app_window, run_stubs, executed):
        sp = app_window.sidebar_panel
        sp.source_prompt_file_entry.setText("first.png")
        app_window.run_ctrl.server_run_callback(
            CommandType.LAST_SETTINGS, {"source_prompt": "second.png", "append": True}
        )
        assert sp.source_prompt_file_entry.text() == "first.png,second.png"


# ---------------------------------------------------------------------------
# Ceiling
# ---------------------------------------------------------------------------

class TestEstimatedImageCount:
    """The image count reported alongside a run-too-large refusal.

    Separate from the seconds: the seconds have always been right, because
    estimate_queue_time applied the latent multiplier internally. The count
    was computed from maximum_gens_per_latent() and never had it applied.
    """

    def test_the_count_scales_with_n_latents(self, app_window, run_stubs):
        args, _copy = app_window.get_args()
        args.total = 1

        args.n_latents = 1
        _seconds, one = app_window.run_ctrl._estimate_run(args)
        args.n_latents = 4
        _seconds, four = app_window.run_ctrl._estimate_run(args)

        # Before the fix these were equal: a run producing four times the images
        # reported the same count, so a refused client was told a quarter of it.
        assert four == one * 4

    def test_the_count_is_at_least_one(self, app_window, run_stubs):
        args, _copy = app_window.get_args()
        args.total = 1
        args.n_latents = 1
        _seconds, count = app_window.run_ctrl._estimate_run(args)
        assert count >= 1


class TestServerRunCeiling:
    """A server request has no user to confirm a long run, so it is refused."""

    def test_no_ceiling_by_default(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert len(executed) == 1

    def test_run_over_the_ceiling_is_refused(self, app_window, run_stubs, executed, monkeypatch):
        from utils.config import config
        monkeypatch.setattr(config, "server_run_max_seconds", 10)
        monkeypatch.setattr(
            app_window.run_ctrl, "_estimate_run", lambda args: (9999, 500)
        )
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert resp["error"] == "run too large"
        assert resp["data"]["estimated_image_count"] == 500
        assert executed == []

    def test_run_under_the_ceiling_is_accepted(self, app_window, run_stubs, executed, monkeypatch):
        from utils.config import config
        monkeypatch.setattr(config, "server_run_max_seconds", 10000)
        monkeypatch.setattr(
            app_window.run_ctrl, "_estimate_run", lambda args: (9999, 500)
        )
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert len(executed) == 1

    def test_a_failed_estimate_does_not_block_the_run(self, app_window, run_stubs, executed, monkeypatch):
        """The estimate is a guard, not a precondition."""
        from utils.config import config

        def boom(args):
            raise RuntimeError("estimate blew up")

        monkeypatch.setattr(config, "server_run_max_seconds", 10)
        monkeypatch.setattr(app_window.run_ctrl, "_estimate_run", boom)
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert len(executed) == 1

    def test_no_models_is_reported_as_an_error_response(self, app_window, run_stubs, executed, monkeypatch):
        from sd_runner.models.model import NoModelsFound
        from utils.config import config

        def no_models(args):
            raise NoModelsFound("No models found")

        monkeypatch.setattr(config, "server_run_max_seconds", 10)
        monkeypatch.setattr(app_window.run_ctrl, "_estimate_run", no_models)
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert resp["error"] == "no models found"
        assert executed == []


# ---------------------------------------------------------------------------
# Staging, which moved into the bridged section
# ---------------------------------------------------------------------------

class TestStagingWhenTheQueueIsFull:
    """The queue-full check and the enqueue have to stay one atomic section.

    They were split apart when the build moved off the GUI thread, so both now
    live in _commit_server_run / _run_from_widgets rather than at the entry.
    """

    def fill_queue(self, app_window):
        app_window.job_queue.job_running = True
        app_window.job_queue.pending_jobs = ["x"] * (app_window.job_queue.max_size + 1)

    def test_parameterized_command_is_staged(self, app_window, run_stubs, executed):
        self.fill_queue(app_window)
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert resp["queued"] == "staged"
        assert app_window.server_staging_queue.pending_count() == 1
        assert executed == []

    def test_contextual_command_is_staged(self, app_window, run_stubs, executed):
        self.fill_queue(app_window)
        resp = app_window.run_ctrl.server_run_callback(CommandType.LAST_SETTINGS, {})
        assert resp["queued"] == "staged"
        assert app_window.server_staging_queue.pending_count() == 1
        assert executed == []

    def test_the_staged_item_keeps_its_command_args_and_client(self, app_window, run_stubs):
        self.fill_queue(app_window)
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        command_type, args, client_id = app_window.server_staging_queue.take()
        assert command_type is CommandType.RENOISER
        assert args["image"] == "remote.png"
        # The client travels with the request: a promotion, possibly in a later
        # session, still has to know who asked for it.
        assert client_id == "weidr"

    def test_room_in_the_queue_means_no_staging(self, app_window, run_stubs, executed):
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert app_window.server_staging_queue.pending_count() == 0
        assert len(executed) == 1


class TestSnapshotIsTakenOnce:
    """The build works from one consistent read of RunnerAppConfig.

    Reading its two dozen fields while the sidebar writes them could otherwise
    catch it mid-update now that the build runs off the GUI thread.
    """

    def test_snapshot_carries_the_current_values(self, app_window):
        app_window.sidebar_panel.model_tags_entry.setText("snapshot_model")
        base_args, preset = app_window.run_ctrl._snapshot_for_server_run(
            CommandType.RENOISER, {}
        )
        assert base_args["model_tags"] == "snapshot_model"
        assert preset is None

    def test_later_edits_do_not_reach_a_built_run(self, app_window, run_stubs, executed):
        """The run is built from the snapshot, not from live config reads."""
        app_window.sidebar_panel.model_tags_entry.setText("at_request_time")
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        app_window.sidebar_panel.model_tags_entry.setText("changed_afterwards")
        assert executed[0].args.model_tags == "at_request_time"


class TestSnapshotReflectsTheSidebar:
    """A request brings only its own parameters.

    The model, loras, resolutions and counts all come from the stored config,
    and most of those fields are written back to it only when the user starts a
    run of their own -- so a request served straight from the stored values
    would use the settings as of that run rather than the ones on screen.
    """

    def test_a_sidebar_edit_reaches_a_server_run(self, app_window, run_stubs, executed):
        app_window.runner_app_config.model_tags = "stale_from_the_last_run"
        app_window.sidebar_panel.model_tags_entry.setText("what_the_user_picked")

        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )

        assert executed[0].args.model_tags == "what_the_user_picked"

    def test_the_edit_is_written_through_to_the_stored_config(self, app_window):
        app_window.runner_app_config.model_tags = "stale_from_the_last_run"
        app_window.sidebar_panel.model_tags_entry.setText("what_the_user_picked")

        app_window.run_ctrl._snapshot_for_server_run(CommandType.RENOISER, {})

        assert app_window.runner_app_config.model_tags == "what_the_user_picked"

    def test_resolution_group_is_stored_as_a_name(self, app_window):
        """The combo shows a description; the cache carries this across sessions."""
        from utils.globals import ResolutionGroup

        app_window.sidebar_panel.resolution_group_combo.setCurrentText(
            ResolutionGroup.SEVEN_SIXTY_EIGHT.get_description()
        )
        app_window.run_ctrl._snapshot_for_server_run(CommandType.RENOISER, {})

        assert (app_window.runner_app_config.resolution_group
                == ResolutionGroup.SEVEN_SIXTY_EIGHT.name)


# ---------------------------------------------------------------------------
# Progress indicator
# ---------------------------------------------------------------------------

class TestServerRunIndicator:
    def test_no_marker_when_nothing_is_running(self, app_window):
        assert app_window.run_ctrl.current_run_is_server_run() is False

    def test_marker_shows_while_a_server_run_is_current(self, app_window, run_stubs, monkeypatch):
        """Without this the label advances for a run shown nowhere on screen."""
        seen = []

        def capture_execute(self):
            seen.append(app_window.run_ctrl.current_run_is_server_run())
            self.is_complete = True

        monkeypatch.setattr(Run, "execute", capture_execute)
        app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert seen == [True]

    def test_no_marker_for_a_user_run(self, app_window, run_stubs, monkeypatch):
        seen = []

        def capture_execute(self):
            seen.append(app_window.run_ctrl.current_run_is_server_run())
            self.is_complete = True

        monkeypatch.setattr(Run, "execute", capture_execute)
        app_window.run_ctrl.run()
        assert seen == [False]
