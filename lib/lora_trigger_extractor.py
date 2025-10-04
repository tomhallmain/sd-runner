#
# LoRA Trigger Extractor
#
# An intermediary module that wraps the safetriggers functionality
# for integration with the SD-Runner models window.
#
# VERSION
__version_info__ = ('2025', '10', '04')
#
# BY
# SD-Runner Integration Layer
#
# BASED ON
# safetriggers by DAVROS*** (2025-03-16)
#
# =========
# PURPOSE
# =========
#
# This module provides a clean API for extracting trigger words and phrases
# from LoRA (.safetensors) files, designed for integration with the SD-Runner
# models window. It wraps the core functionality from lora_extract_safetriggers.py
# and provides caching, error handling, and UI-friendly interfaces.
#

import os
import json
import time
from typing import Optional, Dict, List, Tuple
from dataclasses import dataclass

# Module-level availability flag
SAFETRIGGERS_AVAILABLE = False

# Try to import the core safetriggers functionality
try:
    from lib.lora_extract_safetriggers import (
        read_triggers_from_lora,
        read_triggers_from_safetriggers,
        display_triggers,
        process_triggers
    )
    SAFETRIGGERS_AVAILABLE = True
except ImportError as e:
    # Log the import error for debugging
    print(f"Warning: Failed to import safetriggers functionality: {e}")
    print("LoRA trigger extraction will not be available.")
except Exception as e:
    # Handle any other import-related errors
    print(f"Warning: Unexpected error importing safetriggers functionality: {e}")
    print("LoRA trigger extraction will not be available.")


@dataclass
class TriggerInfo:
    """Container for LoRA trigger information."""
    lora_name: str
    triggers: Optional[Dict[str, int]]
    has_triggers: bool
    trigger_count: int
    top_triggers: List[Tuple[str, int]]
    last_updated: float
    error_message: Optional[str] = None


class LoRATriggerExtractor:
    """Main class for extracting and managing LoRA trigger information."""
    
    def __init__(self):
        self._cache: Dict[str, TriggerInfo] = {}
        self._cache_timestamp: Optional[float] = None
        self._max_cache_age = 3600  # 1 hour
    
    def get_trigger_info(self, lora_path: str, force_refresh: bool = False) -> TriggerInfo:
        """
        Get trigger information for a LoRA file.
        
        Args:
            lora_path: Full path to the .safetensors file
            force_refresh: Force refresh even if cached data exists
            
        Returns:
            TriggerInfo object containing trigger data
        """
        # Check if safetriggers functionality is available
        if not SAFETRIGGERS_AVAILABLE:
            lora_name = os.path.basename(os.path.normpath(lora_path))
            if lora_name.endswith('.safetensors'):
                lora_name = lora_name[:-12]
            return TriggerInfo(
                lora_name=lora_name,
                triggers=None,
                has_triggers=False,
                trigger_count=0,
                top_triggers=[],
                last_updated=time.time(),
                error_message="Safetriggers functionality not available"
            )
        
        # Normalize path for caching
        normalized_path = os.path.normpath(lora_path)
        
        # Check cache first
        if not force_refresh and normalized_path in self._cache:
            cached_info = self._cache[normalized_path]
            if not self._is_cache_stale(cached_info.last_updated):
                return cached_info
        
        # Extract base name for display
        lora_name = os.path.basename(normalized_path)
        if lora_name.endswith('.safetensors'):
            lora_name = lora_name[:-12]  # Remove .safetensors extension
        
        trigger_info = self._extract_triggers(normalized_path, lora_name)
        
        # Cache the result
        self._cache[normalized_path] = trigger_info
        
        return trigger_info
    
    def _extract_triggers(self, lora_path: str, lora_name: str) -> TriggerInfo:
        """Extract triggers from a LoRA file."""
        try:
            # Create a mock args object for the safetriggers functions
            class MockArgs:
                def __init__(self):
                    self.combine = True  # Combine all tag_frequency groups
                    self.display = False  # Don't display, just extract
                    self.mksafetriggers = False  # Don't create files automatically
                    self.triggerminimum = 1  # Include all triggers
                    self.triggercount = 1000  # Include many triggers
            
            args = MockArgs()
            
            # Extract triggers using the safetriggers functionality
            triggers = read_triggers_from_lora(lora_path, args)
            
            if triggers and len(triggers) > 0:
                # Sort triggers by frequency (descending)
                sorted_triggers = sorted(triggers.items(), key=lambda x: x[1], reverse=True)
                top_triggers = sorted_triggers[:10]  # Top 10 triggers
                
                return TriggerInfo(
                    lora_name=lora_name,
                    triggers=triggers,
                    has_triggers=True,
                    trigger_count=len(triggers),
                    top_triggers=top_triggers,
                    last_updated=time.time(),
                    error_message=None
                )
            else:
                return TriggerInfo(
                    lora_name=lora_name,
                    triggers=None,
                    has_triggers=False,
                    trigger_count=0,
                    top_triggers=[],
                    last_updated=time.time(),
                    error_message="No triggers found in LoRA"
                )
                
        except Exception as e:
            return TriggerInfo(
                lora_name=lora_name,
                triggers=None,
                has_triggers=False,
                trigger_count=0,
                top_triggers=[],
                last_updated=time.time(),
                error_message=f"Error extracting triggers: {str(e)}"
            )
    
    def get_cached_trigger_info(self, lora_path: str) -> Optional[TriggerInfo]:
        """Get cached trigger information if available."""
        normalized_path = os.path.normpath(lora_path)
        if normalized_path in self._cache:
            cached_info = self._cache[normalized_path]
            if not self._is_cache_stale(cached_info.last_updated):
                return cached_info
        return None
    
    def create_safetriggers_file(self, lora_path: str) -> bool:
        """
        Create a .safetriggers file for the given LoRA.
        
        Args:
            lora_path: Full path to the .safetensors file
            
        Returns:
            True if successful, False otherwise
        """
        # Check if safetriggers functionality is available
        if not SAFETRIGGERS_AVAILABLE:
            return False
            
        try:
            # Create a mock args object
            class MockArgs:
                def __init__(self):
                    self.combine = True
                    self.display = False
                    self.mksafetriggers = True
                    self.triggerminimum = 1
                    self.triggercount = 1000
            
            args = MockArgs()
            
            # Extract triggers
            triggers = read_triggers_from_lora(lora_path, args)
            
            if triggers and len(triggers) > 0:
                # The process_triggers function will create the .safetriggers file
                process_triggers(lora_path, triggers, args)
                return True
            else:
                return False
                
        except Exception:
            return False
    
    def read_existing_safetriggers(self, safetriggers_path: str) -> Optional[Dict[str, int]]:
        """
        Read an existing .safetriggers file.
        
        Args:
            safetriggers_path: Full path to the .safetriggers file
            
        Returns:
            Dictionary of triggers or None if error
        """
        # Check if safetriggers functionality is available
        if not SAFETRIGGERS_AVAILABLE:
            return None
            
        try:
            return read_triggers_from_safetriggers(safetriggers_path)
        except Exception:
            return None
    
    def clear_cache(self):
        """Clear the trigger cache."""
        self._cache.clear()
        self._cache_timestamp = None
    
    def _is_cache_stale(self, timestamp: float) -> bool:
        """Check if cached data is stale."""
        return (time.time() - timestamp) > self._max_cache_age
    
    def get_cache_stats(self) -> Dict[str, int]:
        """Get cache statistics."""
        return {
            'cached_items': len(self._cache),
            'cache_age_seconds': int(time.time() - self._cache_timestamp) if self._cache_timestamp else 0
        }


# Global instance for easy access
_trigger_extractor = LoRATriggerExtractor()


def get_trigger_info(lora_path: str, force_refresh: bool = False) -> TriggerInfo:
    """Convenience function to get trigger information."""
    return _trigger_extractor.get_trigger_info(lora_path, force_refresh)


def create_safetriggers_file(lora_path: str) -> bool:
    """Convenience function to create a .safetriggers file."""
    return _trigger_extractor.create_safetriggers_file(lora_path)


def read_existing_safetriggers(safetriggers_path: str) -> Optional[Dict[str, int]]:
    """Convenience function to read existing .safetriggers file."""
    return _trigger_extractor.read_existing_safetriggers(safetriggers_path)


def clear_trigger_cache():
    """Convenience function to clear the trigger cache."""
    _trigger_extractor.clear_cache()


def get_cache_stats() -> Dict[str, int]:
    """Convenience function to get cache statistics."""
    return _trigger_extractor.get_cache_stats()


def is_safetriggers_available() -> bool:
    """Check if safetriggers functionality is available."""
    return SAFETRIGGERS_AVAILABLE
