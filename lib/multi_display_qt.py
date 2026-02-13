"""
Multi-display utilities for PySide6 applications.

This module provides functionality to:
1. Detect which display a PySide6 window is currently on
2. Position new windows on the same display as their parent
3. Handle multi-monitor setups across different operating systems
4. SmartWindow class that automatically handles positioning
"""

from PySide6.QtWidgets import QWidget, QApplication, QMainWindow, QDialog
from PySide6.QtCore import Qt, QRect
import platform
import logging
import os

logger = logging.getLogger(__name__)

# Module-level constants
BUFFER_DISTANCE_FROM_SCREEN_BOTTOM = 20  # Buffer from bottom of screen
TITLE_BAR_HEIGHT = 40  # Assumed height for OS title bar / taskbar clearance


class MultiDisplayManager:
    """
    Manages multi-display functionality for PySide6 applications.
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
            size = new_window.sizeHint()
            if size.isValid():
                width = size.width()
                height = size.height()
            else:
                width = new_window.width()
                height = new_window.height()
        return width, height
    
    def get_window_display_info(self, window):
        """
        Get information about which display a window is currently on.
        
        Args:
            window: A PySide6 window (QWidget, QMainWindow, etc.)
            
        Returns:
            dict: Display information containing:
                - display_index: Index of the display (0-based)
                - is_primary: Whether this is the primary display
                - bounds: (x, y, width, height) of the display
                - window_position: (x, y) of the window on this display
        """
        try:
            # Get window position
            window_x = window.x()
            window_y = window.y()
            
            # Get the screen that contains the window
            screen = window.screen()
            if screen is None:
                screen = QApplication.primaryScreen()
            
            screen_geometry = screen.geometry()
            screen_x = screen_geometry.x()
            screen_y = screen_geometry.y()
            screen_width = screen_geometry.width()
            screen_height = screen_geometry.height()
            
            # Get all screens to find the index
            screens = QApplication.screens()
            display_index = screens.index(screen) if screen in screens else 0
            is_primary = (screen == QApplication.primaryScreen())
            
            # Calculate window position relative to the screen
            window_position = (window_x - screen_x, window_y - screen_y)
            
            return {
                'display_index': display_index,
                'is_primary': is_primary,
                'bounds': (screen_x, screen_y, screen_width, screen_height),
                'window_position': window_position
            }
            
        except Exception as e:
            logger.error(f"Error getting window display info: {e}")
            # Return default primary display info
            try:
                screen = QApplication.primaryScreen()
                screen_geometry = screen.geometry()
                return {
                    'display_index': 0,
                    'is_primary': True,
                    'bounds': (screen_geometry.x(), screen_geometry.y(), 
                              screen_geometry.width(), screen_geometry.height()),
                    'window_position': (window.x(), window.y())
                }
            except:
                return {
                    'display_index': 0,
                    'is_primary': True,
                    'bounds': (0, 0, 1920, 1080),  # Fallback default
                    'window_position': (0, 0)
                }
    
    def position_window_on_same_display(self, parent_window, new_window, 
                                      offset_x=50, offset_y=50, 
                                      center=False, center_relative_to=None,
                                      geometry=None,
                                      respect_title_bar=False):
        """
        Position a new window on the same display as the parent window.
        
        Args:
            parent_window: The parent window to match display for
            new_window: The new window to position
            offset_x: X offset from parent window (default: 50)
            offset_y: Y offset from parent window (default: 50)
            center: If True, center the window (default: False)
            center_relative_to: When center=True, center relative to this window if provided;
                otherwise center on the display. Use None for display-centered.
            geometry: Custom geometry string (e.g., "400x300"). If None, uses window's natural size
            respect_title_bar: If True (default: False), enforce a minimum Y offset of
                TITLE_BAR_HEIGHT from the screen top so the title bar is always visible
            
        Returns:
            QRect: The geometry rectangle that was applied
        """
        # logger.debug(f"position_window_on_same_display called with offset_x={offset_x}, offset_y={offset_y}, center={center}")
        try:
            # Get parent window position and size
            parent_x = parent_window.x()
            parent_y = parent_window.y()
            parent_width = parent_window.width()
            parent_height = parent_window.height()
            
            # Get the screen that contains the parent window
            parent_screen = parent_window.screen()
            if parent_screen is None:
                parent_screen = QApplication.primaryScreen()
            
            screen_geometry = parent_screen.geometry()
            
            # logger.debug(f"Parent window - x={parent_x}, y={parent_y}, width={parent_width}, height={parent_height}")
            
            if center:
                width, height = self._extract_window_dimensions(geometry, new_window)
                screen_x = screen_geometry.x()
                screen_y = screen_geometry.y()
                screen_width = screen_geometry.width()
                screen_height = screen_geometry.height()
                
                if center_relative_to is not None:
                    # Center relative to the given window (e.g. position_parent)
                    center_x = center_relative_to.x() + (center_relative_to.width() - width) // 2
                    center_y = center_relative_to.y() + (center_relative_to.height() - height) // 2
                else:
                    # Center on the display
                    center_x = screen_x + (screen_width - width) // 2
                    center_y = screen_y + (screen_height - height) // 2
                
                # Clamp so the window stays on the display (e.g. if dialog is larger than screen)
                center_x = max(screen_x, min(center_x, screen_x + screen_width - width))
                center_y = max(screen_y, min(center_y, screen_y + screen_height - height))
                
                final_rect = QRect(center_x, center_y, width, height)
            else:
                # Position with offset
                new_x = parent_x + offset_x
                new_y = parent_y + offset_y
                
                # Get window dimensions for bounds checking
                width, height = self._extract_window_dimensions(geometry, new_window)
                
                # Check if window would go off the bottom of the screen
                screen_geometry = parent_screen.geometry()
                screen_y = screen_geometry.y()
                screen_height = screen_geometry.height()
                
                min_y = screen_y + (TITLE_BAR_HEIGHT if respect_title_bar else 0)

                if new_y + height > screen_y + screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                    # Wrap to top; keep same horizontal offset so window aligns with others
                    new_y = min_y
                    new_x = parent_x + offset_x
                    logger.debug(f"Window would go off-screen, wrapping to top")
                
                # Ensure the window's title bar is always visible.
                new_y = max(min_y, new_y)
                
                final_rect = QRect(new_x, new_y, width, height)
            
            # Apply the geometry
            new_window.setGeometry(final_rect)
            return final_rect
            
        except Exception as e:
            logger.error(f"Error positioning window: {e}")
            # Fallback to simple offset positioning
            try:
                parent_x = parent_window.x()
                parent_y = parent_window.y()
                width, height = self._extract_window_dimensions(geometry, new_window)
                fallback_rect = QRect(parent_x + offset_x, parent_y + offset_y, width, height)
                new_window.setGeometry(fallback_rect)
                return fallback_rect
            except:
                return QRect(0, 0, 400, 300)
    
    def get_display_bounds(self, window, display_index=0):
        """
        Get the bounds of a specific display.
        
        Args:
            window: A PySide6 window (used to get screen info)
            display_index: Index of the display (0-based)
            
        Returns:
            tuple: (x, y, width, height) of the display
        """
        try:
            screens = QApplication.screens()
            if 0 <= display_index < len(screens):
                screen = screens[display_index]
                screen_geometry = screen.geometry()
                return (screen_geometry.x(), screen_geometry.y(), 
                       screen_geometry.width(), screen_geometry.height())
            else:
                # Fallback to primary screen
                screen = QApplication.primaryScreen()
                screen_geometry = screen.geometry()
                return (screen_geometry.x(), screen_geometry.y(), 
                       screen_geometry.width(), screen_geometry.height())
        except Exception as e:
            logger.error(f"Error getting display bounds: {e}")
            try:
                screen = QApplication.primaryScreen()
                screen_geometry = screen.geometry()
                return (screen_geometry.x(), screen_geometry.y(), 
                       screen_geometry.width(), screen_geometry.height())
            except:
                return (0, 0, 1920, 1080)  # Fallback default
    
    def is_window_on_primary_display(self, window: QWidget):
        """
        Check if a window is on the primary display.
        
        Args:
            window: A PySide6 window
            
        Returns:
            bool: True if on primary display, False otherwise
        """
        try:
            screen = window.screen()
            if screen is None:
                return True  # Assume primary if we can't determine
            return (screen == QApplication.primaryScreen())
        except Exception as e:
            logger.error(f"Error checking primary display: {e}")
            return True  # Assume primary if we can't determine


# Global instance for easy access
display_manager = MultiDisplayManager()


class SmartWindow(QWidget):
    """
    A QWidget subclass that automatically positions itself on the same display as its parent.
    
    This class extends PySide6's QWidget to provide automatic multi-display positioning.
    Simply use SmartWindow instead of QWidget, and it will automatically position
    itself on the same display as its parent window.
    
    Usage:
        # Instead of: new_window = QWidget(parent)
        new_window = SmartWindow(persistent_parent=parent, title="My Window", geometry="400x300")
        
        # For staggered positioning, pass the last window as position_parent:
        new_window = SmartWindow(persistent_parent=main_root, position_parent=previous_window,
                                 title="My Window", geometry="400x300", offset_x=30, offset_y=30)
    """
    
    def __init__(self, persistent_parent=None, position_parent=None, title=None, geometry=None, 
                 offset_x=30, offset_y=30, center=False, 
                 auto_position=True, window_flags=None, **kwargs):
        """
        Initialize a SmartWindow.
        
        Args:
            persistent_parent: The actual QWidget parent used for lifecycle/persistence
            position_parent: The window used solely for positioning calculations
            title: Window title
            geometry: Window geometry string (e.g., "400x300")
            offset_x: X offset from parent window (default: 30)
            offset_y: Y offset from parent window (default: 30)
            center: If True, center the window on the display (default: False)
            auto_position: If True, automatically position on same display (default: True)
            window_flags: Qt.WindowFlags to set (default: None, uses Qt.Window)
            **kwargs: Additional arguments passed to QWidget constructor
        """
        
        # Set window flags if provided, otherwise default to Window
        if window_flags is None:
            window_flags = Qt.WindowType.Window
        
        # Initialize the QWidget with persistent parent
        # QWidget(parent, f=Qt.WindowFlags()) - parent first, then flags
        super().__init__(persistent_parent, **kwargs)
        if window_flags:
            self.setWindowFlags(window_flags)
        
        if position_parent is None:
            position_parent = persistent_parent
        
        # Set title if provided
        if title:
            self.setWindowTitle(title)
        
        # Set geometry if provided (size only, position will be set later)
        if geometry:
            # Parse geometry string
            if '+' in geometry:
                size_part = geometry.split('+')[0]
                width, height = map(int, size_part.split('x'))
            else:
                width, height = map(int, geometry.split('x'))
            self.resize(width, height)
        
        # Check if geometry already includes position information
        geometry_has_position = geometry and '+' in geometry
        
        # Position on the same display as given positioning parent (if auto_position is True)
        if position_parent and auto_position and not geometry_has_position:
            try:
                # Debug: Log parent window position
                # parent_x = position_parent.x()
                # parent_y = position_parent.y()
                # logger.debug(f"Parent window position: ({parent_x}, {parent_y})")
                
                display_manager.position_window_on_same_display(
                    position_parent, self, 
                    offset_x=offset_x, 
                    offset_y=offset_y, 
                    center=center,
                    center_relative_to=position_parent,
                    geometry=geometry
                )
                
            except Exception as e:
                logger.warning(f"Failed to position SmartWindow on same display: {e}")
                # Fallback to simple offset positioning with bounds checking
                try:
                    parent_x = position_parent.x()
                    parent_y = position_parent.y()
                    new_x = parent_x + offset_x
                    new_y = parent_y + offset_y
                    
                    # Get the screen that contains the parent window
                    parent_screen = position_parent.screen()
                    if parent_screen is None:
                        parent_screen = QApplication.primaryScreen()
                    screen_geometry = parent_screen.geometry()
                    screen_y = screen_geometry.y()
                    screen_height = screen_geometry.height()
                    
                    # Get window height for bounds checking
                    _, window_height = self._extract_window_dimensions(geometry, self)
                    
                    # Check if window would go off bottom of screen
                    if new_y + window_height > screen_y + screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                        # Wrap to top; keep same horizontal offset
                        new_y = screen_y + 50  # Start near top of screen
                        new_x = parent_x + offset_x
                        logger.debug(f"Window would go off-screen, wrapping to top")
                    
                    width, height = self._extract_window_dimensions(geometry, self)
                    fallback_rect = QRect(new_x, new_y, width, height)
                    self.setGeometry(fallback_rect)
                    logger.debug(f"Fallback positioning: {fallback_rect}")
                except Exception as fallback_e:
                    logger.warning(f"Fallback positioning also failed: {fallback_e}")
                    pass  # Use default positioning
        elif position_parent and not auto_position and not geometry_has_position:
            # Parent provided but auto_position is False - still position relative to parent
            try:
                parent_x = position_parent.x()
                parent_y = position_parent.y()
                new_x = parent_x + offset_x
                new_y = parent_y + offset_y
                
                # Get the screen that contains the parent window
                parent_screen = position_parent.screen()
                if parent_screen is None:
                    parent_screen = QApplication.primaryScreen()
                screen_geometry = parent_screen.geometry()
                screen_y = screen_geometry.y()
                screen_height = screen_geometry.height()
                
                # Get window height for bounds checking
                _, window_height = self._extract_window_dimensions(geometry)
                
                # Check if window would go off bottom of screen
                if new_y + window_height > screen_y + screen_height - BUFFER_DISTANCE_FROM_SCREEN_BOTTOM:
                    # Wrap to top; keep same horizontal offset
                    new_y = screen_y + 50  # Start near top of screen
                    new_x = parent_x + offset_x
                    logger.debug(f"Window would go off-screen, wrapping to top")
                
                # Create geometry with calculated position
                width, height = self._extract_window_dimensions(geometry, self)
                final_rect = QRect(new_x, new_y, width, height)
                self.setGeometry(final_rect)
                logger.debug(f"Positioning relative to parent (auto_position=False): {final_rect}")
                
            except Exception as e:
                logger.warning(f"Failed to position relative to parent: {e}")
        else:
            if geometry_has_position:
                # Apply position from geometry string (e.g. "900x700+100+0").
                # Use move() + resize() so x,y are frame position (including title bar);
                # setGeometry() uses client area, so y=0 would put the title bar off-screen.
                try:
                    size_part, pos_part = geometry.split("+", 1)
                    width, height = map(int, size_part.split("x"))
                    parts = pos_part.split("+", 1)
                    x = int(parts[0])
                    y = int(parts[1]) if len(parts) > 1 else 0
                    self.move(x, y)
                    self.resize(width, height)
                    logger.debug(f"Applied positioned geometry: {geometry}")
                except (ValueError, AttributeError) as e:
                    logger.warning(f"Failed to parse positioned geometry {geometry!r}: {e}")
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
    
    def reposition_on_same_display(self, parent: QWidget, offset_x=50, offset_y=50, center=False):
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
            logger.warning(f"Failed to reposition SmartWindow: {e}")
    
    def position_on_same_display(self, parent: QWidget, offset_x=50, offset_y=50, center=False):
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
        already been positioned by SmartWindow, without losing the positioning.
        
        Args:
            geometry: New geometry string (e.g., "700x600" or "500x400")
        """
        current_rect = self.geometry()
        current_x = current_rect.x()
        current_y = current_rect.y()
        
        # Parse new size from geometry string
        if '+' in geometry:
            size_part = geometry.split('+')[0]
            width, height = map(int, size_part.split('x'))
        else:
            width, height = map(int, geometry.split('x'))
        
        # Apply new size while preserving position
        new_rect = QRect(current_x, current_y, width, height)
        self.setGeometry(new_rect)
    
    def center_on_display(self, width=None, height=None):
        """
        Center the window on the same display as its parent.
        
        Args:
            width: Desired width (if None, uses current width)
            height: Desired height (if None, uses current height)
        """
        parent = self.parent()
        if not parent or not isinstance(parent, QWidget):
            return
            
        try:
            # Get parent window position and size
            parent_x = parent.x()
            parent_y = parent.y()
            parent_width = parent.width()
            parent_height = parent.height()
            
            # Get current or specified dimensions
            if width is None:
                width = self.width()
            if height is None:
                height = self.height()
            
            # Calculate center position on the same display as parent
            center_x = parent_x + (parent_width - width) // 2
            center_y = parent_y + (parent_height - height) // 2
            
            # Apply the centered geometry
            new_rect = QRect(center_x, center_y, width, height)
            self.setGeometry(new_rect)
            
        except Exception as e:
            logger.warning(f"Failed to center window on display: {e}")
    
    def _extract_window_dimensions(self, geometry, window=None):
        """
        Extract width and height from geometry string or use defaults.
        
        Args:
            geometry: Geometry string (e.g., "400x300" or "400x300+100+200")
            window: Optional window object to get size from if geometry is None
            
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
            if window:
                width = window.width()
                height = window.height()
            else:
                width, height = 400, 300  # Default size
        return width, height


# Backward compatibility alias
SmartToplevel = SmartWindow


class SmartDialog(QDialog):
    """
    A QDialog subclass that positions on the same display as its parent,
    with optional center=True or pre-positioned geometry (e.g. "900x700+100+0" with auto_position=False).

    Usage:
        # Centered on same display as parent (e.g. password dialog)
        dlg = SmartDialog(parent=master, position_parent=master, title="Password", geometry="450x300", center=True)

        # Pre-positioned (e.g. admin window at top of screen)
        geo = "900x700+{}+0".format(master.geometry().x() + 50)
        dlg = SmartDialog(parent=master, position_parent=master, title="Admin", geometry=geo, auto_position=False)
    """

    def __init__(
        self,
        parent=None,
        position_parent=None,
        title=None,
        geometry=None,
        offset_x=50,
        offset_y=50,
        center=False,
        auto_position=True,
        respect_title_bar=False,
        **kwargs,
    ):
        super().__init__(parent, **kwargs)
        # position_parent is not defaulted to parent: when None, center_relative_to=None (center on display).

        if title:
            self.setWindowTitle(title)

        if geometry:
            if "+" in geometry:
                size_part = geometry.split("+")[0]
                width, height = map(int, size_part.split("x"))
            else:
                width, height = map(int, geometry.split("x"))
            self.resize(width, height)

        geometry_has_position = geometry and "+" in geometry

        if geometry_has_position:
            try:
                size_part, pos_part = geometry.split("+", 1)
                width, height = map(int, size_part.split("x"))
                parts = pos_part.split("+", 1)
                x = int(parts[0])
                y = int(parts[1]) if len(parts) > 1 else 0
                if respect_title_bar:
                    y = max(y, TITLE_BAR_HEIGHT)
                self.move(x, y)
                self.resize(width, height)
            except (ValueError, AttributeError):
                pass
        elif (position_parent or parent) and auto_position:
            try:
                # Use position_parent or parent to resolve which display; center_relative_to
                # controls centering: when None, center on display; when set, center on that window.
                display_manager.position_window_on_same_display(
                    position_parent or parent,
                    self,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    center=center,
                    center_relative_to=position_parent,
                    geometry=geometry,
                    respect_title_bar=respect_title_bar,
                )
            except Exception as e:
                logger.warning(f"Failed to position SmartDialog on same display: {e}")


class SmartMainWindow(QMainWindow):
    """
    A QMainWindow subclass that automatically handles multi-display positioning
    and can optionally save/restore window geometry across sessions.
    
    This class extends PySide6's QMainWindow to provide:
    1. Multi-display positioning support
    2. Optional window state persistence (saves position/size on close, restores on open)
    
    Usage:
        # Basic usage - just inherits multi-display capabilities
        class MyMainWindow(SmartMainWindow):
            def __init__(self):
                super().__init__()
                # ... setup UI ...
        
        # With state persistence
        class MyMainWindow(SmartMainWindow):
            def __init__(self):
                super().__init__(restore_geometry=True, settings_key="MyApp/MainWindow")
                # ... setup UI ...
    """
    
    def __init__(self, parent=None, restore_geometry=False, **kwargs):
        """
        Initialize a SmartMainWindow.
        
        Args:
            parent: Parent widget (usually None for main window)
            restore_geometry: If True, save/restore window geometry across sessions using app_info_cache
            **kwargs: Additional arguments passed to QMainWindow constructor
        """
        super().__init__(parent, **kwargs)
        
        self._restore_geometry = restore_geometry
        self._geometry_restored = False
    
    def restore_window_geometry(self):
        """
        Restore window geometry from app_info_cache.
        Call this after setup_ui() to ensure the window has its default size first.
        """
        if self._geometry_restored:
            return  # Already restored
            
        try:
            from utils.app_info_cache_qt import app_info_cache
            
            position_data = app_info_cache.get_display_position()
            
            if position_data and position_data.is_valid():
                x = position_data.x
                y = position_data.y
                width = position_data.width
                height = position_data.height
                
                # Verify the saved position is on a valid screen
                screens = QApplication.screens()
                position_valid = False
                
                for screen in screens:
                    screen_geometry = screen.geometry()
                    # Check if the saved position is within any screen's bounds
                    # (with some tolerance for windows that might be partially off-screen)
                    if (screen_geometry.x() - 100 <= x <= screen_geometry.x() + screen_geometry.width() + 100 and
                        screen_geometry.y() - 100 <= y <= screen_geometry.y() + screen_geometry.height() + 100):
                        position_valid = True
                        break
                
                if position_valid:
                    # Restore both position and size
                    self.setGeometry(QRect(x, y, width, height))
                    logger.debug(f"Restored window geometry from app_info_cache: {x}, {y}, {width}, {height}")
                    self._geometry_restored = True
                    return
                else:
                    # Position is not on any valid screen, center on primary display
                    logger.debug("Saved window position not on any valid screen, centering on primary")
                    self._center_on_primary_display()
                    self._geometry_restored = True
                    return
            else:
                # No saved geometry, center on primary display
                logger.debug("No saved window geometry found, centering on primary display")
                self._center_on_primary_display()
                self._geometry_restored = True
        except Exception as e:
            logger.error(f"Error restoring window geometry: {e}")
            self._center_on_primary_display()
            self._geometry_restored = True
    
    def _center_on_primary_display(self):
        """Center the window on the primary display"""
        try:
            screen = QApplication.primaryScreen()
            if screen:
                screen_geometry = screen.geometry()
                width = self.width() if self.width() > 0 else 1000
                height = self.height() if self.height() > 0 else 700
                
                center_x = screen_geometry.x() + (screen_geometry.width() - width) // 2
                center_y = screen_geometry.y() + (screen_geometry.height() - height) // 2
                
                self.setGeometry(QRect(center_x, center_y, width, height))
        except Exception as e:
            logger.error(f"Error centering window: {e}")
    
    def closeEvent(self, event):
        """Handle window close event - save geometry if enabled"""
        if self._restore_geometry:
            try:
                from utils.app_info_cache_qt import app_info_cache
                
                # Save window position using app_info_cache
                app_info_cache.set_display_position(self)
                
                # Also save virtual screen info for multi-display validation
                try:
                    app_info_cache.set_virtual_screen_info(self)
                except Exception as e:
                    logger.debug(f"Could not save virtual screen info: {e}")
                
                # Store the cache to disk
                app_info_cache.store()
                
                geometry = self.geometry()
                logger.debug(f"Saved window geometry to app_info_cache: {geometry.x()}, {geometry.y()}, {geometry.width()}, {geometry.height()}")
            except Exception as e:
                logger.error(f"Error saving window geometry: {e}")
        
        # Call parent closeEvent
        super().closeEvent(event)
    
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
    
    def reposition_on_display(self, display_index=0, center=True):
        """
        Reposition this window on a specific display.
        
        Args:
            display_index: Index of the display (0-based, default: 0 for primary)
            center: If True, center the window on the display (default: True)
        """
        try:
            screens = QApplication.screens()
            if 0 <= display_index < len(screens):
                screen = screens[display_index]
                screen_geometry = screen.geometry()
                
                if center:
                    width = self.width() if self.width() > 0 else 1000
                    height = self.height() if self.height() > 0 else 700
                    
                    center_x = screen_geometry.x() + (screen_geometry.width() - width) // 2
                    center_y = screen_geometry.y() + (screen_geometry.height() - height) // 2
                    
                    self.setGeometry(QRect(center_x, center_y, width, height))
                else:
                    # Just move to the display without centering
                    current_geometry = self.geometry()
                    new_x = screen_geometry.x() + (current_geometry.x() % screen_geometry.width())
                    new_y = screen_geometry.y() + (current_geometry.y() % screen_geometry.height())
                    self.setGeometry(QRect(new_x, new_y, current_geometry.width(), current_geometry.height()))
        except Exception as e:
            logger.error(f"Error repositioning window on display {display_index}: {e}")
