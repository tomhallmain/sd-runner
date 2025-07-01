"""
Password authentication utilities for the SD Runner application.
"""

from ui.password_admin_window import PasswordAdminWindow
from ui.password_dialog import PasswordDialog
from ui.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions



def check_password_required(action_name: ProtectedActions, master, callback=None):
    """
    Check if an action requires password authentication and prompt if needed.
    
    Args:
        action_name: The action to check (must be a ProtectedActions enum value)
        master: The parent window for the password dialog
        callback: Optional callback function to call after password verification
        
    Returns:
        bool: True if password was verified or not required, False if cancelled
    """
    # Check if the action requires password protection
    if not PasswordAdminWindow.is_action_protected(action_name.value):
        # No password required, proceed immediately
        if callback:
            callback(True)
        return True
    
    # Check if session timeout is enabled and session is still valid
    if PasswordAdminWindow.is_session_timeout_enabled():
        timeout_minutes = PasswordAdminWindow.get_session_timeout_minutes()
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
            if PasswordAdminWindow.is_session_timeout_enabled():
                PasswordSessionManager.record_successful_verification(action_name)
        if callback:
            callback(result)
    
    return PasswordDialog.prompt_password(master, description, password_callback)


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
                # If we can't find a master window, proceed without password check
                return func(self, *args, **kwargs)
            
            def password_callback(result):
                if result:
                    # Password verified, execute the function
                    return func(self, *args, **kwargs)
                else:
                    # Password cancelled or incorrect
                    return None
            
            return check_password_required(action_name, master, password_callback)
        
        return wrapper
    return decorator





 