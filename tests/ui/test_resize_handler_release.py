"""The frameless window's resize handler filters every event in the application
until it is released, so a closed window must release it."""

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QWidget

from lib.custom_title_bar import WindowResizeHandler


class CountingHandler(WindowResizeHandler):
    def __init__(self, window):
        self.seen = 0
        super().__init__(window)

    def eventFilter(self, obj, event):
        self.seen += 1
        return False


def test_a_released_handler_no_longer_sees_events(qapp):
    window = QWidget()
    target = QWidget()
    handler = CountingHandler(window)
    QApplication.sendEvent(target, QEvent(QEvent.Type.User))
    assert handler.seen > 0

    handler.release()
    seen = handler.seen
    QApplication.sendEvent(target, QEvent(QEvent.Type.User))
    assert handler.seen == seen

    handler.release()  # a second release is harmless
    window.deleteLater()
    target.deleteLater()


def test_closing_the_main_window_releases_it(app_window):
    app_window.close()
    assert app_window._resize_handler._released
