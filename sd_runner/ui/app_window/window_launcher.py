"""
WindowLauncher -- opens all secondary windows and dialogs.

Each method creates the appropriate secondary window or dialog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sd_runner.ui.auth.password_utils import require_password
from sd_runner.ui.window_focus import try_focus_existing_window
from utils.globals import ProtectedActions
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from sd_runner.ui.app_window.app_window import AppWindow

_ = I18N._
logger = get_logger("ui.window_launcher")


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
            from sd_runner.ui.prompts.blacklist_window import BlacklistWindow
            existing = BlacklistWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                BlacklistWindow._instance = None
            self._open_window(BlacklistWindow)
        except Exception as e:
            self._handle_error(e, "Blacklist Window Error")

    # ------------------------------------------------------------------
    # Presets / Schedules
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_PRESETS)
    def open_presets_window(self) -> None:
        try:
            from sd_runner.ui.presets.presets_window import PresetsWindow
            existing = PresetsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                PresetsWindow._instance = None
            self._open_window(PresetsWindow)
        except Exception as e:
            self._handle_error(e, "Presets Window Error")

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def open_preset_schedules_window(self) -> None:
        try:
            from sd_runner.ui.presets.schedules_window import SchedulesWindow
            existing = SchedulesWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                SchedulesWindow._instance = None
            self._open_window(SchedulesWindow)
        except Exception as e:
            self._handle_error(e, "Schedules Window Error")

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def open_timed_schedules_window(self) -> None:
        try:
            from sd_runner.ui.presets.timed_schedules_window import TimedSchedulesWindow
            existing = TimedSchedulesWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                TimedSchedulesWindow._instance = None
            self._open_window(TimedSchedulesWindow)
        except Exception as e:
            self._handle_error(e, "Timed Schedules Window Error")

    # ------------------------------------------------------------------
    # Concepts / Expansions / Prompt Config
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def open_concept_editor_window(self) -> None:
        try:
            from sd_runner.ui.prompts.concept_editor_window import ConceptEditorWindow
            existing = ConceptEditorWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ConceptEditorWindow._instance = None
            self._open_window(ConceptEditorWindow)
        except Exception as e:
            self._handle_error(e, "Concept Editor Window Error")

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def open_expansions_window(self) -> None:
        try:
            from sd_runner.ui.prompts.expansions_window import ExpansionsWindow
            existing = ExpansionsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ExpansionsWindow._instance = None
            self._open_window(ExpansionsWindow)
        except Exception as e:
            self._handle_error(e, "Expansions Window Error")

    def open_prompt_config_window(self) -> None:
        try:
            from sd_runner.ui.prompts.prompt_config_window import PromptConfigWindow

            existing = PromptConfigWindow.get_prompt_config_window_instance()
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                PromptConfigWindow.set_prompt_config_window_instance(None)
            PromptConfigWindow(
                self._app, self._app.app_actions, self._app.runner_app_config,
            )
        except Exception as e:
            self._handle_error(e, "Prompt Config Window Error")

    def open_prompt_generator_window(self) -> None:
        try:
            from sd_runner.ui.prompts.prompt_generator_window import PromptGeneratorWindow
            existing = PromptGeneratorWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                PromptGeneratorWindow._instance = None
            self._open_window(PromptGeneratorWindow)
        except Exception as e:
            self._handle_error(e, "Prompt Generator Window Error")

    def open_frequent_tags_window(self) -> None:
        """Open the frequent prompt-tags browser.

        .. todo:: Not yet exposed -- no button or keybinding invokes this
           method.  Wire a UI trigger once the feature is ready, and ensure
           ``add_tags`` is included in ``AppWindow._build_app_actions``.
        """
        try:
            from sd_runner.ui.prompts.frequent_prompt_tags_window import (
                FrequentPromptTagsWindow,
            )
            existing = FrequentPromptTagsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                FrequentPromptTagsWindow._instance = None
            self._open_window(FrequentPromptTagsWindow)
        except Exception as e:
            self._handle_error(e, "Frequent Tags Window Error")

    def open_image_to_prompt_window(self) -> None:
        try:
            from sd_runner.ui.prompts.image_to_prompt_window import ImageToPromptWindow
            existing = ImageToPromptWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ImageToPromptWindow._instance = None
            self._open_window(ImageToPromptWindow)
        except Exception as e:
            self._handle_error(e, "Image to Prompt Window Error")

    def open_config_window(self) -> None:
        try:
            from sd_runner.ui.config_window import ConfigWindow
            existing = ConfigWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ConfigWindow._instance = None
            self._open_window(ConfigWindow)
        except Exception as e:
            self._handle_error(e, "Config Window Error")

    # ------------------------------------------------------------------
    # Models / Adapters
    # ------------------------------------------------------------------
    def open_models_window(self) -> None:
        try:
            from sd_runner.ui.models.models_window import ModelsWindow
            existing = ModelsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ModelsWindow._instance = None
            self._open_window(ModelsWindow)
        except Exception as e:
            self._handle_error(e, "Models Window Error")

    def open_model_presets_window(self) -> None:
        try:
            from sd_runner.ui.models.model_presets_window import ModelPresetsWindow
            existing = ModelPresetsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                ModelPresetsWindow._instance = None
            self._open_window(ModelPresetsWindow)
        except Exception as e:
            self._handle_error(e, "Model Presets Window Error")

    def open_lora_models_window(self) -> None:
        try:
            from sd_runner.ui.models.models_window import ModelsWindow
            existing = ModelsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    existing.select_tab(1)
                    return
                ModelsWindow._instance = None
            win = ModelsWindow(self._app, self._app.app_actions)
            win.select_tab(1)
        except Exception as e:
            self._handle_error(e, "LoRA Models Window Error")

    def open_controlnet_adapters_window(self) -> None:
        try:
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            existing = RecentAdaptersWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    existing.select_tab(0)
                    return
                RecentAdaptersWindow._instance = None
            win = RecentAdaptersWindow(self._app, self._app.app_actions)
            win.select_tab(0)
        except Exception as e:
            self._handle_error(e, "ControlNet Adapters Window Error")

    def open_ipadapter_adapters_window(self) -> None:
        try:
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            existing = RecentAdaptersWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    existing.select_tab(1)
                    return
                RecentAdaptersWindow._instance = None
            win = RecentAdaptersWindow(self._app, self._app.app_actions)
            win.select_tab(1)
        except Exception as e:
            self._handle_error(e, "IPAdapter Adapters Window Error")

    def open_source_prompt_adapters_window(self) -> None:
        try:
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            existing = RecentAdaptersWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    existing.select_tab(2)
                    return
                RecentAdaptersWindow._instance = None
            win = RecentAdaptersWindow(self._app, self._app.app_actions)
            win.select_tab(2)
        except Exception as e:
            self._handle_error(e, "Source Prompt Adapters Window Error")

    # ------------------------------------------------------------------
    # Runs (queue + history)
    # ------------------------------------------------------------------
    def open_runs_window(self) -> None:
        try:
            from sd_runner.ui.runs.runs_window import RunsWindow
            existing = RunsWindow._instance
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                RunsWindow._instance = None
            self._open_window(RunsWindow)
        except Exception as e:
            self._handle_error(e, "Runs Window Error")

    # ------------------------------------------------------------------
    # Auth / Admin
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.ACCESS_ADMIN)
    def open_password_admin_window(self) -> None:
        try:
            from sd_runner.ui.auth.password_admin_window import PasswordAdminWindow

            existing = PasswordAdminWindow.top_level
            if existing is not None:
                if try_focus_existing_window(existing):
                    return
                PasswordAdminWindow.top_level = None
            PasswordAdminWindow(self._app, self._app.app_actions)
        except Exception as e:
            self._handle_error(e, "Password Admin Window Error")
