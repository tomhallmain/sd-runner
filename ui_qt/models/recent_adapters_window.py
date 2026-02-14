"""
RecentAdaptersWindow -- recent ControlNet and IP Adapter browser (PySide6 port).

Ported from ``ui/recent_adapters_window.py``.  All static class-level
data (``_recent_controlnets``, ``_recent_ipadapters``,
``_recent_adapter_files_split``, etc.) and the static helper methods
(``load_recent_adapters``, ``save_recent_adapters``,
``add_recent_adapter_file``, ``contains_recent_adapter_file``, etc.)
stay on the *original* ``ui.recent_adapters_window.RecentAdaptersWindow``
so that ``CacheController`` and ``AppActions`` continue to work.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from ui.recent_adapters_window import RecentAdaptersWindow as _Backend
from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.translations import I18N

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._
logger = get_logger("ui_qt.recent_adapters_window")


# ======================================================================
# Helpers
# ======================================================================

def _sort_tree(tree: QTreeWidget, col: int) -> None:
    current = getattr(tree, "_sort_reverse", False)
    new_reverse = not current
    tree._sort_reverse = new_reverse
    order = Qt.SortOrder.DescendingOrder if new_reverse else Qt.SortOrder.AscendingOrder
    tree.sortItems(col, order)


def _get_file_creation_date(file_path: str) -> str:
    try:
        if os.path.exists(file_path):
            dt = datetime.fromtimestamp(os.stat(file_path).st_ctime)
            return dt.strftime("%Y-%m-%d %H:%M")
    except Exception:
        pass
    return "Unknown"


def _get_adapter_type(file_path: str, is_controlnet: bool) -> str:
    fn = os.path.basename(file_path).lower()
    if is_controlnet:
        for kw, label in [("canny", "Canny"), ("depth", "Depth"), ("pose", "Pose"),
                           ("lineart", "LineArt"), ("openpose", "OpenPose")]:
            if kw in fn:
                return label
        return "ControlNet"
    else:
        for kw, label in [("face", "Face"), ("style", "Style"), ("plus", "Plus")]:
            if kw in fn:
                return label
        return "IP Adapter"


# ======================================================================
# RecentAdaptersWindow
# ======================================================================

class RecentAdaptersWindow(SmartDialog):
    """PySide6 recent-adapters browser with four tabs."""

    # Persistent storage for recent adapters (just file paths)
    _recent_controlnets: list[str] = []
    _recent_ipadapters: list[str] = []
    _recent_adapter_files_split: list[str] = []
    _controlnet_cache = None
    _ipadapter_cache = None
    _cache_timestamp = None

    # Default constants
    DEFAULT_MAX_RECENT_ITEMS = 1000
    DEFAULT_MAX_RECENT_SPLIT_ITEMS = 2000
    MAX_RECENT_ITEMS_KEY = "max_recent_items"
    MAX_RECENT_SPLIT_ITEMS_KEY = "max_recent_split_items"

    @staticmethod
    def _get_max_recent_items() -> int:
        from utils.app_info_cache import app_info_cache
        return app_info_cache.get(
            RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY,
            default_val=RecentAdaptersWindow.DEFAULT_MAX_RECENT_ITEMS
        )

    @staticmethod
    def _get_max_recent_split_items() -> int:
        from utils.app_info_cache import app_info_cache
        return app_info_cache.get(
            RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY,
            default_val=RecentAdaptersWindow.DEFAULT_MAX_RECENT_SPLIT_ITEMS
        )

    @staticmethod
    def load_recent_adapters() -> None:
        from utils.app_info_cache import app_info_cache
        try:
            max_recent_items = RecentAdaptersWindow._get_max_recent_items()
            max_recent_split_items = RecentAdaptersWindow._get_max_recent_split_items()
            RecentAdaptersWindow._recent_controlnets = app_info_cache.get("recent_controlnets", [])
            RecentAdaptersWindow._recent_ipadapters = app_info_cache.get("recent_ipadapters", [])
            RecentAdaptersWindow._recent_adapter_files_split = app_info_cache.get("recent_adapter_files_split", [])
            if len(RecentAdaptersWindow._recent_controlnets) > max_recent_items:
                RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:max_recent_items]
            if len(RecentAdaptersWindow._recent_ipadapters) > max_recent_items:
                RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:max_recent_items]
            if len(RecentAdaptersWindow._recent_adapter_files_split) > max_recent_split_items:
                RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:max_recent_split_items]
        except Exception as e:
            import logging
            logging.getLogger("ui_qt.recent_adapters_window").error(f"Failed to load recent adapters from cache: {e}")
            RecentAdaptersWindow._recent_controlnets = []
            RecentAdaptersWindow._recent_ipadapters = []
            RecentAdaptersWindow._recent_adapter_files_split = []

    @staticmethod
    def save_recent_adapters() -> None:
        from utils.app_info_cache import app_info_cache
        try:
            app_info_cache.set("recent_controlnets", RecentAdaptersWindow._recent_controlnets)
            app_info_cache.set("recent_ipadapters", RecentAdaptersWindow._recent_ipadapters)
            app_info_cache.set("recent_adapter_files_split", RecentAdaptersWindow._recent_adapter_files_split)
        except Exception as e:
            import logging
            logging.getLogger("ui_qt.recent_adapters_window").error(f"Failed to save recent adapters to cache: {e}")

    @staticmethod
    def _validate_and_process_file_paths(file_paths: str) -> list[str]:
        import os
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
        max_recent_items = RecentAdaptersWindow._get_max_recent_items()
        valid_paths = RecentAdaptersWindow._validate_and_process_file_paths(file_path)
        for path in valid_paths:
            if path in RecentAdaptersWindow._recent_controlnets:
                RecentAdaptersWindow._recent_controlnets.remove(path)
            RecentAdaptersWindow._recent_controlnets.insert(0, path)
        if len(RecentAdaptersWindow._recent_controlnets) > max_recent_items:
            RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:max_recent_items]

    @staticmethod
    def add_recent_ipadapter(file_path: str) -> None:
        max_recent_items = RecentAdaptersWindow._get_max_recent_items()
        valid_paths = RecentAdaptersWindow._validate_and_process_file_paths(file_path)
        for path in valid_paths:
            if path in RecentAdaptersWindow._recent_ipadapters:
                RecentAdaptersWindow._recent_ipadapters.remove(path)
            RecentAdaptersWindow._recent_ipadapters.insert(0, path)
        if len(RecentAdaptersWindow._recent_ipadapters) > max_recent_items:
            RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:max_recent_items]

    @staticmethod
    def add_recent_adapter_file(file_path: str) -> None:
        import os
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
        max_recent_split_items = RecentAdaptersWindow._get_max_recent_split_items()
        if len(RecentAdaptersWindow._recent_adapter_files_split) > max_recent_split_items:
            RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:max_recent_split_items]

    @staticmethod
    def contains_recent_adapter_file(file_path: str) -> int:
        import os
        if not file_path or file_path.strip() == "":
            return -1
        try:
            norm = os.path.abspath(file_path.strip())
        except Exception:
            norm = file_path.strip()
        try:
            return RecentAdaptersWindow._recent_adapter_files_split.index(norm)
        except ValueError:
            return -1

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(parent=parent, title=_("Recent Adapters"), geometry="1000x500")
        self._app_actions = app_actions
        self._max_recent = RecentAdaptersWindow._get_max_recent_items()
        self._max_split = RecentAdaptersWindow._get_max_recent_split_items()

        self._tabs = QTabWidget()
        cn_page = QWidget()
        ip_page = QWidget()
        all_page = QWidget()
        cfg_page = QWidget()
        self._tabs.addTab(cn_page, _("Recent ControlNets"))
        self._tabs.addTab(ip_page, _("Recent IP Adapters"))
        self._tabs.addTab(all_page, _("All Recent Adapters"))
        self._tabs.addTab(cfg_page, _("Configuration"))

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.addWidget(self._tabs)

        self._build_controlnet_tab(cn_page)
        self._build_ipadapter_tab(ip_page)
        self._build_all_tab(all_page)
        self._build_config_tab(cfg_page)

        QShortcut(QKeySequence("Escape"), self, self.close)
        self.show()

    def select_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    # ==================================================================
    # ControlNet tab
    # ==================================================================
    def _build_controlnet_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        frow = QHBoxLayout()
        frow.addWidget(QLabel(_("Filter")))
        self._cn_filter = QLineEdit()
        self._cn_filter.textChanged.connect(self._refresh_cn)
        frow.addWidget(self._cn_filter)
        layout.addLayout(frow)

        self._cn_cache_label = QLabel("")
        layout.addWidget(self._cn_cache_label)

        self._cn_tree = self._make_tree([_("ControlNet File"), _("Type"), _("Created")])
        self._cn_tree.itemDoubleClicked.connect(lambda: self._select_cn())
        layout.addWidget(self._cn_tree)

        btn = QHBoxLayout()
        for text, replace in [(_("Replace"), True), (_("Add"), False)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, r=replace: self._select_cn(replace=r))
            btn.addWidget(b)
        refresh = QPushButton(_("Refresh")); refresh.clicked.connect(self._refresh_cache); btn.addWidget(refresh)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_cn()
        self._update_cache_status()

    # ==================================================================
    # IP Adapter tab
    # ==================================================================
    def _build_ipadapter_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        frow = QHBoxLayout()
        frow.addWidget(QLabel(_("Filter")))
        self._ip_filter = QLineEdit()
        self._ip_filter.textChanged.connect(self._refresh_ip)
        frow.addWidget(self._ip_filter)
        layout.addLayout(frow)

        self._ip_cache_label = QLabel("")
        layout.addWidget(self._ip_cache_label)

        self._ip_tree = self._make_tree([_("IP Adapter File"), _("Type"), _("Created")])
        self._ip_tree.itemDoubleClicked.connect(lambda: self._select_ip())
        layout.addWidget(self._ip_tree)

        btn = QHBoxLayout()
        for text, replace in [(_("Replace"), True), (_("Add"), False)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, r=replace: self._select_ip(replace=r))
            btn.addWidget(b)
        refresh = QPushButton(_("Refresh")); refresh.clicked.connect(self._refresh_cache); btn.addWidget(refresh)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_ip()
        self._update_cache_status()

    # ==================================================================
    # All tab
    # ==================================================================
    def _build_all_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        info = QLabel(_("Individual files, including from directory-split runs (no directories)"))
        info.setStyleSheet("font-style: italic; font-size: 8pt;")
        layout.addWidget(info)

        frow = QHBoxLayout()
        frow.addWidget(QLabel(_("Filter")))
        self._all_filter = QLineEdit()
        self._all_filter.textChanged.connect(self._refresh_all)
        frow.addWidget(self._all_filter)
        layout.addLayout(frow)

        self._all_tree = self._make_tree([_("Adapter File"), _("Type"), _("Created")])
        layout.addWidget(self._all_tree)

        btn = QHBoxLayout()
        for text, cn, repl in [
            (_("ControlNet (Replace)"), True, True),
            (_("ControlNet (Add)"), True, False),
            (_("IP Adapter (Replace)"), False, True),
            (_("IP Adapter (Add)"), False, False),
        ]:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, _cn=cn, _r=repl: self._select_all(_cn, _r))
            btn.addWidget(b)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_all()

    # ==================================================================
    # Config tab
    # ==================================================================
    def _build_config_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 20, 20, 20)

        title = QLabel(_("Recent Adapters Configuration"))
        title.setStyleSheet("font-size: 12pt; font-weight: bold;")
        layout.addWidget(title)

        row1 = QHBoxLayout()
        row1.addWidget(QLabel(_("Max Recent Items:")))
        self._max_recent_spin = QSpinBox()
        self._max_recent_spin.setRange(1, 100_000)
        self._max_recent_spin.setValue(self._max_recent)
        row1.addWidget(self._max_recent_spin)
        row1.addStretch()
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        row2.addWidget(QLabel(_("Max Recent Split Items:")))
        self._max_split_spin = QSpinBox()
        self._max_split_spin.setRange(1, 100_000)
        self._max_split_spin.setValue(self._max_split)
        row2.addWidget(self._max_split_spin)
        row2.addStretch()
        layout.addLayout(row2)

        desc = QLabel(
            _("These settings control how many recent adapters are kept in memory.\n"
              "Higher values use more memory but keep more history.\n"
              "Changes take effect immediately and are saved automatically.")
        )
        desc.setWordWrap(True)
        layout.addWidget(desc)

        btn = QHBoxLayout()
        save_btn = QPushButton(_("Save Settings"))
        save_btn.clicked.connect(self._save_config)
        btn.addWidget(save_btn)
        reset_btn = QPushButton(_("Reset to Defaults"))
        reset_btn.clicked.connect(self._reset_config)
        btn.addWidget(reset_btn)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        layout.addStretch()

    # ==================================================================
    # Tree factory
    # ==================================================================
    def _make_tree(self, headers: list[str]) -> QTreeWidget:
        tree = QTreeWidget()
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSortingEnabled(False)
        hdr = tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        if len(headers) > 1:
            hdr.resizeSection(1, 150)
        if len(headers) > 2:
            hdr.resizeSection(2, 150)
        hdr.sectionClicked.connect(lambda col, t=tree: _sort_tree(t, col))
        return tree

    # ==================================================================
    # Refresh lists
    # ==================================================================
    def _refresh_cn(self) -> None:
        ft = (self._cn_filter.text() or "").lower()
        data = self._cached_cn()
        if ft:
            data = [(n, t, c) for n, t, c in data if ft in n.lower()]
        self._cn_tree.clear()
        for n, t, c in data:
            QTreeWidgetItem(self._cn_tree, [n, t, c])
        self._cn_tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _refresh_ip(self) -> None:
        ft = (self._ip_filter.text() or "").lower()
        data = self._cached_ip()
        if ft:
            data = [(n, t, c) for n, t, c in data if ft in n.lower()]
        self._ip_tree.clear()
        for n, t, c in data:
            QTreeWidgetItem(self._ip_tree, [n, t, c])
        self._ip_tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _refresh_all(self) -> None:
        ft = (self._all_filter.text() or "").lower()
        data = [
            (fp, _get_adapter_type(fp, is_controlnet=False), _get_file_creation_date(fp))
            for fp in RecentAdaptersWindow._recent_adapter_files_split
        ]
        if ft:
            data = [(n, t, c) for n, t, c in data if ft in n.lower()]
        self._all_tree.clear()
        for n, t, c in data:
            QTreeWidgetItem(self._all_tree, [n, t, c])
        self._all_tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _refresh_cache(self) -> None:
        RecentAdaptersWindow._controlnet_cache = None
        RecentAdaptersWindow._ipadapter_cache = None
        RecentAdaptersWindow._cache_timestamp = None
        self._refresh_cn()
        self._refresh_ip()
        self._update_cache_status()

    # ------------------------------------------------------------------
    # Cache builders
    # ------------------------------------------------------------------
    def _cached_cn(self) -> list[tuple[str, str, str]]:
        if RecentAdaptersWindow._controlnet_cache is None:
            RecentAdaptersWindow._controlnet_cache = [
                (fp, _get_adapter_type(fp, True), _get_file_creation_date(fp))
                for fp in RecentAdaptersWindow._recent_controlnets
            ]
            RecentAdaptersWindow._cache_timestamp = time.time()
        return RecentAdaptersWindow._controlnet_cache

    def _cached_ip(self) -> list[tuple[str, str, str]]:
        if RecentAdaptersWindow._ipadapter_cache is None:
            RecentAdaptersWindow._ipadapter_cache = [
                (fp, _get_adapter_type(fp, False), _get_file_creation_date(fp))
                for fp in RecentAdaptersWindow._recent_ipadapters
            ]
            RecentAdaptersWindow._cache_timestamp = time.time()
        return RecentAdaptersWindow._ipadapter_cache

    def _update_cache_status(self) -> None:
        prefix = _("Cache")
        if RecentAdaptersWindow._cache_timestamp is None:
            text = f"{prefix}: {_('Not loaded')}"
        else:
            ts = datetime.fromtimestamp(RecentAdaptersWindow._cache_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            text = f"{prefix}: {ts}"
        for lbl in [
            getattr(self, "_cn_cache_label", None),
            getattr(self, "_ip_cache_label", None),
        ]:
            if lbl:
                lbl.setText(text)

    # ==================================================================
    # Selection callbacks
    # ==================================================================
    def _select_cn(self, replace: bool = True) -> None:
        items = self._cn_tree.selectedItems()
        if not items:
            return
        fp = items[0].text(0)
        RecentAdaptersWindow.add_recent_controlnet(fp)
        self._app_actions.set_adapter_from_adapters_window(fp, is_controlnet=True, replace=replace)
        self.close()

    def _select_ip(self, replace: bool = True) -> None:
        items = self._ip_tree.selectedItems()
        if not items:
            return
        fp = items[0].text(0)
        RecentAdaptersWindow.add_recent_ipadapter(fp)
        self._app_actions.set_adapter_from_adapters_window(fp, is_controlnet=False, replace=replace)
        self.close()

    def _select_all(self, is_controlnet: bool, replace: bool) -> None:
        items = self._all_tree.selectedItems()
        if not items:
            return
        fp = items[0].text(0)
        if is_controlnet:
            RecentAdaptersWindow.add_recent_controlnet(fp)
        else:
            RecentAdaptersWindow.add_recent_ipadapter(fp)
        self._app_actions.set_adapter_from_adapters_window(fp, is_controlnet=is_controlnet, replace=replace)
        self.close()

    # ==================================================================
    # Configuration
    # ==================================================================
    def _save_config(self) -> None:
        try:
            mi = max(1, self._max_recent_spin.value())
            ms = max(1, self._max_split_spin.value())
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_ITEMS_KEY, mi)
            app_info_cache.set(RecentAdaptersWindow.MAX_RECENT_SPLIT_ITEMS_KEY, ms)
            self._apply_limits(mi, ms)
            logger.info(f"Saved config: max_recent_items={mi}, max_recent_split_items={ms}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _reset_config(self) -> None:
        mi = RecentAdaptersWindow.DEFAULT_MAX_RECENT_ITEMS
        ms = RecentAdaptersWindow.DEFAULT_MAX_RECENT_SPLIT_ITEMS
        self._max_recent_spin.setValue(mi)
        self._max_split_spin.setValue(ms)
        self._save_config()

    @staticmethod
    def _apply_limits(max_items: int, max_split: int) -> None:
        if len(RecentAdaptersWindow._recent_controlnets) > max_items:
            RecentAdaptersWindow._recent_controlnets = RecentAdaptersWindow._recent_controlnets[:max_items]
        if len(RecentAdaptersWindow._recent_ipadapters) > max_items:
            RecentAdaptersWindow._recent_ipadapters = RecentAdaptersWindow._recent_ipadapters[:max_items]
        if len(RecentAdaptersWindow._recent_adapter_files_split) > max_split:
            RecentAdaptersWindow._recent_adapter_files_split = RecentAdaptersWindow._recent_adapter_files_split[:max_split]
