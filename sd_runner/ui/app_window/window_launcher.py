"""
WindowLauncher -- opens all secondary windows and dialogs.

Each method creates the appropriate secondary window or dialog.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sd_runner.ui.auth.password_utils import require_password
from sd_runner.ui.window_focus import try_focus_existing_window
from sd_runner.globals import ProtectedActions
from lib.logging_setup import get_logger
from lib.translations import I18N

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
    def _handle_error(self, error: Exception, title: str) -> None:
        self._app.notification_ctrl.handle_error(str(error), title=title)

    def _focus_or_open(self, load_window, error_title: str, tab: int | None = None) -> None:
        """Focus the open instance of a singleton window, or construct one.

        *load_window* returns the window class; it is a callable so each
        window module is imported only when that window is first asked for.
        A stale ``_instance`` (closed, or hidden by Escape) is cleared before
        constructing. *tab*, when given, is selected on whichever window ends
        up showing.
        """
        try:
            window_class = load_window()
            window = window_class._instance
            if not try_focus_existing_window(window):
                window_class._instance = None
                window = window_class(self._app, self._app.app_actions)
            if tab is not None:
                window.select_tab(tab)
        except Exception as e:
            self._handle_error(e, error_title)

    # ------------------------------------------------------------------
    # Blacklist
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_BLACKLIST)
    def show_tag_blacklist(self) -> None:
        def load():
            from sd_runner.ui.prompts.blacklist_window import BlacklistWindow
            return BlacklistWindow
        self._focus_or_open(load, _("Blacklist Window Error"))

    # ------------------------------------------------------------------
    # Presets / Schedules
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_PRESETS)
    def open_presets_window(self) -> None:
        def load():
            from sd_runner.ui.presets.presets_window import PresetsWindow
            return PresetsWindow
        self._focus_or_open(load, _("Presets Window Error"))

    @require_password(ProtectedActions.EDIT_SCHEDULES)
    def open_preset_schedules_window(self) -> None:
        def load():
            from sd_runner.ui.presets.schedules_window import SchedulesWindow
            return SchedulesWindow
        self._focus_or_open(load, _("Schedules Window Error"))

    @require_password(ProtectedActions.EDIT_TIMED_SCHEDULES)
    def open_timed_schedules_window(self) -> None:
        def load():
            from sd_runner.ui.presets.timed_schedules_window import TimedSchedulesWindow
            return TimedSchedulesWindow
        self._focus_or_open(load, _("Timed Schedules Window Error"))

    # ------------------------------------------------------------------
    # Concepts / Expansions / Prompt Config
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.EDIT_CONCEPTS)
    def open_concept_editor_window(self) -> None:
        def load():
            from sd_runner.ui.prompts.concept_editor_window import ConceptEditorWindow
            return ConceptEditorWindow
        self._focus_or_open(load, _("Concept Editor Window Error"))

    @require_password(ProtectedActions.EDIT_EXPANSIONS)
    def open_expansions_window(self) -> None:
        def load():
            from sd_runner.ui.prompts.expansions_window import ExpansionsWindow
            return ExpansionsWindow
        self._focus_or_open(load, _("Expansions Window Error"))

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
            self._handle_error(e, _("Prompt Config Window Error"))

    def open_prompt_generator_window(self) -> None:
        def load():
            from sd_runner.ui.prompts.prompt_generator_window import PromptGeneratorWindow
            return PromptGeneratorWindow
        self._focus_or_open(load, _("Prompt Generator Window Error"))

    def open_frequent_tags_window(self) -> None:
        """Open the frequent prompt-tags browser.

        .. todo:: Not yet exposed -- no button or keybinding invokes this
           method.  Wire a UI trigger once the feature is ready, and ensure
           ``add_tags`` is included in ``AppWindow._build_app_actions``.
        """
        def load():
            from sd_runner.ui.prompts.frequent_prompt_tags_window import FrequentPromptTagsWindow
            return FrequentPromptTagsWindow
        self._focus_or_open(load, _("Frequent Tags Window Error"))

    def open_image_to_prompt_window(self) -> None:
        def load():
            from sd_runner.ui.prompts.image_to_prompt_window import ImageToPromptWindow
            return ImageToPromptWindow
        self._focus_or_open(load, _("Image to Prompt Window Error"))

    def open_config_window(self) -> None:
        def load():
            from sd_runner.ui.config_window import ConfigWindow
            return ConfigWindow
        self._focus_or_open(load, _("Config Window Error"))

    # ------------------------------------------------------------------
    # Models / Adapters
    # ------------------------------------------------------------------
    def open_models_window(self) -> None:
        def load():
            from sd_runner.ui.models.models_window import ModelsWindow
            return ModelsWindow
        self._focus_or_open(load, _("Models Window Error"))

    def open_model_presets_window(self) -> None:
        def load():
            from sd_runner.ui.models.model_presets_window import ModelPresetsWindow
            return ModelPresetsWindow
        self._focus_or_open(load, _("Model Presets Window Error"))

    def open_lora_models_window(self) -> None:
        def load():
            from sd_runner.ui.models.models_window import ModelsWindow
            return ModelsWindow
        self._focus_or_open(load, _("LoRA Models Window Error"), tab=1)

    def open_controlnet_adapters_window(self) -> None:
        def load():
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            return RecentAdaptersWindow
        self._focus_or_open(load, _("ControlNet Adapters Window Error"), tab=0)

    def open_ipadapter_adapters_window(self) -> None:
        def load():
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            return RecentAdaptersWindow
        self._focus_or_open(load, _("IPAdapter Adapters Window Error"), tab=1)

    def open_source_prompt_adapters_window(self) -> None:
        def load():
            from sd_runner.ui.models.recent_adapters_window import RecentAdaptersWindow
            return RecentAdaptersWindow
        self._focus_or_open(load, _("Source Prompt Adapters Window Error"), tab=2)

    # ------------------------------------------------------------------
    # Runs (queue + history)
    # ------------------------------------------------------------------
    def open_runs_window(self) -> None:
        def load():
            from sd_runner.ui.runs.runs_window import RunsWindow
            return RunsWindow
        self._focus_or_open(load, _("Runs Window Error"))

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
            self._handle_error(e, _("Password Admin Window Error"))
