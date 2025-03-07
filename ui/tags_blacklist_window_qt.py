from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                 QLabel, QPushButton, QLineEdit, QListWidget,
                                 QDialog)
from PyQt6.QtCore import Qt

from ui.dialog_base import DialogBase
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class TagsBlacklistWindow(DialogBase):
    blacklisted_tags = []
    
    def __init__(self, parent=None, toast_callback=None):
        super().__init__(parent, _("Tags Blacklist"), width=600, height=800)
        
        self.toast_callback = toast_callback
        self.filtered_tags = TagsBlacklistWindow.blacklisted_tags[:]
        
        self.setup_ui()
        self.load_tags()

    def setup_ui(self):
        # Search box
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_("Search tags..."))
        self.search_edit.textChanged.connect(self.filter_tags)
        search_layout.addWidget(self.search_edit)
        self.add_layout_to_content(search_layout)

        # Tags list
        self.tags_list = QListWidget()
        self.add_widget_to_content(self.tags_list)

        # Add tag controls
        add_layout = QHBoxLayout()
        self.add_edit = QLineEdit()
        self.add_edit.setPlaceholderText(_("Enter tag to blacklist"))
        self.add_btn = QPushButton(_("Add Tag"))
        self.add_btn.clicked.connect(self.add_tag)
        add_layout.addWidget(self.add_edit)
        add_layout.addWidget(self.add_btn)
        self.add_layout_to_content(add_layout)

        # Override default buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()

        self.delete_btn = self.add_button(_("Delete Selected"), self.delete_selected_tag)
        self.close_btn = self.add_button(_("Close"), self.close)

    @staticmethod
    def set_tags():
        TagsBlacklistWindow.blacklisted_tags = app_info_cache.get("blacklisted_tags", default_val=[])

    @staticmethod
    def store_tags():
        app_info_cache.set("blacklisted_tags", TagsBlacklistWindow.blacklisted_tags)

    def load_tags(self):
        self.refresh()

    def filter_tags(self, text):
        self.filtered_tags = [
            tag for tag in TagsBlacklistWindow.blacklisted_tags
            if text.lower() in tag.lower()
        ]
        self.refresh_list()

    def refresh_list(self):
        self.tags_list.clear()
        for tag in self.filtered_tags:
            self.tags_list.addItem(tag)

    def refresh(self):
        self.filtered_tags = TagsBlacklistWindow.blacklisted_tags[:]
        self.refresh_list()

    def add_tag(self):
        tag = self.add_edit.text().strip()
        if not tag:
            return
            
        if tag not in TagsBlacklistWindow.blacklisted_tags:
            TagsBlacklistWindow.blacklisted_tags.append(tag)
            self.store_tags()
            self.refresh()
            self.add_edit.clear()
            if self.toast_callback:
                self.toast_callback(_("Added tag to blacklist: {0}").format(tag))

    def delete_selected_tag(self):
        if not self.tags_list.currentItem():
            return
            
        tag = self.tags_list.currentItem().text()
        if tag in TagsBlacklistWindow.blacklisted_tags:
            TagsBlacklistWindow.blacklisted_tags.remove(tag)
            self.store_tags()
            self.refresh()
            if self.toast_callback:
                self.toast_callback(_("Removed tag from blacklist: {0}").format(tag))

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
    
    window = TagsBlacklistWindow(toast_callback=mock_toast)
    window.show()
    
    sys.exit(app.exec()) 