from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QWidget)
from PyQt6.QtCore import Qt

from ui.app_style import AppStyle

class DialogBase(QDialog):
    """Base dialog class for the application's various windows."""
    
    def __init__(self, parent=None, title="Dialog", width=500, height=800):
        super().__init__(parent)
        
        # Set up window properties
        self.setWindowTitle(title)
        self.resize(width, height)
        self.setStyleSheet(f"""
            QDialog {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
            }}
            QLabel {{
                color: {AppStyle.FG_COLOR};
            }}
            QPushButton {{
                background-color: {AppStyle.BG_COLOR};
                color: {AppStyle.FG_COLOR};
                border: 1px solid {AppStyle.FG_COLOR};
                padding: 5px;
                border-radius: 3px;
            }}
            QPushButton:hover {{
                background-color: {AppStyle.FG_COLOR};
                color: {AppStyle.BG_COLOR};
            }}
        """)
        
        # Create main layout
        self.main_layout = QVBoxLayout(self)
        self.setLayout(self.main_layout)
        
        # Content area
        self.content_widget = QWidget(self)
        self.content_layout = QVBoxLayout(self.content_widget)
        self.main_layout.addWidget(self.content_widget)
        
        # Button area
        self.button_widget = QWidget(self)
        self.button_layout = QHBoxLayout(self.button_widget)
        self.main_layout.addWidget(self.button_widget)
        
        # Add default buttons
        self.create_buttons()
    
    def create_buttons(self):
        """Create default dialog buttons. Override to customize."""
        self.close_button = QPushButton("Close", self)
        self.close_button.clicked.connect(self.close)
        self.button_layout.addWidget(self.close_button)
    
    def add_widget_to_content(self, widget):
        """Add a widget to the content area."""
        self.content_layout.addWidget(widget)
    
    def add_layout_to_content(self, layout):
        """Add a layout to the content area."""
        self.content_layout.addLayout(layout)
    
    def add_button(self, text, callback=None, tooltip=None):
        """Add a button to the button area."""
        button = QPushButton(text, self)
        if callback:
            button.clicked.connect(callback)
        if tooltip:
            button.setToolTip(tooltip)
        self.button_layout.addWidget(button)
        return button
    
    def add_label(self, text, wrap=True):
        """Add a label to the content area."""
        label = QLabel(text, self)
        if wrap:
            label.setWordWrap(True)
        self.add_widget_to_content(label)
        return label

# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    
    class TestDialog(DialogBase):
        def __init__(self, parent=None):
            super().__init__(parent, "Test Dialog")
            
            # Add some test content
            self.add_label("This is a test dialog with some wrapped text that should demonstrate the basic functionality of the DialogBase class.")
            
            # Add a custom button
            self.add_button("Custom Action", lambda: print("Custom action clicked!"))
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    dialog = TestDialog()
    dialog.show()
    
    sys.exit(app.exec()) 