"""Collapsing the negative tags box, the shown concept set, and the order of
expansion and the blacklist check."""

import pytest
from PySide6.QtCore import Qt

from sd_runner.config import config
from sd_runner.persistence.app_info_cache import app_info_cache
from sd_runner.ui.app_window.sidebar_panel import SidebarPanel

KEY = SidebarPanel.NEGATIVE_TAGS_COLLAPSED_KEY


@pytest.fixture
def collapsed_window(qapp, request):
    """An AppWindow built after a previous session saved the box collapsed."""
    app_info_cache.set(KEY, True)
    return request.getfixturevalue("app_window")


class TestNegativeTagsCollapse:
    def test_expanded_when_nothing_is_saved(self, app_window):
        sp = app_window.sidebar_panel
        assert sp.negative_tags_toggle.isChecked()
        assert not sp.negative_tags_box.isHidden()
        assert sp.negative_tags_toggle.arrowType() == Qt.ArrowType.DownArrow

    def test_collapsing_hides_the_box_and_saves_the_setting(self, app_window):
        sp = app_window.sidebar_panel
        sp.negative_tags_toggle.click()
        assert sp.negative_tags_box.isHidden()
        assert sp.negative_tags_toggle.arrowType() == Qt.ArrowType.RightArrow
        assert app_info_cache.get(KEY) is True

    def test_expanding_again_shows_the_box_and_saves_the_setting(self, app_window):
        sp = app_window.sidebar_panel
        sp.negative_tags_toggle.click()
        sp.negative_tags_toggle.click()
        assert not sp.negative_tags_box.isHidden()
        assert app_info_cache.get(KEY) is False

    def test_a_saved_collapse_is_restored_at_startup(self, collapsed_window):
        sp = collapsed_window.sidebar_panel
        assert not sp.negative_tags_toggle.isChecked()
        assert sp.negative_tags_box.isHidden()
        assert sp.negative_tags_toggle.arrowType() == Qt.ArrowType.RightArrow

    def test_the_setting_is_not_part_of_the_run_config(self, app_window):
        before = app_window.runner_app_config.to_dict()
        app_window.sidebar_panel.negative_tags_toggle.click()
        after = app_window.runner_app_config.to_dict()
        assert before == after

    def test_collapsed_negative_tags_still_reach_the_config(self, app_window):
        sp = app_window.sidebar_panel
        sp.negative_tags_toggle.click()
        sp.negative_tags_box.setPlainText("blurry")
        sp.set_negative_tags()
        assert app_window.runner_app_config.negative_tags == "blurry"


@pytest.fixture
def konzepte(app_window, monkeypatch):
    """A second concept set in the sidebar's combo."""
    monkeypatch.setitem(config.concepts_dirs, "Konzepte", "/app/Konzepte")
    app_window.sidebar_panel.concepts_dir_combo.addItem("Konzepte")
    return app_window


class TestConceptsDirCombo:
    def test_shows_the_stored_set(self, konzepte):
        konzepte.runner_app_config.prompter_config.concepts_dir = "/app/Konzepte"
        konzepte.sidebar_panel.set_concepts_dir_from_config()
        assert konzepte.sidebar_panel.concepts_dir_combo.currentText() == "Konzepte"

    def test_a_config_from_history_updates_the_combo(self, konzepte):
        konzepte.runner_app_config.prompter_config.concepts_dir = "/app/Konzepte"
        konzepte._set_widgets_from_config()
        assert konzepte.sidebar_panel.concepts_dir_combo.currentText() == "Konzepte"

    def test_a_path_from_another_install_becomes_the_local_one(self, konzepte):
        prompter_config = konzepte.runner_app_config.prompter_config
        prompter_config.concepts_dir = "/other/machine/Konzepte"
        konzepte.sidebar_panel.set_concepts_dir_from_config()
        assert prompter_config.concepts_dir == "/app/Konzepte"

    def test_an_unconfigured_set_falls_back_to_the_default(self, konzepte):
        prompter_config = konzepte.runner_app_config.prompter_config
        prompter_config.concepts_dir = "/gone/Sammlung"
        konzepte.sidebar_panel.set_concepts_dir_from_config()
        assert konzepte.sidebar_panel.concepts_dir_combo.currentText() == config.default_concepts_dir
        assert prompter_config.concepts_dir == config.concepts_dirs[config.default_concepts_dir]


class TestPositiveTagExpansion:
    @pytest.fixture
    def validated(self, app_window, monkeypatch):
        seen = []
        monkeypatch.setitem(config.wildcards, "wild", "expanded text")

        def validate(text):
            seen.append(text)
            return True

        monkeypatch.setattr(app_window.run_ctrl, "validate_blacklist", validate)
        return seen

    def test_the_check_sees_what_a_variable_stands_for(self, app_window, validated):
        app_window.sidebar_panel.positive_tags_box.setPlainText("$wild")
        app_window.sidebar_panel.set_positive_tags()
        assert validated == ["expanded text"]
        assert app_window.sidebar_panel.positive_tags_box.toPlainText() == "expanded text"

    def test_a_failed_check_leaves_the_box_as_typed(self, app_window, validated, monkeypatch):
        monkeypatch.setattr(app_window.run_ctrl, "validate_blacklist", lambda text: False)
        app_window.sidebar_panel.positive_tags_box.setPlainText("$wild")
        app_window.sidebar_panel.set_positive_tags()
        assert app_window.sidebar_panel.positive_tags_box.toPlainText() == "$wild"

    def test_a_deferred_variable_stays_in_the_box(self, app_window, validated):
        app_window.sidebar_panel.positive_tags_box.setPlainText("$$wild")
        app_window.sidebar_panel.set_positive_tags()
        assert app_window.sidebar_panel.positive_tags_box.toPlainText() == "$$wild"
