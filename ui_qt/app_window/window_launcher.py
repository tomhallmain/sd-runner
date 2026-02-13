"""
WindowLauncher -- opens all secondary windows and dialogs.

A thin class where each method creates the appropriate dialog/window.
Extracted from: all open_*_window methods.

Ported windows import from ``ui_qt/`` (e.g. ``ui_qt.presets``).
Windows still awaiting port import from the original ``ui/``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ui_qt.auth.password_utils import require_password
from utils.globals import ProtectedActions
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("ui_qt.window_launcher")


class WindowLauncher:
    """
    Opens every secondary window / dialog.  Keeps the "which windows
    exist" knowledge in one place and makes window implementations
    easy to swap.
    """

    def __init__(self, app_window: AppWindow):
        self._app = app_window

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _handle_error(self, error: Exception, title: str = "Window Error") -> None:
        self._app.notification_ctrl.handle_error(str(error), title=title)

    def _open_window(self, window_class, *args, **kwargs):
        """Instantiate *window_class* with standard error handling."""
        try:
            return window_class(self._app, self._app.app_actions, *args, **kwargs)
        except Exception as e:
            self._handle_error(e, f"{window_class.__name__} Error")

    # ------------------------------------------------------------------
    # Blacklist
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def show_tag_blacklist(self) -> None:
        try:
            from ui_qt.prompts.blacklist_window import BlacklistWindow
            self._open_window(BlacklistWindow)
        except Exception as e:
            self._handle_error(e, "Blacklist Window Error")

    # ------------------------------------------------------------------
    # Presets / Schedules
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_PRESETS)
    def open_presets_window(self) -> None:
        try:
            from ui_qt.presets.presets_window import PresetsWindow
            self._open_window(PresetsWindow)
        except Exception as e:
            self._handle_error(e, "Presets Window Error")

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def open_preset_schedules_window(self) -> None:
        try:
            from ui_qt.presets.schedules_window import SchedulesWindow
            self._open_window(SchedulesWindow)
        except Exception as e:
            self._handle_error(e, "Schedules Window Error")

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def open_timed_schedules_window(self) -> None:
        try:
            from ui_qt.presets.timed_schedules_window import TimedSchedulesWindow
            self._open_window(TimedSchedulesWindow)
        except Exception as e:
            self._handle_error(e, "Timed Schedules Window Error")

    # ------------------------------------------------------------------
    # Concepts / Expansions / Prompt Config
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def open_concept_editor_window(self) -> None:
        try:
            from ui_qt.prompts.concept_editor_window import ConceptEditorWindow
            self._open_window(ConceptEditorWindow)
        except Exception as e:
            self._handle_error(e, "Concept Editor Window Error")

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def open_expansions_window(self) -> None:
        try:
            from ui_qt.prompts.expansions_window import ExpansionsWindow
            self._open_window(ExpansionsWindow)
        except Exception as e:
            self._handle_error(e, "Expansions Window Error")

    def open_prompt_config_window(self) -> None:
        try:
            from ui_qt.prompts.prompt_config_window import PromptConfigWindow
            PromptConfigWindow(
                self._app, self._app.app_actions, self._app.runner_app_config,
            )
        except Exception as e:
            self._handle_error(e, "Prompt Config Window Error")

    def open_frequent_tags_window(self) -> None:
        """Open the frequent prompt-tags browser.

        .. todo:: Not yet exposed -- no button or keybinding invokes this
           method.  Wire a UI trigger once the feature is ready, and ensure
           ``add_tags`` is included in ``AppWindow._build_app_actions``.
        """
        try:
            from ui_qt.prompts.frequent_prompt_tags_window import (
                FrequentPromptTagsWindow,
            )
            self._open_window(FrequentPromptTagsWindow)
        except Exception as e:
            self._handle_error(e, "Frequent Tags Window Error")

    # ------------------------------------------------------------------
    # Models / Adapters
    # ------------------------------------------------------------------
    def open_models_window(self) -> None:
        try:
            from ui_qt.models.models_window import ModelsWindow
            self._open_window(ModelsWindow)
        except Exception as e:
            self._handle_error(e, "Models Window Error")

    def open_lora_models_window(self) -> None:
        try:
            from ui_qt.models.models_window import ModelsWindow
            win = ModelsWindow(self._app, self._app.app_actions)
            win.select_tab(1)
        except Exception as e:
            self._handle_error(e, "LoRA Models Window Error")

    def open_controlnet_adapters_window(self) -> None:
        try:
            from ui_qt.models.recent_adapters_window import RecentAdaptersWindow
            win = RecentAdaptersWindow(self._app, self._app.app_actions)
            win.select_tab(0)
        except Exception as e:
            self._handle_error(e, "ControlNet Adapters Window Error")

    def open_ipadapter_adapters_window(self) -> None:
        try:
            from ui_qt.models.recent_adapters_window import RecentAdaptersWindow
            win = RecentAdaptersWindow(self._app, self._app.app_actions)
            win.select_tab(1)
        except Exception as e:
            self._handle_error(e, "IPAdapter Adapters Window Error")

    # ------------------------------------------------------------------
    # Auth / Admin
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.ACCESS_ADMIN)
    def open_password_admin_window(self) -> None:
        try:
            from ui_qt.auth.password_admin_window import PasswordAdminWindow
            PasswordAdminWindow(self._app, self._app.app_actions)
        except Exception as e:
            self._handle_error(e, "Password Admin Window Error")
