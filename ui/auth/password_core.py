"""
Core password functionality for the SD Runner application.
This module contains the foundational password management and configuration classes.
It has no dependencies on other password modules to avoid circular imports.
"""

import hashlib
import os
import keyring
from utils.globals import ProtectedActions
from utils.app_info_cache import app_info_cache


class SecurityConfig:
    """Central configuration manager for password protection settings."""
    
    # Default password-protected actions
    DEFAULT_PROTECTED_ACTIONS = {
        ProtectedActions.NSFW_PROMPTS.value: True,
        ProtectedActions.EDIT_BLACKLIST.value: True,
        ProtectedActions.EDIT_SCHEDULES.value: False,
        ProtectedActions.EDIT_EXPANSIONS.value: False,
        ProtectedActions.EDIT_PRESETS.value: False,
        ProtectedActions.EDIT_CONCEPTS.value: False,
        ProtectedActions.ACCESS_ADMIN.value: True  # Always protected
    }
    
    # Default session timeout settings (in minutes)
    DEFAULT_SESSION_TIMEOUT_ENABLED = True
    DEFAULT_SESSION_TIMEOUT_MINUTES = 30  # 30 minutes default
    
    def __init__(self):
        self._load_settings()
    
    def _load_settings(self):
        """Load settings from cache or use defaults."""
        self.protected_actions = app_info_cache.get("protected_actions", default_val=self.DEFAULT_PROTECTED_ACTIONS.copy())
        self.session_timeout_enabled = app_info_cache.get("session_timeout_enabled", default_val=self.DEFAULT_SESSION_TIMEOUT_ENABLED)
        self.session_timeout_minutes = app_info_cache.get("session_timeout_minutes", default_val=self.DEFAULT_SESSION_TIMEOUT_MINUTES)
        
        # Ensure ACCESS_ADMIN always remains protected
        self.protected_actions[ProtectedActions.ACCESS_ADMIN.value] = True
    
    def save_settings(self):
        """Save current settings to cache."""
        app_info_cache.set("protected_actions", self.protected_actions)
        app_info_cache.set("session_timeout_enabled", self.session_timeout_enabled)
        app_info_cache.set("session_timeout_minutes", self.session_timeout_minutes)
    
    def reset_to_defaults(self):
        """Reset all settings to their default values."""
        self.protected_actions = self.DEFAULT_PROTECTED_ACTIONS.copy()
        self.session_timeout_enabled = self.DEFAULT_SESSION_TIMEOUT_ENABLED
        self.session_timeout_minutes = self.DEFAULT_SESSION_TIMEOUT_MINUTES
        
        # Ensure ACCESS_ADMIN always remains protected
        self.protected_actions[ProtectedActions.ACCESS_ADMIN.value] = True
    
    def is_action_protected(self, action_name):
        """Check if a specific action requires password authentication."""
        return self.protected_actions.get(action_name, False)
    
    def is_session_timeout_enabled(self):
        """Check if session timeout is enabled."""
        return self.session_timeout_enabled
    
    def get_session_timeout_minutes(self):
        """Get the session timeout duration in minutes."""
        return self.session_timeout_minutes
    
    def set_action_protected(self, action_name, protected):
        """Set whether an action requires password protection."""
        self.protected_actions[action_name] = protected
        # Ensure ACCESS_ADMIN always remains protected
        self.protected_actions[ProtectedActions.ACCESS_ADMIN.value] = True
    
    def set_session_timeout_enabled(self, enabled):
        """Set whether session timeout is enabled."""
        self.session_timeout_enabled = enabled
    
    def set_session_timeout_minutes(self, minutes):
        """Set the session timeout duration in minutes."""
        if minutes > 0:
            self.session_timeout_minutes = minutes


# Global instance
_security_config = None

def get_security_config():
    """Get the global password configuration instance."""
    global _security_config
    if _security_config is None:
        _security_config = SecurityConfig()
    return _security_config


class PasswordManager:
    """Manages password storage and verification."""
    
    SERVICE_NAME = "SDRunner"
    APP_IDENTIFIER = "password_protection"
    
    @staticmethod
    def is_security_configured():
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