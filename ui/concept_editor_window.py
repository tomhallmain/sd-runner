from tkinter import Entry, Frame, Label, StringVar, messagebox, LEFT, W, Listbox, END, SINGLE, BOTH, Y, Scrollbar, Checkbutton, IntVar, Toplevel
from tkinter.ttk import Button, Combobox

from sd_runner.concepts import Concepts, SFW, NSFW, NSFL, ArtStyles
from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.config import config
from utils.translations import I18N

_ = I18N._

class ConceptEditorWindow():
    last_set_concept = None
    concept_change_history = []
    MAX_CONCEPTS = 50
    MAX_HEIGHT = 400
    N_CONCEPTS_CUTOFF = 30
    COL_0_WIDTH = 600
    top_level = None

    @staticmethod
    def load_concept_changes():
        ConceptEditorWindow.concept_change_history = app_info_cache.get("concept_changes", default_val=[])

    @staticmethod
    def store_concept_changes():
        app_info_cache.set("concept_changes", ConceptEditorWindow.concept_change_history)

    @staticmethod
    def get_history_concept_change(start_index=0):
        # Get a previous concept.
        concept = None
        for i in range(len(ConceptEditorWindow.concept_change_history)):
            if i < start_index:
                continue
            concept = ConceptEditorWindow.concept_change_history[i]
            break
        return concept

    @staticmethod
    def update_history(tag):
        if len(ConceptEditorWindow.concept_change_history) > 0 and \
                tag == ConceptEditorWindow.concept_change_history[0]:
            return
        ConceptEditorWindow.concept_change_history.insert(0, tag)
        if len(ConceptEditorWindow.concept_change_history) > ConceptEditorWindow.MAX_CONCEPTS:
            del ConceptEditorWindow.concept_change_history[-1]

    @staticmethod
    def get_geometry(is_gui=True):
        width = 500
        height = 400
        return f"{width}x{height}"

    def __init__(self, master, app_actions):
        ConceptEditorWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        ConceptEditorWindow.top_level.geometry(self.get_geometry())
        self.master = ConceptEditorWindow.top_level
        self.app_actions = app_actions
        self.search_text = ""
        self.filtered_concepts = []
        self.concept_files = []
        self.current_concept = None
        self.current_file = None
        # Define categories with their class and default checked state
        self.file_categories = {
            "SFW": (SFW, True),  # (class, default_checked)
            "NSFW": (NSFW, False),
            "NSFL": (NSFL, False),
            "Art Styles": (ArtStyles, True),
            "Dictionary": (None, False)  # Special case for dictionary file
        }
        self.category_vars = {}  # Store checkbox variables
        self.loaded_concepts = {}  # Cache for loaded concepts by file

        # Setup main frame
        self.frame = Frame(self.master)
        self.frame.grid(column=0, row=0, sticky="nsew")
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)
        self.frame.config(bg=AppStyle.BG_COLOR)

        # Create main layout
        self.setup_ui()
        
        # Load initial data
        self.load_concept_files()
        self.refresh()

        # Bind events
        self.master.bind("<Key>", self.filter_concepts)
        self.master.bind("<Return>", self.save_concept)
        self.master.bind("<Escape>", self.close_windows)
        self.master.protocol("WM_DELETE_WINDOW", self.close_windows)

    def setup_ui(self):
        # Search frame
        search_frame = Frame(self.frame, bg=AppStyle.BG_COLOR)
        search_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=5)
        search_frame.columnconfigure(1, weight=1)
        
        Label(search_frame, text=_("Search/Add Concept:"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(row=0, column=0, padx=5)
        self.search_var = StringVar()
        self.search_entry = Entry(search_frame, textvariable=self.search_var, width=40)
        self.search_entry.grid(row=0, column=1, padx=5, sticky="ew")
        self.search_entry.bind("<KeyRelease>", self.filter_concepts)

        # Main content frame
        content_frame = Frame(self.frame, bg=AppStyle.BG_COLOR)
        content_frame.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)
        content_frame.columnconfigure(0, weight=1)
        content_frame.rowconfigure(0, weight=1)

        # Left panel - Concept list and controls
        left_frame = Frame(content_frame, bg=AppStyle.BG_COLOR)
        left_frame.grid(row=0, column=0, sticky="nsew", padx=5)
        left_frame.columnconfigure(0, weight=1)
        left_frame.rowconfigure(1, weight=1)  # Make concept list expand vertically
        
        # Category checkboxes
        checkbox_frame = Frame(left_frame, bg=AppStyle.BG_COLOR)
        checkbox_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
        
        for i, (category, (class_obj, default_checked)) in enumerate(self.file_categories.items()):
            var = IntVar(value=1 if default_checked else 0)
            self.category_vars[category] = var
            cb = Checkbutton(checkbox_frame, text=category, variable=var, command=self.refresh)
            cb.grid(row=0, column=i, padx=5)
        
        # Concept list with scrollbar
        list_frame = Frame(left_frame, bg=AppStyle.BG_COLOR)
        list_frame.grid(row=1, column=0, sticky="nsew", pady=(0, 5))
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        
        scrollbar = Scrollbar(list_frame)
        scrollbar.grid(row=0, column=1, sticky="ns")
        
        self.concept_list = Listbox(list_frame, yscrollcommand=scrollbar.set, selectmode=SINGLE,
                                  bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR)
        self.concept_list.grid(row=0, column=0, sticky="nsew")
        scrollbar.config(command=self.concept_list.yview)
        self.concept_list.bind("<<ListboxSelect>>", self.on_concept_select)

        # Edit controls
        edit_frame = Frame(left_frame, bg=AppStyle.BG_COLOR)
        edit_frame.grid(row=2, column=0, sticky="ew", pady=5)
        edit_frame.columnconfigure(1, weight=1)

        # File selection
        Label(edit_frame, text=_("File:"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(row=0, column=0, padx=5, sticky="w")
        self.file_combo = Combobox(edit_frame, values=[], state="readonly", width=37)
        self.file_combo.grid(row=0, column=1, padx=5, sticky="ew", pady=5)

        # Buttons
        button_frame = Frame(edit_frame, bg=AppStyle.BG_COLOR)
        button_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=5)
        
        self.save_btn = Button(button_frame, text=_("Save"), command=self.save_concept)
        self.save_btn.grid(row=0, column=0, padx=5)
        
        self.delete_btn = Button(button_frame, text=_("Delete"), command=self.delete_concept)
        self.delete_btn.grid(row=0, column=1, padx=5)

    def load_concept_files(self):
        """Load all concept files from the concepts directory"""
        self.concept_files = []
        
        # Add files from each category based on checkbox state
        for category, (class_obj, default_checked) in self.file_categories.items():
            if self.category_vars[category].get():
                if category == "Dictionary":
                    # Special case for dictionary file
                    self.concept_files.append(Concepts.ALL_WORDS_LIST_FILENAME)
                else:
                    # Get all non-private attributes from the class
                    for attr_name in dir(class_obj):
                        if not attr_name.startswith('_'):
                            attr_value = getattr(class_obj, attr_name)
                            if isinstance(attr_value, str):  # Only add string attributes (filenames)
                                self.concept_files.append(attr_value)
                
        self.file_combo['values'] = sorted(self.concept_files)

    def get_concepts_from_file(self, filename):
        """Get concepts from a file, using cache if available"""
        if filename not in self.loaded_concepts:
            self.loaded_concepts[filename] = Concepts.load(filename)
        return self.loaded_concepts[filename]

    def filter_concepts(self, event=None):
        """Filter concepts based on search text"""
        self.search_text = self.search_var.get().lower()
        if not self.search_text:  # If search is empty, clear the list
            self.concept_list.delete(0, END)
            self.filtered_concepts = []
            return
            
        self.refresh()

    def refresh(self):
        """Refresh the concept list based on current filter and selected categories"""
        # Reload concept files based on checkbox states
        self.load_concept_files()
        
        self.concept_list.delete(0, END)
        self.filtered_concepts = []
        
        if not self.search_text:  # Don't load concepts if there's no search
            self.concept_list.insert(END, _("Enter search text to see concepts..."))
            return
            
        # Search through enabled concept files
        tier1_matches = []  # Matches at start of string
        tier2_matches = []  # Matches after word boundary
        tier3_matches = []  # Any other matches
        
        for filename in self.concept_files:
            concepts = self.get_concepts_from_file(filename)
            for concept in concepts:
                concept_lower = concept.lower()
                if self.search_text in concept_lower:
                    # Check for tier 1: match at start
                    if concept_lower.startswith(self.search_text):
                        tier1_matches.append(concept)
                    # Check for tier 2: match after word boundary
                    elif any(self.search_text in word for word in concept_lower.split()):
                        tier2_matches.append(concept)
                    # Tier 3: any other match
                    else:
                        tier3_matches.append(concept)
        
        # Combine all matches in priority order
        self.filtered_concepts = tier1_matches + tier2_matches + tier3_matches
        
        # Add to listbox
        for concept in self.filtered_concepts:
            self.concept_list.insert(END, concept)

    def on_concept_select(self, event):
        """Handle concept selection from list"""
        selection = self.concept_list.curselection()
        if not selection:
            return
            
        self.current_concept = self.concept_list.get(selection[0])
        
        # Find which file contains this concept
        for filename in self.concept_files:
            concepts = self.get_concepts_from_file(filename)
            if self.current_concept in concepts:
                self.current_file = filename
                self.file_combo.set(filename)
                break

    def save_concept(self, event=None):
        """Save a new concept to the selected file"""
        new_concept = self.search_var.get().strip()
        if not new_concept:
            return
            
        selected_file = self.file_combo.get()
        if not selected_file:
            messagebox.showerror(_("Error"), _("Please select a file to save to"))
            return
            
        # Load current concepts from file
        concepts = self.get_concepts_from_file(selected_file)
        
        # Add new concept if not already present
        if new_concept not in concepts:
            concepts.append(new_concept)
            concepts.sort()
            
            # Save to file
            Concepts.save(selected_file, concepts)
                
            self.app_actions.toast(_("Saved concept: {0}").format(new_concept))
            
            # Search for the new concept to confirm it was saved
            self.refresh()
            
            # Select the new concept in the list
            items = self.concept_list.get(0, END)
            if new_concept in items:
                idx = items.index(new_concept)
                self.concept_list.selection_clear(0, END)
                self.concept_list.selection_set(idx)
                self.concept_list.see(idx)
                
            # Update current file
            self.current_file = selected_file

    def delete_concept(self):
        """Delete the current concept from its file"""
        if not self.current_concept or not self.current_file:
            return
            
        if messagebox.askyesno(_("Confirm"), _("Delete concept: {0}?").format(self.current_concept)):
            concepts = self.get_concepts_from_file(self.current_file)
            if self.current_concept in concepts:
                concepts.remove(self.current_concept)
                Concepts.save(self.current_file, concepts)
                    
                self.app_actions.toast(_("Deleted concept: {0}").format(self.current_concept))
                self.current_concept = None
                self.current_file = None
                self.search_var.set("")
                self.file_combo.set("")
                self.refresh()

    def close_windows(self, event=None):
        """Close the window"""
        self.master.destroy()

