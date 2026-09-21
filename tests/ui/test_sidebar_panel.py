"""Collapsing the negative tags box, and remembering it across sessions."""

import pytest
from PySide6.QtCore import Qt

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
