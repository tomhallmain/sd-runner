"""
Password authentication utilities for the SD Runner application.
This module provides the authentication flow logic and decorators.
It imports from password_core.py and password_dialog.py to avoid circular dependencies.
"""

from ui.auth.password_core import get_security_config, PasswordManager
from ui.auth.password_dialog import PasswordDialog
from ui.auth.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions



def _check_all_actions_protection(action_names: list[ProtectedActions], config) -> bool:
    """Check if any actions require password protection."""
    if isinstance(action_names, ProtectedActions):
        action_names = [action_names]
    return any(config.is_action_protected(action.value) for action in action_names)

def _check_session_validity(action_names: list[ProtectedActions], config, timeout_minutes: int) -> bool:
    """Check if all protected actions have a valid session."""
    protected_actions = [action for action in action_names if config.is_action_protected(action.value)]
    if not protected_actions:
        return True  # No protected actions, so session is valid
    return all(PasswordSessionManager.is_session_valid(action, timeout_minutes) for action in protected_actions)

def _record_sessions_for_all_actions(action_names: list[ProtectedActions], config):
    """Record successful verification for all actions."""
    if config.is_session_timeout_enabled():
        for action in action_names:
            PasswordSessionManager.record_successful_verification(action)

def check_password_required(
    action_names: list[ProtectedActions],
    master,
    callback=None,
    app_actions=None,
    custom_text=None,
    allow_unauthenticated=True
):
    """
    Check if actions require password authentication and prompt if needed.
    
    Args:
        action_names: List of actions to check (must be ProtectedActions enum values)
        master: The parent window for the password dialog
        callback: Optional callback function to call after password verification
        app_actions: Optional AppActions instance for opening admin window
        custom_text: Optional custom text to display in the password dialog
        allow_unauthenticated: Whether to allow proceeding without password if none is configured
        
    Returns:
        bool: True if password was verified or not required, False if cancelled
    """
    config = get_security_config()
    
    # Check if any of the actions require password protection
    if not _check_all_actions_protection(action_names, config):
        # No actions are protected, but check if we need to enforce authentication anyway
        if not allow_unauthenticated and not PasswordManager.is_security_configured():
            # Actions are not protected but we require authentication and no password is configured
            # Check if security advice is enabled
            if config.is_security_advice_enabled():
                # Show the dialog to prompt for password configuration
                description = action_names[0].get_description()

                def password_callback(result):
                    if callback:
                        callback(result)

                return PasswordDialog.prompt_password(master, config, description, password_callback, app_actions, action_names[0], custom_text, allow_unauthenticated)
            else:
                # Security advice is disabled, proceed without showing dialog
                # No password required and unauthenticated access is allowed, proceed immediately
                if callback:
                    callback(True)
                return True
    
    # Special case: If the only action is the admin action and no password is configured, allow access
    if len(action_names) == 1 and action_names[0] == ProtectedActions.ACCESS_ADMIN and not PasswordManager.is_security_configured():
        # Allow admin access when no password is configured (for initial setup)
        if callback:
            callback(True)
        return True
    
    # Check if session timeout is enabled and any session is still valid
    if allow_unauthenticated and config.is_session_timeout_enabled():
        timeout_minutes = config.get_session_timeout_minutes()
        if _check_session_validity(action_names, config, timeout_minutes):
            # Session is still valid, proceed without password prompt
            if callback:
                callback(True)
            return True
    
    # Password required, show dialog using the primary action
    description = action_names[0].get_description()
    
    def password_callback(result):
        if result:
            # Password verified successfully, record the session for all actions
            _record_sessions_for_all_actions(action_names, config)
        if callback:
            callback(result)
    
    return PasswordDialog.prompt_password(master, config, description, password_callback, app_actions, action_names[0], custom_text, allow_unauthenticated)


def require_password(
    *action_names: ProtectedActions,
    custom_text=None,
    allow_unauthenticated=True
):
    """
    Decorator to require password authentication for a function.
    Can accept multiple ProtectedActions as positional arguments.
    
    Usage:
        @require_password(ProtectedActions.EDIT_BLACKLIST)
        def edit_blacklist_function(self, *args, **kwargs):
            # Function implementation
            pass
            
        @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS, "This will show all concepts that are filtered by the blacklist")
        def reveal_concepts_function(self, *args, **kwargs):
            # Function implementation
            pass
            
        @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS, "Warning text", allow_unauthenticated=False)
        def sensitive_function(self, *args, **kwargs):
            # Function that requires password even if none is configured
            pass
            
        @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS, ProtectedActions.EDIT_BLACKLIST)
        def multi_protected_function(self, *args, **kwargs):
            # Function that requires both reveal and edit permissions
            pass
    """
    def decorator(func):
        def wrapper(self, *args, **kwargs):
            # Get the master window from self if it exists
            master = getattr(self, 'master', None)
            if not master:
                # Try to get it from the class if it's a static method
                master = getattr(self.__class__, 'top_level', None)
            
            if not master:
                print("No master window found - failed to require password")
                # If we can't find a master window, proceed without password check
                return func(self, *args, **kwargs)
            
            # Get app_actions from the instance
            app_actions = getattr(self, 'app_actions', None)
            
            def password_callback(result):
                if result:
                    # Password verified, execute the function
                    return func(self, *args, **kwargs)
                else:
                    # Password cancelled or incorrect
                    return None
            
            return check_password_required(list(action_names), master, password_callback, app_actions, custom_text, allow_unauthenticated)
        
        return wrapper
    return decorator 