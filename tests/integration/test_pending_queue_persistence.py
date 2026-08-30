"""Cross-session persistence of the run queue and the server staging queue.

``CacheController.store_pending_queues`` / ``_restore_pending_queues`` are the
pair that carries both queues across a restart. They had no direct coverage at
all, and both bugs found after the server-run work landed lived in them: a
staged entry restored as the wrong enum type, and a queued server run that made
the whole cache unencodable. The stored shape has since changed a third time
(entries carry the requesting client), and each earlier shape is still accepted
on restore -- so the fallbacks are exercised here rather than assumed.
"""
import json

import pytest

from extensions.sd_runner_server import CommandType
from tests.utils import make_run_config
from ui_qt.app_window import cache_controller as cache_controller_module


@pytest.fixture
def cache(app_window):
    """The cache instance the controller actually writes to.

    Read through the controller's own module binding rather than importing the
    singleton directly: the isolation fixture swaps in a fresh instance per test
    and repoints module-level bindings, so this is what the code under test sees.
    """
    return cache_controller_module.app_info_cache


@pytest.fixture
def ctrl(app_window):
    return app_window.cache_ctrl


def stored_requests(cache):
    return cache.get(cache_controller_module.CacheController.PENDING_SERVER_REQUESTS_KEY)


def stored_runs(cache):
    return cache.get(cache_controller_module.CacheController.PENDING_SD_RUNS_KEY)


def put_requests(cache, entries):
    cache.set(cache_controller_module.CacheController.PENDING_SERVER_REQUESTS_KEY, entries)


# ---------------------------------------------------------------------------
# Staging queue — store
# ---------------------------------------------------------------------------

class TestStoringStagedRequests:
    def test_a_staged_request_is_written_under_its_command_name(self, app_window, ctrl, cache):
        app_window.server_staging_queue.add(
            CommandType.IP_ADAPTER, {"image": "a.png"}, "weidr"
        )
        ctrl.store_pending_queues()

        assert stored_requests(cache) == [
            {"command_type": "IP_ADAPTER", "args": {"image": "a.png"}, "client_id": "weidr"}
        ]

    def test_the_stored_form_is_json_encodable(self, app_window, ctrl, cache):
        """The cache is encrypted json; an unencodable value breaks every save."""
        app_window.server_staging_queue.add(CommandType.TAKE_PROMPT, {"image": "a.png"})
        ctrl.store_pending_queues()

        json.dumps(stored_requests(cache))

    def test_a_command_that_selects_no_workflow_still_stores(self, app_window, ctrl, cache):
        """LAST_SETTINGS and TAKE_PROMPT have no WorkflowType of the same name."""
        app_window.server_staging_queue.add(CommandType.LAST_SETTINGS, {})
        ctrl.store_pending_queues()

        assert stored_requests(cache)[0]["command_type"] == "LAST_SETTINGS"

    def test_a_malformed_entry_does_not_cost_the_others(self, app_window, ctrl, cache):
        """The unpack is guarded per entry, so one bad shape is not fatal.

        Unguarded it aborted the whole method, and the queue was silently saved
        as nothing -- the failure mode the run half of this pair already had.
        """
        staging = app_window.server_staging_queue
        staging._requests.append(("not", "a triple", "at", "all"))
        staging.add(CommandType.RENOISER, {"image": "good.png"}, "weidr")
        ctrl.store_pending_queues()

        assert stored_requests(cache) == [
            {"command_type": "RENOISER", "args": {"image": "good.png"}, "client_id": "weidr"}
        ]


# ---------------------------------------------------------------------------
# Staging queue — restore
# ---------------------------------------------------------------------------

class TestRestoringStagedRequests:
    def test_a_stored_request_comes_back_as_the_triple_the_queue_holds(
        self, app_window, ctrl, cache
    ):
        app_window.server_staging_queue.add(
            CommandType.IMAGE_EDIT, {"image": "a.png"}, "weidr"
        )
        ctrl.store_pending_queues()
        app_window.server_staging_queue.cancel()

        ctrl._restore_pending_queues()

        assert app_window.server_staging_queue.take() == (
            CommandType.IMAGE_EDIT, {"image": "a.png"}, "weidr"
        )

    def test_the_command_survives_as_a_command_not_a_workflow(self, app_window, ctrl, cache):
        """Five command names collide with WorkflowType names; this is one.

        Restoring it against the wrong enum is what raised AttributeError on the
        first promotion of a restored request.
        """
        app_window.server_staging_queue.add(CommandType.IP_ADAPTER, {})
        ctrl.store_pending_queues()
        app_window.server_staging_queue.cancel()

        ctrl._restore_pending_queues()

        command_type, _args, _client = app_window.server_staging_queue.take()
        assert command_type is CommandType.IP_ADAPTER

    def test_an_entry_written_before_requests_carried_a_client(
        self, app_window, ctrl, cache
    ):
        """It restores with no origin, which the run path then names."""
        put_requests(cache, [{"command_type": "RENOISER", "args": {"image": "a.png"}}])

        ctrl._restore_pending_queues()

        assert app_window.server_staging_queue.take() == (
            CommandType.RENOISER, {"image": "a.png"}, ""
        )

    def test_an_entry_written_under_the_stale_workflow_type_key(
        self, app_window, ctrl, cache
    ):
        """The old writer already held a CommandType, just filed under that key."""
        put_requests(cache, [{"workflow_type": "REDO_PROMPT", "args": {"image": "a.png"}}])

        ctrl._restore_pending_queues()

        command_type, _args, _client = app_window.server_staging_queue.take()
        assert command_type is CommandType.REDO_PROMPT

    def test_an_unrecognized_entry_is_dropped_without_taking_its_neighbours(
        self, app_window, ctrl, cache
    ):
        put_requests(cache, [
            {"command_type": "NOT_A_COMMAND", "args": {}},
            {"command_type": "RENOISER", "args": {"image": "good.png"}, "client_id": "weidr"},
        ])

        ctrl._restore_pending_queues()

        assert app_window.server_staging_queue.pending_count() == 1
        assert app_window.server_staging_queue.take()[1] == {"image": "good.png"}

    def test_the_key_is_cleared_so_a_restore_does_not_repeat(
        self, app_window, ctrl, cache
    ):
        app_window.server_staging_queue.add(CommandType.RENOISER, {"image": "a.png"})
        ctrl.store_pending_queues()
        app_window.server_staging_queue.cancel()

        ctrl._restore_pending_queues()
        ctrl._restore_pending_queues()

        assert app_window.server_staging_queue.pending_count() == 1


# ---------------------------------------------------------------------------
# Run queue
# ---------------------------------------------------------------------------

class TestPendingRuns:
    def test_a_queued_run_survives_the_round_trip(self, app_window, ctrl, cache):
        run_config = make_run_config(workflow_tag="IP_ADAPTER", model_tags="a_model")
        app_window.job_queue.pending_jobs.append(run_config)
        ctrl.store_pending_queues()
        app_window.job_queue.pending_jobs.clear()

        ctrl._restore_pending_queues()

        assert len(app_window.job_queue.pending_jobs) == 1
        assert app_window.job_queue.pending_jobs[0].model_tags == "a_model"

    def test_a_runs_origin_survives_with_it(self, app_window, ctrl, cache):
        """A queued server run is attributable after the restart that dropped it."""
        run_config = make_run_config(workflow_tag="RENOISER")
        run_config.run_origin = "weidr"
        app_window.job_queue.pending_jobs.append(run_config)
        ctrl.store_pending_queues()
        app_window.job_queue.pending_jobs.clear()

        ctrl._restore_pending_queues()

        assert app_window.job_queue.pending_jobs[0].run_origin == "weidr"

    def test_a_sidebar_built_run_is_written_too(self, app_window, ctrl, cache):
        """It used to be skipped outright, so this queue could only be empty."""
        args, _copy = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)
        ctrl.store_pending_queues()

        assert len(stored_runs(cache)) == 1

    def test_the_stored_form_is_json_encodable(self, app_window, ctrl, cache):
        """Enum members on a run are what made the whole cache unwritable."""
        args, _copy = app_window.get_args()
        app_window.job_queue.pending_jobs.append(args)
        ctrl.store_pending_queues()

        json.dumps(stored_runs(cache))

    def test_a_restored_queue_starts_paused(self, app_window, ctrl, cache):
        """Nothing should start generating on its own at startup."""
        app_window.job_queue.pending_jobs.append(make_run_config(workflow_tag="RENOISER"))
        ctrl.store_pending_queues()
        app_window.job_queue.pending_jobs.clear()
        app_window.job_queue.paused = False

        ctrl._restore_pending_queues()

        assert app_window.job_queue.paused is True

    def test_an_entry_in_a_foreign_shape_is_refused(self, app_window, ctrl, cache):
        """Rather than restored as a run with silently empty fields."""
        cache.set(
            cache_controller_module.CacheController.PENDING_SD_RUNS_KEY,
            [{"not": "a run"}],
        )

        ctrl._restore_pending_queues()

        assert app_window.job_queue.pending_jobs == []
