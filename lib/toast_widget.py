from PyQt6.QtWidgets import QLabel, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, QTimer, QPoint

class ToastWidget(QWidget):
    def __init__(self, parent=None, message="", duration=2000):
        super().__init__(parent)
        
        # Set window flags
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Create layout
        layout = QVBoxLayout()
        self.setLayout(layout)
        
        # Create label
        self.label = QLabel(message)
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.label.setStyleSheet("""
            QLabel {
                color: white;
                background-color: rgba(40, 40, 40, 200);
                border-radius: 10px;
                padding: 10px 20px;
                font-size: 12pt;
            }
        """)
        layout.addWidget(self.label)
        
        # Position the toast
        if parent:
            parent_rect = parent.geometry()
            x = parent_rect.right() - self.sizeHint().width()
            y = parent_rect.top()
            self.move(QPoint(x, y))
        
        # Set up auto-close timer
        QTimer.singleShot(duration, self.close)
    
    @classmethod
    def show_message(cls, parent, message, duration=2000):
        """Convenience method to create and show a toast message."""
        toast = cls(parent, message, duration)
        toast.show()
        return toast

# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton
    
    class TestWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("Toast Test")
            self.resize(400, 300)
            
            button = QPushButton("Show Toast", self)
            button.move(150, 150)
            button.clicked.connect(self.show_toast)
        
        def show_toast(self):
            ToastWidget.show_message(self, "This is a test toast message!")
    
    app = QApplication(sys.argv)
    window = TestWindow()
    window.show()
    sys.exit(app.exec()) 