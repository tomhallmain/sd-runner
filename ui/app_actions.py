from typing import Dict, Callable, Any, Optional

class AppActions:

    REQUIRED_ACTIONS = {
        "update_progress", "update_pending", "update_time_estimation", 
        "construct_preset", "set_widgets_from_preset", "open_password_admin_window",
        "toast", "_alert",
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

    def alert(self, title: str, message: str, kind: str = "info", severity: str = "normal", master: Optional[object] = None) -> None:
        """
        Override the alert method to automatically inject the master parameter.
        If master is explicitly provided, use it; otherwise use the stored master.
        """
        # Use provided master or fall back to stored master
        parent_window = master if master is not None else self._master
        
        # Call the original alert method with the determined parent window
        return self._alert(title, message, kind=kind, severity=severity, master=parent_window)

    def get_master(self):
        return self._master

