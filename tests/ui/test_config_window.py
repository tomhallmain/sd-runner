"""The settings dialog the sidebar Config button opens.

``WindowLauncher`` constructs the window and leaves it to show itself. A
dialog that is only constructed stays hidden, and the click logs nothing,
so visibility is part of opening.
"""

from sd_runner.globals import SoftwareType
from sd_runner.ui.config_window import ConfigWindow
from tests.utils import close_window


def test_opening_the_config_window_shows_it(qapp):
    window = ConfigWindow()
    try:
        assert window.isVisible()
        assert ConfigWindow._instance is window
        assert window._le_models_dir.minimumWidth() >= 720
        assert window.width() >= 1100
    finally:
        close_window(window)
        assert ConfigWindow._instance is None


def test_the_config_window_edits_every_local_start_command(qapp):
    window = ConfigWindow()
    try:
        names = [software.name for software in SoftwareType.local_types()]
        assert list(window._launch_entries) == names
        for entry in window._launch_entries.values():
            assert entry.minimumWidth() >= 720
            assert entry.text() == ""
    finally:
        close_window(window)
