import traceback

from tkinter import Tk, TclError

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

    def _get_virtual_screen_info(self, root):
        """Get virtual screen information using Tcl commands directly"""
        try:
            # Use Tcl commands to get virtual screen information
            virtual_width = int(root.tk.call("winfo", "vrootwidth", root._w))
            virtual_height = int(root.tk.call("winfo", "vrootheight", root._w))
            
            # For virtual x and y, we need to use a different approach
            # These might not be directly available in all Tk versions
            virtual_x = 0
            virtual_y = 0
            
            # Try to get the virtual screen origin
            try:
                virtual_x = int(root.tk.call("winfo", "vrootx", root._w))
                virtual_y = int(root.tk.call("winfo", "vrooty", root._w))
            except:
                # If not available, assume (0, 0)
                pass
                
            return PositionData(x=virtual_x, y=virtual_y, width=virtual_width, height=virtual_height)
        except Exception as e:
            logger.warning(f"Could not get virtual screen info: {e}")
            raise TclError("Virtual screen methods not available")

    def is_visible_on_display(self, root: Tk, cached_virtual_screen: 'PositionData' = None):
        """
        Check if a window position is still visible on any connected display.
        
        Args:
            root: Root window to use for screen detection
            cached_virtual_screen: Cached virtual screen info (optional)
            
        Returns:
            bool: True if the position is visible on any display, False otherwise
        """
        try:
            assert root is not None
            
            # Get screen dimensions
            screen_width = root.winfo_screenwidth()
            screen_height = root.winfo_screenheight()
            
            # Check if any part of the window would be visible
            window_right = self.x + self.width
            window_bottom = self.y + self.height
            
            # For multi-display setups, try to get virtual screen info
            # but fall back to regular screen if virtual methods aren't available
            try:
                current_virtual_screen = self._get_virtual_screen_info(root)
                
                # If we have cached virtual screen info, compare it with current
                if cached_virtual_screen is not None:
                    if cached_virtual_screen != current_virtual_screen:
                        logger.debug("Virtual screen configuration has changed, position not visible")
                        return False
                
                # logger.debug(f"Virtual screen: x={current_virtual_screen.x}, y={current_virtual_screen.y}, width={current_virtual_screen.width}, height={current_virtual_screen.height}")
                # logger.debug(f"Window: x={self.x}, y={self.y}, width={self.width}, height={self.height}")
                # logger.debug(f"Window bounds: right={window_right}, bottom={window_bottom}")
                
                # Use virtual screen bounds for multi-display detection
                is_visible = (window_right > current_virtual_screen.x and 
                             self.x < current_virtual_screen.x + current_virtual_screen.width and
                             window_bottom > current_virtual_screen.y and 
                             self.y < current_virtual_screen.y + current_virtual_screen.height)
                
            except (AttributeError, TclError) as e:
                logger.warning(f"Virtual screen methods not available: {e}")

                # logger.debug(f"Regular screen: width={screen_width}, height={screen_height}")

                # Virtual screen methods not available, use regular screen bounds

                # For multi-display setups, we need to check if any part of the window
                # intersects with the visible screen area (can have negative coordinates)
                # A window is visible if any part of it intersects with the screen
                # This means: window_right > 0 AND window_left < screen_width
                # But we need to be more permissive for multi-display setups
                is_visible = (window_right > 0 and 
                             self.x < screen_width and
                             window_bottom > 0 and 
                             self.y < screen_height)
                
                # If the above fails but we have reasonable coordinates, assume visible
                # This handles cases where virtual screen methods aren't available
                # but we're in a multi-display setup with negative coordinates
                if not is_visible and (self.x > -2000 and self.x < 2000 and 
                                     self.y > -1000 and self.y < 2000 and
                                     self.width > 0 and self.width < 3000 and
                                     self.height > 0 and self.height < 2000):
                    is_visible = True
            
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
        return PositionData(x=master.winfo_x(), y=master.winfo_y(), width=master.winfo_width(), height=master.winfo_height())

    @staticmethod
    def from_master_virtual_screen(master):
        return PositionData.from_master(master)._get_virtual_screen_info(master)

    @staticmethod
    def from_dict(data: dict):
        return PositionData(x=data.get("x"), y=data.get("y"), width=data.get("width"), height=data.get("height"))
        
