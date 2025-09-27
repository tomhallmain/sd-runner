from datetime import datetime
import os
import time
from tkinter import Toplevel, Frame, Label, StringVar, Entry, Scrollbar
import tkinter.font as fnt
from tkinter.ttk import Button, Notebook, Treeview
from typing import Optional, Any

from ui.app_style import AppStyle
from utils.app_info_cache import app_info_cache
from utils.translations import I18N

_ = I18N._


class RecentAdaptersWindow:
    top_level: Optional[Toplevel] = None
    _controlnet_cache: Optional[list[tuple[str, str, str]]] = None  # (name, type, created_date)
    _ipadapter_cache: Optional[list[tuple[str, str, str]]] = None    # (name, type, created_date)
    _cache_timestamp: Optional[float] = None
    
    # Persistent storage for recent adapters (just file paths)
    _recent_controlnets: list[str] = []
    _recent_ipadapters: list[str] = []

    def __init__(self, master: Toplevel, app_actions: Any) -> None:
        RecentAdaptersWindow.top_level = Toplevel(master, bg=AppStyle.BG_COLOR)
        RecentAdaptersWindow.top_level.title(_("Recent Adapters"))
        RecentAdaptersWindow.top_level.geometry("800x450")

        self.master: Toplevel = RecentAdaptersWindow.top_level
        self.app_actions: Any = app_actions

        # Main frame
        self.frame: Frame = Frame(self.master, bg=AppStyle.BG_COLOR)
        self.frame.grid(column=0, row=0, sticky="nsew", padx=10, pady=10)
        self.frame.columnconfigure(0, weight=1)
        self.frame.rowconfigure(0, weight=1)

        # Notebook
        self.notebook = Notebook(self.frame)
        self.notebook.grid(column=0, row=0, sticky="nsew")

        # Tabs
        self.controlnet_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.ipadapter_tab = Frame(self.notebook, bg=AppStyle.BG_COLOR)
        self.notebook.add(self.controlnet_tab, text=_("Recent ControlNets"))
        self.notebook.add(self.ipadapter_tab, text=_("Recent IP Adapters"))

        # Build each tab
        self._build_controlnet_tab()
        self._build_ipadapter_tab()

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
        self.cn_tree.column("#0", width=400, minwidth=200)
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
        self.ip_tree.column("#0", width=400, minwidth=200)
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

    @staticmethod
    def load_recent_adapters() -> None:
        """Load recent adapters from app info cache."""
        try:
            # Load recent controlnets (just file paths)
            RecentAdaptersWindow._recent_controlnets = app_info_cache.get("recent_controlnets", [])
            
            # Load recent ipadapters (just file paths)
            RecentAdaptersWindow._recent_ipadapters = app_info_cache.get("recent_ipadapters", [])
            
            # Ensure lists don't exceed reasonable limits
            MAX_RECENT_ITEMS = 50
            if len(RecentAdaptersWindow._recent_controlnets) > MAX_RECENT_ITEMS:
                RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:MAX_RECENT_ITEMS]
            if len(RecentAdaptersWindow._recent_ipadapters) > MAX_RECENT_ITEMS:
                RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:MAX_RECENT_ITEMS]
        except Exception as e:
            # If loading fails, start with empty lists
            RecentAdaptersWindow._recent_controlnets = []
            RecentAdaptersWindow._recent_ipadapters = []

    @staticmethod
    def save_recent_adapters() -> None:
        """Save recent adapters to app info cache."""
        try:
            app_info_cache.set("recent_controlnets", RecentAdaptersWindow._recent_controlnets)
            app_info_cache.set("recent_ipadapters", RecentAdaptersWindow._recent_ipadapters)
        except Exception as e:
            # Log error but don't raise to avoid breaking the app
            pass

    @staticmethod
    def add_recent_controlnet(file_path: str) -> None:
        """Add a controlnet to recent adapters list."""
        # Remove if already exists
        if file_path in RecentAdaptersWindow._recent_controlnets:
            RecentAdaptersWindow._recent_controlnets.remove(file_path)
        
        # Add to beginning
        RecentAdaptersWindow._recent_controlnets.insert(0, file_path)
        
        # Limit to reasonable number
        MAX_RECENT_ITEMS = 50
        if len(RecentAdaptersWindow._recent_controlnets) > MAX_RECENT_ITEMS:
            RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:MAX_RECENT_ITEMS]

    @staticmethod
    def add_recent_ipadapter(file_path: str) -> None:
        """Add an IP adapter to recent adapters list."""
        # Remove if already exists
        if file_path in RecentAdaptersWindow._recent_ipadapters:
            RecentAdaptersWindow._recent_ipadapters.remove(file_path)
        
        # Add to beginning
        RecentAdaptersWindow._recent_ipadapters.insert(0, file_path)
        
        # Limit to reasonable number
        MAX_RECENT_ITEMS = 50
        if len(RecentAdaptersWindow._recent_ipadapters) > MAX_RECENT_ITEMS:
            RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:MAX_RECENT_ITEMS]
