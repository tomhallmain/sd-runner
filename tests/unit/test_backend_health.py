"""Connectivity checks against local backends.

No network: ``urlopen`` is replaced throughout. What is worth asserting is the
URL each backend is asked for, and that every failure becomes a "down" answer
rather than an exception -- callers are polling loops and error dialogs, and
neither can do anything useful with a raised URLError.
"""

import socket
from urllib import error

import pytest

from extensions import backend_health
from extensions.backend_health import (
    ENDPOINTS, check, check_functional, health_url, is_reachable, local_backends,
)
from utils.globals import SoftwareType


class FakeResponse:
    def __init__(self, status=200):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def urls(monkeypatch):
    """Point every backend at a known URL and record what gets requested."""
    for software_type, endpoint in ENDPOINTS.items():
        monkeypatch.setattr(
            backend_health.config, endpoint.config_field,
            f"http://localhost/{software_type.value}", raising=False,
        )
    requested = []

    def fake_urlopen(req, timeout=None):
        requested.append((req.full_url, req.get_method()))
        return FakeResponse()

    monkeypatch.setattr(backend_health.request, "urlopen", fake_urlopen)
    return requested


def fail_with(monkeypatch, exception):
    def raiser(req, timeout=None):
        raise exception
    monkeypatch.setattr(backend_health.request, "urlopen", raiser)


# ---------------------------------------------------------------------------
# Coverage of the endpoint table
# ---------------------------------------------------------------------------

class TestEndpointTable:
    def test_every_local_backend_is_covered(self):
        """A local backend with no entry silently becomes uncheckable."""
        missing = [s for s in SoftwareType if not s.is_cloud() and s not in ENDPOINTS]
        assert missing == []

    def test_no_cloud_backend_is_covered(self):
        """There is no local process to check, and no local URL to check it at."""
        assert [s for s in ENDPOINTS if s.is_cloud()] == []

    def test_local_backends_lists_them_all(self):
        assert set(local_backends()) == set(ENDPOINTS)


class TestHealthUrl:
    def test_it_joins_the_configured_url_and_the_path(self, urls):
        assert health_url(SoftwareType.SDWebUI) == (
            "http://localhost/SDWebUI/sdapi/v1/options"
        )

    def test_a_trailing_slash_does_not_double_up(self, monkeypatch):
        monkeypatch.setattr(backend_health.config, "comfyui_url", "http://host:8188/")
        assert health_url(SoftwareType.ComfyUI) == "http://host:8188/system_stats"

    def test_an_unconfigured_url_has_no_health_url(self, monkeypatch):
        monkeypatch.setattr(backend_health.config, "comfyui_url", None)
        assert health_url(SoftwareType.ComfyUI) is None

    def test_a_cloud_backend_has_no_health_url(self):
        assert health_url(SoftwareType.OpenAI) is None

    def test_the_api_is_preferred_over_the_web_root(self):
        """A web UI serves its page well before its API can take a request."""
        assert ENDPOINTS[SoftwareType.SDWebUI].path == "/sdapi/v1/options"
        assert ENDPOINTS[SoftwareType.ComfyUI].path != "/"

    def test_swarmui_is_checked_by_asking_for_a_session(self):
        """Its root answers long before a session can be issued, and every
        SwarmUI call needs one."""
        assert ENDPOINTS[SoftwareType.SwarmUI].method == "POST"


# ---------------------------------------------------------------------------
# Checking
# ---------------------------------------------------------------------------

class TestCheck:
    def test_a_200_is_reachable(self, urls):
        assert check(SoftwareType.ComfyUI).reachable is True

    def test_it_requests_the_health_url(self, urls):
        check(SoftwareType.InvokeAI)
        assert urls == [("http://localhost/InvokeAI/api/v1/app/version", "GET")]

    def test_swarmui_is_asked_with_a_post(self, urls):
        check(SoftwareType.SwarmUI)
        assert urls[0][1] == "POST"

    def test_an_unconfigured_backend_is_not_reachable(self, monkeypatch):
        monkeypatch.setattr(backend_health.config, "comfyui_url", None)
        result = check(SoftwareType.ComfyUI)
        assert result.reachable is False
        assert "comfyui_url" in result.detail

    def test_a_cloud_backend_is_not_checkable(self):
        result = check(SoftwareType.StabilityAI)
        assert result.reachable is False
        assert "not a local backend" in result.detail


class TestFailuresBecomeAnswers:
    """Never raises: every caller is a poll loop or a message to a user."""

    def test_a_refused_connection(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("Connection refused"))
        assert check(SoftwareType.ComfyUI).reachable is False

    def test_a_timeout(self, urls, monkeypatch):
        fail_with(monkeypatch, socket.timeout())
        assert check(SoftwareType.ComfyUI).reachable is False

    def test_an_unexpected_error(self, urls, monkeypatch):
        fail_with(monkeypatch, RuntimeError("something else entirely"))
        assert check(SoftwareType.ComfyUI).reachable is False

    def test_a_server_error_is_down(self, urls, monkeypatch):
        fail_with(monkeypatch, error.HTTPError(
            "u", 500, "Internal Server Error", {}, None))
        assert check(SoftwareType.ComfyUI).reachable is False

    @pytest.mark.parametrize("code", [401, 403, 405])
    def test_a_backend_that_refuses_the_probe_is_still_up(self, urls, monkeypatch, code):
        """It answered, which is the question being asked."""
        fail_with(monkeypatch, error.HTTPError("u", code, "no", {}, None))
        assert check(SoftwareType.ComfyUI).reachable is True

    def test_the_detail_explains_a_failure(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("Connection refused"))
        assert "refused" in check(SoftwareType.ComfyUI).detail

    def test_a_success_needs_no_detail(self, urls):
        assert check(SoftwareType.ComfyUI).detail == ""


class TestIsReachable:
    def test_it_is_the_boolean_form(self, urls):
        assert is_reachable(SoftwareType.ComfyUI) is True

    def test_it_is_false_when_down(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("nope"))
        assert is_reachable(SoftwareType.ComfyUI) is False


class TestResultRendering:
    def test_a_reachable_result_reads_as_up(self, urls):
        assert "up" in str(check(SoftwareType.ComfyUI))

    def test_a_failed_result_carries_the_reason(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("Connection refused"))
        assert "refused" in str(check(SoftwareType.ComfyUI))


# ---------------------------------------------------------------------------
# Level 2 — could it generate?
# ---------------------------------------------------------------------------

@pytest.fixture
def probes(urls, monkeypatch):
    """Serve canned JSON per endpoint suffix. Anything unlisted returns None."""
    responses = {}

    def fake_get_json(url, timeout, method="GET", body=None):
        for suffix, payload in responses.items():
            if url.endswith(suffix):
                return payload
        return None

    monkeypatch.setattr(backend_health, "_get_json", fake_get_json)
    return responses


class TestComfyUIFunctional:
    def test_idle_with_nodes_loaded_is_healthy(self, probes):
        probes["/queue"] = {"queue_running": [], "queue_pending": []}
        probes["/object_info"] = {"KSampler": {}}
        assert check_functional(SoftwareType.ComfyUI).reachable is True

    def test_no_nodes_loaded_is_not_healthy(self, probes):
        probes["/queue"] = {"queue_running": [], "queue_pending": []}
        probes["/object_info"] = {}
        result = check_functional(SoftwareType.ComfyUI)
        assert result.reachable is False
        assert "no nodes" in result.detail

    def test_a_busy_backend_is_healthy(self, probes):
        """Working is evidence of health, not a failure to be idle."""
        probes["/queue"] = {"queue_running": [["job"]], "queue_pending": []}
        result = check_functional(SoftwareType.ComfyUI)
        assert result.reachable is True
        assert result.detail == "busy"

    def test_an_unreadable_queue_is_not_healthy(self, probes):
        assert check_functional(SoftwareType.ComfyUI).reachable is False


class TestSDWebUIFunctional:
    def test_a_loaded_model_and_no_job_is_healthy(self, probes):
        probes["/sdapi/v1/options"] = {"sd_model_checkpoint": "model.safetensors"}
        probes["/sdapi/v1/progress"] = {"state": {"job_count": 0}}
        assert check_functional(SoftwareType.SDWebUI).reachable is True

    def test_no_model_loaded_is_not_healthy(self, probes):
        """It is up, but it could not generate if asked."""
        probes["/sdapi/v1/options"] = {"sd_model_checkpoint": ""}
        result = check_functional(SoftwareType.SDWebUI)
        assert result.reachable is False
        assert "no model" in result.detail

    def test_a_job_in_progress_is_healthy(self, probes):
        probes["/sdapi/v1/options"] = {"sd_model_checkpoint": "model.safetensors"}
        probes["/sdapi/v1/progress"] = {"state": {"job_count": 1}}
        result = check_functional(SoftwareType.SDWebUI)
        assert result.reachable is True
        assert result.detail == "busy"

    @pytest.mark.parametrize("software_type", [
        SoftwareType.Forge, SoftwareType.SDNext,
    ])
    def test_the_forks_use_the_same_api(self, probes, software_type):
        probes["/sdapi/v1/options"] = {"sd_model_checkpoint": "model.safetensors"}
        probes["/sdapi/v1/progress"] = {"state": {"job_count": 0}}
        assert check_functional(software_type).reachable is True


class TestOtherBackendsFunctional:
    def test_invokeai_needs_models(self, probes):
        probes["/api/v1/models/"] = []
        assert check_functional(SoftwareType.InvokeAI).reachable is False

    def test_invokeai_with_models_and_an_idle_queue(self, probes):
        probes["/api/v1/models/"] = [{"name": "a model"}]
        probes["/api/v1/queue/default/status"] = {"queue": {"pending": 0, "in_progress": 0}}
        assert check_functional(SoftwareType.InvokeAI).reachable is True

    def test_swarmui_reuses_a_cached_session(self, probes, monkeypatch):
        from sd_runner.generators.swarmui import SwarmUIGen
        monkeypatch.setattr(SwarmUIGen, "_session_id", "cached-session")
        probes["/API/ListModels"] = {"models": ["a model"]}
        assert check_functional(SoftwareType.SwarmUI).reachable is True

    def test_swarmui_without_a_session_is_not_healthy(self, probes, monkeypatch):
        from sd_runner.generators.swarmui import SwarmUIGen
        monkeypatch.setattr(SwarmUIGen, "_session_id", None)
        result = check_functional(SoftwareType.SwarmUI)
        assert result.reachable is False
        assert "session" in result.detail

    def test_fooocus_falls_back_to_connectivity(self, probes):
        """It publishes no model or queue endpoint; say so rather than invent one."""
        result = check_functional(SoftwareType.Fooocus)
        assert result.reachable is True
        assert result.detail == "connectivity only"


class TestFunctionalRequiresConnectivity:
    def test_an_unreachable_backend_short_circuits(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("Connection refused"))
        result = check_functional(SoftwareType.ComfyUI)
        assert result.reachable is False
        assert "refused" in result.detail


class TestTimeoutIsABudget:
    """The caller's number bounds the whole answer, not each request in it."""

    def test_the_budget_is_shared_across_requests(self, probes, monkeypatch):
        """A level 2 check makes several requests; together they must fit."""
        asked = []

        def recording_get_json(url, timeout, method="GET", body=None):
            asked.append(timeout)
            if url.endswith("/queue"):
                return {"queue_running": [], "queue_pending": []}
            return {"KSampler": {}}

        monkeypatch.setattr(backend_health, "_get_json", recording_get_json)
        check_functional(SoftwareType.ComfyUI, timeout=10)
        # Each request gets what is left, never the full allowance again.
        assert len(asked) == 2
        assert asked[1] <= asked[0]
        assert all(t <= 10 for t in asked)

    def test_a_timed_out_connectivity_check_says_so(self, urls, monkeypatch):
        """Distinct from refused: the client can retry this one with patience."""
        import socket as socket_module
        fail_with(monkeypatch, error.URLError(socket_module.timeout()))
        result = check(SoftwareType.ComfyUI)
        assert result.reachable is False
        assert result.timed_out is True

    def test_a_refused_connection_is_not_a_timeout(self, urls, monkeypatch):
        fail_with(monkeypatch, error.URLError("Connection refused"))
        assert check(SoftwareType.ComfyUI).timed_out is False

    def test_a_successful_check_is_not_a_timeout(self, urls):
        assert check(SoftwareType.ComfyUI).timed_out is False

    def test_an_exhausted_budget_reports_a_timeout(self, urls, monkeypatch):
        """The clock running out mid-check is not "no models available"."""
        monkeypatch.setattr(backend_health, "_get_json",
                            lambda *a, **k: None)
        monkeypatch.setattr(
            backend_health._Budget, "expired", property(lambda self: True)
        )
        result = check_functional(SoftwareType.ComfyUI, timeout=5)
        assert result.timed_out is True
