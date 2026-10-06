"""How ``WindowLauncher`` finds or opens a secondary window.

Secondary windows are singletons: an open one is focused rather than
duplicated, a stale ``_instance`` (closed, or hidden by Escape) is replaced, and
an error while opening becomes an alert titled for that window. Each public
method is pinned to the window, tab, title and password gate it is meant to
use, because their bodies are one-line calls that differ only in those.
"""

from types import SimpleNamespace

import pytest

from lib.translations import I18N
from sd_runner.globals import ProtectedActions
from sd_runner.ui.app_window.window_launcher import WindowLauncher
from tests.utils import install_password_bypass

_ = I18N._


class RecordingNotifications:
    def __init__(self):
        self.errors = []

    def handle_error(self, error_text, title=None, kind="error"):
        self.errors.append((error_text, title))


def make_window_class(fail=False):
    """A fresh stand-in window class, with its own ``_instance`` slot."""

    class FakeWindow:
        _instance = None
        constructed = []

        def __init__(self, parent, app_actions):
            if fail:
                raise RuntimeError("cannot build")
            self.args = (parent, app_actions)
            self.visible = True
            self.activated = False
            self.tabs = []
            FakeWindow._instance = self
            FakeWindow.constructed.append(self)

        def isVisible(self):
            return self.visible

        def isMinimized(self):
            return False

        def raise_(self):
            pass

        def activateWindow(self):
            self.activated = True

        def select_tab(self, index):
            self.tabs.append(index)

    return FakeWindow


@pytest.fixture
def app():
    return SimpleNamespace(app_actions=object(), notification_ctrl=RecordingNotifications())


@pytest.fixture
def launcher(app):
    return WindowLauncher(app)


class TestFocusOrOpen:
    def test_constructs_when_none_is_open(self, launcher, app):
        window_class = make_window_class()
        launcher._focus_or_open(lambda: window_class, "title")
        [window] = window_class.constructed
        assert window.args == (app, app.app_actions)
        assert window.tabs == []

    def test_focuses_the_open_window_instead_of_constructing(self, launcher):
        window_class = make_window_class()
        launcher._focus_or_open(lambda: window_class, "title")
        launcher._focus_or_open(lambda: window_class, "title")
        [window] = window_class.constructed
        assert window.activated

    def test_replaces_a_hidden_window(self, launcher):
        window_class = make_window_class()
        launcher._focus_or_open(lambda: window_class, "title")
        stale = window_class._instance
        stale.visible = False

        launcher._focus_or_open(lambda: window_class, "title")

        assert len(window_class.constructed) == 2
        assert window_class._instance is not stale

    def test_selects_the_tab_on_a_new_window(self, launcher):
        window_class = make_window_class()
        launcher._focus_or_open(lambda: window_class, "title", tab=2)
        assert window_class._instance.tabs == [2]

    def test_selects_the_tab_on_the_open_window(self, launcher):
        window_class = make_window_class()
        launcher._focus_or_open(lambda: window_class, "title", tab=0)
        launcher._focus_or_open(lambda: window_class, "title", tab=1)
        [window] = window_class.constructed
        assert window.tabs == [0, 1]

    def test_construction_error_is_reported_under_the_given_title(self, launcher, app):
        window_class = make_window_class(fail=True)
        launcher._focus_or_open(lambda: window_class, "Some Title")
        assert app.notification_ctrl.errors == [("cannot build", "Some Title")]

    def test_import_error_is_reported_under_the_given_title(self, launcher, app):
        def load():
            raise ImportError("no such module")

        launcher._focus_or_open(load, "Some Title")
        assert app.notification_ctrl.errors == [("no such module", "Some Title")]


# method, window module, window class, tab, untranslated title, password gate
ROUTES = [
    ("show_tag_blacklist", "sd_runner.ui.prompts.blacklist_window", "BlacklistWindow",
     None, "Blacklist Window Error", ProtectedActions.EDIT_BLACKLIST),
    ("open_presets_window", "sd_runner.ui.presets.presets_window", "PresetsWindow",
     None, "Presets Window Error", ProtectedActions.EDIT_PRESETS),
    ("open_preset_schedules_window", "sd_runner.ui.presets.schedules_window", "SchedulesWindow",
     None, "Schedules Window Error", ProtectedActions.EDIT_SCHEDULES),
    ("open_timed_schedules_window", "sd_runner.ui.presets.timed_schedules_window", "TimedSchedulesWindow",
     None, "Timed Schedules Window Error", ProtectedActions.EDIT_TIMED_SCHEDULES),
    ("open_concept_editor_window", "sd_runner.ui.prompts.concept_editor_window", "ConceptEditorWindow",
     None, "Concept Editor Window Error", ProtectedActions.EDIT_CONCEPTS),
    ("open_expansions_window", "sd_runner.ui.prompts.expansions_window", "ExpansionsWindow",
     None, "Expansions Window Error", ProtectedActions.EDIT_EXPANSIONS),
    ("open_prompt_generator_window", "sd_runner.ui.prompts.prompt_generator_window", "PromptGeneratorWindow",
     None, "Prompt Generator Window Error", None),
    ("open_frequent_tags_window", "sd_runner.ui.prompts.frequent_prompt_tags_window", "FrequentPromptTagsWindow",
     None, "Frequent Tags Window Error", None),
    ("open_image_to_prompt_window", "sd_runner.ui.prompts.image_to_prompt_window", "ImageToPromptWindow",
     None, "Image to Prompt Window Error", None),
    ("open_config_window", "sd_runner.ui.config_window", "ConfigWindow",
     None, "Config Window Error", None),
    ("open_models_window", "sd_runner.ui.models.models_window", "ModelsWindow",
     None, "Models Window Error", None),
    ("open_model_presets_window", "sd_runner.ui.models.model_presets_window", "ModelPresetsWindow",
     None, "Model Presets Window Error", None),
    ("open_lora_models_window", "sd_runner.ui.models.models_window", "ModelsWindow",
     1, "LoRA Models Window Error", None),
    ("open_controlnet_adapters_window", "sd_runner.ui.models.recent_adapters_window", "RecentAdaptersWindow",
     0, "ControlNet Adapters Window Error", None),
    ("open_ipadapter_adapters_window", "sd_runner.ui.models.recent_adapters_window", "RecentAdaptersWindow",
     1, "IPAdapter Adapters Window Error", None),
    ("open_source_prompt_adapters_window", "sd_runner.ui.models.recent_adapters_window", "RecentAdaptersWindow",
     2, "Source Prompt Adapters Window Error", None),
    ("open_runs_window", "sd_runner.ui.runs.runs_window", "RunsWindow",
     None, "Runs Window Error", None),
]


@pytest.mark.parametrize(
    "method, module, class_name, tab, title, gate", ROUTES, ids=[r[0] for r in ROUTES],
)
def test_public_method_routes_to_its_window(launcher, monkeypatch, method, module, class_name, tab, title, gate):
    crossings = install_password_bypass(monkeypatch)
    calls = []
    monkeypatch.setattr(
        launcher, "_focus_or_open",
        lambda load, error_title, tab=None: calls.append((load(), error_title, tab)),
    )

    getattr(launcher, method)()

    [(window_class, error_title, called_tab)] = calls
    assert (window_class.__module__, window_class.__name__) == (module, class_name)
    assert error_title == _(title)
    assert called_tab == tab
    assert [actions for actions, _granted in crossings] == ([[gate]] if gate else [])


GATED = [r[0] for r in ROUTES if r[5] is not None] + ["open_password_admin_window"]


@pytest.mark.parametrize("method", GATED)
def test_refused_password_opens_nothing(launcher, app, monkeypatch, method):
    install_password_bypass(monkeypatch, granted=False)
    calls = []
    monkeypatch.setattr(launcher, "_focus_or_open", lambda *a, **k: calls.append(a))
    import sd_runner.ui.app_window.window_launcher as window_launcher

    def must_not_run(*args, **kwargs):
        raise AssertionError("reached past the password gate")

    monkeypatch.setattr(window_launcher, "try_focus_existing_window", must_not_run)

    getattr(launcher, method)()

    # The launcher reports exceptions rather than raising them, so a reached
    # must_not_run shows up as an error here.
    assert calls == []
    assert app.notification_ctrl.errors == []


# The two windows that keep their singleton somewhere other than ``_instance``
# are opened by hand; only their error path is shared with the rest.

def test_prompt_config_error_is_reported_under_its_title(launcher, app, monkeypatch):
    from sd_runner.ui.prompts.prompt_config_window import PromptConfigWindow

    def broken():
        raise RuntimeError("cannot read")

    monkeypatch.setattr(PromptConfigWindow, "get_prompt_config_window_instance", staticmethod(broken))

    launcher.open_prompt_config_window()

    assert app.notification_ctrl.errors == [("cannot read", _("Prompt Config Window Error"))]


def test_password_admin_error_is_reported_under_its_title(launcher, app, monkeypatch):
    import sd_runner.ui.app_window.window_launcher as window_launcher
    from sd_runner.ui.auth.password_admin_window import PasswordAdminWindow

    crossings = install_password_bypass(monkeypatch)
    monkeypatch.setattr(PasswordAdminWindow, "top_level", object())

    def broken(window):
        raise RuntimeError("cannot focus")

    monkeypatch.setattr(window_launcher, "try_focus_existing_window", broken)

    launcher.open_password_admin_window()

    assert app.notification_ctrl.errors == [("cannot focus", _("Password Admin Window Error"))]
    assert [actions for actions, _granted in crossings] == [[ProtectedActions.ACCESS_ADMIN]]
