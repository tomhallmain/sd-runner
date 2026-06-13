"""UI tests for PromptGeneratorWindow — on-demand prompt preview dialog."""
import pytest
from PySide6.QtWidgets import QApplication

from ui_qt.prompts.prompt_generator_window import PromptGeneratorWindow
from utils.translations import I18N
_ = I18N._


class TestPromptGeneratorWindowOpens:
    def test_opens_and_shows_no_prompt_status(self, app_window):
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert win._status.text() != ""
        finally:
            win.close()

    def test_text_boxes_empty_before_generation(self, app_window):
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            assert win._positive_box.toPlainText() == ""
            assert win._negative_box.toPlainText() == ""
        finally:
            win.close()


class TestPromptGeneratorWindowGuards:
    """Actions that should show a toast rather than crash when nothing is generated yet."""

    def _capture_toasts(self, app_window):
        toasts = []
        app_window.app_actions._actions["toast"] = lambda msg, **kw: toasts.append(msg)
        return toasts

    def test_copy_positive_before_generate_shows_toast(self, app_window):
        toasts = self._capture_toasts(app_window)
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._copy_positive_btn.click()
            QApplication.processEvents()
            assert len(toasts) == 1
        finally:
            win.close()

    def test_copy_negative_before_generate_shows_toast(self, app_window):
        toasts = self._capture_toasts(app_window)
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._copy_negative_btn.click()
            QApplication.processEvents()
            assert len(toasts) == 1
        finally:
            win.close()

    def test_save_before_generate_shows_toast(self, app_window):
        toasts = self._capture_toasts(app_window)
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._save_history_btn.click()
            QApplication.processEvents()
            assert len(toasts) == 1
        finally:
            win.close()

    def test_generate_once_produces_nonempty_positive(self, app_window):
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._generate_btn.click()
            QApplication.processEvents()
            assert win._positive_box.toPlainText().strip() != ""
        finally:
            win.close()

    def test_generate_once_updates_status(self, app_window):
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            initial_status = win._status.text()
            win._generate_btn.click()
            QApplication.processEvents()
            assert win._status.text() != initial_status
        finally:
            win.close()

    def test_copy_positive_after_generate_shows_toast(self, app_window):
        toasts = self._capture_toasts(app_window)
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._generate_btn.click()
            QApplication.processEvents()
            toasts.clear()
            win._copy_positive_btn.click()
            QApplication.processEvents()
            assert toasts[0] == _("Copied to clipboard")
        finally:
            win.close()

    def test_save_after_generate_shows_toast(self, app_window):
        toasts = self._capture_toasts(app_window)
        win = PromptGeneratorWindow(parent=app_window, app_actions=app_window.app_actions)
        try:
            win._generate_btn.click()
            QApplication.processEvents()
            toasts.clear()
            win._save_history_btn.click()
            QApplication.processEvents()
            assert len(toasts) == 1
        finally:
            win.close()
