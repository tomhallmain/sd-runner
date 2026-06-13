import pytest
from utils.job_queue import JobQueue, SDRunsQueue, ServerStagingQueue


class TestJobQueueBasics:
    def test_empty_queue_has_no_pending(self):
        q = JobQueue()
        assert q.has_pending() is False

    def test_add_makes_pending(self):
        q = JobQueue()
        q.add("job1")
        assert q.has_pending() is True

    def test_take_returns_first_item_fifo(self):
        q = JobQueue()
        q.add("first")
        q.add("second")
        assert q.take() == "first"
        assert q.take() == "second"

    def test_take_on_empty_returns_none(self):
        q = JobQueue()
        assert q.take() is None

    def test_take_removes_from_pending(self):
        q = JobQueue()
        q.add("job")
        q.take()
        assert len(q.pending_jobs) == 0

    def test_cancel_clears_all_pending(self):
        q = JobQueue()
        q.add("a")
        q.add("b")
        q.cancel()
        assert q.has_pending() is False
        assert len(q.pending_jobs) == 0

    def test_cancel_also_clears_job_running_flag(self):
        q = JobQueue()
        q.job_running = True
        q.cancel()
        assert q.job_running is False

    def test_has_pending_true_when_job_running(self):
        q = JobQueue()
        q.job_running = True
        assert q.has_pending() is True

    def test_max_size_enforced(self):
        q = JobQueue(max_size=2)
        q.add("a")
        q.add("b")
        q.add("c")  # one over max_size (limit is strict greater than)
        with pytest.raises(Exception, match="limit"):
            q.add("d")

    def test_paused_flag_defaults_false(self):
        q = JobQueue()
        assert q.paused is False

    def test_paused_flag_can_be_set(self):
        q = JobQueue()
        q.paused = True
        assert q.paused is True

    def test_estimate_time_raises_not_implemented(self):
        q = JobQueue()
        with pytest.raises(NotImplementedError):
            q.estimate_time()


class TestJobQueuePendingText:
    def test_empty_queue_returns_empty_string(self):
        q = JobQueue()
        assert q.pending_text() == ""

    def test_sd_runs_queue_shows_pending_count(self):
        q = SDRunsQueue()
        q.add("run1")
        text = q.pending_text()
        assert "1" in text

    def test_preset_schedules_queue_shows_pending_count(self):
        from utils.job_queue import PresetSchedulesQueue
        q = PresetSchedulesQueue()
        q.add("sched1")
        text = q.pending_text()
        assert "1" in text


class TestSDRunsQueue:
    def test_has_sd_runs_name(self):
        q = SDRunsQueue()
        assert q.name == JobQueue.JOB_QUEUE_SD_RUNS_KEY

    def test_estimate_time_zero_for_empty_queue(self):
        q = SDRunsQueue()
        assert q.estimate_time() == 0

    def test_estimate_time_sums_job_estimates(self):
        q = SDRunsQueue()

        class FakeRunConfig:
            def estimate_time(self, gen_config=None):
                return 30

        q.add(FakeRunConfig())
        q.add(FakeRunConfig())
        assert q.estimate_time() == 60


class TestServerStagingQueue:
    def test_empty_on_creation(self):
        q = ServerStagingQueue()
        assert q.has_pending() is False
        assert q.pending_count() == 0

    def test_add_returns_position(self):
        q = ServerStagingQueue()
        pos = q.add("wf_type", {"key": "val"})
        assert pos == 1
        pos2 = q.add("wf_type", {"key": "val2"})
        assert pos2 == 2

    def test_take_returns_fifo_tuple(self):
        q = ServerStagingQueue()
        q.add("type_a", {"x": 1})
        q.add("type_b", {"x": 2})
        wf, args = q.take()
        assert wf == "type_a"
        assert args == {"x": 1}

    def test_take_on_empty_returns_none(self):
        q = ServerStagingQueue()
        assert q.take() is None

    def test_pending_count_tracks_adds_and_takes(self):
        q = ServerStagingQueue()
        q.add("t", {})
        q.add("t", {})
        assert q.pending_count() == 2
        q.take()
        assert q.pending_count() == 1

    def test_cancel_clears_all(self):
        q = ServerStagingQueue()
        q.add("t", {})
        q.cancel()
        assert q.has_pending() is False

    def test_max_size_enforced(self):
        q = ServerStagingQueue()
        q.MAX_SIZE = 2
        q.add("t", {})
        q.add("t", {})
        with pytest.raises(Exception, match="full"):
            q.add("t", {})

    def test_pending_text_empty_when_no_items(self):
        q = ServerStagingQueue()
        assert q.pending_text() == ""

    def test_pending_text_contains_count(self):
        q = ServerStagingQueue()
        q.add("t", {})
        q.add("t", {})
        assert "2" in q.pending_text()
