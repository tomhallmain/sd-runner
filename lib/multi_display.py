"""
Multi-display utilities for tkinter applications.

This module provides functionality to:
1. Detect which display a tkinter window is currently on
2. Position new Toplevel windows on the same display as their parent
3. Handle multi-monitor setups across different operating systems
4. SmartToplevel class that automatically handles positioning
"""

import tkinter as tk
import platform
import logging

logger = logging.getLogger(__name__)

# Module-level constants
BUFFER_DISTANCE_FROM_SCREEN_BOTTOM = 20  # Buffer from bottom of screen


class MultiDisplayManager:
    """
    Manages multi-display functionality for tkinter applications.
    """
    
    def __init__(self):
        self.system = platform.system().lower()
        self._display_info_cache = {}
    
    def _extract_window_dimensions(self, geometry, new_window):
        """
        Extract width and height from geometry string or window.
        
        Args:
            geometry: Geometry string (e.g., "400x300" or "400x300+100+200")
            new_window: Window object to get natural size from
            
        Returns:
            tuple: (width, height)
        """
        if geometry:
            if '+' in geometry:
                size_part = geometry.split('+')[0]
                width, height = map(int, size_part.split('x'))
            else:
                width, height = map(int, geometry.split('x'))
        else:
            # Use window's natural size
            width = new_window.winfo_reqwidth()
            height = new_window.winfo_reqheight()
        return width, height
    
    def get_window_display_info(self, window):
        """
        Get information about which display a window is currently on.
        
        Args:
            window: A tkinter window (Tk, Toplevel, etc.)
            
        Returns:
            dict: Display information containing:
                - display_index: Index of the display (0-based)
                - is_primary: Whether this is the primary display
                - bounds: (x, y, width, height) of the display
                - window_position: (x, y) of the window on this display
        """
        try:
            # Get window position
            window_x = window.winfo_x()
            window_y = window.winfo_y()
            
            # Get screen dimensions
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            
            # For now, we'll use a simple approach that works for most setups
            # In a true multi-monitor setup, this would need platform-specific code
            
            # Check if window is on primary display (coordinates 0,0 to screen_width, screen_height)
            if (0 <= window_x < screen_width and 0 <= window_y < screen_height):
                display_index = 0
                is_primary = True
                bounds = (0, 0, screen_width, screen_height)
                window_position = (window_x, window_y)
            else:
                # Window appears to be on a secondary display
                # This is a simplified approach - real multi-monitor detection
                # would require platform-specific APIs
                display_index = 1
                is_primary = False
                bounds = (0, 0, screen_width, screen_height)  # Simplified
                window_position = (window_x, window_y)
            
            return {
                'display_index': display_index,
                'is_primary': is_primary,
                'bounds': bounds,
                'window_position': window_position
            }
            
        except Exception as e:
            logger.error(f"Error getting window display info: {e}")
            # Return default primary display info
            return {
                'display_index': 0,
                'is_primary': True,
                'bounds': (0, 0, window.winfo_screenwidth(), window.winfo_screenheight()),
                'window_position': (window.winfo_x(), window.winfo_y())
            }
    
    def position_window_on_same_display(self, parent_window, new_window, 
                                      offset_x=50, offset_y=50, 
                                      center=False, geometry=None):
        """
        Position a new window on the same display as the parent window.
        
        Args:
            parent_window: The parent window to match display for
            new_window: The new window to position
            offset_x: X offset from parent window (default: 50)
            offset_y: Y offset from parent window (default: 50)
            center: If True, center the window on the display (default: False)
            geometry: Custom geometry string (e.g., "400x300"). If None, uses window's natural size
            
        Returns:
            str: The geometry string that was applied
        """
        # logger.debug(f"position_window_on_same_display called with offset_x={offset_x}, offset_y={offset_y}, center={center}")
        try:
            # Get parent window position and size
            parent_x = parent_window.winfo_x()
            parent_y = parent_window.winfo_y()
            parent_width = parent_window.winfo_width()
            parent_height = parent_window.winfo_height()
            
            # logger.debug(f"Parent window - x={parent_x}, y={parent_y}, width={parent_width}, height={parent_height}")
            
            if center:
                # Center the window on the same display as parent
                width, height = self._extract_window_dimensions(geometry, new_window)
                
                # Calculate center position
                center_x = parent_x + (parent_width - width) // 2
                center_y = parent_y + (parent_height - height) // 2
                
                # Ensure window stays within screen bounds
                screen_width = parent_window.winfo_screenwidth()
                screen_height = parent_window.winfo_screenheight()
                
                center_x = max(0, min(center_x, screen_width - width))
                center_y = max(0, min(center_y, screen_height - height))
                
                final_geometry = f"{width}x{height}+{center_x}+{center_y}"
            else:
                # Position with offset
                new_x = parent_x + offset_x
                new_y = parent_y + offset_y
                
                # Get window dimensions for bounds checking
                width, height = self._extract_window_dimensions(geometry, new_window)
                
                # Check if window would go off the bottom of the screen
                screen_height = parent_window.winfo_screenheight()
                
                if new_y + height > screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                    # Wrap to top and add horizontal offset
                    new_y = 50  # Start near top of screen
                    new_x = parent_x + offset_x + 100  # Add extra horizontal offset
                    logger.debug(f"Window would go off-screen, wrapping to top with increased horizontal offset")
                
                # For multi-display setups, we need to allow negative coordinates
                # Only apply minimal bounds checking to prevent windows from being completely off-screen
                # Don't clamp to screen bounds as that breaks multi-display positioning
                new_x = new_x  # Keep the calculated position
                new_y = max(0, new_y)  # Only prevent negative Y (title bar should be visible)
                
                if geometry:
                    # Use provided geometry with calculated position
                    if '+' in geometry:
                        size_part = geometry.split('+')[0]
                        final_geometry = f"{size_part}+{new_x}+{new_y}"
                    else:
                        final_geometry = f"{geometry}+{new_x}+{new_y}"
                else:
                    # Use window's natural size
                    final_geometry = f"{width}x{height}+{new_x}+{new_y}"
            
            # Apply the geometry
            new_window.geometry(final_geometry)
            return final_geometry
            
        except Exception as e:
            logger.error(f"Error positioning window: {e}")
            # Fallback to simple offset positioning
            try:
                parent_x = parent_window.winfo_x()
                parent_y = parent_window.winfo_y()
                fallback_geometry = f"+{parent_x + offset_x}+{parent_y + offset_y}"
                new_window.geometry(fallback_geometry)
                return fallback_geometry
            except:
                return ""
    
    def get_display_bounds(self, window, display_index=0):
        """
        Get the bounds of a specific display.
        
        Args:
            window: A tkinter window (used to get screen info)
            display_index: Index of the display (0-based)
            
        Returns:
            tuple: (x, y, width, height) of the display
        """
        try:
            if display_index == 0:
                # Primary display
                return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
            else:
                # For secondary displays, this is simplified
                # Real implementation would need platform-specific code
                screen_width = window.winfo_screenwidth()
                screen_height = window.winfo_screenheight()
                return (screen_width, 0, screen_width, screen_height)
        except Exception as e:
            logger.error(f"Error getting display bounds: {e}")
            return (0, 0, window.winfo_screenwidth(), window.winfo_screenheight())
    
    def is_window_on_primary_display(self, window: tk.Tk):
        """
        Check if a window is on the primary display.
        
        Args:
            window: A tkinter window
            
        Returns:
            bool: True if on primary display, False otherwise
        """
        try:
            x = window.winfo_x()
            y = window.winfo_y()
            screen_width = window.winfo_screenwidth()
            screen_height = window.winfo_screenheight()
            
            return (0 <= x < screen_width and 0 <= y < screen_height)
        except Exception as e:
            logger.error(f"Error checking primary display: {e}")
            return True  # Assume primary if we can't determine


# Global instance for easy access
display_manager = MultiDisplayManager()


class SmartToplevel(tk.Toplevel):
    """
    A Toplevel subclass that automatically positions itself on the same display as its parent.
    
    This class extends tkinter's Toplevel to provide automatic multi-display positioning.
    Simply use SmartToplevel instead of Toplevel, and it will automatically position
    itself on the same display as its parent window.
    
    Usage:
        # Instead of: new_window = tk.Toplevel(parent)
        new_window = SmartToplevel(persistent_parent=parent, title="My Window", geometry="400x300")
        
        # For staggered positioning, pass the last window as position_parent:
        new_window = SmartToplevel(persistent_parent=main_root, position_parent=previous_window,
                                   title="My Window", geometry="400x300", offset_x=30, offset_y=30)
    """
    
    def __init__(self, persistent_parent=None, position_parent=None, title=None, geometry=None, 
                 offset_x=30, offset_y=30, center=False, 
                 auto_position=True, **kwargs):
        """
        Initialize a SmartToplevel window.
        
        Args:
            persistent_parent: The actual Tk parent used for lifecycle/persistence
            position_parent: The window used solely for positioning calculations
            title: Window title
            geometry: Window geometry string (e.g., "400x300")
            offset_x: X offset from parent window (default: 30)
            offset_y: Y offset from parent window (default: 30)
            center: If True, center the window on the display (default: False)
            auto_position: If True, automatically position on same display (default: True)
            **kwargs: Additional arguments passed to Toplevel constructor
        """
        
        try:
            # Import AppStyle here to avoid circular imports
            from ui.app_style import AppStyle
            
            # Set default styling if not provided in kwargs
            if 'bg' not in kwargs:
                kwargs['bg'] = AppStyle.BG_COLOR
        except ImportError as e:
            logger.warning(f"Error setting default styling: {e}")
        
        # Initialize the Toplevel with persistent parent
        super().__init__(persistent_parent, **kwargs)
        if position_parent is None:
            position_parent = persistent_parent
        
        # Set title if provided
        if title:
            self.title(title)
        
        # Set geometry if provided
        if geometry:
            self.geometry(geometry)
        
        # Check if geometry already includes position information
        geometry_has_position = geometry and '+' in geometry
        
        # Position on the same display as given positioning parent (if auto_position is True)
        if position_parent and auto_position and not geometry_has_position:
            try:
                # Debug: Log parent window position
                # parent_x = position_parent.winfo_x()
                # parent_y = position_parent.winfo_y()
                # logger.debug(f"Parent window position: ({parent_x}, {parent_y})")
                
                display_manager.position_window_on_same_display(
                    position_parent, self, 
                    offset_x=offset_x, 
                    offset_y=offset_y, 
                    center=center,
                    geometry=geometry
                )
                
            except Exception as e:
                logger.warning(f"Failed to position SmartToplevel on same display: {e}")
                # Fallback to simple offset positioning with bounds checking
                try:
                    parent_x = position_parent.winfo_x()
                    parent_y = position_parent.winfo_y()
                    new_x = parent_x + offset_x
                    new_y = parent_y + offset_y
                    
                    # Check if window would go off the bottom of the screen
                    screen_height = position_parent.winfo_screenheight()
                    
                    # Get window height for bounds checking
                    _, window_height = self._extract_window_dimensions(geometry)
                    
                    # Check if window would go off bottom of screen
                    if new_y + window_height > screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                        # Wrap to top and add horizontal offset
                        new_y = 50  # Start near top of screen
                        new_x = parent_x + offset_x + 100  # Add extra horizontal offset
                        logger.debug(f"Window would go off-screen, wrapping to top with increased horizontal offset")
                    
                    fallback_geometry = f"+{new_x}+{new_y}"
                    self.geometry(fallback_geometry)
                    logger.debug(f"Fallback positioning: {fallback_geometry}")
                except Exception as fallback_e:
                    logger.warning(f"Fallback positioning also failed: {fallback_e}")
                    pass  # Use default positioning
        elif position_parent and not auto_position and not geometry_has_position:
            # Parent provided but auto_position is False - still position relative to parent
            try:
                parent_x = position_parent.winfo_x()
                parent_y = position_parent.winfo_y()
                new_x = parent_x + offset_x
                new_y = parent_y + offset_y
                
                # Check if window would go off the bottom of the screen
                screen_height = position_parent.winfo_screenheight()
                
                # Get window height for bounds checking
                _, window_height = self._extract_window_dimensions(geometry)
                
                # Check if window would go off bottom of screen
                if new_y + window_height > screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                    # Wrap to top and add horizontal offset
                    new_y = 50  # Start near top of screen
                    new_x = parent_x + offset_x + 100  # Add extra horizontal offset
                    logger.debug(f"Window would go off-screen, wrapping to top with increased horizontal offset")
                
                # Create geometry string with calculated position
                if geometry and '+' in geometry:
                    size_part = geometry.split('+')[0]
                    final_geometry = f"{size_part}+{new_x}+{new_y}"
                else:
                    final_geometry = f"{geometry or '400x300'}+{new_x}+{new_y}"
                
                self.geometry(final_geometry)
                logger.debug(f"Positioning relative to parent (auto_position=False): {final_geometry}")
                
            except Exception as e:
                logger.warning(f"Failed to position relative to parent: {e}")
        else:
            if geometry_has_position:
                logger.debug(f"Skipping positioning - geometry already includes position: {geometry}")
            else:
                logger.debug(f"Skipping positioning - position_parent={position_parent}, auto_position={auto_position}")

    def get_display_info(self):
        """
        Get information about which display this window is currently on.
        
        Returns:
            dict: Display information (same format as MultiDisplayManager.get_window_display_info)
        """
        return display_manager.get_window_display_info(self)
    
    def is_on_primary_display(self):
        """
        Check if this window is on the primary display.
        
        Returns:
            bool: True if on primary display, False otherwise
        """
        return display_manager.is_window_on_primary_display(self)
    
    def reposition_on_same_display(self, parent: tk.Tk, offset_x=50, offset_y=50, center=False):
        """
        Reposition this window on the same display as the given parent.
        
        Args:
            parent: Parent window to match display for
            offset_x: X offset from parent window (default: 50)
            offset_y: Y offset from parent window (default: 50)
            center: If True, center the window on the display (default: False)
        """
        try:
            display_manager.position_window_on_same_display(
                parent, self, 
                offset_x=offset_x, 
                offset_y=offset_y, 
                center=center
            )
        except Exception as e:
            logger.warning(f"Failed to reposition SmartToplevel: {e}")
    
    def position_on_same_display(self, parent: tk.Tk, offset_x=50, offset_y=50, center=False):
        """
        Position this window on the same display as the given parent.
        This is a convenience method that can be called after window creation.
        
        Args:
            parent: Parent window to match display for
            offset_x: X offset from parent window (default: 50)
            offset_y: Y offset from parent window (default: 50)
            center: If True, center the window on the display (default: False)
        """
        self.reposition_on_same_display(parent, offset_x, offset_y, center)
    
    def set_geometry_preserving_position(self, geometry):
        """
        Set the window geometry while preserving the current position.
        
        This is useful when you want to change the size of a window that has
        already been positioned by SmartToplevel, without losing the positioning.
        
        Args:
            geometry: New geometry string (e.g., "700x600" or "500x400")
        """
        current_geometry = self.geometry()
        
        if '+' in current_geometry:
            # Extract position from current geometry and apply new size
            position_part = current_geometry.split('+', 1)[1]  # Get everything after the first '+'
            new_geometry = f"{geometry}+{position_part}"
            self.geometry(new_geometry)
        else:
            # No position set yet, just set size
            self.geometry(geometry)
    
    def center_on_display(self, width=None, height=None):
        """
        Center the window on the same display as its parent.
        
        Args:
            width: Desired width (if None, uses current width)
            height: Desired height (if None, uses current height)
        """
        if not self.master:
            return
            
        try:
            # Get parent window position and size
            parent_x = self.master.winfo_x()
            parent_y = self.master.winfo_y()
            parent_width = self.master.winfo_width()
            parent_height = self.master.winfo_height()
            
            # Get current or specified dimensions
            if width is None:
                width = self.winfo_width()
            if height is None:
                height = self.winfo_height()
            
            # Calculate center position on the same display as parent
            center_x = parent_x + (parent_width - width) // 2
            center_y = parent_y + (parent_height - height) // 2
            
            # Apply the centered geometry
            new_geometry = f"{width}x{height}+{center_x}+{center_y}"
            self.geometry(new_geometry)
            
        except Exception as e:
            logger.warning(f"Failed to center window on display: {e}")
    
    def _extract_window_dimensions(self, geometry):
        """
        Extract width and height from geometry string or use defaults.
        
        Args:
            geometry: Geometry string (e.g., "400x300" or "400x300+100+200")
            
        Returns:
            tuple: (width, height)
        """
        if geometry:
            if '+' in geometry:
                size_part = geometry.split('+')[0]
                width, height = map(int, size_part.split('x'))
            else:
                width, height = map(int, geometry.split('x'))
        else:
            width, height = 400, 300  # Default size
        return width, height


