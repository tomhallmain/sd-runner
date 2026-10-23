"""The NSFW allowance follows the prompt mode shown when the user runs.

Blacklist validation reads the stored prompt mode. get_args checks the typed
tags first, so the mode has to be stored from the combo before that check, or
a switch to an NSFW mode is still validated as the previous mode.
"""

import pytest

from sd_runner.globals import BlacklistPromptMode, PromptMode
from sd_runner.prompts.blacklist import Blacklist, BlacklistItem


@pytest.fixture
def alerts(app_window, monkeypatch):
    shown = []
    monkeypatch.setattr(
        app_window.notification_ctrl, "alert",
        lambda title, message, kind="info", **kw: shown.append((title, message)),
    )
    return shown


def _choose_mode(app_window, mode):
    combo = app_window.sidebar_panel.prompt_mode_combo
    combo.blockSignals(True)
    combo.setCurrentText(mode.display())
    combo.blockSignals(False)


def _type_tags(app_window, text):
    app_window.sidebar_panel.positive_tags_box.setPlainText(text)


@pytest.fixture
def blocked_tag(app_config):
    app_config.blacklist_prevent_execution = True
    Blacklist.add_item(BlacklistItem("forbidden"))


def test_switching_to_nsfw_keeps_the_tag_when_allowed_in_nsfw(app_window, alerts, blocked_tag):
    Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
    app_window.runner_app_config.prompter_config.prompt_mode = PromptMode.SFW
    _choose_mode(app_window, PromptMode.NSFW)
    _type_tags(app_window, "forbidden, soft light")

    app_window.get_args()

    assert alerts == []
    assert app_window.sidebar_panel.positive_tags_box.toPlainText() == "forbidden, soft light"
    assert "forbidden" in app_window.runner_app_config.positive_tags


def test_switching_to_sfw_still_removes_the_tag(app_window, alerts, blocked_tag):
    Blacklist.blacklist_prompt_mode = BlacklistPromptMode.ALLOW_IN_NSFW
    app_window.runner_app_config.prompter_config.prompt_mode = PromptMode.NSFW
    _choose_mode(app_window, PromptMode.SFW)
    _type_tags(app_window, "forbidden, soft light")

    app_window.get_args()

    assert len(alerts) == 1
    assert app_window.sidebar_panel.positive_tags_box.toPlainText() == "soft light"
