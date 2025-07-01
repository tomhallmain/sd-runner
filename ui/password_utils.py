"""
Password authentication utilities for the SD Runner application.
"""

import hashlib
import os
import keyring
from ui.password_admin_window import PasswordAdminWindow
from ui.password_dialog import PasswordDialog
from ui.password_session_manager import PasswordSessionManager
from utils.globals import ProtectedActions
from utils.app_info_cache import app_info_cache


class PasswordManager:
    """Manages password storage and verification."""
    
    SERVICE_NAME = "SDRunner"
    APP_IDENTIFIER = "password_protection"
    
    @staticmethod
    def is_password_configured():
        """Check if a password is configured."""
        try:
            # Check if password hash exists in secure storage
            password_hash = keyring.get_password(
                PasswordManager.SERVICE_NAME, 
                f"{PasswordManager.APP_IDENTIFIER}_hash"
            )
            return password_hash is not None and len(password_hash) > 0
        except:
            return False
    
    @staticmethod
    def set_password(password):
        """Set a new password."""
        try:
            # Create a salted hash of the password
            salt = os.urandom(32)
            password_hash = PasswordManager._hash_password(password, salt)
            
            # Store the hash in secure storage
            keyring.set_password(
                PasswordManager.SERVICE_NAME,
                f"{PasswordManager.APP_IDENTIFIER}_hash",
                salt.hex() + password_hash.hex()
            )
            return True
        except Exception as e:
            print(f"Error setting password: {e}")
            return False
    
    @staticmethod
    def verify_password(password):
        """Verify a password against the stored hash."""
        try:
            # Get the stored hash from secure storage
            stored_data_hex = keyring.get_password(
                PasswordManager.SERVICE_NAME, 
                f"{PasswordManager.APP_IDENTIFIER}_hash"
            )
            
            if not stored_data_hex:
                return False
            
            # Convert hex back to bytes
            stored_data = bytes.fromhex(stored_data_hex)
            
            # Extract salt and hash
            salt = stored_data[:32]
            stored_hash = stored_data[32:]
            
            # Hash the provided password with the same salt
            password_hash = PasswordManager._hash_password(password, salt)
            
            return password_hash == stored_hash
        except Exception as e:
            print(f"Error verifying password: {e}")
            return False
    
    @staticmethod
    def _hash_password(password, salt):
        """Create a hash of the password with salt."""
        # Use PBKDF2-like approach with multiple iterations
        password_bytes = password.encode('utf-8')
        hash_obj = hashlib.pbkdf2_hmac('sha256', password_bytes, salt, 100000)
        return hash_obj
    
    @staticmethod
    def clear_password():
        """Clear the stored password."""
        try:
            # Remove the password hash from secure storage
            keyring.delete_password(
                PasswordManager.SERVICE_NAME,
                f"{PasswordManager.APP_IDENTIFIER}_hash"
            )
            return True
        except Exception as e:
            print(f"Error clearing password: {e}")
            return False


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





 