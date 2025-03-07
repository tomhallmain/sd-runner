from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                 QLabel, QPushButton, QLineEdit, QListWidget,
                                 QDialog, QTextEdit)
from PyQt6.QtCore import Qt

from ui.dialog_base import DialogBase
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class ExpansionsWindow(DialogBase):
    expansions = {}
    
    def __init__(self, parent=None, toast_callback=None):
        super().__init__(parent, _("Expansions"), width=800, height=800)
        
        self.toast_callback = toast_callback
        self.filtered_expansions = list(ExpansionsWindow.expansions.items())
        
        self.setup_ui()
        self.load_expansions()

    def setup_ui(self):
        # Search box
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_("Search expansions..."))
        self.search_edit.textChanged.connect(self.filter_expansions)
        search_layout.addWidget(self.search_edit)
        self.add_layout_to_content(search_layout)

        # Expansions list
        self.expansions_list = QListWidget()
        self.expansions_list.currentItemChanged.connect(self.on_expansion_selected)
        self.add_widget_to_content(self.expansions_list)

        # Edit area
        edit_layout = QVBoxLayout()
        
        # Key input
        key_layout = QHBoxLayout()
        self.key_label = QLabel(_("Key:"))
        self.key_edit = QLineEdit()
        key_layout.addWidget(self.key_label)
        key_layout.addWidget(self.key_edit)
        edit_layout.addLayout(key_layout)
        
        # Value input
        value_layout = QVBoxLayout()
        self.value_label = QLabel(_("Value:"))
        self.value_edit = QTextEdit()
        value_layout.addWidget(self.value_label)
        value_layout.addWidget(self.value_edit)
        edit_layout.addLayout(value_layout)
        
        # Save button
        self.save_btn = QPushButton(_("Save"))
        self.save_btn.clicked.connect(self.save_expansion)
        edit_layout.addWidget(self.save_btn)
        
        self.add_layout_to_content(edit_layout)

        # Override default buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()

        self.new_btn = self.add_button(_("New"), self.new_expansion)
        self.delete_btn = self.add_button(_("Delete Selected"), self.delete_selected_expansion)
        self.close_btn = self.add_button(_("Close"), self.close)

    @staticmethod
    def set_expansions():
        ExpansionsWindow.expansions = app_info_cache.get("expansions", default_val={})

    @staticmethod
    def store_expansions():
        app_info_cache.set("expansions", ExpansionsWindow.expansions)

    def load_expansions(self):
        self.refresh()

    def filter_expansions(self, text):
        self.filtered_expansions = [
            (key, value) for key, value in ExpansionsWindow.expansions.items()
            if text.lower() in key.lower() or text.lower() in value.lower()
        ]
        self.refresh_list()

    def refresh_list(self):
        self.expansions_list.clear()
        for key, _ in self.filtered_expansions:
            self.expansions_list.addItem(key)

    def refresh(self):
        self.filtered_expansions = list(ExpansionsWindow.expansions.items())
        self.refresh_list()

    def on_expansion_selected(self, current, previous):
        if not current:
            self.key_edit.clear()
            self.value_edit.clear()
            return
            
        key = current.text()
        value = ExpansionsWindow.expansions.get(key, "")
        self.key_edit.setText(key)
        self.value_edit.setText(value)

    def new_expansion(self):
        self.expansions_list.clearSelection()
        self.key_edit.clear()
        self.value_edit.clear()

    def save_expansion(self):
        key = self.key_edit.text().strip()
        value = self.value_edit.toPlainText().strip()
        
        if not key or not value:
            return
            
        old_key = None
        if self.expansions_list.currentItem():
            old_key = self.expansions_list.currentItem().text()
            if old_key != key and old_key in ExpansionsWindow.expansions:
                del ExpansionsWindow.expansions[old_key]
                
        ExpansionsWindow.expansions[key] = value
        self.store_expansions()
        self.refresh()
        
        # Select the saved item
        items = self.expansions_list.findItems(key, Qt.MatchFlag.MatchExactly)
        if items:
            self.expansions_list.setCurrentItem(items[0])
            
        if self.toast_callback:
            if old_key and old_key != key:
                self.toast_callback(_("Updated expansion: {0} -> {1}").format(old_key, key))
            else:
                self.toast_callback(_("Saved expansion: {0}").format(key))

    def delete_selected_expansion(self):
        if not self.expansions_list.currentItem():
            return
            
        key = self.expansions_list.currentItem().text()
        if key in ExpansionsWindow.expansions:
            del ExpansionsWindow.expansions[key]
            self.store_expansions()
            self.refresh()
            self.key_edit.clear()
            self.value_edit.clear()
            if self.toast_callback:
                self.toast_callback(_("Deleted expansion: {0}").format(key))

# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.app_style import AppStyle
    
    def mock_toast(message):
        print(f"Toast: {message}")
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    window = ExpansionsWindow(toast_callback=mock_toast)
    window.show()
    
    sys.exit(app.exec()) 