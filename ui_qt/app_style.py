"""
Qt (PySide6) application style for Media Compare.
Dark violet theme. Used by app_qt and ui widgets.
Includes title bar styling for frameless windows.
"""


class AppStyle:
    """Application theme and colors for the Qt UI. Dark violet by default."""
    IS_DEFAULT_THEME = True   # True = dark violet theme
    LIGHT_THEME = "light"
    DARK_THEME = "dark"

    # Dark violet palette (dark theme) — base: #26242f from config
    _DARK_BG_COLOR = "#26242f"
    _DARK_FG_COLOR = "#e8e6ef"
    _DARK_BG_SIDEBAR = "#1e1c26"
    _DARK_BG_BUTTON = "#33303d"
    _DARK_BG_BUTTON_HOVER = "#3f3c4a"
    _DARK_BG_INPUT = "#2d2b37"
    _DARK_BORDER_COLOR = "#33303d"
    _DARK_PROGRESS_CHUNK = "#5c4f8a"
    _DARK_MEDIA_BG = "#1e1c26"

    # Light theme palette
    _LIGHT_BG_COLOR = "#f0f4f8"
    _LIGHT_FG_COLOR = "#1a1a2e"
    _LIGHT_BG_SIDEBAR = "#e8ecf0"
    _LIGHT_BG_BUTTON = "#d8dce0"
    _LIGHT_BG_BUTTON_HOVER = "#c8ccd0"
    _LIGHT_BG_INPUT = "#ffffff"
    _LIGHT_BORDER_COLOR = "#c0c4c8"
    _LIGHT_PROGRESS_CHUNK = "#4a90d9"
    _LIGHT_MEDIA_BG = "#e8ecf0"

    # Active palette — updated by _apply_palette()
    BG_COLOR = _DARK_BG_COLOR
    FG_COLOR = _DARK_FG_COLOR
    BG_SIDEBAR = _DARK_BG_SIDEBAR
    BG_BUTTON = _DARK_BG_BUTTON
    BG_BUTTON_HOVER = _DARK_BG_BUTTON_HOVER
    BG_INPUT = _DARK_BG_INPUT
    BORDER_COLOR = _DARK_BORDER_COLOR
    PROGRESS_CHUNK = _DARK_PROGRESS_CHUNK
    MEDIA_BG = _DARK_MEDIA_BG

    # Legacy aliases for code that still references LIGHT_* directly
    LIGHT_BG_COLOR = _LIGHT_BG_COLOR
    LIGHT_FG_COLOR = _LIGHT_FG_COLOR
    LIGHT_BG_SIDEBAR = _LIGHT_BG_SIDEBAR
    LIGHT_BG_BUTTON = _LIGHT_BG_BUTTON
    LIGHT_BG_BUTTON_HOVER = _LIGHT_BG_BUTTON_HOVER
    LIGHT_BG_INPUT = _LIGHT_BG_INPUT
    LIGHT_BORDER_COLOR = _LIGHT_BORDER_COLOR
    LIGHT_PROGRESS_CHUNK = _LIGHT_PROGRESS_CHUNK
    LIGHT_MEDIA_BG = _LIGHT_MEDIA_BG
    
    # Title bar specific colors
    CLOSE_HOVER = "#e81123"
    CLOSE_PRESSED = "#f1707a"
    
    # Configuration
    _corner_radius = 10
    _is_dark = True

    @staticmethod
    def get_theme_name():
        return AppStyle.DARK_THEME if AppStyle.IS_DEFAULT_THEME else AppStyle.LIGHT_THEME

    @classmethod
    def toggle_theme(cls, to_theme=None):
        """Toggle between dark and light themes, or set a specific theme."""
        if to_theme == cls.DARK_THEME:
            cls.IS_DEFAULT_THEME = True
        elif to_theme == cls.LIGHT_THEME:
            cls.IS_DEFAULT_THEME = False
        else:
            cls.IS_DEFAULT_THEME = not cls.IS_DEFAULT_THEME
        cls._apply_palette()

    @classmethod
    def _apply_palette(cls):
        """Swap the active colour attributes to match the current theme."""
        dark = cls.IS_DEFAULT_THEME
        cls.BG_COLOR        = cls._DARK_BG_COLOR        if dark else cls._LIGHT_BG_COLOR
        cls.FG_COLOR        = cls._DARK_FG_COLOR        if dark else cls._LIGHT_FG_COLOR
        cls.BG_SIDEBAR      = cls._DARK_BG_SIDEBAR      if dark else cls._LIGHT_BG_SIDEBAR
        cls.BG_BUTTON       = cls._DARK_BG_BUTTON       if dark else cls._LIGHT_BG_BUTTON
        cls.BG_BUTTON_HOVER = cls._DARK_BG_BUTTON_HOVER if dark else cls._LIGHT_BG_BUTTON_HOVER
        cls.BG_INPUT        = cls._DARK_BG_INPUT        if dark else cls._LIGHT_BG_INPUT
        cls.BORDER_COLOR    = cls._DARK_BORDER_COLOR    if dark else cls._LIGHT_BORDER_COLOR
        cls.PROGRESS_CHUNK  = cls._DARK_PROGRESS_CHUNK  if dark else cls._LIGHT_PROGRESS_CHUNK
        cls.MEDIA_BG        = cls._DARK_MEDIA_BG        if dark else cls._LIGHT_MEDIA_BG

    @classmethod
    def set_corner_radius(cls, radius: int):
        """Set the corner radius for rounded window corners."""
        cls._corner_radius = radius
    
    @classmethod
    def get_corner_radius(cls) -> int:
        """Get the current corner radius."""
        return cls._corner_radius
    
    @classmethod
    def is_dark_theme(cls) -> bool:
        """Check if dark theme is active."""
        return cls.IS_DEFAULT_THEME
    
    @classmethod
    def get_colors(cls, is_dark: bool = None) -> dict:
        """Get color dictionary for the specified theme."""
        if is_dark is None:
            is_dark = cls.IS_DEFAULT_THEME

        if is_dark:
            return {
                'bg': cls._DARK_BG_COLOR,
                'fg': cls._DARK_FG_COLOR,
                'sidebar': cls._DARK_BG_SIDEBAR,
                'button': cls._DARK_BG_BUTTON,
                'hover': cls._DARK_BG_BUTTON_HOVER,
                'input': cls._DARK_BG_INPUT,
                'border': cls._DARK_BORDER_COLOR,
                'progress': cls._DARK_PROGRESS_CHUNK,
                'media': cls._DARK_MEDIA_BG,
            }
        else:
            return {
                'bg': cls._LIGHT_BG_COLOR,
                'fg': cls._LIGHT_FG_COLOR,
                'sidebar': cls._LIGHT_BG_SIDEBAR,
                'button': cls._LIGHT_BG_BUTTON,
                'hover': cls._LIGHT_BG_BUTTON_HOVER,
                'input': cls._LIGHT_BG_INPUT,
                'border': cls._LIGHT_BORDER_COLOR,
                'progress': cls._LIGHT_PROGRESS_CHUNK,
                'media': cls._LIGHT_MEDIA_BG,
            }

    @staticmethod
    def get_stylesheet():
        """Return a Qt stylesheet string for the application (dark blue theme).
        Applied once on the top-level window; all child widgets inherit.
        QComboBox is styled only at top level (no ::drop-down or ::down-arrow) so the
        platform draws the arrow; see BookmarkManager app_style for same approach."""
        return f"""
            QMainWindow, QDialog, QWidget, QFrame {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
            }}
            QLabel {{
                color: {AppStyle.FG_COLOR};
                padding: 2px 0;
            }}
            QLineEdit {{
                background-color: {AppStyle.BG_INPUT};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.BORDER_COLOR};
                padding: 4px 8px;
                border-radius: 4px;
            }}
            QPlainTextEdit, QTextEdit {{
                background-color: {AppStyle.BG_INPUT};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.BORDER_COLOR};
                padding: 6px 8px;
                border-radius: 4px;
                selection-background-color: {AppStyle.BG_BUTTON_HOVER};
            }}
            QTableWidget {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
                gridline-color: {AppStyle.BORDER_COLOR};
            }}
            QTableWidget::item {{
                color: {AppStyle.FG_COLOR};
            }}
            QHeaderView::section {{
                background-color: {AppStyle.BG_BUTTON};
                color: {AppStyle.FG_COLOR};
                padding: 6px;
                border: 1px solid {AppStyle.BORDER_COLOR};
            }}
            QScrollArea {{
                background-color: {AppStyle.BG_COLOR};
                border: none;
            }}
            QPushButton {{
                background-color: {AppStyle.BG_BUTTON};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.BORDER_COLOR};
                padding: 3px 10px;
                border-radius: 4px;
            }}
            QPushButton:hover {{
                background-color: {AppStyle.BG_BUTTON_HOVER};
            }}
            QPushButton:pressed {{
                background-color: {AppStyle.BG_INPUT};
            }}
            QComboBox {{
                background-color: {AppStyle.BG_INPUT};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.BORDER_COLOR};
                padding: 3px 8px;
                border-radius: 4px;
                min-height: 1.2em;
            }}
            QComboBox:hover {{
                border-color: {AppStyle.PROGRESS_CHUNK};
            }}
            QComboBox QAbstractItemView {{
                background-color: {AppStyle.BG_INPUT};
                color: {AppStyle.FG_COLOR};
                selection-background-color: {AppStyle.BG_BUTTON_HOVER};
            }}
            QSlider::groove:horizontal {{
                border: 1px solid {AppStyle.BORDER_COLOR};
                height: 6px;
                background: {AppStyle.BG_INPUT};
                border-radius: 3px;
            }}
            QSlider::handle:horizontal {{
                background: {AppStyle.PROGRESS_CHUNK};
                border: 1px solid {AppStyle.BORDER_COLOR};
                width: 14px;
                margin: -4px 0;
                border-radius: 7px;
            }}
            QSlider::handle:horizontal:hover {{
                background: {AppStyle.BG_BUTTON_HOVER};
            }}
            QCheckBox {{
                color: {AppStyle.FG_COLOR};
                spacing: 6px;
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border: 1px solid {AppStyle.BORDER_COLOR};
                border-radius: 3px;
                background: {AppStyle.BG_INPUT};
            }}
            QCheckBox::indicator:checked {{
                background: {AppStyle.PROGRESS_CHUNK};
            }}
            QProgressBar {{
                border: 1px solid {AppStyle.BORDER_COLOR};
                border-radius: 4px;
                background: {AppStyle.BG_INPUT};
            }}
            QProgressBar::chunk {{
                background-color: {AppStyle.PROGRESS_CHUNK};
                border-radius: 3px;
            }}
            QMenuBar {{
                background-color: {AppStyle.BG_SIDEBAR};
                color: {AppStyle.FG_COLOR};
            }}
            QMenuBar::item:selected {{
                background-color: {AppStyle.BG_BUTTON_HOVER};
            }}
            QMenu {{
                background-color: {AppStyle.BG_SIDEBAR};
                color: {AppStyle.FG_COLOR};
            }}
            QMenu::item:selected {{
                background-color: {AppStyle.BG_BUTTON_HOVER};
            }}
        """
    
    @classmethod
    def get_frameless_stylesheet(cls, is_dark: bool = None) -> str:
        """Get additional stylesheet for frameless windows with rounded corners."""
        if is_dark is None:
            is_dark = cls.IS_DEFAULT_THEME
        
        colors = cls.get_colors(is_dark)
        radius = cls._corner_radius
        
        return f"""
            /* Base styling for frameless window */
            QMainWindow {{
                background-color: transparent;
            }}
            
            /* Transparent outer container for rounded corners */
            QWidget#transparentOuter {{
                background-color: transparent;
            }}
            
            /* Main frame with rounded corners - the visible window background */
            QFrame#mainFrame {{
                background-color: {colors['bg']};
                border: 1px solid {colors['border']};
                border-radius: {radius}px;
            }}
            
            /* Content area styling */
            QWidget#contentArea {{
                background-color: {colors['bg']};
                border-bottom-left-radius: {radius}px;
                border-bottom-right-radius: {radius}px;
            }}
            
            /* Title bar menu dropdown styling */
            QMenu {{
                background-color: {colors['sidebar']};
                color: {colors['fg']};
                border: 1px solid {colors['border']};
                padding: 4px 0;
            }}
            QMenu::item {{
                padding: 6px 20px;
            }}
            QMenu::item:selected {{
                background-color: {colors['hover']};
            }}
            QMenu::separator {{
                height: 1px;
                background-color: {colors['border']};
                margin: 4px 8px;
            }}
        """
    
    @classmethod
    def get_title_bar_style(cls, is_dark: bool = None) -> str:
        """Get the stylesheet for the custom title bar."""
        if is_dark is None:
            is_dark = cls.IS_DEFAULT_THEME
        
        colors = cls.get_colors(is_dark)
        radius = cls._corner_radius
        
        return f"""
            CustomTitleBar {{
                background-color: {colors['bg']};
                border-bottom: 1px solid {colors['border']};
                border-top-left-radius: {radius}px;
                border-top-right-radius: {radius}px;
            }}
        """
    
    @classmethod
    def get_title_bar_button_style(cls, button_type: str, is_dark: bool = None) -> str:
        """
        Get the stylesheet for a title bar button.
        
        Args:
            button_type: One of 'minimize', 'maximize', 'close'
            is_dark: Whether dark theme is active
        """
        if is_dark is None:
            is_dark = cls.IS_DEFAULT_THEME
            
        colors = cls.get_colors(is_dark)
        
        # Common button properties
        base_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {colors['fg']};
                padding: 0px;
                margin: 0px;
            }}
        """
        
        if button_type == "close":
            return base_style + f"""
                QPushButton {{
                    font-size: 12px;
                    font-family: "Segoe MDL2 Assets", "Segoe UI Symbol", sans-serif;
                }}
                QPushButton:hover {{
                    background-color: {cls.CLOSE_HOVER};
                    color: white;
                }}
                QPushButton:pressed {{
                    background-color: {cls.CLOSE_PRESSED};
                    color: white;
                }}
            """
        else:
            return base_style + f"""
                QPushButton {{
                    font-size: 11px;
                    font-family: "Segoe MDL2 Assets", "Segoe UI Symbol", sans-serif;
                }}
                QPushButton:hover {{
                    background-color: {colors['hover']};
                }}
                QPushButton:pressed {{
                    background-color: {colors['hover']};
                }}
            """
    
    @classmethod
    def apply_to_title_bar(cls, title_bar, is_dark: bool = None):
        """
        Apply theme styling to a CustomTitleBar widget.
        
        Args:
            title_bar: CustomTitleBar instance
            is_dark: Whether dark theme is active
        """
        if is_dark is None:
            is_dark = cls.IS_DEFAULT_THEME
            
        colors = cls.get_colors(is_dark)
        
        # Apply title bar container style
        title_bar.setStyleSheet(cls.get_title_bar_style(is_dark))
        
        # Apply title label style
        title_bar.title_label.setStyleSheet(
            f"color: {colors['fg']}; font-size: 12px; background: transparent;"
        )
        
        # Apply button styles
        title_bar.minimize_btn.setStyleSheet(cls.get_title_bar_button_style('minimize', is_dark))
        title_bar.maximize_btn.setStyleSheet(cls.get_title_bar_button_style('maximize', is_dark))
        title_bar.close_btn.setStyleSheet(cls.get_title_bar_button_style('close', is_dark))
