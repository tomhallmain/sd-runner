"""What the window does around a generate that takes a long time.

A VLM generate blocks for tens of seconds while it loads and runs a model. The
call is therefore handed to the responsiveness port rather than made on the GUI
thread, and the window says so while it waits. Both halves matter: the status
has to be corrected afterwards on either outcome, and an error raised inside a
worker has to arrive back here rather than being swallowed into a ``None``.

The backends themselves are not exercised -- a stub service stands in, because
what is asserted is the window's handling, not what a model returns.
"""

from types import SimpleNamespace

import pytest

from sd_runner.image_to_prompt.types import (
    ImageToPromptBackend,
    ImageToPromptResult,
)
from sd_runner.ui.prompts.image_to_prompt_window import ImageToPromptWindow
from tests.utils import close_window


class RecordingAppActions:
    def __init__(self):
        self.alerts = []
        self.toasts = []

    def alert(self, title, message, kind=None, master=None, **kwargs):
        self.alerts.append((title, message, kind))
        return True

    def toast(self, message, *args, **kwargs):
        self.toasts.append(message)

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


class StubService:
    """Stands in for ImageToPromptService, recording the window's state mid-call."""

    def __init__(self, window, error=None, positive="a cat", negative=""):
        self._window = window
        self._error = error
        self._positive = positive
        self._negative = negative
        self.seen_enabled = None
        self.seen_status = None
        self.calls = 0

    def generate(self, image_path, prompt_hint="", include_negative=False):
        self.calls += 1
        self.seen_enabled = self._window._generate_btn.isEnabled()
        self.seen_status = self._window._status.text()
        if self._error is not None:
            raise self._error
        return ImageToPromptResult(
            backend=ImageToPromptBackend.VLM,
            positive_prompt=self._positive,
            negative_prompt=self._negative,
        )


class InlineResponsiveness:
    """The port's contract without a thread: run it, return what it returned."""

    def __init__(self):
        self.calls = 0

    def run_off_thread(self, func):
        self.calls += 1
        return func()


@pytest.fixture
def window(qapp):
    actions = RecordingAppActions()
    win = ImageToPromptWindow(None, actions)
    win._test_actions = actions
    win._app = SimpleNamespace(responsiveness=InlineResponsiveness())
    win._image_path.setText("some/image.png")
    try:
        yield win
    finally:
        close_window(win)


def run_with(window, service):
    """Drive one generate against a stubbed service."""
    window._service_for_backend = lambda backend: service
    window._generate()


# ---------------------------------------------------------------------------
# While it runs
# ---------------------------------------------------------------------------

class TestWhileGenerating:
    def test_the_call_goes_through_the_responsiveness_port(self, window):
        """Off the GUI thread, so the window keeps painting through a load that
        can take tens of seconds."""
        run_with(window, StubService(window))
        assert window._app.responsiveness.calls == 1

    def test_the_button_is_disabled_during_the_call(self, window):
        """A second generate would load a second model."""
        service = StubService(window)
        run_with(window, service)
        assert service.seen_enabled is False

    def test_the_status_says_it_is_working(self, window):
        service = StubService(window)
        run_with(window, service)
        assert service.seen_status

    def test_the_status_names_the_backend(self, window):
        service = StubService(window)
        run_with(window, service)
        assert window._selected_backend().value in service.seen_status


# ---------------------------------------------------------------------------
# Afterwards
# ---------------------------------------------------------------------------

class TestAfterASuccess:
    def test_the_button_comes_back(self, window):
        run_with(window, StubService(window))
        assert window._generate_btn.isEnabled()

    def test_the_status_is_replaced(self, window):
        service = StubService(window)
        run_with(window, service)
        assert window._status.text() != service.seen_status

    def test_the_positive_reaches_the_box(self, window):
        run_with(window, StubService(window, positive="a cat, sunlit"))
        assert window._positive_box.toPlainText() == "a cat, sunlit"

    def test_no_alert_is_raised(self, window):
        run_with(window, StubService(window))
        assert window._test_actions.alerts == []


class TestAfterAFailure:
    def test_the_button_comes_back(self, window):
        """Re-enabled in a finally, or one failure leaves the window unusable."""
        run_with(window, StubService(window, error=RuntimeError("boom")))
        assert window._generate_btn.isEnabled()

    def test_the_error_reaches_the_user(self, window):
        """Raised on a worker thread it would unwind that thread and arrive
        here as a missing result, with nothing said."""
        run_with(window, StubService(window, error=RuntimeError("boom")))
        assert any("boom" in message for _t, message, _k in window._test_actions.alerts)

    def test_an_unconfigured_backend_is_a_warning_not_an_error(self, window):
        """NotImplementedError means the user has something to fix rather than
        something broken."""
        run_with(window, StubService(window, error=NotImplementedError("no model")))
        assert window._test_actions.alerts[0][2] == "warning"

    def test_the_status_stops_saying_it_is_working(self, window):
        """The alert is modal and gets dismissed; the label is what stays on
        screen."""
        service = StubService(window, error=RuntimeError("boom"))
        run_with(window, service)
        assert window._status.text() != service.seen_status

    def test_the_output_boxes_are_left_alone(self, window):
        window._positive_box.setPlainText("from a previous run")
        run_with(window, StubService(window, error=RuntimeError("boom")))
        assert window._positive_box.toPlainText() == "from a previous run"


# ---------------------------------------------------------------------------
# Without an application object
# ---------------------------------------------------------------------------

class TestWithNoResponsiveness:
    def test_the_generate_still_runs(self, window):
        """The port comes off the parent window, and the dialog is constructed
        with one that may not carry it."""
        window._app = None
        service = StubService(window)
        run_with(window, service)
        assert service.calls == 1

    def test_the_result_still_arrives(self, window):
        window._app = None
        run_with(window, StubService(window, positive="a cat, sunlit"))
        assert window._positive_box.toPlainText() == "a cat, sunlit"

    def test_an_error_still_reaches_the_user(self, window):
        window._app = None
        run_with(window, StubService(window, error=RuntimeError("boom")))
        assert window._test_actions.alerts


# ---------------------------------------------------------------------------
# Nothing to generate from
# ---------------------------------------------------------------------------

class TestWithNoImage:
    def test_it_says_so_and_does_not_call_a_backend(self, window):
        service = StubService(window)
        window._image_path.setText("")
        run_with(window, service)
        assert service.calls == 0
        assert window._test_actions.toasts
