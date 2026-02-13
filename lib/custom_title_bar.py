"""
Custom title bar implementation for PySide6 applications.

This module provides a reusable custom title bar that can be applied to any QMainWindow.
It supports:
- Drag to move the window
- Double-click to maximize/restore
- Minimize, maximize/restore, and close buttons
- Optional menu bar integration
- Theme-aware styling
- Window resizing via edges and corners
"""

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QPushButton, 
    QSizePolicy, QApplication, QFrame, QMenu, QMenuBar
)
from PySide6.QtCore import Qt, QPoint, Signal, QSize, QRect, QEvent, QObject
from PySide6.QtGui import QMouseEvent, QCursor, QAction, QPixmap, QIcon


class TitleBarMenuButton(QPushButton):
    """A styled menu button for the title bar."""
    
    _button_counter = 0  # Class-level counter for unique IDs
    
    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        # Assign unique object name to ensure style isolation
        TitleBarMenuButton._button_counter += 1
        self.setObjectName(f"titleBarMenuBtn_{TitleBarMenuButton._button_counter}")
        self.setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self._menu = None
        self._menu_connected = False
        self._is_menu_active = False  # Track if menu is currently showing
    
    def setMenu(self, menu: QMenu):
        """Set the dropdown menu for this button."""
        self._menu = menu
        # Only connect once to avoid duplicate signal connections
        if not self._menu_connected:
            self.clicked.connect(self._show_menu)
            self._menu_connected = True
    
    def is_menu_active(self) -> bool:
        """Check if this button's menu is currently showing."""
        return self._is_menu_active
    
    def _show_menu(self):
        """Show the dropdown menu below the button."""
        if self._menu:
            # Set active state before showing menu
            self._is_menu_active = True
            self._update_active_style()
            
            # Position the menu below the button
            pos = self.mapToGlobal(QPoint(0, self.height()))
            self._menu.exec(pos)
            
            # Clear active state after menu closes
            self._is_menu_active = False
            self._update_active_style()
    
    def _update_active_style(self):
        """Update the button's visual style based on active state."""
        # Request a style refresh from the parent title bar
        parent = self.parent()
        while parent:
            if hasattr(parent, '_apply_menu_button_style'):
                parent._apply_menu_button_style(self)
                break
            parent = parent.parent()


class TitleBarButton(QPushButton):
    """A styled button for the title bar."""
    
    def __init__(self, text: str = "", button_type: str = "default", parent=None):
        super().__init__(text, parent)
        self.button_type = button_type
        self.setFixedSize(46, 30)  # Slightly smaller to fit within title bar
        self.setCursor(Qt.ArrowCursor)
        # Prevent button from stealing focus but allow click
        self.setFocusPolicy(Qt.NoFocus)
        # Ensure mouse events are properly handled by the button
        self.setAttribute(Qt.WA_Hover, True)


class CustomTitleBar(QWidget):
    """
    A custom title bar widget that can be used with frameless windows.
    
    Signals:
        minimize_clicked: Emitted when minimize button is clicked
        maximize_clicked: Emitted when maximize/restore button is clicked
        close_clicked: Emitted when close button is clicked
        double_clicked: Emitted when title bar is double-clicked
    """
    
    minimize_clicked = Signal()
    maximize_clicked = Signal()
    close_clicked = Signal()
    double_clicked = Signal()
    
    def __init__(self, parent=None, title: str = "", show_icon: bool = True, corner_radius: int = 0):
        super().__init__(parent)
        self._parent_window = parent
        self._drag_position = QPoint()
        self._is_dragging = False
        self._is_maximized = False
        self._is_dark = True
        self._corner_radius = corner_radius
        self._menu_buttons = []  # Track menu buttons for styling
        
        self.setFixedHeight(32)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_StyledBackground, True)
        
        self._setup_ui(title, show_icon)
        self.apply_theme(True)
        
    def _setup_ui(self, title: str, show_icon: bool):
        """Set up the title bar UI."""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(0)
        layout.setAlignment(Qt.AlignVCenter)  # Vertically center all items
        
        # Icon placeholder (optional)
        if show_icon:
            self.icon_label = QLabel()
            self.icon_label.setFixedSize(16, 16)
            layout.addWidget(self.icon_label, 0, Qt.AlignVCenter)
            layout.addSpacing(8)
        
        # Title label – uses Ignored horizontal policy so long notification
        # text never forces the window to grow.  stretch=1 lets the label
        # fill all available space between icon/menus and window buttons.
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("font-size: 12px;")
        self.title_label.setMinimumWidth(0)
        self.title_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        layout.addWidget(self.title_label, 1, Qt.AlignVCenter)
        
        # Container for menu buttons (added after title)
        self._menu_container = QWidget()
        self._menu_layout = QHBoxLayout(self._menu_container)
        self._menu_layout.setContentsMargins(15, 0, 0, 0)
        self._menu_layout.setSpacing(0)
        layout.addWidget(self._menu_container, 0, Qt.AlignVCenter)
        
        # Window control buttons - aligned to fill height
        self.minimize_btn = TitleBarButton("─", "minimize", self)
        self.minimize_btn.setToolTip("Minimize")
        self.minimize_btn.clicked.connect(self._on_minimize)
        layout.addWidget(self.minimize_btn, 0, Qt.AlignVCenter)
        
        self.maximize_btn = TitleBarButton("□", "maximize", self)
        self.maximize_btn.setToolTip("Maximize")
        self.maximize_btn.clicked.connect(self._on_maximize)
        layout.addWidget(self.maximize_btn, 0, Qt.AlignVCenter)
        
        self.close_btn = TitleBarButton("✕", "close", self)
        self.close_btn.setToolTip("Close")
        self.close_btn.clicked.connect(self._on_close)
        layout.addWidget(self.close_btn, 0, Qt.AlignVCenter)
    
    def add_menu(self, title: str, menu: QMenu) -> TitleBarMenuButton:
        """
        Add a menu button to the title bar.
        
        Args:
            title: The text to display on the menu button
            menu: The QMenu to show when the button is clicked
            
        Returns:
            The created TitleBarMenuButton
        """
        btn = TitleBarMenuButton(title, self)
        btn.setMenu(menu)
        self._menu_buttons.append(btn)
        self._menu_layout.addWidget(btn, 0, Qt.AlignVCenter)
        # Apply current theme to the new button
        self._apply_menu_button_style(btn)
        return btn
    
    def add_menus(self, menu_definitions: list):
        """
        Add multiple menus to the title bar.
        
        Args:
            menu_definitions: List of tuples (title, menu) or (title, menu_items) where
                              menu_items is a list of tuples (action_text, callback) or
                              None for separator
        """
        for menu_def in menu_definitions:
            if len(menu_def) == 2:
                title, menu_or_items = menu_def
                if isinstance(menu_or_items, QMenu):
                    self.add_menu(title, menu_or_items)
                elif isinstance(menu_or_items, list):
                    menu = QMenu(self)
                    for item in menu_or_items:
                        if item is None:
                            menu.addSeparator()
                        elif isinstance(item, tuple) and len(item) >= 2:
                            action_text, callback = item[0], item[1]
                            shortcut = item[2] if len(item) > 2 else None
                            action = menu.addAction(action_text)
                            if callback:
                                action.triggered.connect(callback)
                            if shortcut:
                                action.setShortcut(shortcut)
                    self.add_menu(title, menu)
    
    def _apply_menu_button_style(self, btn: TitleBarMenuButton):
        """Apply theme style to a menu button."""
        from .app_style import AppStyle
        colors = AppStyle.get_colors(self._is_dark)
        # Use the specific object name to ensure style isolation for each button
        obj_name = btn.objectName()
        
        # Check if this button's menu is currently active/open
        is_active = btn.is_menu_active() if hasattr(btn, 'is_menu_active') else False
        
        # Use highlighted background if menu is active, otherwise transparent
        base_bg = colors['hover'] if is_active else "transparent"
        
        btn.setStyleSheet(f"""
            QPushButton#{obj_name} {{
                background-color: {base_bg};
                border: none;
                color: {colors['fg']};
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton#{obj_name}:hover {{
                background-color: {colors['hover']};
            }}
            QPushButton#{obj_name}:pressed {{
                background-color: {colors['hover']};
            }}
        """)
        
    def set_title(self, title: str):
        """Set the title bar text."""
        self.title_label.setText(title)
    
    def set_icon(self, icon_path: str):
        """
        Set the window icon in the title bar.
        
        Args:
            icon_path: Path to the icon image file
        """
        if hasattr(self, 'icon_label'):
            pixmap = QPixmap(icon_path)
            if not pixmap.isNull():
                # Scale to fit the label size while maintaining aspect ratio
                scaled_pixmap = pixmap.scaled(
                    self.icon_label.size(),
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
                self.icon_label.setPixmap(scaled_pixmap)
    
    def set_icon_from_pixmap(self, pixmap: QPixmap):
        """
        Set the window icon from a QPixmap.
        
        Args:
            pixmap: The QPixmap to use as the icon
        """
        if hasattr(self, 'icon_label') and not pixmap.isNull():
            scaled_pixmap = pixmap.scaled(
                self.icon_label.size(),
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
            self.icon_label.setPixmap(scaled_pixmap)
        
    def set_maximized_state(self, is_maximized: bool):
        """Update the maximize button appearance based on window state."""
        self._is_maximized = is_maximized
        if is_maximized:
            self.maximize_btn.setText("❐")
            self.maximize_btn.setToolTip("Restore")
        else:
            self.maximize_btn.setText("□")
            self.maximize_btn.setToolTip("Maximize")
            
    def apply_theme(self, is_dark: bool):
        """Apply theme to the title bar using AppStyle."""
        self._is_dark = is_dark
        from .app_style import AppStyle
        AppStyle.apply_to_title_bar(self, is_dark)
        # Also style menu buttons
        for btn in self._menu_buttons:
            self._apply_menu_button_style(btn)
            
    def _on_minimize(self):
        """Handle minimize button click."""
        self.minimize_clicked.emit()
        if self._parent_window:
            # Use showMinimized directly - works regardless of maximized state
            self._parent_window.showMinimized()
            
    def _on_maximize(self):
        """Handle maximize/restore button click."""
        self.maximize_clicked.emit()
        if self._parent_window:
            if self._parent_window.isMaximized():
                self._parent_window.showNormal()
                self.set_maximized_state(False)
            else:
                self._parent_window.showMaximized()
                self.set_maximized_state(True)
                
    def _on_close(self):
        """Handle close button click."""
        self.close_clicked.emit()
        if self._parent_window:
            self._parent_window.close()
            
    def mousePressEvent(self, event: QMouseEvent):
        """Handle mouse press for window dragging."""
        if event.button() == Qt.LeftButton:
            # Don't start drag if clicking on buttons (title bar buttons or menu buttons)
            widget = self.childAt(event.pos())
            if isinstance(widget, (TitleBarButton, TitleBarMenuButton)):
                event.ignore()
                return
            # Also check parent widget in case we clicked on a child
            if widget and isinstance(widget.parent(), (TitleBarButton, TitleBarMenuButton)):
                event.ignore()
                return
            
            self._is_dragging = True
            self._drag_position = event.globalPos() - self._parent_window.frameGeometry().topLeft()
            event.accept()
            
    def mouseMoveEvent(self, event: QMouseEvent):
        """Handle mouse move for window dragging."""
        if self._is_dragging and event.buttons() == Qt.LeftButton:
            if self._parent_window:
                # If maximized, restore before dragging
                if self._parent_window.isMaximized():
                    # Calculate relative position within the title bar
                    title_bar_width = self.width()
                    relative_x = event.pos().x() / title_bar_width
                    
                    # Restore window
                    self._parent_window.showNormal()
                    self.set_maximized_state(False)
                    
                    # Adjust drag position to keep window under cursor
                    new_width = self._parent_window.width()
                    self._drag_position = QPoint(
                        int(relative_x * new_width),
                        event.pos().y()
                    )
                
                new_pos = event.globalPos() - self._drag_position
                self._parent_window.move(new_pos)
            event.accept()
            
    def mouseReleaseEvent(self, event: QMouseEvent):
        """Handle mouse release."""
        self._is_dragging = False
        event.accept()
        
    def mouseDoubleClickEvent(self, event: QMouseEvent):
        """Handle double-click to maximize/restore."""
        if event.button() == Qt.LeftButton:
            # Don't maximize if double-clicking on buttons
            widget = self.childAt(event.pos())
            if isinstance(widget, TitleBarButton):
                return
                
            self.double_clicked.emit()
            self._on_maximize()
            event.accept()


class ResizeGrip:
    """Constants and utilities for window resize functionality."""
    
    # Resize edge/corner constants
    EDGE_NONE = 0
    EDGE_TOP = 1
    EDGE_BOTTOM = 2
    EDGE_LEFT = 4
    EDGE_RIGHT = 8
    EDGE_TOP_LEFT = EDGE_TOP | EDGE_LEFT
    EDGE_TOP_RIGHT = EDGE_TOP | EDGE_RIGHT
    EDGE_BOTTOM_LEFT = EDGE_BOTTOM | EDGE_LEFT
    EDGE_BOTTOM_RIGHT = EDGE_BOTTOM | EDGE_RIGHT
    
    # Default grip size in pixels
    GRIP_SIZE = 8
    
    @staticmethod
    def get_resize_edge(pos: QPoint, window_rect: QRect, grip_size: int = 8) -> int:
        """
        Determine which edge/corner the position is on.
        
        Args:
            pos: Mouse position relative to window
            window_rect: Window geometry
            grip_size: Size of the resize grip area
            
        Returns:
            Edge constant indicating which edge(s) the position is on
        """
        edge = ResizeGrip.EDGE_NONE
        
        x, y = pos.x(), pos.y()
        width, height = window_rect.width(), window_rect.height()
        
        if x < grip_size:
            edge |= ResizeGrip.EDGE_LEFT
        elif x > width - grip_size:
            edge |= ResizeGrip.EDGE_RIGHT
            
        if y < grip_size:
            edge |= ResizeGrip.EDGE_TOP
        elif y > height - grip_size:
            edge |= ResizeGrip.EDGE_BOTTOM
            
        return edge
    
    @staticmethod
    def get_cursor_for_edge(edge: int) -> Qt.CursorShape:
        """Get the appropriate cursor for a resize edge."""
        cursors = {
            ResizeGrip.EDGE_TOP: Qt.SizeVerCursor,
            ResizeGrip.EDGE_BOTTOM: Qt.SizeVerCursor,
            ResizeGrip.EDGE_LEFT: Qt.SizeHorCursor,
            ResizeGrip.EDGE_RIGHT: Qt.SizeHorCursor,
            ResizeGrip.EDGE_TOP_LEFT: Qt.SizeFDiagCursor,
            ResizeGrip.EDGE_BOTTOM_RIGHT: Qt.SizeFDiagCursor,
            ResizeGrip.EDGE_TOP_RIGHT: Qt.SizeBDiagCursor,
            ResizeGrip.EDGE_BOTTOM_LEFT: Qt.SizeBDiagCursor,
        }
        return cursors.get(edge, Qt.ArrowCursor)


class WindowResizeHandler(QObject):
    """
    An event filter that handles window resizing for frameless windows.
    
    Uses an application-level event filter to track cursor position globally,
    allowing resize cursor and functionality to work even when hovering over
    child widgets near the window edges.
    """
    
    def __init__(self, window, grip_size: int = 8):
        super().__init__(window)
        self._window = window
        self._grip_size = grip_size
        self._resize_edge = ResizeGrip.EDGE_NONE
        self._resize_start_pos = QPoint()
        self._resize_start_geometry = QRect()
        self._is_resizing = False
        self._current_cursor_edge = ResizeGrip.EDGE_NONE  # Track which edge cursor is set for
        
        # Install event filter on the application to catch all mouse events
        QApplication.instance().installEventFilter(self)
        
    def _get_edge_from_global_pos(self, global_pos: QPoint) -> int:
        """Determine which edge the global position is on."""
        if self._window.isMaximized():
            return ResizeGrip.EDGE_NONE
        
        # Get window geometry in global coordinates
        window_rect = self._window.frameGeometry()
        
        grip = self._grip_size
        
        x, y = global_pos.x(), global_pos.y()
        left, top = window_rect.left(), window_rect.top()
        right, bottom = window_rect.right(), window_rect.bottom()
        width = window_rect.width()
        
        # Check if cursor is within window bounds (with grip tolerance)
        if not (left - grip <= x <= right + grip and top - grip <= y <= bottom + grip):
            return ResizeGrip.EDGE_NONE
        
        # Title bar button area (approximately right 150px of the window, top 32px)
        title_bar_height = 32
        button_area_width = 150  # 3 buttons * ~50px each
        in_button_area = (y >= top and y <= top + title_bar_height and 
                         x >= right - button_area_width)
        
        # Check edges
        edge = ResizeGrip.EDGE_NONE
        
        # Left edge
        if x <= left + grip:
            edge |= ResizeGrip.EDGE_LEFT
        # Right edge (but not in button area)
        elif x >= right - grip and not in_button_area:
            edge |= ResizeGrip.EDGE_RIGHT
        
        # Top edge (but not in button area)
        if y <= top + grip and not in_button_area:
            edge |= ResizeGrip.EDGE_TOP
        # Bottom edge
        elif y >= bottom - grip:
            edge |= ResizeGrip.EDGE_BOTTOM
            
        return edge
        
    def eventFilter(self, obj, event: QEvent) -> bool:
        """Filter events to handle window resizing."""
        # Only process mouse events
        event_type = event.type()
        
        if event_type == QEvent.MouseMove:
            return self._handle_mouse_move(event)
        elif event_type == QEvent.MouseButtonPress:
            return self._handle_mouse_press(event)
        elif event_type == QEvent.MouseButtonRelease:
            return self._handle_mouse_release(event)
            
        return False
    
    def _handle_mouse_move(self, event: QMouseEvent) -> bool:
        """Handle mouse move for resize cursor and resizing."""
        global_pos = event.globalPos()
        
        if self._is_resizing:
            self._perform_resize(global_pos)
            return True  # Consume the event during resize
        
        # Check if cursor is on window edge
        edge = self._get_edge_from_global_pos(global_pos)
        
        if edge != ResizeGrip.EDGE_NONE:
            # Only update cursor if edge changed
            if edge != self._current_cursor_edge:
                # Restore previous cursor first if one was set
                if self._current_cursor_edge != ResizeGrip.EDGE_NONE:
                    QApplication.restoreOverrideCursor()
                # Set new resize cursor
                QApplication.setOverrideCursor(ResizeGrip.get_cursor_for_edge(edge))
                self._current_cursor_edge = edge
        elif self._current_cursor_edge != ResizeGrip.EDGE_NONE:
            # Restore normal cursor when leaving edge
            QApplication.restoreOverrideCursor()
            self._current_cursor_edge = ResizeGrip.EDGE_NONE
        
        # Don't consume the event - let it propagate
        return False
    
    def _handle_mouse_press(self, event: QMouseEvent) -> bool:
        """Handle mouse press for resize."""
        if event.button() != Qt.LeftButton:
            return False
        
        # Check if clicked widget is a button - don't intercept button clicks
        widget_at_pos = QApplication.widgetAt(event.globalPos())
        if widget_at_pos is not None:
            if isinstance(widget_at_pos, QPushButton):
                return False
            # Also check parent in case click is on button's label
            parent = widget_at_pos.parent()
            if parent is not None and isinstance(parent, QPushButton):
                return False
        
        global_pos = event.globalPos()
        edge = self._get_edge_from_global_pos(global_pos)
        
        if edge != ResizeGrip.EDGE_NONE:
            self._resize_edge = edge
            self._resize_start_pos = global_pos
            self._resize_start_geometry = self._window.geometry()
            self._is_resizing = True
            return True  # Consume the event
        
        return False
    
    def _handle_mouse_release(self, event: QMouseEvent) -> bool:
        """Handle mouse release."""
        if self._is_resizing:
            self._is_resizing = False
            self._resize_edge = ResizeGrip.EDGE_NONE
            # Restore cursor if one was set
            if self._current_cursor_edge != ResizeGrip.EDGE_NONE:
                QApplication.restoreOverrideCursor()
                self._current_cursor_edge = ResizeGrip.EDGE_NONE
            return True
        return False
    
    def _perform_resize(self, global_pos: QPoint):
        """Perform the window resize operation."""
        delta = global_pos - self._resize_start_pos
        geometry = QRect(self._resize_start_geometry)
        
        min_width = max(self._window.minimumWidth(), 200)
        min_height = max(self._window.minimumHeight(), 100)
        
        edge = self._resize_edge
        
        if edge & ResizeGrip.EDGE_LEFT:
            new_width = geometry.width() - delta.x()
            if new_width >= min_width:
                geometry.setLeft(geometry.left() + delta.x())
        
        if edge & ResizeGrip.EDGE_RIGHT:
            new_width = geometry.width() + delta.x()
            if new_width >= min_width:
                geometry.setWidth(new_width)
        
        if edge & ResizeGrip.EDGE_TOP:
            new_height = geometry.height() - delta.y()
            if new_height >= min_height:
                geometry.setTop(geometry.top() + delta.y())
        
        if edge & ResizeGrip.EDGE_BOTTOM:
            new_height = geometry.height() + delta.y()
            if new_height >= min_height:
                geometry.setHeight(new_height)
        
        self._window.setGeometry(geometry)


# Keep ResizeBorderFrame as an alias for backwards compatibility
ResizeBorderFrame = WindowResizeHandler


class FramelessWindowMixin:
    """
    A mixin class that adds custom title bar and frameless window functionality
    to any QMainWindow subclass.
    
    Usage:
        class MyWindow(FramelessWindowMixin, QMainWindow):
            def __init__(self):
                QMainWindow.__init__(self)
                self.setup_frameless_window(title="My App")
                # ... rest of your UI setup
    
    Note: The mixin must be listed BEFORE QMainWindow in the inheritance order.
    """
    
    def setup_frameless_window(self, title: str = "", enable_resize: bool = True,
                               title_bar_height: int = 32, grip_size: int = 8,
                               corner_radius: int = 10):
        """
        Initialize the frameless window with custom title bar.
        
        Args:
            title: Window title
            enable_resize: Whether to enable window resizing via edges/corners
            title_bar_height: Height of the custom title bar
            grip_size: Size of the resize grip areas
            corner_radius: Radius for rounded corners (0 for square corners)
        """
        self._frameless_resize_enabled = enable_resize
        self._frameless_grip_size = grip_size
        self._frameless_corner_radius = corner_radius
        self._frameless_is_dark_theme = True
        
        # Set frameless window hint
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        
        # Enable translucent background for rounded corners
        if corner_radius > 0:
            self.setAttribute(Qt.WA_TranslucentBackground)
        
        # Create the custom title bar
        from .app_style import AppStyle
        AppStyle.set_corner_radius(corner_radius)
        self._title_bar = CustomTitleBar(self, title, corner_radius=corner_radius)
        self._title_bar.setFixedHeight(title_bar_height)
        
    def get_title_bar(self) -> CustomTitleBar:
        """Get the custom title bar widget."""
        return getattr(self, '_title_bar', None)
    
    def set_title_bar_visible(self, visible: bool):
        """Show or hide the custom title bar."""
        if hasattr(self, '_title_bar'):
            self._title_bar.setVisible(visible)
            
    def apply_frameless_theme(self, is_dark: bool):
        """Apply theme to the frameless window components."""
        self._frameless_is_dark_theme = is_dark
        if hasattr(self, '_title_bar'):
            self._title_bar.apply_theme(is_dark)


def install_title_bar_to_layout(window, layout, title: str = "", is_dark: bool = True) -> CustomTitleBar:
    """
    Helper function to install a custom title bar to an existing layout.
    
    This is useful when you want to add a title bar to a window without using
    the FramelessWindowMixin.
    
    Args:
        window: The parent window
        layout: The main vertical layout of the window
        title: Window title
        is_dark: Whether to use dark theme
        
    Returns:
        The created CustomTitleBar widget
    """
    from .app_style import AppStyle
    title_bar = CustomTitleBar(window, title)
    title_bar.apply_theme(is_dark)
    layout.insertWidget(0, title_bar)
    return title_bar
