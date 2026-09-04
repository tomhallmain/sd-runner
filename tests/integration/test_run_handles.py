"""Per-run handles: the id a client is given when its request is accepted.

``run_status`` used to answer only by origin, so a client firing several
requests was told that work of its own was in progress, not which. The id a
``Run`` carries was minted when the queue started it, which is long after the
moment a reply has to be written.

The id now lives on ``RunConfig`` from construction, so it exists before the
run is queued, survives a restore, and survives the round trip through the
staging queue -- which is the case with no ``RunConfig`` at all until the item
is promoted.
"""

from extensions.sd_runner_server import CommandType
from sd_runner.runs.job_queue import ServerStagingQueue
from sd_runner.runs.run_config import RunConfig


class TestRunConfigCarriesAnId:
    def test_every_run_config_has_one(self):
        assert RunConfig().run_id

    def test_two_configs_do_not_share_one(self):
        """Minted per config, not per tick: two built in the same instant are
        still separate runs and separate handles."""
        assert RunConfig().run_id != RunConfig().run_id

    def test_an_id_in_the_args_is_kept(self):
        """A promotion and a restore both rebuild a config that was already
        answered for, so the stored id has to win over a fresh one."""
        assert RunConfig(args={"run_id": "carried"}).run_id == "carried"

    def test_it_survives_serialization(self):
        rc = RunConfig(args={"workflow_tag": "IP_ADAPTER"})
        assert RunConfig.from_dict(rc.to_dict()).run_id == rc.run_id


class TestStagingCarriesTheId:
    """A staged request has no RunConfig, so the queue is where its id lives."""

    def test_add_mints_one_when_the_caller_has_none(self):
        q = ServerStagingQueue()
        q.add("type_a", {"x": 1}, "weidr")
        assert q.take()[3]

    def test_add_keeps_the_one_it_is_given(self):
        q = ServerStagingQueue()
        q.add("type_a", {"x": 1}, "weidr", "given")
        assert q.take()[3] == "given"

    def test_two_staged_requests_get_different_ids(self):
        q = ServerStagingQueue()
        q.add("type_a", {"x": 1}, "weidr")
        q.add("type_b", {"x": 2}, "weidr")
        assert q.take()[3] != q.take()[3]


class TestTheReplyCarriesTheId:
    def test_an_accepted_request_answers_with_its_run_id(
        self, app_window, run_stubs, executed
    ):
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        assert resp["run_id"] == executed[0].args.run_id

    def test_the_run_answers_to_the_id_the_client_was_given(
        self, app_window, run_stubs, executed
    ):
        """Run.id and RunConfig.run_id are one identity, not two."""
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}
        )
        assert executed[0].id == resp["run_id"]

    def test_two_requests_get_two_ids(self, app_window, run_stubs, executed):
        first = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "a.png"}, "weidr"
        )
        second = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "b.png"}, "weidr"
        )
        assert first["run_id"] != second["run_id"]


class TestABatchIsAddressable:
    """The case the handle design has to answer for.

    A batch stages its items without building a ``RunConfig`` for any of them,
    so the ids cannot come from there. One per accepted item, in order.
    """

    def test_every_accepted_item_gets_an_id(self, app_window, run_stubs):
        resp = app_window.run_ctrl.server_batch_enqueue(
            [{"type": "renoiser", "args": {"image": "a.png"}},
             {"type": "renoiser", "args": {"image": "b.png"}}],
            "weidr",
        )
        assert len(resp["run_ids"]) == resp["count"]
        assert len(set(resp["run_ids"])) == len(resp["run_ids"])

    def test_a_skipped_item_contributes_no_id(self, app_window, run_stubs):
        """run_ids lines up with what was accepted, not with what was sent."""
        resp = app_window.run_ctrl.server_batch_enqueue(
            [{"type": "renoiser", "args": {"image": "a.png"}},
             {"type": "not_a_command", "args": {}}],
            "weidr",
        )
        assert resp["count"] == 1
        assert len(resp["run_ids"]) == 1

    def test_a_batch_id_reaches_the_run_it_names(self, app_window, run_stubs, executed):
        """The first item is promoted immediately when nothing is running, so
        its id has to arrive on the run rather than being replaced by one the
        rebuild minted."""
        resp = app_window.run_ctrl.server_batch_enqueue(
            [{"type": "renoiser", "args": {"image": "a.png"}}], "weidr"
        )
        assert executed[0].args.run_id == resp["run_ids"][0]


class TestRunStatusAnswersForOneRun:
    def test_a_queued_run_reports_queued(self, app_window, run_stubs):
        """Nothing drains the queue here, so the run stays in it."""
        rc = RunConfig(args={"workflow_tag": "IP_ADAPTER"})
        app_window.job_queue.pending_jobs.append(rc)

        status = app_window.run_ctrl.run_status(run_id=rc.run_id)
        assert status["run_state"] == "queued"
        assert status["run_id"] == rc.run_id

    def test_a_staged_request_reports_staged(self, app_window, run_stubs):
        app_window.server_staging_queue.add(
            CommandType.RENOISER, {"image": "a.png"}, "weidr", "staged-id"
        )
        assert app_window.run_ctrl.run_status(run_id="staged-id")["run_state"] == "staged"

    def test_an_unheard_of_id_reports_unknown(self, app_window, run_stubs):
        assert app_window.run_ctrl.run_status(run_id="nope")["run_state"] == "unknown"

    def test_a_finished_run_reports_unknown(self, app_window, run_stubs, executed):
        """Nothing retains an id once its run is done, so 'no longer
        outstanding' is the honest answer rather than 'finished'."""
        resp = app_window.run_ctrl.server_run_callback(
            CommandType.RENOISER, {"image": "remote.png"}, "weidr"
        )
        status = app_window.run_ctrl.run_status(run_id=resp["run_id"])
        assert status["run_state"] == "unknown"

    def test_the_origin_answer_is_unchanged(self, app_window, run_stubs):
        """Asking by id must not take away the coarse answer clients already use."""
        status = app_window.run_ctrl.run_status(origin="weidr")
        assert "mine_running" in status
        assert "run_state" not in status
