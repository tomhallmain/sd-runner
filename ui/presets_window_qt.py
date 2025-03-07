from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, 
                                 QLabel, QPushButton, QLineEdit, QListWidget,
                                 QScrollArea)
from PyQt6.QtCore import Qt, pyqtSignal

from ui.dialog_base import DialogBase
from ui.preset import Preset
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class PresetsWindow(DialogBase):
    """Window for managing presets."""
    
    # Class variables
    recent_presets = []
    last_set_preset = None
    preset_history = []
    MAX_PRESETS = 50
    MAX_HEIGHT = 900
    N_TAGS_CUTOFF = 30
    COL_0_WIDTH = 600
    
    def __init__(self, parent=None, toast_callback=None, construct_preset_callback=None, 
                 apply_preset_callback=None):
        super().__init__(parent, _("Presets Window"), width=600, height=800)
        
        self.toast_callback = toast_callback
        self.construct_preset_callback = construct_preset_callback
        self.apply_preset_callback = apply_preset_callback
        
        self.filtered_presets = PresetsWindow.recent_presets[:]
        self.setup_ui()
        self.load_presets()
    
    def setup_ui(self):
        """Set up the UI components."""
        # Search box
        search_layout = QHBoxLayout()
        self.search_edit = QLineEdit(self)
        self.search_edit.setPlaceholderText(_("Search presets..."))
        self.search_edit.textChanged.connect(self.filter_presets)
        search_layout.addWidget(self.search_edit)
        self.add_layout_to_content(search_layout)
        
        # Presets list
        self.presets_list = QListWidget(self)
        self.presets_list.itemDoubleClicked.connect(self.apply_selected_preset)
        self.add_widget_to_content(self.presets_list)
        
        # Override create_buttons to add our custom buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()
        
        self.add_button(_("New Preset"), self.create_new_preset)
        self.add_button(_("Apply Selected"), self.apply_selected_preset)
        self.add_button(_("Delete Selected"), self.delete_selected_preset)
        self.add_button(_("Close"), self.close)
    
    def load_presets(self):
        """Load presets from cache."""
        PresetsWindow.recent_presets = []
        for preset_dict in list(app_info_cache.get("recent_presets", default_val=[])):
            PresetsWindow.recent_presets.append(Preset.from_dict(preset_dict))
        self.refresh()
    
    def store_presets(self):
        """Store presets to cache."""
        preset_dicts = []
        for preset in PresetsWindow.recent_presets:
            preset_dicts.append(preset.to_dict())
        app_info_cache.set("recent_presets", preset_dicts)
    
    def filter_presets(self, text):
        """Filter presets based on search text."""
        self.filtered_presets = [
            preset for preset in PresetsWindow.recent_presets
            if text.lower() in preset.name.lower()
        ]
        self.refresh_list()
    
    def refresh_list(self):
        """Refresh the presets list widget."""
        self.presets_list.clear()
        for preset in self.filtered_presets:
            self.presets_list.addItem(preset.name)
    
    def refresh(self):
        """Refresh the entire window."""
        self.filtered_presets = PresetsWindow.recent_presets[:]
        self.refresh_list()
    
    def create_new_preset(self):
        """Create a new preset from current settings."""
        if not self.construct_preset_callback:
            return
            
        preset = self.construct_preset_callback()
        if preset in PresetsWindow.recent_presets:
            PresetsWindow.recent_presets.remove(preset)
        
        PresetsWindow.recent_presets.insert(0, preset)
        if len(PresetsWindow.recent_presets) > PresetsWindow.MAX_PRESETS:
            PresetsWindow.recent_presets.pop()
        
        self.store_presets()
        self.refresh()
        
        if self.toast_callback:
            self.toast_callback(_("Created new preset: {0}").format(preset.name))
    
    def apply_selected_preset(self):
        """Apply the selected preset."""
        if not self.presets_list.currentItem():
            return
            
        preset_name = self.presets_list.currentItem().text()
        preset = self.get_preset_by_name(preset_name)
        
        if preset and self.apply_preset_callback:
            self.apply_preset_callback(preset)
            if self.toast_callback:
                self.toast_callback(_("Applied preset: {0}").format(preset.name))
    
    def delete_selected_preset(self):
        """Delete the selected preset."""
        if not self.presets_list.currentItem():
            return
            
        preset_name = self.presets_list.currentItem().text()
        preset = self.get_preset_by_name(preset_name)
        
        if preset:
            PresetsWindow.recent_presets.remove(preset)
            self.store_presets()
            self.refresh()
            
            if self.toast_callback:
                self.toast_callback(_("Deleted preset: {0}").format(preset.name))
    
    @staticmethod
    def get_preset_by_name(name):
        """Get a preset by its name."""
        for preset in PresetsWindow.recent_presets:
            if name == preset.name:
                return preset
        return None
    
    @staticmethod
    def get_preset_names():
        """Get a sorted list of preset names."""
        return sorted(list(map(lambda x: x.name, PresetsWindow.recent_presets)))
    
    @staticmethod
    def get_most_recent_preset_name():
        """Get the name of the most recent preset."""
        return (PresetsWindow.recent_presets[0].name 
                if PresetsWindow.recent_presets 
                else _("New Preset (ERROR no presets found)"))

# Example usage
if __name__ == "__main__":
    import sys
    from PyQt6.QtWidgets import QApplication
    from ui.app_style import AppStyle
    
    def mock_toast(message):
        print(f"Toast: {message}")
    
    def mock_construct_preset():
        return Preset("Test Preset", "test", {})
    
    def mock_apply_preset(preset):
        print(f"Applying preset: {preset.name}")
    
    app = QApplication(sys.argv)
    
    # Set up dark theme for testing
    AppStyle.IS_DEFAULT_THEME = True
    AppStyle.BG_COLOR = "#053E10"
    AppStyle.FG_COLOR = "white"
    
    window = PresetsWindow(
        toast_callback=mock_toast,
        construct_preset_callback=mock_construct_preset,
        apply_preset_callback=mock_apply_preset
    )
    window.show()
    
    sys.exit(app.exec()) 