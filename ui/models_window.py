from datetime import datetime
import time
import os
from tkinter import Frame, Label, StringVar, Entry, Scrollbar, Text
import tkinter.font as fnt
from tkinter.ttk import Button, Notebook, Treeview
from typing import Optional, Any

from lib.multi_display import SmartToplevel
from sd_runner.models import Model
from ui.app_style import AppStyle
from ui.auth.password_utils import require_password
from utils.globals import ArchitectureType, ProtectedActions, PromptMode
from utils.translations import I18N
from lib.lora_trigger_extractor import get_trigger_info, create_safetriggers_file, TriggerInfo, is_safetriggers_available

_ = I18N._


class ModelsWindow:
    top_level: Optional[SmartToplevel] = None
    _checkpoints_cache: Optional[list[tuple[str, str, str]]] = None  # (name, arch_type, created_date)
    _adapters_cache: Optional[list[tuple[str, str, str]]] = None    # (name, arch_type, created_date)
    _cache_timestamp: Optional[float] = None

    def __init__(self, master, app_actions: Any) -> None:
        ModelsWindow.top_level = SmartToplevel(persistent_parent=master, title=_("Models"), geometry="800x450")
        self.master: SmartToplevel = ModelsWindow.top_level
        self.app_actions: Any = app_actions
        self.show_blacklisted: bool = False

        # Ensure models are loaded
        Model.load_all_if_unloaded()

        # Main frame
        self.frame: Frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew", padx=10, pady=10)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Notebook
        self.notebook = Notebook(self.frame)
        self.notebook.grid(column=0, row=0, sticky="nsew")

        # Tabs
        self.checkpoints_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.adapters_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.notebook.add(self.checkpoints_tab, text=_("Checkpoints"))
        self.notebook.add(self.adapters_tab, text=_("LoRAs & Adapters"))

        # Build each tab
        self._build_checkpoints_tab()
        self._build_adapters_tab()

        # Close binding
        self.master.bind("<Escape>", lambda e: self.master.destroy())
        self.master.protocol("WM_DELETE_WINDOW", self.master.destroy)

    def _build_checkpoints_tab(self) -> None:
        self.checkpoints_tab.columnconfigure(0, weight=1)
        self.checkpoints_tab.rowconfigure(2, weight=1)
        # Filter
        Label(self.checkpoints_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.cp_filter = StringVar(self.master)
        self.cp_filter_entry = Entry(self.checkpoints_tab, textvariable=self.cp_filter, width=40, font=fnt.Font(size=9))
        self.cp_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        
        # Cache status
        self.cp_cache_status = Label(self.checkpoints_tab, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8))
        self.cp_cache_status.grid(column=0, row=2, sticky="w", pady=(0, 6))
        
        # Treeview with scrollbar
        tree_frame = Frame(self.checkpoints_tab, bg=AppStyle.BG_COLOR)
        tree_frame.grid(column=0, row=3, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.cp_tree = Treeview(tree_frame, columns=("architecture", "created"), show="tree headings", height=15)
        self.cp_tree.heading("#0", text=_("Model Name"), command=lambda: self._sort_tree(self.cp_tree, "#0"))
        self.cp_tree.heading("architecture", text=_("Architecture"), command=lambda: self._sort_tree(self.cp_tree, "architecture"))
        self.cp_tree.heading("created", text=_("Created"), command=lambda: self._sort_tree(self.cp_tree, "created"))
        self.cp_tree.column("#0", width=300, minwidth=150)
        self.cp_tree.column("architecture", width=120, minwidth=80)
        self.cp_tree.column("created", width=150, minwidth=100)
        
        # Scrollbar for treeview
        cp_scrollbar = Scrollbar(tree_frame, orient="vertical", command=self.cp_tree.yview)
        self.cp_tree.configure(yscrollcommand=cp_scrollbar.set)
        
        self.cp_tree.grid(column=0, row=0, sticky="nsew")
        cp_scrollbar.grid(column=1, row=0, sticky="ns")
        
        # Buttons
        btn_frame = Frame(self.checkpoints_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=4, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_checkpoint(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_checkpoint(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        refresh_btn = Button(btn_frame, text=_("Refresh"), command=self._refresh_cache)
        refresh_btn.grid(column=2, row=0, padx=(0, 6))
        self.show_blacklisted_btn = Button(btn_frame, text=_("Show Blacklisted"), command=self._toggle_blacklisted)
        self.show_blacklisted_btn.grid(column=3, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=4, row=0)

        # Populate
        self._refresh_checkpoint_list()
        self.cp_filter.trace_add("write", lambda *_: self._refresh_checkpoint_list())
        self.cp_tree.bind("<Double-Button-1>", lambda e: self._select_checkpoint())
        
        # Update cache status display
        self._update_cache_status_display()

    def _build_adapters_tab(self) -> None:
        self.adapters_tab.columnconfigure(0, weight=1)
        self.adapters_tab.rowconfigure(2, weight=1)
        # Filter
        Label(self.adapters_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.ad_filter = StringVar(self.master)
        self.ad_filter_entry = Entry(self.adapters_tab, textvariable=self.ad_filter, width=40, font=fnt.Font(size=9))
        self.ad_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        
        # Cache status
        self.ad_cache_status = Label(self.adapters_tab, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8))
        self.ad_cache_status.grid(column=0, row=2, sticky="w", pady=(0, 6))
        
        # Treeview with scrollbar
        tree_frame = Frame(self.adapters_tab, bg=AppStyle.BG_COLOR)
        tree_frame.grid(column=0, row=3, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.ad_tree = Treeview(tree_frame, columns=("architecture", "created"), show="tree headings", height=15)
        self.ad_tree.heading("#0", text=_("LoRA/Adapter Name"), command=lambda: self._sort_tree(self.ad_tree, "#0"))
        self.ad_tree.heading("architecture", text=_("Architecture"), command=lambda: self._sort_tree(self.ad_tree, "architecture"))
        self.ad_tree.heading("created", text=_("Created"), command=lambda: self._sort_tree(self.ad_tree, "created"))
        self.ad_tree.column("#0", width=300, minwidth=150)
        self.ad_tree.column("architecture", width=120, minwidth=80)
        self.ad_tree.column("created", width=150, minwidth=100)
        
        # Scrollbar for treeview
        ad_scrollbar = Scrollbar(tree_frame, orient="vertical", command=self.ad_tree.yview)
        self.ad_tree.configure(yscrollcommand=ad_scrollbar.set)
        
        self.ad_tree.grid(column=0, row=0, sticky="nsew")
        ad_scrollbar.grid(column=1, row=0, sticky="ns")
        
        # Buttons
        btn_frame = Frame(self.adapters_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=4, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_adapter(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_adapter(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        lora_info_btn = Button(btn_frame, text=_("LoRA Info"), command=self._show_lora_info)
        lora_info_btn.grid(column=2, row=0, padx=(0, 6))
        
        # Disable LoRA Info button if safetriggers is not available
        if not is_safetriggers_available():
            lora_info_btn.config(state="disabled", text=_("LoRA Info"))
        refresh_btn = Button(btn_frame, text=_("Refresh"), command=self._refresh_cache)
        refresh_btn.grid(column=3, row=0, padx=(0, 6))
        self.show_blacklisted_btn_ad = Button(btn_frame, text=_("Show Blacklisted"), command=self._toggle_blacklisted)
        self.show_blacklisted_btn_ad.grid(column=4, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=5, row=0)

        # Populate
        self._refresh_adapter_list()
        self.ad_filter.trace_add("write", lambda *_: self._refresh_adapter_list())
        self.ad_tree.bind("<Double-Button-1>", lambda e: self._select_adapter())
        
        # Update cache status display
        self._update_cache_status_display()

    def _sort_tree(self, tree: Treeview, column: str) -> None:
        """Sort treeview by column. Toggle between ascending and descending."""
        # Get current sort state
        current_sort = getattr(tree, '_sort_state', {})
        reverse = current_sort.get(column, False)
        
        # Toggle sort direction
        reverse = not reverse
        tree._sort_state = {column: reverse}
        
        # Get all items and sort them
        if column == "#0":
            # For the display column (#0), get the text directly
            items = [(tree.item(item, "text"), item) for item in tree.get_children('')]
        else:
            # For data columns, use tree.set()
            items = [(tree.set(item, column), item) for item in tree.get_children('')]
        
        # Special handling for date column
        if column == "created":
            # Sort by actual date values
            items.sort(key=lambda x: self._parse_date(x[0]), reverse=reverse)
        else:
            # Sort alphabetically
            items.sort(key=lambda x: x[0].lower(), reverse=reverse)
        
        # Reorder items in treeview
        for index, (val, item) in enumerate(items):
            tree.move(item, '', index)

    def _parse_date(self, date_str: str) -> tuple[int, int, int, int, int]:
        """Parse date string for sorting. Returns a tuple for proper sorting."""
        if not date_str or date_str == "Unknown":
            return (0, 0, 0)  # Sort unknown dates first
        
        try:
            # Parse format like "2024-01-15 14:30"
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
            return (dt.year, dt.month, dt.day, dt.hour, dt.minute)
        except:
            return (0, 0, 0)  # Sort invalid dates first

    def _apply_default_sort(self, tree: Treeview) -> None:
        """Apply default sort: architecture type, then name."""
        # Get all items with their values
        items = []
        for item in tree.get_children(''):
            arch_type = tree.set(item, "architecture")
            name = tree.item(item)["text"]
            items.append((arch_type, name, item))
        
        # Sort by architecture type first, then by name
        items.sort(key=lambda x: (x[0], x[1].lower()))
        
        # Reorder items in treeview
        for index, (arch_type, name, item) in enumerate(items):
            tree.move(item, '', index)

    def _refresh_checkpoint_list(self) -> None:
        filter_text = (self.cp_filter.get() or "").lower()
        
        # Get cached data
        cached_data = self._get_cached_checkpoints_data()
        
        # Filter data based on search text
        if filter_text:
            filtered_data = [(name, arch_type, created_date) for name, arch_type, created_date in cached_data 
                           if filter_text in name.lower()]
        else:
            filtered_data = cached_data
        
        # Clear existing items
        for item in self.cp_tree.get_children():
            self.cp_tree.delete(item)
        
        # Add items to treeview
        for name, arch_type, created_date in filtered_data:
            self.cp_tree.insert("", "end", text=name, values=(arch_type, created_date))
        
        # Apply default sort: architecture type, then name
        self._apply_default_sort(self.cp_tree)

    def _refresh_adapter_list(self) -> None:
        filter_text = (self.ad_filter.get() or "").lower()
        
        # Get cached data
        cached_data = self._get_cached_adapters_data()
        
        # Filter data based on search text
        if filter_text:
            filtered_data = [(name, arch_type, created_date) for name, arch_type, created_date in cached_data 
                           if filter_text in name.lower()]
        else:
            filtered_data = cached_data
        
        # Clear existing items
        for item in self.ad_tree.get_children():
            self.ad_tree.delete(item)
        
        # Add items to treeview
        for name, arch_type, created_date in filtered_data:
            self.ad_tree.insert("", "end", text=name, values=(arch_type, created_date))
        
        # Apply default sort: architecture type, then name
        self._apply_default_sort(self.ad_tree)

    def _select_checkpoint(self, replace: bool = True) -> None:
        try:
            selection = self.cp_tree.selection()
            if not selection:
                return
            # Get the selected item's text (model name)
            model_name: str = self.cp_tree.item(selection[0])["text"]
            # Unified callback: is_lora=False
            self.app_actions.set_model_from_models_window(model_name, is_lora=False, replace=replace)
            # Close after action
            self.master.destroy()
        except Exception:
            # Do nothing on selection issues
            pass

    def _select_adapter(self, replace: bool = False) -> None:
        try:
            selection = self.ad_tree.selection()
            if not selection:
                return
            # Get the selected item's text (model name)
            model_name: str = self.ad_tree.item(selection[0])["text"]
            # Unified callback: is_lora=True
            self.app_actions.set_model_from_models_window(model_name, is_lora=True, replace=replace)
            # Keep window open when adding, close when replacing
            if replace:
                self.master.destroy()
        except Exception:
            pass

    def _refresh_cache(self) -> None:
        """Refresh the model data cache."""
        ModelsWindow._checkpoints_cache = None
        ModelsWindow._adapters_cache = None
        ModelsWindow._cache_timestamp = None
        self._refresh_checkpoint_list()
        self._refresh_adapter_list()
        self._update_cache_status_display()

    def _get_cached_checkpoints_data(self) -> list[tuple[str, str, str]]:
        """Get cached checkpoints data or build cache if needed."""
        if ModelsWindow._checkpoints_cache is None:
            ModelsWindow._checkpoints_cache = self._build_checkpoints_data()
            ModelsWindow._cache_timestamp = self._get_current_timestamp()
            self._update_cache_status_display()
        return ModelsWindow._checkpoints_cache

    def _get_cached_adapters_data(self) -> list[tuple[str, str, str]]:
        """Get cached adapters data or build cache if needed."""
        if ModelsWindow._adapters_cache is None:
            ModelsWindow._adapters_cache = self._build_adapters_data()
            ModelsWindow._cache_timestamp = self._get_current_timestamp()
            self._update_cache_status_display()
        return ModelsWindow._adapters_cache

    def _build_checkpoints_data(self) -> list[tuple[str, str, str]]:
        """Build checkpoints data cache."""
        data = []
        for item in sorted(list(Model.CHECKPOINTS.keys())):
            model: Model = Model.CHECKPOINTS[item]
            
            # Filter out blacklisted models unless explicitly showing them
            if not self.show_blacklisted and model.is_blacklisted():
                continue
                
            arch_type: ArchitectureType = model.get_architecture_type()
            created_date: str = model.get_file_creation_date()
            data.append((item, arch_type.display(), created_date))
        return data

    def _build_adapters_data(self) -> list[tuple[str, str, str]]:
        """Build adapters data cache."""
        data = []
        for item in sorted(list(Model.LORAS.keys())):
            model: Model = Model.LORAS[item]
            
            # Filter out blacklisted models unless explicitly showing them
            if not self.show_blacklisted and model.is_blacklisted():
                continue
                
            arch_type: ArchitectureType = model.get_architecture_type()
            created_date: str = model.get_file_creation_date()
            data.append((item, arch_type.display(), created_date))
        return data

    def _get_current_timestamp(self) -> float:
        """Get current timestamp for cache tracking."""
        return time.time()

    def _update_cache_status_display(self) -> None:
        """Update the cache status display in both tabs."""
        cache_prefix = _("Cache")
        
        if ModelsWindow._cache_timestamp is None:
            status_text = f"{cache_prefix}: {_('Not loaded')}"
        else:
            cache_time = datetime.fromtimestamp(ModelsWindow._cache_timestamp)
            time_str = cache_time.strftime("%Y-%m-%d %H:%M:%S")
            status_text = f"{cache_prefix}: {time_str}"
        
        if hasattr(self, 'cp_cache_status'):
            self.cp_cache_status.config(text=status_text)
        if hasattr(self, 'ad_cache_status'):
            self.ad_cache_status.config(text=status_text)

    def _is_cache_stale(self, max_age_seconds: int = 3600) -> bool:
        """Check if cache is stale (older than max_age_seconds)."""
        if ModelsWindow._cache_timestamp is None:
            return True
        return (time.time() - ModelsWindow._cache_timestamp) > max_age_seconds

    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _toggle_blacklisted(self) -> None:
        """Toggle the display of blacklisted models."""
        self.show_blacklisted = not self.show_blacklisted
        
        # Clear cache since filtering has changed
        ModelsWindow._checkpoints_cache = None
        ModelsWindow._adapters_cache = None
        ModelsWindow._cache_timestamp = None
        
        # Update button text
        if self.show_blacklisted:
            if hasattr(self, 'show_blacklisted_btn'):
                self.show_blacklisted_btn.config(text=_("Hide Blacklisted"))
            if hasattr(self, 'show_blacklisted_btn_ad'):
                self.show_blacklisted_btn_ad.config(text=_("Hide Blacklisted"))
        else:
            if hasattr(self, 'show_blacklisted_btn'):
                self.show_blacklisted_btn.config(text=_("Show Blacklisted"))
            if hasattr(self, 'show_blacklisted_btn_ad'):
                self.show_blacklisted_btn_ad.config(text=_("Show Blacklisted"))
        
        # Refresh both lists
        self._refresh_checkpoint_list()
        self._refresh_adapter_list()
        self._update_cache_status_display()

    def _show_lora_info(self) -> None:
        """Show LoRA information window for the selected LoRA."""
        # Check if safetriggers functionality is available
        if not is_safetriggers_available():
            self.app_actions.alert(_("Feature Unavailable"), 
                                 _("LoRA trigger extraction is not available.\n\nThis may be due to missing dependencies or import errors."),
                                 kind="warning", master=self.master)
            return
            
        try:
            selection = self.ad_tree.selection()
            if not selection:
                self.app_actions.alert(_("No Selection"), _("Please select a LoRA to view information."),
                                      kind="warning", master=self.master)
                return
            
            # Get the selected item's text (model name)
            model_name: str = self.ad_tree.item(selection[0])["text"]
            
            # Find the model
            model = Model.LORAS.get(model_name)
            if not model:
                self.app_actions.alert(_("Error"), _("Model not found: {0}").format(model_name),
                                      kind="error", master=self.master)
                return
            
            # Open the LoRA info window
            LoRAInfoWindow(self.master, model, self.app_actions)
                
        except Exception as e:
            self.app_actions.alert(_("Error"), _("Failed to show LoRA information: {0}").format(str(e)),
                                   kind="error", master=self.master)


class LoRAInfoWindow:
    """Window for displaying detailed LoRA information including triggers."""
    
    def __init__(self, master, model: Model, app_actions: Any):
        self.master = master
        self.model = model
        self.app_actions = app_actions
        
        # Create the window
        self.window = SmartToplevel(persistent_parent=master, title=_("LoRA Information: {0}").format(model.id),
                                   geometry="800x600")
        
        # Main frame
        self.main_frame = Frame(self.window, bg=AppStyle.BG_COLOR)
        self.main_frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # Build the interface
        self._build_interface()
        
        # Load trigger information
        self._load_trigger_info()
        
        # Close binding
        self.window.bind("<Escape>", lambda e: self.window.destroy())
        self.window.protocol("WM_DELETE_WINDOW", self.window.destroy)
    
    def _build_interface(self) -> None:
        """Build the LoRA information interface."""
        # Title
        title_label = Label(self.main_frame, text=_("LoRA Information"), 
                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                           font=fnt.Font(size=16, weight="bold"))
        title_label.pack(pady=(0, 15))
        
        # Model information section
        info_frame = Frame(self.main_frame, bg=AppStyle.BG_COLOR)
        info_frame.pack(fill="x", pady=(0, 15))
        
        # Model name
        name_label = Label(info_frame, text=_("Name:"), 
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=12, weight="bold"))
        name_label.grid(column=0, row=0, sticky="w", padx=(0, 10))
        
        name_value = Label(info_frame, text=self.model.id,
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=12))
        name_value.grid(column=1, row=0, sticky="w")
        
        # Architecture type
        arch_label = Label(info_frame, text=_("Architecture:"), 
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=12, weight="bold"))
        arch_label.grid(column=0, row=1, sticky="w", padx=(0, 10), pady=(5, 0))
        
        arch_value = Label(info_frame, text=self.model.get_architecture_type().display(),
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=12))
        arch_value.grid(column=1, row=1, sticky="w", pady=(5, 0))
        
        # File path
        path_label = Label(info_frame, text=_("File Path:"), 
                           bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                           font=fnt.Font(size=12, weight="bold"))
        path_label.grid(column=0, row=2, sticky="w", padx=(0, 10), pady=(5, 0))
        
        file_path = self._get_model_file_path()
        path_value = Label(info_frame, text=file_path,
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=10))
        path_value.grid(column=1, row=2, sticky="w", pady=(5, 0))
        
        # Created date
        date_label = Label(info_frame, text=_("Created:"), 
                          bg=AppStyle.BG_COLOR, fg=AppStyle.BG_COLOR,
                          font=fnt.Font(size=12, weight="bold"))
        date_label.grid(column=0, row=3, sticky="w", padx=(0, 10), pady=(5, 0))
        
        date_value = Label(info_frame, text=self.model.get_file_creation_date(),
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=12))
        date_value.grid(column=1, row=3, sticky="w", pady=(5, 0))
        
        # LoRA strength
        strength_label = Label(info_frame, text=_("Strength:"), 
                             bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                             font=fnt.Font(size=12, weight="bold"))
        strength_label.grid(column=0, row=4, sticky="w", padx=(0, 10), pady=(5, 0))
        
        strength_value = Label(info_frame, text=f"{self.model.lora_strength:.2f}",
                             bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                             font=fnt.Font(size=12))
        strength_value.grid(column=1, row=4, sticky="w", pady=(5, 0))
        
        # Separator line
        separator = Frame(self.main_frame, height=2, bg=AppStyle.FG_COLOR)
        separator.pack(fill="x", pady=15)
        
        # Trigger information section
        trigger_title = Label(self.main_frame, text=_("Trigger Information"), 
                             bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                             font=fnt.Font(size=14, weight="bold"))
        trigger_title.pack(pady=(0, 10))
        
        # Trigger status
        self.trigger_status = Label(self.main_frame, text=_("Loading trigger information..."), 
                                  bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                                  font=fnt.Font(size=11))
        self.trigger_status.pack(pady=(0, 10))
        
        # Trigger list frame
        self.trigger_frame = Frame(self.main_frame, bg=AppStyle.BG_COLOR)
        self.trigger_frame.pack(fill="both", expand=True)
        
        # Buttons frame
        button_frame = Frame(self.main_frame, bg=AppStyle.BG_COLOR)
        button_frame.pack(fill="x", pady=(15, 0))
        
        # Create .safetriggers file button
        self.create_file_btn = Button(button_frame, text=_("Create .safetriggers File"), 
                                    command=self._create_safetriggers_file,
                                    state="disabled")
        self.create_file_btn.pack(side="left", padx=(0, 10))
        
        # Close button
        close_btn = Button(button_frame, text=_("Close"), command=self.window.destroy)
        close_btn.pack(side="right")
    
    def _get_model_file_path(self) -> str:
        """Get the full file path for the model."""
        try:
            lora_or_sd = "Lora" if self.model.is_lora else "Stable-diffusion"
            root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
            
            if self.model.path:
                if os.path.isabs(self.model.path):
                    return self.model.path
                else:
                    return os.path.join(root_dir, self.model.path)
            else:
                return os.path.join(root_dir, self.model.id)
        except Exception:
            return _("Unknown")
    
    def _load_trigger_info(self) -> None:
        """Load trigger information for the LoRA."""
        # Check if safetriggers functionality is available
        if not is_safetriggers_available():
            self.trigger_status.config(text=_("Trigger extraction not available"))
            return
            
        try:
            file_path = self._get_model_file_path()
            
            # Ensure it's a .safetensors file
            if not file_path.endswith('.safetensors'):
                file_path += '.safetensors'
            
            if not os.path.exists(file_path):
                self.trigger_status.config(text=_("LoRA file not found"))
                return
            
            # Get trigger information
            trigger_info = get_trigger_info(file_path, force_refresh=True)
            
            if trigger_info.has_triggers and trigger_info.triggers:
                self._display_triggers(trigger_info)
            else:
                error_msg = trigger_info.error_message if trigger_info.error_message else _("No triggers found")
                self.trigger_status.config(text=_("No triggers found: {0}").format(error_msg))
                
        except Exception as e:
            self.trigger_status.config(text=_("Error loading triggers: {0}").format(str(e)))
    
    def _display_triggers(self, trigger_info: TriggerInfo) -> None:
        """Display the trigger information."""
        # Update status
        self.trigger_status.config(text=_("Found {0} triggers").format(trigger_info.trigger_count))
        
        # Enable create file button
        self.create_file_btn.config(state="normal")
        
        # Create scrollable text area for triggers
        text_widget = Text(self.trigger_frame, wrap="word", height=12, width=80,
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR,
                          font=fnt.Font(size=9))
        text_scrollbar = Scrollbar(self.trigger_frame, orient="vertical", command=text_widget.yview)
        text_widget.configure(yscrollcommand=text_scrollbar.set)
        
        text_widget.pack(side="left", fill="both", expand=True)
        text_scrollbar.pack(side="right", fill="y")
        
        # Populate triggers (sorted by frequency)
        sorted_triggers = sorted(trigger_info.triggers.items(), key=lambda x: x[1], reverse=True)
        
        # Add header
        text_widget.insert("end", f"{'Count':>6}  {'Trigger Word/Phrase':<50}\n")
        text_widget.insert("end", "-" * 60 + "\n")
        
        for trigger, count in sorted_triggers:
            text_widget.insert("end", f"{count:>6}  {trigger:<50}\n")
        
        text_widget.config(state="disabled")
    
    def _create_safetriggers_file(self) -> None:
        """Create a .safetriggers file for the LoRA."""
        # Check if safetriggers functionality is available
        if not is_safetriggers_available():
            self.app_actions.alert(_("Feature Unavailable"), 
                               _("Cannot create .safetriggers file: trigger extraction is not available."),
                               kind="error", master=self.window)
            return
            
        try:
            file_path = self._get_model_file_path()
            
            # Ensure it's a .safetensors file
            if not file_path.endswith('.safetensors'):
                file_path += '.safetensors'
            
            if not os.path.exists(file_path):
                self.app_actions.alert(_("Error"), _("LoRA file not found: {0}").format(file_path),
                                      kind="error", master=self.window)
                return
            
            # Create the .safetriggers file
            success = create_safetriggers_file(file_path)
            
            if success:
                safetriggers_path = file_path.replace('.safetensors', '.safetriggers')
                self.app_actions.alert(_("Success"), 
                                 _("Created .safetriggers file:\n{0}").format(safetriggers_path),
                                 kind="info", master=self.window)
            else:
                self.app_actions.alert(_("Error"), _("Failed to create .safetriggers file"),
                                      kind="error", master=self.window)
                
        except Exception as e:
            self.app_actions.alert(_("Error"), _("Failed to create .safetriggers file: {0}").format(str(e)),
                                   kind="error", master=self.window)


