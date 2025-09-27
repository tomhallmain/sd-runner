from datetime import datetime
import time
from tkinter import Toplevel, Frame, Label, StringVar, Entry, Scrollbar
import tkinter.font as fnt
from tkinter.ttk import Button, Notebook, Treeview
from typing import Optional, Any

from sd_runner.models import Model
from ui.app_style import AppStyle
from ui.auth.password_utils import require_password
from utils.globals import ArchitectureType, ProtectedActions, PromptMode
from utils.translations import I18N

_ = I18N._


class ModelsWindow:
    top_level: Optional[Toplevel] = None
    _checkpoints_cache: Optional[list[tuple[str, str, str]]] = None  # (name, arch_type, created_date)
    _adapters_cache: Optional[list[tuple[str, str, str]]] = None    # (name, arch_type, created_date)
    _cache_timestamp: Optional[float] = None

    def __init__(self, master: Toplevel, app_actions: Any) -> None:
        ModelsWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        ModelsWindow.top_level.title(_("Models"))
        ModelsWindow.top_level.geometry("800x450")

        self.master: Toplevel = ModelsWindow.top_level
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
        refresh_btn = Button(btn_frame, text=_("Refresh"), command=self._refresh_cache)
        refresh_btn.grid(column=2, row=0, padx=(0, 6))
        self.show_blacklisted_btn_ad = Button(btn_frame, text=_("Show Blacklisted"), command=self._toggle_blacklisted)
        self.show_blacklisted_btn_ad.grid(column=3, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=4, row=0)

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


