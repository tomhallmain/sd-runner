"""Serving requests with no window.

The pieces ``HeadlessApp`` substitutes for the ones that only exist to reach a
window, and the boundary that decides what a process without one will serve.
Constructing the whole application is exercised in the integration suite; these
are the parts that need no cache on disk.
"""

import os
import subprocess
import sys
from types import SimpleNamespace

import pytest

from extensions.sd_runner_server import CommandType
from sd_runner.headless_app import DirectBridge, LoggingNotifications
from ui_qt.app_window.run_controller import RunController


def make_headless_controller(**app_fields) -> RunController:
    """A RunController over an application object with no sidebar.

    The absence is the whole configuration: nothing tells the controller it is
    headless, so what it refuses has to follow from finding no widgets. The
    notification sink is the real one, since where an alert goes is part of
    what these assert.
    """
    fields = {"sidebar_panel": None, "notification_ctrl": LoggingNotifications()}
    fields.update(app_fields)
    return RunController(app_window=SimpleNamespace(**fields))


# ---------------------------------------------------------------------------
# The thread bridge, with no thread to cross
# ---------------------------------------------------------------------------

class TestDirectBridge:
    def test_invoke_calls_through(self):
        assert DirectBridge().invoke(lambda a, b: a + b, 1, b=2) == 3

    def test_wrap_returns_the_same_callable(self):
        def f():
            return None
        assert DirectBridge().wrap(f) is f

    def test_invoke_propagates_the_error(self):
        """The Qt bridge re-raises what the marshalled call raised; so does this."""
        def boom():
            raise ValueError("no")
        with pytest.raises(ValueError):
            DirectBridge().invoke(boom)


# ---------------------------------------------------------------------------
# Alerts, where there is nobody to answer them
# ---------------------------------------------------------------------------

class TestLoggingNotifications:
    @pytest.mark.parametrize("kind", ["askokcancel", "askyesno", "askyesnocancel"])
    def test_a_question_is_declined(self, kind):
        """Anything modal is a refusal: an unanswered question is not a yes.

        The interactive path asks before a long run, so treating this as
        confirmed would start exactly the runs the confirmation exists to stop.
        """
        assert LoggingNotifications().alert("t", "m", kind=kind) is False

    @pytest.mark.parametrize("kind", ["info", "warning", "error"])
    def test_a_statement_is_not_declined(self, kind):
        assert LoggingNotifications().alert("t", "m", kind=kind) is True

    def test_the_other_sinks_do_not_raise(self):
        sink = LoggingNotifications()
        sink.toast("hello")
        sink.title_notify("hello")
        sink.handle_error("bad")
        sink.set_label_state("x")


# ---------------------------------------------------------------------------
# What a process with no window will not serve
# ---------------------------------------------------------------------------

class TestContextualCommandsAreRefused:
    def test_last_settings_is_refused(self):
        """"Reuse what is currently set" has no answer where nothing is set."""
        ctrl = make_headless_controller()
        resp = ctrl.server_run_callback(CommandType.LAST_SETTINGS, {})
        assert resp["error"] == "no user interface"

    def test_revert_to_simple_gen_is_refused(self):
        ctrl = make_headless_controller()
        assert ctrl.server_revert_to_simple_gen()["error"] == "no user interface"

    def test_a_preset_schedule_is_never_diverted_to(self):
        """The widget read behind this would otherwise be reached with no widgets."""
        ctrl = make_headless_controller(job_queue_preset_schedules=None)
        assert ctrl._divert_to_preset_schedule(None, {"image": "a.png"}) is False


class TestBlacklistIsEnforceableWithoutWidgets:
    """The gate every prompt reaching a backend passes, including a served one.

    It took the prompt mode off the sidebar combo, which made it unanswerable
    with no window -- and it is not a check that may be skipped there.
    """

    def _controller(self, prompt_mode):
        from tests.utils import make_prompter_config
        from utils.runner_app_config import RunnerAppConfig

        cfg = RunnerAppConfig()
        cfg.prompter_config = make_prompter_config(prompt_mode)
        return make_headless_controller(runner_app_config=cfg)

    def test_a_clean_prompt_passes(self, monkeypatch):
        from utils.config import config
        from utils.globals import PromptMode

        monkeypatch.setattr(config, "blacklist_prevent_execution", True)
        ctrl = self._controller(PromptMode.SFW)
        assert ctrl.validate_blacklist("a calm lake at sunrise") is True

    def test_a_blacklisted_prompt_is_refused(self, monkeypatch):
        from sd_runner.blacklist import Blacklist
        from utils.config import config
        from utils.globals import BlacklistMode, PromptMode

        monkeypatch.setattr(config, "blacklist_prevent_execution", True)
        Blacklist.set_blacklist_mode(BlacklistMode.REMOVE_ENTIRE_TAG)
        Blacklist.add_to_blacklist("forbidden")
        ctrl = self._controller(PromptMode.SFW)
        assert ctrl.validate_blacklist("a forbidden thing") is False


# ---------------------------------------------------------------------------
# The property the whole design rests on
# ---------------------------------------------------------------------------

class TestImportsNoQt:
    def test_the_headless_app_imports_without_pyside(self):
        """A headless box may have no PySide6 at all, so importing must not need it.

        Run in a subprocess with the toolkit blocked, because this one has
        almost certainly imported it already for the UI tests. Failing here
        means something on the run path grew a module-level Qt import: the fix
        is to move that import inside the method that needs it, not to relax
        this.
        """
        program = (
            "import sys\n"
            "class Blocker:\n"
            "    def find_module(self, name, path=None):\n"
            "        if name == 'PySide6' or name.startswith('PySide6.'):\n"
            "            raise ImportError('PySide6 is blocked for this test')\n"
            "        return None\n"
            "    def find_spec(self, name, path=None, target=None):\n"
            "        return self.find_module(name, path)\n"
            "sys.meta_path.insert(0, Blocker())\n"
            "import app_headless\n"
            "from sd_runner.headless_app import HeadlessApp\n"
            # Constructed, not just imported: the controllers, the cache load
            # and the action wiring are where a Qt import would actually be
            # reached, and AppActions refuses to build with an action missing.
            "app = HeadlessApp()\n"
            "assert not hasattr(app, 'sidebar_panel')\n"
            "assert not [m for m in sys.modules if m.startswith('PySide6')]\n"
            "print('ok')\n"
        )
        repo_root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))))
        result = subprocess.run(
            [sys.executable, "-c", program],
            cwd=repo_root, env=dict(os.environ),
            capture_output=True, text=True, timeout=120,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout
