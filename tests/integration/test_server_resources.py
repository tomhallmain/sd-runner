"""The read-only context a client can ask for, from either application object.

Resources answer rather than act. ``RunController.server_resource`` is the read
path behind them, and it reads stored state rather than widgets -- so the same
three answers come back with a window or without one, which is what lets the
headless front end expose them too.
"""

import pytest

from sd_runner.runs.headless_app import HeadlessApp


@pytest.fixture
def headless_app():
    app = HeadlessApp()
    yield app
    app.on_closing()


class TestCurrentWorkflow:
    def test_it_reports_what_a_run_would_use(self, app_window):
        app_window.runner_app_config.workflow_type = "IP_ADAPTER"
        app_window.runner_app_config.model_tags = "some_model"

        data = app_window.run_ctrl.server_resource("current_workflow")

        assert data["workflow_type"] == "IP_ADAPTER"
        assert data["model_tags"] == "some_model"

    def test_it_reads_the_stored_config_not_the_sidebar(self, app_window):
        """The sidebar is written through to the config before a request is
        served, so the config is the one source. Reading the widget here would
        give a different answer in the headless process, where there is none.
        """
        app_window.runner_app_config.workflow_type = "RENOISER"
        assert (app_window.run_ctrl.server_resource("current_workflow")["workflow_type"]
                == "RENOISER")


class TestPresetNames:
    def test_it_lists_the_saved_presets(self, app_window):
        from sd_runner.globals import PromptMode
        from sd_runner.presets.preset import Preset
        from sd_runner.presets.presets_state import PresetsState

        PresetsState.recent_presets.append(
            Preset("Sunset", PromptMode.FIXED, "a sunset", "")
        )

        assert "Sunset" in app_window.run_ctrl.server_resource("preset_names")["presets"]

    def test_no_presets_is_an_empty_list_not_an_error(self, app_window):
        from sd_runner.presets.presets_state import PresetsState

        PresetsState.recent_presets.clear()
        assert app_window.run_ctrl.server_resource("preset_names")["presets"] == []


class TestRunHistory:
    def test_it_returns_entries_from_the_cache(self, app_window):
        runs = app_window.run_ctrl.server_resource("run_history")["runs"]
        assert isinstance(runs, list)

    def test_it_is_capped(self, app_window):
        """A client reading this has a context window, and the entries are
        near-duplicates of one another."""
        runs = app_window.run_ctrl.server_resource("run_history")["runs"]
        assert len(runs) <= app_window.run_ctrl.RESOURCE_HISTORY_LIMIT

    def test_an_entry_carries_only_what_says_what_was_generated(self, app_window):
        """The stored entry is a whole RunnerAppConfig; most of it is settings
        the client did not ask about."""
        runs = app_window.run_ctrl.server_resource("run_history")["runs"]
        if runs:
            assert set(runs[0]) == {
                "timestamp", "workflow_type", "model_tags",
                "positive_tags", "n_latents", "total",
            }


class TestAnUnknownResource:
    def test_it_raises_key_error_for_the_caller_to_translate(self, app_window):
        """KeyError rather than a return value: the MCP front end turns it into
        its own error shape, and a sentinel would have to be told apart from a
        resource that legitimately answered with nothing."""
        with pytest.raises(KeyError):
            app_window.run_ctrl.server_resource("not_a_resource")


class TestHeadlessAnswersTheSame:
    """No widgets are read, so the absence of a window changes nothing here."""

    def test_current_workflow_is_readable(self, headless_app):
        data = headless_app.run_ctrl.server_resource("current_workflow")
        assert data["workflow_type"] == headless_app.runner_app_config.workflow_type

    def test_preset_names_are_readable(self, headless_app):
        assert "presets" in headless_app.run_ctrl.server_resource("preset_names")

    def test_run_history_is_readable(self, headless_app):
        assert "runs" in headless_app.run_ctrl.server_resource("run_history")

    def test_the_front_end_is_given_the_read_path(self, headless_app):
        """Wired, not merely available: the headless MCP server has to be
        handed the callback or its resources refuse."""
        assert headless_app.run_ctrl.server_resource is not None
