"""Is a local backend up and answering?

The one place that knows where to ask each backend. Two features need this and
would otherwise each carry their own copy of the table: launching a backend as
a subprocess has to poll until it is ready (and skip launching one that is
already up), and a client asking SD Runner whether a backend is operational
needs the same question answered.

This is connectivity only -- the process is running and its API responds. It
says nothing about whether a model is loaded or whether the GPU works, which
is a heavier check with side effects.

Cloud backends are not covered: there is no local process, and reachability of
a hosted API is a different question with an API key attached.
"""

import json
import socket
import time
from typing import NamedTuple, Optional
from urllib import error, request

from utils.config import config
from utils.globals import SoftwareType
from utils.logging_setup import get_logger

logger = get_logger("backend_health")

#: Seconds to wait for a backend to answer. Short: a backend that is up
#: answers immediately, and this runs in a polling loop during startup.
DEFAULT_TIMEOUT = 2


class _Endpoint(NamedTuple):
    """Where to ask a backend whether it is up, and how.

    *path* is appended to the backend's configured URL. *method* is POST only
    for SwarmUI, whose root responds long before its API can be used.
    """
    config_field: str
    path: str
    method: str = "GET"


#: The root of a web UI often answers before its API does, so where a backend
#: exposes an API endpoint that is cheap and side-effect free, that is used
#: instead -- being able to load the page is not the thing callers care about.
ENDPOINTS = {
    SoftwareType.ComfyUI: _Endpoint("comfyui_url", "/system_stats"),
    SoftwareType.SDWebUI: _Endpoint("sd_webui_url", "/sdapi/v1/options"),
    SoftwareType.Forge: _Endpoint("forge_url", "/sdapi/v1/options"),
    SoftwareType.SDNext: _Endpoint("sdnext_url", "/sdapi/v1/options"),
    SoftwareType.Fooocus: _Endpoint("fooocus_url", "/"),
    SoftwareType.InvokeAI: _Endpoint("invokeai_url", "/api/v1/app/version"),
    # SwarmUI is the exception: its root serves a page well before the API can
    # issue a session, and every SwarmUI call needs a session. Asking for one
    # is the only check that means anything.
    SoftwareType.SwarmUI: _Endpoint("swarmui_url", "/API/GetNewSession", "POST"),
}


class HealthResult(NamedTuple):
    """The outcome of one connectivity check.

    *reachable* is the answer; *detail* is for a human reading a log or an
    error dialog, and is empty when the check succeeded. *timed_out* separates
    "did not answer in time" from "refused the connection" -- a client can
    retry the first with more patience, while the second needs someone to go
    and look.
    """
    software_type: SoftwareType
    url: str
    reachable: bool
    detail: str = ""
    timed_out: bool = False

    def __str__(self) -> str:
        state = "up" if self.reachable else f"down ({self.detail})"
        return f"{self.software_type.value} at {self.url}: {state}"


def health_url(software_type: SoftwareType) -> Optional[str]:
    """The URL a connectivity check would hit, or None if there isn't one.

    None means either a cloud backend or one with no URL configured -- both
    cases where there is nothing local to check.
    """
    endpoint = ENDPOINTS.get(software_type)
    if endpoint is None:
        return None
    base = getattr(config, endpoint.config_field, None)
    if not base:
        return None
    return base.rstrip("/") + endpoint.path


def check(software_type: SoftwareType, timeout: int = DEFAULT_TIMEOUT) -> HealthResult:
    """Ask one backend whether it is up. Never raises.

    Any failure is a "down" answer rather than an exception: every caller is
    either polling in a loop or reporting to a user, and neither wants to
    distinguish a refused connection from a malformed URL.
    """
    endpoint = ENDPOINTS.get(software_type)
    if endpoint is None:
        return HealthResult(software_type, "", False, "not a local backend")

    url = health_url(software_type)
    if not url:
        return HealthResult(
            software_type, "", False, f"{endpoint.config_field} is not configured"
        )

    try:
        req = request.Request(url, method=endpoint.method)
        if endpoint.method == "POST":
            # SwarmUI's session endpoint wants a body, even an empty one.
            req.data = json.dumps({}).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with request.urlopen(req, timeout=timeout) as response:
            if 200 <= response.status < 300:
                return HealthResult(software_type, url, True)
            return HealthResult(
                software_type, url, False, f"HTTP {response.status}"
            )
    except error.HTTPError as e:
        # A backend that answers at all is running. Some return 4xx for a
        # probe they do not recognise, which still tells us what we asked.
        if e.code in (401, 403, 405):
            return HealthResult(software_type, url, True)
        return HealthResult(software_type, url, False, f"HTTP {e.code}")
    except error.URLError as e:
        # urlopen wraps a socket timeout in URLError, so the distinction has to
        # be recovered from the reason rather than caught separately.
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            return HealthResult(software_type, url, False,
                                f"no response in {timeout}s", timed_out=True)
        return HealthResult(software_type, url, False, str(e.reason))
    except (socket.timeout, TimeoutError):
        return HealthResult(software_type, url, False,
                            f"no response in {timeout}s", timed_out=True)
    except Exception as e:
        return HealthResult(software_type, url, False, str(e))


def is_reachable(software_type: SoftwareType, timeout: int = DEFAULT_TIMEOUT) -> bool:
    """Whether *software_type* is up. The boolean form of ``check``."""
    return check(software_type, timeout=timeout).reachable


# ---------------------------------------------------------------------------
# Level 2 -- is it in a state where it could generate?
#
# Not by generating. A real probe would be the only proof the GPU pipeline
# works, but it writes an output file, needs a model chosen for it, queues
# behind whatever is already running, and has to be cancellable so it does not
# consume a slot the user wanted. Instead these confirm the backend is idle and
# has models -- weaker, and free of side effects.
# ---------------------------------------------------------------------------

class _Budget:
    """The wall-clock allowance for one check, shared by its several requests.

    A level 2 check makes two or three requests. Giving each of them the
    caller's full timeout would let a check asked to take 30 seconds take 90 --
    the client's number has to bound the whole answer, not each step of it.
    """

    def __init__(self, seconds: float):
        self._deadline = time.monotonic() + max(1.0, float(seconds))

    def remaining(self) -> float:
        return max(0.0, self._deadline - time.monotonic())

    @property
    def expired(self) -> bool:
        return self.remaining() <= 0


def _timed_out(software_type: SoftwareType, url: str, seconds: float) -> HealthResult:
    return HealthResult(
        software_type, url or "", False,
        f"did not reach a usable state within {int(seconds)}s", timed_out=True,
    )


def _get_json(url: str, timeout: float, method: str = "GET", body: dict = None):
    """Fetch and parse JSON, or None on any failure."""
    try:
        req = request.Request(url, method=method)
        if body is not None:
            req.data = json.dumps(body).encode("utf-8")
            req.add_header("Content-Type", "application/json")
        with request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as e:
        logger.debug(f"Health probe {url} failed: {e}")
        return None


def _base_url(software_type: SoftwareType) -> Optional[str]:
    endpoint = ENDPOINTS.get(software_type)
    if endpoint is None:
        return None
    base = getattr(config, endpoint.config_field, None)
    return base.rstrip("/") if base else None


def _comfyui_functional(base: str, budget: _Budget) -> HealthResult:
    queue = _get_json(f"{base}/queue", budget.remaining())
    if queue is None:
        return HealthResult(SoftwareType.ComfyUI, base, False, "queue unreadable")
    busy = queue.get("queue_running") or queue.get("queue_pending")
    if busy:
        # Working is itself evidence of health -- see generation_in_progress.
        return HealthResult(SoftwareType.ComfyUI, base, True, "busy")
    nodes = _get_json(f"{base}/object_info", budget.remaining())
    if not nodes:
        return HealthResult(SoftwareType.ComfyUI, base, False, "no nodes loaded")
    return HealthResult(SoftwareType.ComfyUI, base, True)


def _sdwebui_functional(software_type, base: str, budget: _Budget) -> HealthResult:
    options = _get_json(f"{base}/sdapi/v1/options", budget.remaining())
    if options is None:
        return HealthResult(software_type, base, False, "options unreadable")
    if not options.get("sd_model_checkpoint"):
        return HealthResult(software_type, base, False, "no model loaded")
    progress = _get_json(f"{base}/sdapi/v1/progress", budget.remaining())
    if progress and (progress.get("state") or {}).get("job_count"):
        return HealthResult(software_type, base, True, "busy")
    return HealthResult(software_type, base, True)


def _invokeai_functional(base: str, budget: _Budget) -> HealthResult:
    models = _get_json(f"{base}/api/v1/models/", budget.remaining())
    if not models:
        return HealthResult(SoftwareType.InvokeAI, base, False, "no models available")
    status = _get_json(f"{base}/api/v1/queue/default/status", budget.remaining())
    queue = (status or {}).get("queue") or {}
    if queue.get("in_progress") or queue.get("pending"):
        return HealthResult(SoftwareType.InvokeAI, base, True, "busy")
    return HealthResult(SoftwareType.InvokeAI, base, True)


def _swarmui_functional(base: str, budget: _Budget) -> HealthResult:
    # Prefer the session the generator already holds -- SwarmUI tracks sessions
    # per client, and opening a second one when a usable one exists is asking
    # for trouble. Read the cached id rather than calling _get_session(), which
    # is an instance method and would fetch one as a side effect.
    session = None
    try:
        from sd_runner.generators.swarmui import SwarmUIGen
        session = SwarmUIGen._session_id
    except Exception as e:
        logger.debug(f"Could not read the SwarmUI session: {e}")
    if not session:
        # None cached yet: ask for one the same way the connectivity check did.
        handshake = _get_json(f"{base}/API/GetNewSession", budget.remaining(),
                              method="POST", body={})
        session = (handshake or {}).get("session_id")
    if not session:
        return HealthResult(SoftwareType.SwarmUI, base, False, "no session")
    models = _get_json(f"{base}/API/ListModels", budget.remaining(),
                       method="POST", body={"session_id": session})
    if not models:
        return HealthResult(SoftwareType.SwarmUI, base, False, "no models available")
    return HealthResult(SoftwareType.SwarmUI, base, True)


def check_functional(software_type: SoftwareType,
                     timeout: int = DEFAULT_TIMEOUT) -> HealthResult:
    """Whether the backend looks able to generate. Never raises.

    Falls back to plain connectivity for a backend with no usable idle-state
    API -- a weaker answer reported honestly, rather than a stricter one
    invented.
    """
    budget = _Budget(timeout)
    connectivity = check(software_type, timeout=budget.remaining())
    if not connectivity.reachable:
        return connectivity
    if budget.expired:
        return _timed_out(software_type, connectivity.url, timeout)

    base = _base_url(software_type)
    if software_type is SoftwareType.ComfyUI:
        result = _comfyui_functional(base, budget)
    elif software_type in (SoftwareType.SDWebUI, SoftwareType.Forge, SoftwareType.SDNext):
        result = _sdwebui_functional(software_type, base, budget)
    elif software_type is SoftwareType.InvokeAI:
        result = _invokeai_functional(base, budget)
    elif software_type is SoftwareType.SwarmUI:
        result = _swarmui_functional(base, budget)
    else:
        result = None
    if result is not None:
        # A probe that came back empty because the clock ran out is a timeout,
        # not a backend without models -- the difference decides whether the
        # client should retry or go and look.
        if not result.reachable and budget.expired:
            return _timed_out(software_type, connectivity.url, timeout)
        return result
    # Fooocus publishes no model-loaded or queue endpoint, so there is nothing
    # here beyond what connectivity already established.
    return HealthResult(software_type, connectivity.url, True, "connectivity only")


def local_backends() -> list:
    """Every backend this module can check, in enum order."""
    return [s for s in SoftwareType if s in ENDPOINTS]
