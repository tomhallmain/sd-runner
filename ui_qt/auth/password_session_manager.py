"""
Password session manager for tracking successful password verifications.
"""

import time
from typing import Dict, Optional
from utils.globals import ProtectedActions


class PasswordSessionManager:
    """Manages password sessions to avoid repeated password prompts."""
    
    # Dictionary to store session data
    # Key: action_name (string), Value: tuple (timestamp, is_authenticated)
    _session_data: Dict[str, tuple] = {}
    
    @classmethod
    def record_successful_verification(cls, action: ProtectedActions, is_authenticated: bool = True) -> None:
        """
        Record a successful verification for an action.
        
        Args:
            action: The action to record
            is_authenticated: Whether this was a proper password verification (True) or skip without protection (False)
        """
        cls._session_data[action.value] = (time.time(), is_authenticated)
    
    @classmethod
    def is_session_valid(cls, action: ProtectedActions, timeout_minutes: int) -> bool:
        """
        Check if the session for an action is still valid.
        
        Args:
            action: The action to check
            timeout_minutes: Session timeout duration in minutes
            
        Returns:
            bool: True if session is still valid, False otherwise
        """
        if timeout_minutes <= 0:
            return False
            
        action_name = action.value
        if action_name not in cls._session_data:
            return False
            
        last_verification_time, is_authenticated = cls._session_data[action_name]
        current_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        return (current_time - last_verification_time) < timeout_seconds

    @classmethod
    def clear_all_sessions(cls) -> None:
        """
        Clear all session data for all actions.

        This is useful when security settings are changed to ensure
        that all changes take effect immediately.
        """
        cls._session_data.clear()

    @classmethod
    def clear_session(cls, action: Optional[ProtectedActions] = None) -> None:
        """
        Clear session data for an action or all actions.
        
        Args:
            action: Specific action to clear, or None to clear all sessions
        """
        if action is None:
            cls._session_data.clear()
        else:
            cls._session_data.pop(action.value, None)
    
    @classmethod
    def get_session_age_minutes(cls, action: ProtectedActions) -> Optional[float]:
        """
        Get the age of the current session in minutes.
        
        Args:
            action: The action to check
            
        Returns:
            float: Age in minutes, or None if no session exists
        """
        action_name = action.value
        if action_name not in cls._session_data:
            return None
            
        last_verification_time, is_authenticated = cls._session_data[action_name]
        current_time = time.time()
        age_seconds = current_time - last_verification_time
        return age_seconds / 60
    
    @classmethod
    def is_session_authenticated(cls, action: ProtectedActions) -> bool:
        """
        Check if the current session was authenticated with a password.
        
        Args:
            action: The action to check
            
        Returns:
            bool: True if session was authenticated with password, False if skipped without protection
        """
        action_name = action.value
        if action_name not in cls._session_data:
            return False
            
        _, is_authenticated = cls._session_data[action_name]
        return is_authenticated 