from PyQt6.QtWidgets import QLineEdit, QCompleter, QWidget, QVBoxLayout
from PyQt6.QtCore import Qt, pyqtSignal
import re

class AutocompleteLineEdit(QLineEdit):
    """A QLineEdit with autocomplete functionality."""
    
    def __init__(self, completions=None, parent=None, matches_function=None):
        super().__init__(parent)
        
        self.completions = completions or []
        self.matches_function = matches_function or self.default_matches
        
        # Setup completer
        self.completer = QCompleter(self.completions)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setCompleter(self.completer)
        
        # Connect signals
        self.textChanged.connect(self.handle_text_changed)
        
    def handle_text_changed(self, text):
        """Update completer's model when text changes."""
        matches = [item for item in self.completions if self.matches_function(text, item)]
        self.completer.model().setStringList(matches)
        
    @staticmethod
    def default_matches(field_value, completion_entry):
        """Default matching function using case-insensitive substring match."""
        if not field_value:
            return True
        return field_value.lower() in completion_entry.lower()
    
    def set_completions(self, completions):
        """Update the list of completion options."""
        self.completions = completions
        self.completer.model().setStringList(completions)

# Example usage and test
if __name__ == '__main__':
    import sys
    from PyQt6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    
    # Test data
    test_completions = [
        'Dora Lyons (7714)',
        'Hannah Golden (6010)',
        'Walker Burns (9390)'
    ]
    
    # Custom match function example
    def custom_matches(field_value, completion_entry):
        pattern = re.compile(re.escape(field_value) + '.*', re.IGNORECASE)
        return bool(re.match(pattern, completion_entry))
    
    # Create test window
    window = QWidget()
    layout = QVBoxLayout()
    
    # Create autocomplete widget
    auto_edit = AutocompleteLineEdit(
        completions=test_completions,
        matches_function=custom_matches
    )
    
    layout.addWidget(auto_edit)
    window.setLayout(layout)
    window.show()
    
    sys.exit(app.exec()) 