from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                                 QLabel, QPushButton, QLineEdit, QListWidget,
                                 QDialog, QTextEdit, QSpinBox, QCheckBox,
                                 QComboBox, QFileDialog)
from PyQt6.QtCore import Qt
import os
import json

from ui.dialog_base import DialogBase
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._

class ConceptEditorWindow(DialogBase):
    concepts = {}
    
    def __init__(self, parent=None, toast_callback=None):
        super().__init__(parent, _("Concept Editor"), width=1000, height=800)
        
        self.toast_callback = toast_callback
        self.filtered_concepts = list(ConceptEditorWindow.concepts.items())
        
        self.setup_ui()
        self.load_concepts()

    def setup_ui(self):
        # Main layout split into left and right panels
        main_layout = QHBoxLayout()
        
        # Left panel - List and search
        left_panel = QVBoxLayout()
        
        # Search box
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(_("Search concepts..."))
        self.search_edit.textChanged.connect(self.filter_concepts)
        left_panel.addWidget(self.search_edit)

        # Concepts list
        self.concepts_list = QListWidget()
        self.concepts_list.currentItemChanged.connect(self.on_concept_selected)
        left_panel.addWidget(self.concepts_list)
        
        # Left panel buttons
        left_buttons = QHBoxLayout()
        self.new_btn = QPushButton(_("New"))
        self.new_btn.clicked.connect(self.new_concept)
        self.delete_btn = QPushButton(_("Delete"))
        self.delete_btn.clicked.connect(self.delete_selected_concept)
        left_buttons.addWidget(self.new_btn)
        left_buttons.addWidget(self.delete_btn)
        left_panel.addLayout(left_buttons)
        
        # Add left panel to main layout
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        main_layout.addWidget(left_widget)
        
        # Right panel - Edit area
        right_panel = QVBoxLayout()
        
        # Name input
        name_layout = QHBoxLayout()
        self.name_label = QLabel(_("Name:"))
        self.name_edit = QLineEdit()
        name_layout.addWidget(self.name_label)
        name_layout.addWidget(self.name_edit)
        right_panel.addLayout(name_layout)
        
        # Type selection
        type_layout = QHBoxLayout()
        self.type_label = QLabel(_("Type:"))
        self.type_combo = QComboBox()
        self.type_combo.addItems(["text", "image"])
        type_layout.addWidget(self.type_label)
        type_layout.addWidget(self.type_combo)
        right_panel.addLayout(type_layout)
        
        # Trigger input
        trigger_layout = QHBoxLayout()
        self.trigger_label = QLabel(_("Trigger:"))
        self.trigger_edit = QLineEdit()
        trigger_layout.addWidget(self.trigger_label)
        trigger_layout.addWidget(self.trigger_edit)
        right_panel.addLayout(trigger_layout)
        
        # Weight input
        weight_layout = QHBoxLayout()
        self.weight_label = QLabel(_("Weight:"))
        self.weight_spin = QSpinBox()
        self.weight_spin.setRange(-100, 100)
        self.weight_spin.setValue(1)
        weight_layout.addWidget(self.weight_label)
        weight_layout.addWidget(self.weight_spin)
        right_panel.addLayout(weight_layout)
        
        # Value input
        value_layout = QVBoxLayout()
        self.value_label = QLabel(_("Value:"))
        self.value_edit = QTextEdit()
        value_layout.addWidget(self.value_label)
        value_layout.addWidget(self.value_edit)
        right_panel.addLayout(value_layout)
        
        # Image file selection (for image type)
        self.image_layout = QHBoxLayout()
        self.image_path_edit = QLineEdit()
        self.image_path_edit.setReadOnly(True)
        self.browse_btn = QPushButton(_("Browse"))
        self.browse_btn.clicked.connect(self.browse_image)
        self.image_layout.addWidget(self.image_path_edit)
        self.image_layout.addWidget(self.browse_btn)
        right_panel.addLayout(self.image_layout)
        
        # Options
        self.is_active_check = QCheckBox(_("Active"))
        self.is_active_check.setChecked(True)
        right_panel.addWidget(self.is_active_check)
        
        # Save button
        self.save_btn = QPushButton(_("Save"))
        self.save_btn.clicked.connect(self.save_concept)
        right_panel.addWidget(self.save_btn)
        
        # Add right panel to main layout
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        main_layout.addWidget(right_widget)
        
        # Set the main layout
        main_widget = QWidget()
        main_widget.setLayout(main_layout)
        self.add_widget_to_content(main_widget)

        # Override default buttons
        self.button_layout.removeWidget(self.close_button)
        self.close_button.deleteLater()

        # Import/Export buttons
        self.import_btn = self.add_button(_("Import"), self.import_concepts)
        self.export_btn = self.add_button(_("Export"), self.export_concepts)
        self.close_btn = self.add_button(_("Close"), self.close)

    @staticmethod
    def set_concepts():
        ConceptEditorWindow.concepts = app_info_cache.get("concepts", default_val={})

    @staticmethod
    def store_concepts():
        app_info_cache.set("concepts", ConceptEditorWindow.concepts)

    def load_concepts(self):
        self.refresh()

    def filter_concepts(self, text):
        self.filtered_concepts = [
            (key, value) for key, value in ConceptEditorWindow.concepts.items()
            if text.lower() in key.lower()
        ]
        self.refresh_list()

    def refresh_list(self):
        self.concepts_list.clear()
        for key, _ in self.filtered_concepts:
            self.concepts_list.addItem(key)

    def refresh(self):
        self.filtered_concepts = list(ConceptEditorWindow.concepts.items())
        self.refresh_list()

    def on_concept_selected(self, current, previous):
        if not current:
            self.clear_form()
            return
            
        key = current.text()
        concept = ConceptEditorWindow.concepts.get(key, {})
        
        self.name_edit.setText(key)
        self.type_combo.setCurrentText(concept.get("type", "text"))
        self.trigger_edit.setText(concept.get("trigger", ""))
        self.weight_spin.setValue(concept.get("weight", 1))
        self.value_edit.setText(concept.get("value", ""))
        self.image_path_edit.setText(concept.get("image_path", ""))
        self.is_active_check.setChecked(concept.get("is_active", True))

    def clear_form(self):
        self.name_edit.clear()
        self.type_combo.setCurrentText("text")
        self.trigger_edit.clear()
        self.weight_spin.setValue(1)
        self.value_edit.clear()
        self.image_path_edit.clear()
        self.is_active_check.setChecked(True)

    def new_concept(self):
        self.concepts_list.clearSelection()
        self.clear_form()

    def save_concept(self):
        name = self.name_edit.text().strip()
        if not name:
            return
            
        concept = {
            "type": self.type_combo.currentText(),
            "trigger": self.trigger_edit.text().strip(),
            "weight": self.weight_spin.value(),
            "value": self.value_edit.toPlainText().strip(),
            "image_path": self.image_path_edit.text().strip(),
            "is_active": self.is_active_check.isChecked()
        }
        
        old_name = None
        if self.concepts_list.currentItem():
            old_name = self.concepts_list.currentItem().text()
            if old_name != name and old_name in ConceptEditorWindow.concepts:
                del ConceptEditorWindow.concepts[old_name]
                
        ConceptEditorWindow.concepts[name] = concept
        self.store_concepts()
        self.refresh()
        
        # Select the saved item
        items = self.concepts_list.findItems(name, Qt.MatchFlag.MatchExactly)
        if items:
            self.concepts_list.setCurrentItem(items[0])
            
        if self.toast_callback:
            if old_name and old_name != name:
                self.toast_callback(_("Updated concept: {0} -> {1}").format(old_name, name))
            else:
                self.toast_callback(_("Saved concept: {0}").format(name))

    def delete_selected_concept(self):
        if not self.concepts_list.currentItem():
            return
            
        name = self.concepts_list.currentItem().text()
        if name in ConceptEditorWindow.concepts:
            del ConceptEditorWindow.concepts[name]
            self.store_concepts()
            self.refresh()
            self.clear_form()
            if self.toast_callback:
                self.toast_callback(_("Deleted concept: {0}").format(name))

    def browse_image(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            _("Select Image"),
            "",
            _("Image Files (*.png *.jpg *.jpeg *.bmp *.gif)")
        )
        if file_name:
            self.image_path_edit.setText(file_name)

    def import_concepts(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self,
            _("Import Concepts"),
            "",
            _("JSON Files (*.json)")
        )
        if not file_name:
            return
            
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                concepts = json.load(f)
            ConceptEditorWindow.concepts.update(concepts)
            self.store_concepts()
            self.refresh()
            if self.toast_callback:
                self.toast_callback(_("Imported concepts from: {0}").format(os.path.basename(file_name)))
        except Exception as e:
            if self.toast_callback:
                self.toast_callback(_("Error importing concepts: {0}").format(str(e)))

    def export_concepts(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self,
            _("Export Concepts"),
            "",
            _("JSON Files (*.json)")
        )
        if not file_name:
            return
            
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                json.dump(ConceptEditorWindow.concepts, f, indent=2, ensure_ascii=False)
            if self.toast_callback:
                self.toast_callback(_("Exported concepts to: {0}").format(os.path.basename(file_name)))
        except Exception as e:
            if self.toast_callback:
                self.toast_callback(_("Error exporting concepts: {0}").format(str(e)))

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
    
    window = ConceptEditorWindow(toast_callback=mock_toast)
    window.show()
    
    sys.exit(app.exec()) 