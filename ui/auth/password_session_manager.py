"""
Password session manager for tracking successful password verifications.
"""

import time
from typing import Dict, Optional
from utils.globals import ProtectedActions


class PasswordSessionManager:
    """Manages password sessions to avoid repeated password prompts."""
    
    # Dictionary to store last successful password verification times
    # Key: action_name (string), Value: timestamp (float)
    _session_times: Dict[str, float] = {}
    
    @classmethod
    def record_successful_verification(cls, action: ProtectedActions) -> None:
        """Record a successful password verification for an action."""
        cls._session_times[action.value] = time.time()
    
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
        if action_name not in cls._session_times:
            return False
            
        last_verification_time = cls._session_times[action_name]
        current_time = time.time()
        timeout_seconds = timeout_minutes * 60
        
        return (current_time - last_verification_time) < timeout_seconds
    
    @classmethod
    def clear_session(cls, action: Optional[ProtectedActions] = None) -> None:
        """
        Clear session data for an action or all actions.
        
        Args:
            action: Specific action to clear, or None to clear all sessions
        """
        if action is None:
            cls._session_times.clear()
        else:
            cls._session_times.pop(action.value, None)
    
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
        if action_name not in cls._session_times:
            return None
            
        last_verification_time = cls._session_times[action_name]
        current_time = time.time()
        age_seconds = current_time - last_verification_time
        return age_seconds / 60 