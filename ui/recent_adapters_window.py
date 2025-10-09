from datetime import datetime
import os
import time
from tkinter import Toplevel, Frame, Label, StringVar, Entry, Scrollbar, IntVar
import tkinter.font as fnt
from tkinter.ttk import Button, Notebook, Treeview
from typing import Optional, Any

from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.translations import I18N

_ = I18N._

logger = get_logger("recent_adapters_window")


class RecentAdaptersWindow:
    top_level: Optional[Toplevel] = None
    _controlnet_cache: Optional[list[tuple[str, str, str]]] = None  # (name, type, created_date)
    _ipadapter_cache: Optional[list[tuple[str, str, str]]] = None    # (name, type, created_date)
    _cache_timestamp: Optional[float] = None
    
    # Persistent storage for recent adapters (just file paths)
    _recent_controlnets: list[str] = []
    _recent_ipadapters: list[str] = []
    # Unified recent adapter files list (directories expanded to individual files)
    _recent_adapter_files_split: list[str] = []
    
    # Default constants (can be overridden by user configuration)
    DEFAULT_MAX_RECENT_ITEMS = 1000
    DEFAULT_MAX_RECENT_SPLIT_ITEMS = 2000
    
    # Configuration keys for app_info_cache
    MAX_RECENT_ITEMS_KEY = "max_recent_items"
    MAX_RECENT_SPLIT_ITEMS_KEY = "max_recent_split_items"

    def __init__(self, master: Toplevel, app_actions: Any) -> None:
        RecentAdaptersWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        RecentAdaptersWindow.top_level.title(_("Recent Adapters"))
        RecentAdaptersWindow.top_level.geometry("1000x500")

        self.master: Toplevel = RecentAdaptersWindow.top_level
        self.app_actions: Any = app_actions
        
        # Load configuration values from cache
        self.max_recent_items = RecentAdaptersWindow._get_max_recent_items()
        self.max_recent_split_items = RecentAdaptersWindow._get_max_recent_split_items()

        # Main frame
        self.frame: Frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew", padx=15, pady=15)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Notebook
        self.notebook = Notebook(self.frame)
        self.notebook.grid(column=0, row=0, sticky="nsew")

        # Tabs
        self.controlnet_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.ipadapter_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.all_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.config_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.notebook.add(self.controlnet_tab, text=_("Recent ControlNets"))
        self.notebook.add(self.ipadapter_tab, text=_("Recent IP Adapters"))
        self.notebook.add(self.all_tab, text=_("All Recent Adapters"))
        self.notebook.add(self.config_tab, text=_("Configuration"))

        # Build each tab
        self._build_controlnet_tab()
        self._build_ipadapter_tab()
        self._build_all_tab()
        self._build_config_tab()

        # Close binding
        self.master.bind("<Escape>", lambda e: self.master.destroy())
        self.master.protocol("WM_DELETE_WINDOW", self.master.destroy)

    def _build_controlnet_tab(self) -> None:
        self.controlnet_tab.columnconfigure(0, weight=1)
        self.controlnet_tab.rowconfigure(2, weight=1)
        
        # Filter
        Label(self.controlnet_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.cn_filter = StringVar(self.master)
        self.cn_filter_entry = Entry(self.controlnet_tab, textvariable=self.cn_filter, width=40, font=fnt.Font(size=9))
        self.cn_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        
        # Cache status
        self.cn_cache_status = Label(self.controlnet_tab, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8))
        self.cn_cache_status.grid(column=0, row=2, sticky="w", pady=(0, 6))
        
        # Treeview with scrollbar
        tree_frame = Frame(self.controlnet_tab, bg=AppStyle.BG_COLOR)
        tree_frame.grid(column=0, row=3, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.cn_tree = Treeview(tree_frame, columns=("type", "created"), show="tree headings", height=15)
        self.cn_tree.heading("#0", text=_("ControlNet File"), command=lambda: self._sort_tree(self.cn_tree, "#0"))
        self.cn_tree.heading("type", text=_("Type"), command=lambda: self._sort_tree(self.cn_tree, "type"))
        self.cn_tree.heading("created", text=_("Created"), command=lambda: self._sort_tree(self.cn_tree, "created"))
        self.cn_tree.column("#0", width=600, minwidth=300)
        self.cn_tree.column("type", width=150, minwidth=100)
        self.cn_tree.column("created", width=150, minwidth=100)
        
        # Scrollbar for treeview
        cn_scrollbar = Scrollbar(tree_frame, orient="vertical", command=self.cn_tree.yview)
        self.cn_tree.configure(yscrollcommand=cn_scrollbar.set)
        
        self.cn_tree.grid(column=0, row=0, sticky="nsew")
        cn_scrollbar.grid(column=1, row=0, sticky="ns")
        
        # Buttons
        btn_frame = Frame(self.controlnet_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=4, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_controlnet(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_controlnet(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        refresh_btn = Button(btn_frame, text=_("Refresh"), command=self._refresh_cache)
        refresh_btn.grid(column=2, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=3, row=0)

        # Populate
        self._refresh_controlnet_list()
        self.cn_filter.trace_add("write", lambda *_: self._refresh_controlnet_list())
        self.cn_tree.bind("<Double-Button-1>", lambda e: self._select_controlnet())
        
        # Update cache status display
        self._update_cache_status_display()

    def _build_ipadapter_tab(self) -> None:
        self.ipadapter_tab.columnconfigure(0, weight=1)
        self.ipadapter_tab.rowconfigure(2, weight=1)
        
        # Filter
        Label(self.ipadapter_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=0, sticky="w")
        self.ip_filter = StringVar(self.master)
        self.ip_filter_entry = Entry(self.ipadapter_tab, textvariable=self.ip_filter, width=40, font=fnt.Font(size=9))
        self.ip_filter_entry.grid(column=0, row=1, sticky="we", pady=(0, 6))
        
        # Cache status
        self.ip_cache_status = Label(self.ipadapter_tab, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8))
        self.ip_cache_status.grid(column=0, row=2, sticky="w", pady=(0, 6))
        
        # Treeview with scrollbar
        tree_frame = Frame(self.ipadapter_tab, bg=AppStyle.BG_COLOR)
        tree_frame.grid(column=0, row=3, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.ip_tree = Treeview(tree_frame, columns=("type", "created"), show="tree headings", height=15)
        self.ip_tree.heading("#0", text=_("IP Adapter File"), command=lambda: self._sort_tree(self.ip_tree, "#0"))
        self.ip_tree.heading("type", text=_("Type"), command=lambda: self._sort_tree(self.ip_tree, "type"))
        self.ip_tree.heading("created", text=_("Created"), command=lambda: self._sort_tree(self.ip_tree, "created"))
        self.ip_tree.column("#0", width=600, minwidth=300)
        self.ip_tree.column("type", width=150, minwidth=100)
        self.ip_tree.column("created", width=150, minwidth=100)
        
        # Scrollbar for treeview
        ip_scrollbar = Scrollbar(tree_frame, orient="vertical", command=self.ip_tree.yview)
        self.ip_tree.configure(yscrollcommand=ip_scrollbar.set)
        
        self.ip_tree.grid(column=0, row=0, sticky="nsew")
        ip_scrollbar.grid(column=1, row=0, sticky="ns")
        
        # Buttons
        btn_frame = Frame(self.ipadapter_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=4, sticky="we", pady=(6, 0))
        replace_btn = Button(btn_frame, text=_("Replace"), command=lambda: self._select_ipadapter(replace=True))
        replace_btn.grid(column=0, row=0, padx=(0, 6))
        add_btn = Button(btn_frame, text=_("Add"), command=lambda: self._select_ipadapter(replace=False))
        add_btn.grid(column=1, row=0, padx=(0, 6))
        refresh_btn = Button(btn_frame, text=_("Refresh"), command=self._refresh_cache)
        refresh_btn.grid(column=2, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=3, row=0)

        # Populate
        self._refresh_ipadapter_list()
        self.ip_filter.trace_add("write", lambda *_: self._refresh_ipadapter_list())
        self.ip_tree.bind("<Double-Button-1>", lambda e: self._select_ipadapter())
        
        # Update cache status display
        self._update_cache_status_display()

    def _build_all_tab(self) -> None:
        self.all_tab.columnconfigure(0, weight=1)
        self.all_tab.rowconfigure(3, weight=1)
        
        # Info label
        info_label = Label(self.all_tab, text=_("Individual files, including from directory-split runs (no directories)"), 
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8, slant="italic"))
        info_label.grid(column=0, row=0, sticky="w", pady=(0, 4))
        
        # Filter
        Label(self.all_tab, text=_("Filter"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=1, sticky="w")
        self.all_filter = StringVar(self.master)
        self.all_filter_entry = Entry(self.all_tab, textvariable=self.all_filter, width=40, font=fnt.Font(size=9))
        self.all_filter_entry.grid(column=0, row=2, sticky="we", pady=(0, 6))
        
        # Cache status
        self.all_cache_status = Label(self.all_tab, text="", bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, font=fnt.Font(size=8))
        self.all_cache_status.grid(column=0, row=3, sticky="w", pady=(0, 6))
        
        # Treeview with scrollbar
        tree_frame = Frame(self.all_tab, bg=AppStyle.BG_COLOR)
        tree_frame.grid(column=0, row=4, sticky="nsew")
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)
        
        self.all_tree = Treeview(tree_frame, columns=("type", "created"), show="tree headings", height=15)
        self.all_tree.heading("#0", text=_("Adapter File"), command=lambda: self._sort_tree(self.all_tree, "#0"))
        self.all_tree.heading("type", text=_("Type"), command=lambda: self._sort_tree(self.all_tree, "type"))
        self.all_tree.heading("created", text=_("Created"), command=lambda: self._sort_tree(self.all_tree, "created"))
        self.all_tree.column("#0", width=600, minwidth=300)
        self.all_tree.column("type", width=150, minwidth=100)
        self.all_tree.column("created", width=150, minwidth=100)
        
        all_scrollbar = Scrollbar(tree_frame, orient="vertical", command=self.all_tree.yview)
        self.all_tree.configure(yscrollcommand=all_scrollbar.set)
        self.all_tree.grid(column=0, row=0, sticky="nsew")
        all_scrollbar.grid(column=1, row=0, sticky="ns")
        
        # Buttons
        btn_frame = Frame(self.all_tab, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=5, sticky="we", pady=(6, 0))
        # ControlNet
        cn_replace_btn = Button(btn_frame, text=_("Apply to ControlNet (Replace)"), command=lambda: self._select_all_adapter(is_controlnet=True, replace=True))
        cn_replace_btn.grid(column=0, row=0, padx=(0, 6))
        cn_add_btn = Button(btn_frame, text=_("Apply to ControlNet (Add)"), command=lambda: self._select_all_adapter(is_controlnet=True, replace=False))
        cn_add_btn.grid(column=1, row=0, padx=(0, 6))
        # IP Adapter
        ip_replace_btn = Button(btn_frame, text=_("Apply to IP Adapter (Replace)"), command=lambda: self._select_all_adapter(is_controlnet=False, replace=True))
        ip_replace_btn.grid(column=2, row=0, padx=(0, 6))
        ip_add_btn = Button(btn_frame, text=_("Apply to IP Adapter (Add)"), command=lambda: self._select_all_adapter(is_controlnet=False, replace=False))
        ip_add_btn.grid(column=3, row=0, padx=(0, 6))
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=4, row=0)
        
        # Populate
        self._refresh_all_list()
        self.all_filter.trace_add("write", lambda *_: self._refresh_all_list())
        # No default double-click action; the user must choose which target to apply
        
        # Update cache status display
        self._update_cache_status_display()

    def _build_config_tab(self) -> None:
        """Build the configuration tab for setting limits."""
        self.config_tab.columnconfigure(0, weight=1)
        self.config_tab.rowconfigure(0, weight=1)
        
        # Main configuration frame
        config_frame = Frame(self.config_tab, bg=AppStyle.BG_COLOR)
        config_frame.grid(column=0, row=0, sticky="nsew", padx=20, pady=20)
        config_frame.columnconfigure(1, weight=1)
        
        # Title
        title_label = Label(config_frame, text=_("Recent Adapters Configuration"), 
                          bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                          font=fnt.Font(size=12, weight="bold"))
        title_label.grid(column=0, row=0, columnspan=2, sticky="w", pady=(0, 20))
        
        # Max Recent Items
        Label(config_frame, text=_("Max Recent Items:"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=1, sticky="w", pady=(0, 10))
        self.max_recent_items_var = IntVar(value=self.max_recent_items)
        max_recent_entry = Entry(config_frame, textvariable=self.max_recent_items_var, width=10, font=fnt.Font(size=9))
        max_recent_entry.grid(column=1, row=1, sticky="w", pady=(0, 10))
        
        # Max Recent Split Items
        Label(config_frame, text=_("Max Recent Split Items:"), bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR).grid(column=0, row=2, sticky="w", pady=(0, 10))
        self.max_recent_split_items_var = IntVar(value=self.max_recent_split_items)
        max_recent_split_entry = Entry(config_frame, textvariable=self.max_recent_split_items_var, width=10, font=fnt.Font(size=9))
        max_recent_split_entry.grid(column=1, row=2, sticky="w", pady=(0, 20))
        
        # Description
        desc_text = _("These settings control how many recent adapters are kept in memory.\n"
                     "Higher values use more memory but keep more history.\n"
                     "Changes take effect immediately and are saved automatically.")
        desc_label = Label(config_frame, text=desc_text, bg=AppStyle.BG_COLOR, fg=AppStyle.FG_COLOR, 
                          font=fnt.Font(size=8), justify="left")
        desc_label.grid(column=0, row=3, columnspan=2, sticky="w", pady=(0, 20))
        
        # Buttons
        btn_frame = Frame(config_frame, bg=AppStyle.BG_COLOR)
        btn_frame.grid(column=0, row=4, columnspan=2, sticky="w")
        
        save_btn = Button(btn_frame, text=_("Save Settings"), command=self._save_config)
        save_btn.grid(column=0, row=0, padx=(0, 6))
        
        reset_btn = Button(btn_frame, text=_("Reset to Defaults"), command=self._reset_config)
        reset_btn.grid(column=1, row=0, padx=(0, 6))
        
        close_btn = Button(btn_frame, text=_("Close"), command=self.master.destroy)
        close_btn.grid(column=2, row=0)
        
        # Bind changes to auto-save
        self.max_recent_items_var.trace_add("write", lambda *_: self._auto_save_config())
        self.max_recent_split_items_var.trace_add("write", lambda *_: self._auto_save_config())

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
        """Apply default sort: type, then name."""
        # Get all items with their values
        items = []
        for item in tree.get_children(''):
            type_val = tree.set(item, "type")
            name = tree.item(item)["text"]
            items.append((type_val, name, item))
        
        # Sort by type first, then by name
        items.sort(key=lambda x: (x[0], x[1].lower()))
        
        # Reorder items in treeview
        for index, (type_val, name, item) in enumerate(items):
            tree.move(item, '', index)

    def _refresh_controlnet_list(self) -> None:
        filter_text = (self.cn_filter.get() or "").lower()
        
        # Get cached data
        cached_data = self._get_cached_controlnet_data()
        
        # Filter data based on search text
        if filter_text:
            filtered_data = [(name, type_val, created_date) for name, type_val, created_date in cached_data 
                           if filter_text in name.lower()]
        else:
            filtered_data = cached_data
        
        # Clear existing items
        for item in self.cn_tree.get_children():
            self.cn_tree.delete(item)
        
        # Add items to treeview
        for name, type_val, created_date in filtered_data:
            self.cn_tree.insert("", "end", text=name, values=(type_val, created_date))
        
        # Apply default sort: type, then name
        self._apply_default_sort(self.cn_tree)

    def _refresh_ipadapter_list(self) -> None:
        filter_text = (self.ip_filter.get() or "").lower()
        
        # Get cached data
        cached_data = self._get_cached_ipadapter_data()
        
        # Filter data based on search text
        if filter_text:
            filtered_data = [(name, type_val, created_date) for name, type_val, created_date in cached_data 
                           if filter_text in name.lower()]
        else:
            filtered_data = cached_data
        
        # Clear existing items
        for item in self.ip_tree.get_children():
            self.ip_tree.delete(item)
        
        # Add items to treeview
        for name, type_val, created_date in filtered_data:
            self.ip_tree.insert("", "end", text=name, values=(type_val, created_date))
        
        # Apply default sort: type, then name
        self._apply_default_sort(self.ip_tree)

    def _refresh_all_list(self) -> None:
        filter_text = (self.all_filter.get() or "").lower()
        
        # Build cached data from unified recent list
        cached_data = []
        for file_path in RecentAdaptersWindow._recent_adapter_files_split:
            created_date = self._get_file_creation_date(file_path)
            adapter_type = self._get_adapter_type(file_path, is_controlnet=False)
            cached_data.append((file_path, adapter_type, created_date))
        
        # Filter
        if filter_text:
            filtered_data = [(name, type_val, created_date) for name, type_val, created_date in cached_data 
                           if filter_text in name.lower()]
        else:
            filtered_data = cached_data
        
        # Clear and repopulate
        for item in self.all_tree.get_children():
            self.all_tree.delete(item)
        for name, type_val, created_date in filtered_data:
            self.all_tree.insert("", "end", text=name, values=(type_val, created_date))
        
        # Default sort
        self._apply_default_sort(self.all_tree)

    def _select_all_adapter(self, is_controlnet: bool, replace: bool) -> None:
        try:
            selection = self.all_tree.selection()
            if not selection:
                return
            file_path: str = self.all_tree.item(selection[0])["text"]
            # Add to proper recent lists based on user's application
            if is_controlnet:
                RecentAdaptersWindow.add_recent_controlnet(file_path)
            else:
                RecentAdaptersWindow.add_recent_ipadapter(file_path)
            # Unified recent list already contains this
            self.app_actions.set_adapter_from_adapters_window(file_path, is_controlnet=is_controlnet, replace=replace)
            self.master.destroy()
        except Exception:
            pass

    def _select_controlnet(self, replace: bool = True) -> None:
        try:
            selection = self.cn_tree.selection()
            if not selection:
                return
            # Get the selected item's text (file path)
            file_path: str = self.cn_tree.item(selection[0])["text"]
            # Add to recent controlnets
            RecentAdaptersWindow.add_recent_controlnet(file_path)
            # Unified callback: is_controlnet=True
            self.app_actions.set_adapter_from_adapters_window(file_path, is_controlnet=True, replace=replace)
            # Close after action
            self.master.destroy()
        except Exception:
            # Do nothing on selection issues
            pass

    def _select_ipadapter(self, replace: bool = True) -> None:
        try:
            selection = self.ip_tree.selection()
            if not selection:
                return
            # Get the selected item's text (file path)
            file_path: str = self.ip_tree.item(selection[0])["text"]
            # Add to recent ipadapters
            RecentAdaptersWindow.add_recent_ipadapter(file_path)
            # Unified callback: is_controlnet=False
            self.app_actions.set_adapter_from_adapters_window(file_path, is_controlnet=False, replace=replace)
            # Close after action
            self.master.destroy()
        except Exception:
            pass

    def _refresh_cache(self) -> None:
        """Refresh the adapter data cache."""
        RecentAdaptersWindow._controlnet_cache = None
        RecentAdaptersWindow._ipadapter_cache = None
        RecentAdaptersWindow._cache_timestamp = None
        self._refresh_controlnet_list()
        self._refresh_ipadapter_list()
        self._update_cache_status_display()

    def _get_cached_controlnet_data(self) -> list[tuple[str, str, str]]:
        """Get cached controlnet data or build cache if needed."""
        if RecentAdaptersWindow._controlnet_cache is None:
            RecentAdaptersWindow._controlnet_cache = self._build_controlnet_data()
            RecentAdaptersWindow._cache_timestamp = self._get_current_timestamp()
            self._update_cache_status_display()
        return RecentAdaptersWindow._controlnet_cache

    def _get_cached_ipadapter_data(self) -> list[tuple[str, str, str]]:
        """Get cached ipadapter data or build cache if needed."""
        if RecentAdaptersWindow._ipadapter_cache is None:
            RecentAdaptersWindow._ipadapter_cache = self._build_ipadapter_data()
            RecentAdaptersWindow._cache_timestamp = self._get_current_timestamp()
            self._update_cache_status_display()
        return RecentAdaptersWindow._ipadapter_cache

    def _build_controlnet_data(self) -> list[tuple[str, str, str]]:
        """Build controlnet data cache from recent file paths."""
        data = []
        for file_path in RecentAdaptersWindow._recent_controlnets:
            # Get file creation date
            created_date = self._get_file_creation_date(file_path)
            # Determine type based on file name or extension
            adapter_type = self._get_adapter_type(file_path, is_controlnet=True)
            data.append((file_path, adapter_type, created_date))
        return data

    def _build_ipadapter_data(self) -> list[tuple[str, str, str]]:
        """Build ipadapter data cache from recent file paths."""
        data = []
        for file_path in RecentAdaptersWindow._recent_ipadapters:
            # Get file creation date
            created_date = self._get_file_creation_date(file_path)
            # Determine type based on file name or extension
            adapter_type = self._get_adapter_type(file_path, is_controlnet=False)
            data.append((file_path, adapter_type, created_date))
        return data

    def _get_file_creation_date(self, file_path: str) -> str:
        """Get the creation date of a file."""
        try:
            from datetime import datetime
            import os
            
            if os.path.exists(file_path):
                stat = os.stat(file_path)
                creation_time = stat.st_ctime
                dt = datetime.fromtimestamp(creation_time)
                return dt.strftime("%Y-%m-%d %H:%M")
            else:
                return "Unknown"
        except Exception:
            return "Unknown"

    def _get_adapter_type(self, file_path: str, is_controlnet: bool) -> str:
        """Determine adapter type based on file path."""
        if is_controlnet:
            # Try to determine controlnet type from filename
            filename = os.path.basename(file_path).lower()
            if "canny" in filename:
                return "Canny"
            elif "depth" in filename:
                return "Depth"
            elif "pose" in filename:
                return "Pose"
            elif "lineart" in filename:
                return "LineArt"
            elif "openpose" in filename:
                return "OpenPose"
            else:
                return "ControlNet"
        else:
            # Try to determine IP adapter type from filename
            filename = os.path.basename(file_path).lower()
            if "face" in filename:
                return "Face"
            elif "style" in filename:
                return "Style"
            elif "plus" in filename:
                return "Plus"
            else:
                return "IP Adapter"

    def _get_current_timestamp(self) -> float:
        """Get current timestamp for cache tracking."""
        return time.time()

    def _update_cache_status_display(self) -> None:
        """Update the cache status display in both tabs."""
        cache_prefix = _("Cache")
        
        if RecentAdaptersWindow._cache_timestamp is None:
            status_text = f"{cache_prefix}: {_('Not loaded')}"
        else:
            cache_time = datetime.fromtimestamp(RecentAdaptersWindow._cache_timestamp)
            time_str = cache_time.strftime("%Y-%m-%d %H:%M:%S")
            status_text = f"{cache_prefix}: {time_str}"
        
        if hasattr(self, 'cn_cache_status'):
            self.cn_cache_status.config(text=status_text)
        if hasattr(self, 'ip_cache_status'):
            self.ip_cache_status.config(text=status_text)

    def _is_cache_stale(self, max_age_seconds: int = 3600) -> bool:
        """Check if cache is stale (older than max_age_seconds)."""
        if RecentAdaptersWindow._cache_timestamp is None:
            return True
        return (time.time() - RecentAdaptersWindow._cache_timestamp) > max_age_seconds

    def _save_config(self) -> None:
        """Save configuration to app_info_cache."""
        try:
            # Validate values
            max_recent_items = max(1, self.max_recent_items_var.get())
            max_recent_split_items = max(1, self.max_recent_split_items_var.get())
            
            # Update instance variables
            self.max_recent_items = max_recent_items
            self.max_recent_split_items = max_recent_split_items
            
            # Save to cache
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY, max_recent_items)
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY, max_recent_split_items)
            
            # Apply limits to existing lists
            self._apply_limits_to_lists()
            
            logger.info(f"Saved recent adapters configuration: max_recent_items={max_recent_items}, max_recent_split_items={max_recent_split_items}")
        except Exception as e:
            logger.error(f"Failed to save configuration: {e}")

    def _auto_save_config(self) -> None:
        """Auto-save configuration when values change."""
        try:
            # Validate and update values
            max_recent_items = max(1, self.max_recent_items_var.get())
            max_recent_split_items = max(1, self.max_recent_split_items_var.get())
            
            # Update instance variables
            self.max_recent_items = max_recent_items
            self.max_recent_split_items = max_recent_split_items
            
            # Save to cache
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY, max_recent_items)
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY, max_recent_split_items)
            
            # Apply limits to existing lists
            self._apply_limits_to_lists()
        except Exception as e:
            logger.error(f"Failed to auto-save configuration: {e}")

    def _reset_config(self) -> None:
        """Reset configuration to default values."""
        try:
            # Reset to defaults
            self.max_recent_items = RecentAdaptersWindow.DEFAULT_MAX_RECENT_ITEMS
            self.max_recent_split_items = RecentAdaptersWindow.DEFAULT_MAX_RECENT_SPLIT_ITEMS
            
            # Update UI variables
            self.max_recent_items_var.set(self.max_recent_items)
            self.max_recent_split_items_var.set(self.max_recent_split_items)
            
            # Save to cache
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY, self.max_recent_items)
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY, self.max_recent_split_items)
            
            # Apply limits to existing lists
            self._apply_limits_to_lists()
            
            logger.info("Reset recent adapters configuration to defaults")
        except Exception as e:
            logger.error(f"Failed to reset configuration: {e}")

    def _apply_limits_to_lists(self) -> None:
        """Apply current limits to existing recent adapter lists."""
        try:
            # Trim lists to current limits
            if len(RecentAdaptersWindow._recent_controlnets) > self.max_recent_items:
                RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:self.max_recent_items]
            if len(RecentAdaptersWindow._recent_ipadapters) > self.max_recent_items:
                RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:self.max_recent_items]
            if len(RecentAdaptersWindow._recent_adapter_files_split) > self.max_recent_split_items:
                RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:self.max_recent_split_items]
        except Exception as e:
            logger.error(f"Failed to apply limits to lists: {e}")

    @staticmethod
    def _get_max_recent_items() -> int:
        """Get the maximum recent items limit from cache."""
        return app_info_cache.get(
            RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY, 
            default_val=RecentAdaptersWindow.DEFAULT_MAX_RECENT_ITEMS
        )

    @staticmethod
    def _get_max_recent_split_items() -> int:
        """Get the maximum recent split items limit from cache."""
        return app_info_cache.get(
            RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY, 
            default_val=RecentAdaptersWindow.DEFAULT_MAX_RECENT_SPLIT_ITEMS
        )

    @staticmethod
    def load_recent_adapters() -> None:
        """Load recent adapters from app info cache."""
        try:
            # Load configuration values
            max_recent_items = RecentAdaptersWindow._get_max_recent_items()
            max_recent_split_items = RecentAdaptersWindow._get_max_recent_split_items()
            
            # Load recent controlnets (just file paths)
            RecentAdaptersWindow._recent_controlnets = app_info_cache.get("recent_controlnets", [])
            
            # Load recent ipadapters (just file paths)
            RecentAdaptersWindow._recent_ipadapters = app_info_cache.get("recent_ipadapters", [])
            
            # Load unified split adapter files list
            RecentAdaptersWindow._recent_adapter_files_split = app_info_cache.get("recent_adapter_files_split", [])
            
            # Ensure lists don't exceed configured limits
            if len(RecentAdaptersWindow._recent_controlnets) > max_recent_items:
                RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:max_recent_items]
            if len(RecentAdaptersWindow._recent_ipadapters) > max_recent_items:
                RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:max_recent_items]
            if len(RecentAdaptersWindow._recent_adapter_files_split) > max_recent_split_items:
                RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:max_recent_split_items]
        except Exception as e:
            # Log the error but don't raise to avoid breaking the app
            logger.error(f"Failed to load recent adapters from cache: {e}")
            # Initialize with empty lists as fallback
            RecentAdaptersWindow._recent_controlnets = []
            RecentAdaptersWindow._recent_ipadapters = []
            RecentAdaptersWindow._recent_adapter_files_split = []

    @staticmethod
    def save_recent_adapters() -> None:
        """Save recent adapters to app info cache."""
        try:
            app_info_cache.set("recent_controlnets", RecentAdaptersWindow._recent_controlnets)
            app_info_cache.set("recent_ipadapters", RecentAdaptersWindow._recent_ipadapters)
            app_info_cache.set("recent_adapter_files_split", RecentAdaptersWindow._recent_adapter_files_split)
        except Exception as e:
            # Log the error but don't raise to avoid breaking the app
            logger.error(f"Failed to save recent adapters to cache: {e}")

    @staticmethod
    def _validate_and_process_file_paths(file_paths: str) -> list[str]:
        """Validate file paths and return list of valid existing files.
        
        Args:
            file_paths: Comma-separated string of file paths
            
        Returns:
            List of valid existing file paths
        """
        if not file_paths or file_paths.strip() == "":
            return []
        
        valid_paths = []
        for file_path in file_paths.split(","):
            file_path = file_path.strip()
            if file_path and os.path.exists(file_path):
                valid_paths.append(file_path)
        return valid_paths

    @staticmethod
    def add_recent_controlnet(file_path: str) -> None:
        """Add a controlnet to recent adapters list."""
        # Get current limit from cache
        max_recent_items = RecentAdaptersWindow._get_max_recent_items()
        
        # Validate and process file paths
        valid_paths = RecentAdaptersWindow._validate_and_process_file_paths(file_path)
        
        for path in valid_paths:
            # Remove if already exists
            if path in RecentAdaptersWindow._recent_controlnets:
                RecentAdaptersWindow._recent_controlnets.remove(path)
            
            # Add to beginning
            RecentAdaptersWindow._recent_controlnets.insert(0, path)
        
        # Limit to configured number
        if len(RecentAdaptersWindow._recent_controlnets) > max_recent_items:
            RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:max_recent_items]

    @staticmethod
    def add_recent_ipadapter(file_path: str) -> None:
        """Add an IP adapter to recent adapters list."""
        # Get current limit from cache
        max_recent_items = RecentAdaptersWindow._get_max_recent_items()
        
        # Validate and process file paths
        valid_paths = RecentAdaptersWindow._validate_and_process_file_paths(file_path)
        
        for path in valid_paths:
            # Remove if already exists
            if path in RecentAdaptersWindow._recent_ipadapters:
                RecentAdaptersWindow._recent_ipadapters.remove(path)
            
            # Add to beginning
            RecentAdaptersWindow._recent_ipadapters.insert(0, path)
        
        # Limit to configured number
        if len(RecentAdaptersWindow._recent_ipadapters) > max_recent_items:
            RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:max_recent_items]

    @staticmethod
    def add_recent_adapter_file(file_path: str) -> None:
        """Add a single adapter file path to the unified list (no directory expansion)."""
        if not file_path or file_path.strip() == "":
            return
        path = file_path.strip()
        try:
            if not os.path.isfile(path):
                return
        except Exception:
            return

        try:
            norm = os.path.abspath(path)
        except Exception:
            norm = path

        if norm in RecentAdaptersWindow._recent_adapter_files_split:
            RecentAdaptersWindow._recent_adapter_files_split.remove(norm)
        RecentAdaptersWindow._recent_adapter_files_split.insert(0, norm)

        # Get current limit from cache
        max_recent_split_items = RecentAdaptersWindow._get_max_recent_split_items()

        if len(RecentAdaptersWindow._recent_adapter_files_split) > max_recent_split_items:
            RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:max_recent_split_items]

    @staticmethod
    def contains_recent_adapter_file(file_path: str) -> bool:
        """Return True only if the provided file path is present in the unified list."""
        if not file_path or file_path.strip() == "":
            return False
        try:
            norm = os.path.abspath(file_path.strip())
        except Exception:
            norm = file_path.strip()
        return norm in RecentAdaptersWindow._recent_adapter_files_split
