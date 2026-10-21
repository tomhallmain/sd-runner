"""The settings dialog the sidebar Config button opens.

``WindowLauncher`` constructs the window and leaves it to show itself. A
dialog that is only constructed stays hidden, and the click logs nothing,
so visibility is part of opening.
"""

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
