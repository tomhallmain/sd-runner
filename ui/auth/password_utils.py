"""
Password authentication utilities for the SD Runner application.
This module provides the authentication flow logic and decorators.
It imports from password_core.py and password_dialog.py to avoid circular dependencies.
"""

from ui.auth.password_core import get_security_config, PasswordManager
from ui.auth.password_dialog import PasswordDialog
from ui.auth.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions


def check_password_required(action_name: ProtectedActions, master, callback=None, app_actions=None):
    """
    Check if an action requires password authentication and prompt if needed.
    
    Args:
        action_name: The action to check (must be a ProtectedActions enum value)
        master: The parent window for the password dialog
        callback: Optional callback function to call after password verification
        app_actions: Optional AppActions instance for opening admin window
        
    Returns:
        bool: True if password was verified or not required, False if cancelled
    """
    config = get_security_config()
    
    # Check if the action requires password protection
    if not config.is_action_protected(action_name.value):
        # No password required, proceed immediately
        if callback:
            callback(True)
        return True
    
    # Special case: If this is the admin action and no password is configured, allow access
    if action_name == ProtectedActions.ACCESS_ADMIN and not PasswordManager.is_security_configured():
        # Allow admin access when no password is configured (for initial setup)
        if callback:
            callback(True)
        return True
    
    # Check if session timeout is enabled and session is still valid
    if config.is_session_timeout_enabled():
        timeout_minutes = config.get_session_timeout_minutes()
        if PasswordSessionManager.is_session_valid(action_name, timeout_minutes):
            # Session is still valid, proceed without password prompt
            if callback:
                callback(True)
            return True
    
    # Password required, show dialog
    description = action_name.get_description()
    
    def password_callback(result):
        if result:
            # Password verified successfully, record the session
            if config.is_session_timeout_enabled():
                PasswordSessionManager.record_successful_verification(action_name)
        if callback:
            callback(result)
    
    return PasswordDialog.prompt_password(master, description, password_callback, app_actions, action_name)


def require_password(action_name: ProtectedActions):
    """
    Decorator to require password authentication for a function.
    
    Usage:
        @require_password(ProtectedActions.EDIT_BLACKLIST)
        def edit_blacklist_function(self, *args, **kwargs):
            # Function implementation
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
            
            return check_password_required(action_name, master, password_callback, app_actions)
        
        return wrapper
    return decorator 