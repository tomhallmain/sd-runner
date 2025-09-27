from typing import Dict, Callable, Any

class AppActions:

    REQUIRED_ACTIONS = {
        "update_progress", "update_pending", "update_time_estimation", 
        "construct_preset", "set_widgets_from_preset", "open_password_admin_window",
        "toast", "alert",
        # Models window callbacks
        "set_model_from_models_window",
        # Recent adapters window callbacks
        "set_adapter_from_adapters_window",
    }
    
    def __init__(self, actions: Dict[str, Callable[..., Any]]):
        missing = self.REQUIRED_ACTIONS - set(actions.keys())
        if missing:
            raise ValueError(f"Missing required actions: {missing}")
        self._actions = actions
    
    def __getattr__(self, name):
        if name in self._actions:
            return self._actions[name]
        raise AttributeError(f"Action '{name}' not found")


