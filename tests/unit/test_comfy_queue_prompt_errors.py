"""What ``ComfyGen.queue_prompt`` does when a generation fails.

An empty list means a generation that completed and wrote nothing. A failure
raises. The two used to be indistinguishable: a ``return`` inside the method's
``finally`` discarded every exception on its way out, so a dead backend and a
barren one both surfaced as ``[]`` and the "Is ComfyUI running?" message could
never reach a caller.

Cleanup has to happen on the failing path too -- the websocket close and the
pending-count release both sit in that same ``finally``.
"""

from urllib import error

import pytest

from sd_runner.generators import comfy as comfy_module
from sd_runner.generators.comfy import ComfyGen
from tests.utils import make_gen_config


class StubPrompt:
    """The only thing queue_prompt asks of a prompt is its JSON."""

    def get_json(self):
        return b'{"prompt": {}}'


class StubWebSocket:
    """Records whether it was closed, and can refuse to connect."""

    def __init__(self, fail_connect=False):
        self.fail_connect = fail_connect
        self.closed = False

    def connect(self, *args, **kwargs):
        if self.fail_connect:
            raise error.URLError("no route to host")

    def close(self):
        self.closed = True


@pytest.fixture
def gen():
    generator = ComfyGen(make_gen_config(), ui_callbacks=None)
    # queue_prompt releases the pending count; arm it so the release is real,
    # as it would be inside a scheduled task.
    generator.count_pending_dispatch()
    generator._arm_pending_release()
    return generator


@pytest.fixture(autouse=True)
def no_leftover_connections():
    ComfyGen._active_connections.clear()
    yield
    ComfyGen._active_connections.clear()


def install_socket(monkeypatch, socket):
    monkeypatch.setattr(comfy_module.websocket, "WebSocket", lambda: socket)
    return socket


# ---------------------------------------------------------------------------
# Failures reach the caller
# ---------------------------------------------------------------------------

class TestFailuresRaise:
    def test_a_dead_backend_raises_rather_than_reporting_no_images(
        self, gen, monkeypatch
    ):
        install_socket(monkeypatch, StubWebSocket(fail_connect=True))
        with pytest.raises(Exception, match="Is ComfyUI running"):
            gen.queue_prompt(StubPrompt())

    def test_an_error_during_generation_propagates(self, gen, monkeypatch):
        install_socket(monkeypatch, StubWebSocket())

        def boom(*args, **kwargs):
            raise RuntimeError("backend blew up mid-prompt")

        monkeypatch.setattr(ComfyGen, "get_images", staticmethod(boom))
        with pytest.raises(RuntimeError, match="blew up"):
            gen.queue_prompt(StubPrompt())

    def test_a_completed_generation_returns_its_paths(self, gen, monkeypatch):
        install_socket(monkeypatch, StubWebSocket())
        monkeypatch.setattr(
            ComfyGen,
            "get_images",
            staticmethod(lambda *a, **kw: ([], ["/out/one.png"], 1.5)),
        )
        assert gen.queue_prompt(StubPrompt()) == ["/out/one.png"]

    def test_an_empty_result_is_still_an_empty_list_not_an_error(
        self, gen, monkeypatch
    ):
        """A generation that wrote nothing is not a failure."""
        install_socket(monkeypatch, StubWebSocket())
        monkeypatch.setattr(
            ComfyGen, "get_images", staticmethod(lambda *a, **kw: ([], [], 1.0))
        )
        assert gen.queue_prompt(StubPrompt()) == []


# ---------------------------------------------------------------------------
# Cleanup happens regardless
# ---------------------------------------------------------------------------

class TestCleanupOnFailure:
    def test_the_socket_is_closed_and_untracked_when_generation_fails(
        self, gen, monkeypatch
    ):
        socket = install_socket(monkeypatch, StubWebSocket())
        monkeypatch.setattr(
            ComfyGen,
            "get_images",
            staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x"))),
        )
        with pytest.raises(RuntimeError):
            gen.queue_prompt(StubPrompt())
        assert socket.closed
        assert socket not in ComfyGen._active_connections

    def test_a_socket_that_never_connected_is_not_tracked(self, gen, monkeypatch):
        socket = install_socket(monkeypatch, StubWebSocket(fail_connect=True))
        with pytest.raises(Exception):
            gen.queue_prompt(StubPrompt())
        assert socket not in ComfyGen._active_connections

    def test_the_pending_count_is_released_when_generation_fails(
        self, gen, monkeypatch
    ):
        before = gen.pending_counter
        install_socket(monkeypatch, StubWebSocket())
        monkeypatch.setattr(
            ComfyGen,
            "get_images",
            staticmethod(lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("x"))),
        )
        with pytest.raises(RuntimeError):
            gen.queue_prompt(StubPrompt())
        assert gen.pending_counter == before - 1
