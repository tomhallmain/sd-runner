from typing import Dict, Callable, Any, Optional


class AppActions:

    REQUIRED_ACTIONS = {
        "update_progress", "update_pending", "update_time_estimation",
        "construct_preset", "set_widgets_from_preset", "open_password_admin_window",
        "toast", "_alert", "title_notify",
        # Models window callbacks
        "set_model_from_models_window",
        # Recent adapters window callbacks
        "set_adapter_from_adapters_window",
        # Unified recent adapter files callbacks
        "add_recent_adapter_file",
        "contains_recent_adapter_file",
    }

    def __init__(self, actions: Dict[str, Callable[..., Any]], master: Optional[object] = None):
        missing = self.REQUIRED_ACTIONS - set(actions.keys())
        if missing:
            raise ValueError(f"Missing required actions: {missing}")
        self._actions = actions
        self._master = master

    def __getattr__(self, name):
        if name in self._actions:
            return self._actions[name]
        raise AttributeError(f"Action '{name}' not found")

    # ------------------------------------------------------------------
    # Alert (with automatic master injection)
    # ------------------------------------------------------------------
    def alert(self, title: str, message: str, kind: str = "info", severity: str = "normal", master: Optional[object] = None):
        """
        Show a modal message box.  Automatically injects the stored master
        as parent when *master* is not explicitly provided.
        """
        parent_window = master if master is not None else self._master
        return self._alert(title, message, kind=kind, severity=severity, master=parent_window)

    # ------------------------------------------------------------------
    # Convenience toast variants
    # ------------------------------------------------------------------
    def warn(self, message: str, duration_ms: int = 3000) -> None:
        """Show a warning toast with the warning accent colour."""
        from ui_qt.app_style import AppStyle
        return self.toast(message, duration_ms=duration_ms, bg_color=AppStyle.TOAST_COLOR_WARNING)

    def success(self, message: str, duration_ms: int = 2000) -> None:
        """Show a success toast with the success accent colour."""
        from ui_qt.app_style import AppStyle
        return self.toast(message, duration_ms=duration_ms, bg_color=AppStyle.TOAST_COLOR_SUCCESS)

    # ------------------------------------------------------------------
    def get_master(self):
        return self._master

