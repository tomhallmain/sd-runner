import traceback

from utils.logging_setup import get_logger

logger = get_logger(__name__)

class PositionData:
    def __init__(self, x=None, y=None, width=None, height=None):
        self.x = x
        self.y = y
        self.width = width
        self.height = height

    def get_geometry(self):
        return f"{self.width}x{self.height}+{self.x}+{self.y}"
        
    def is_valid(self):
        return self.x is not None and self.y is not None and self.width is not None and self.height is not None

    def is_visible_on_display(self, window=None, cached_virtual_screen: 'PositionData' = None):
        """
        Check if a window position is still visible on any connected display.
        
        Args:
            window: PySide6 window to use for screen detection (optional)
            cached_virtual_screen: Cached virtual screen info (optional)
            
        Returns:
            bool: True if the position is visible on any display, False otherwise
        """
        try:
            from PySide6.QtWidgets import QApplication
            
            # Get all screens
            screens = QApplication.screens()
            if not screens:
                # No screens available, assume visible
                return True
            
            # Calculate current virtual screen bounds
            min_x = min(screen.geometry().x() for screen in screens)
            min_y = min(screen.geometry().y() for screen in screens)
            max_x = max(screen.geometry().x() + screen.geometry().width() for screen in screens)
            max_y = max(screen.geometry().y() + screen.geometry().height() for screen in screens)
            
            current_virtual_screen = PositionData(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)
            
            # If we have cached virtual screen info, compare it with current
            if cached_virtual_screen is not None:
                if cached_virtual_screen != current_virtual_screen:
                    logger.debug("Virtual screen configuration has changed, position not visible")
                    return False
            
            # Check if any part of the window would be visible
            window_right = self.x + self.width
            window_bottom = self.y + self.height
            
            # Use virtual screen bounds for multi-display detection
            is_visible = (window_right > current_virtual_screen.x and 
                         self.x < current_virtual_screen.x + current_virtual_screen.width and
                         window_bottom > current_virtual_screen.y and 
                         self.y < current_virtual_screen.y + current_virtual_screen.height)
            
            if not is_visible:
                logger.debug(f"Position not visible: {self.__str__()}")
            return is_visible
            
        except Exception as e:
            logger.error(f"Error checking position visibility: {e}")
            traceback.print_exc()
            return False

    def __str__(self):
        return f"PositionData(x={self.x}, y={self.y}, width={self.width}, height={self.height})"
    
    def __eq__(self, other):
        if not isinstance(other, PositionData):
            return False
        return (self.x == other.x and 
                self.y == other.y and 
                self.width == other.width and 
                self.height == other.height)
    
    def __hash__(self):
        return hash((self.x, self.y, self.width, self.height))

    def to_dict(self):
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height
        }

    @staticmethod
    def from_master(master):
        """Create PositionData from a PySide6 window"""
        from PySide6.QtWidgets import QWidget
        
        if not isinstance(master, QWidget):
            raise TypeError(f"Expected QWidget, got {type(master)}")
        
        geometry = master.geometry()
        return PositionData(x=geometry.x(), y=geometry.y(), width=geometry.width(), height=geometry.height())

    @staticmethod
    def from_master_virtual_screen(master):
        """Create PositionData for virtual screen from a PySide6 window"""
        from PySide6.QtWidgets import QWidget, QApplication
        
        if not isinstance(master, QWidget):
            raise TypeError(f"Expected QWidget, got {type(master)}")
        
        # Get virtual screen info from QApplication
        screens = QApplication.screens()
        if not screens:
            return None
        
        # Calculate virtual screen bounds from all screens
        min_x = min(screen.geometry().x() for screen in screens)
        min_y = min(screen.geometry().y() for screen in screens)
        max_x = max(screen.geometry().x() + screen.geometry().width() for screen in screens)
        max_y = max(screen.geometry().y() + screen.geometry().height() for screen in screens)
        
        return PositionData(x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y)

    @staticmethod
    def from_dict(data):
        """
        Reconstruct PositionData from a dict.

        Handles cross-toolkit cache gracefully: if *data* is not a dict or
        is missing expected keys the result will have ``None`` fields that
        ``is_valid()`` will reject.
        """
        if not isinstance(data, dict):
            logger.warning(f"PositionData.from_dict received non-dict: {type(data)}")
            return PositionData()
        return PositionData(
            x=data.get("x"), y=data.get("y"),
            width=data.get("width"), height=data.get("height"),
        )
