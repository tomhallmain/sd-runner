"""
RecentAdaptersWindow -- recent ControlNet and IP Adapter browser.

The recent lists and favourites live in ``sd_runner.models.recent_adapters_state``;
this class browses them and holds the display rows it builds from them.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Callable, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QSpinBox, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from lib.tree_sort_qt import toggle_sort
from sd_runner.models.recent_adapters_state import RecentAdaptersState
from sd_runner.persistence.app_info_cache import app_info_cache
from lib.logging_setup import get_logger
from lib.translations import I18N

if TYPE_CHECKING:
    from sd_runner.ui.app_actions import AppActions

_ = I18N._
logger = get_logger("ui.recent_adapters_window")


# ======================================================================
# Helpers
# ======================================================================

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


@dataclass(frozen=True)
class _AdapterKind:
    """One of the per-kind recent tabs: what it lists and where a pick goes."""

    #: ``adapter_type`` for ``set_adapter_from_adapters_window``.
    key: str
    tab_title: str
    file_header: str
    #: Name of the ``RecentAdaptersWindow`` class attribute caching its rows.
    cache_attr: str
    recent_files: Callable[[], list[str]]
    type_label: Callable[[str], str]
    record_recent: Callable[[str], None]


def _adapter_kinds() -> tuple[_AdapterKind, ...]:
    """The per-kind tabs, in tab order. Built per call so labels follow the locale."""
    return (
        _AdapterKind(
            key="controlnet",
            tab_title=_("Recent ControlNets"),
            file_header=_("ControlNet File"),
            cache_attr="_controlnet_cache",
            recent_files=lambda: RecentAdaptersState._recent_controlnets,
            type_label=lambda fp: _get_adapter_type(fp, True),
            record_recent=RecentAdaptersState.add_recent_controlnet,
        ),
        _AdapterKind(
            key="ipadapter",
            tab_title=_("Recent IP Adapters"),
            file_header=_("IP Adapter File"),
            cache_attr="_ipadapter_cache",
            recent_files=lambda: RecentAdaptersState._recent_ipadapters,
            type_label=lambda fp: _get_adapter_type(fp, False),
            record_recent=RecentAdaptersState.add_recent_ipadapter,
        ),
        _AdapterKind(
            key="source_prompt",
            tab_title=_("Recent Source Prompts"),
            file_header=_("Source Prompt File"),
            cache_attr="_source_prompt_cache",
            recent_files=lambda: RecentAdaptersState._recent_source_prompts,
            type_label=lambda fp: _("Source Prompt"),
            record_recent=RecentAdaptersState.add_recent_source_prompt,
        ),
    )


# ======================================================================
# RecentAdaptersWindow
# ======================================================================

class RecentAdaptersWindow(SmartDialog):
    """PySide6 recent-adapters browser for accessing adapter history."""

    _instance = None

    #: Display rows built from the state lists. Cleared when the rows they
    #: were built from change, and rebuilt on the next read.
    _controlnet_cache = None
    _ipadapter_cache = None
    _source_prompt_cache = None
    _favorites_cache = None
    _cache_timestamp = None

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(parent=parent, title=_("Recent Adapters"), geometry="1000x500")
        RecentAdaptersWindow._instance = self
        self._app_actions = app_actions
        self._max_recent = RecentAdaptersState._get_max_recent_items()
        self._max_split = RecentAdaptersState._get_max_recent_split_items()

        self._tabs = QTabWidget()
        self._kinds = _adapter_kinds()
        #: Per-kind widgets, keyed by ``_AdapterKind.key``.
        self._filters: dict[str, QLineEdit] = {}
        self._trees: dict[str, QTreeWidget] = {}
        self._cache_labels: dict[str, QLabel] = {}
        kind_pages = []
        for kind in self._kinds:
            page = QWidget()
            self._tabs.addTab(page, kind.tab_title)
            kind_pages.append(page)
        all_page = QWidget()
        fav_page = QWidget()
        cfg_page = QWidget()
        self._tabs.addTab(all_page, _("All Recent Adapters"))
        self._tabs.addTab(fav_page, _("Favorites"))
        self._tabs.addTab(cfg_page, _("Configuration"))

        root = QVBoxLayout(self)
        root.setContentsMargins(15, 15, 15, 15)
        root.addWidget(self._tabs)

        for kind, page in zip(self._kinds, kind_pages):
            self._build_kind_tab(page, kind)
        self._build_all_tab(all_page)
        self._build_favorites_tab(fav_page)
        self._build_config_tab(cfg_page)

        QShortcut(QKeySequence("Escape"), self, self.close)
        self.show()

    def select_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    # ==================================================================
    # Per-kind tabs (ControlNet, IP Adapter, Source Prompt)
    # ==================================================================
    def _build_kind_tab(self, page: QWidget, kind: _AdapterKind) -> None:
        layout = QVBoxLayout(page)
        frow = QHBoxLayout()
        frow.addWidget(QLabel(_("Filter")))
        filter_edit = QLineEdit()
        filter_edit.textChanged.connect(lambda _text, k=kind: self._refresh_kind(k))
        frow.addWidget(filter_edit)
        layout.addLayout(frow)
        self._filters[kind.key] = filter_edit

        cache_label = QLabel("")
        layout.addWidget(cache_label)
        self._cache_labels[kind.key] = cache_label

        tree = self._make_tree([kind.file_header, _("Type"), _("Created")])
        tree.itemDoubleClicked.connect(lambda *_args, k=kind: self._select_kind(k))
        layout.addWidget(tree)
        self._trees[kind.key] = tree

        btn = QHBoxLayout()
        for text, replace in [(_("Replace"), True), (_("Add"), False)]:
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, k=kind, r=replace: self._select_kind(k, replace=r))
            btn.addWidget(b)
        copy_btn = QPushButton(_("Copy"))
        copy_btn.clicked.connect(lambda: self._copy_selected_path(tree))
        btn.addWidget(copy_btn)
        fav_btn = QPushButton(_("Add to Favorites"))
        fav_btn.clicked.connect(lambda: self._add_selected_to_favorites(tree))
        btn.addWidget(fav_btn)
        refresh = QPushButton(_("Refresh")); refresh.clicked.connect(self._refresh_cache); btn.addWidget(refresh)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_kind(kind)
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
        copy_btn = QPushButton(_("Copy"))
        copy_btn.clicked.connect(lambda: self._copy_selected_path(self._all_tree))
        btn.addWidget(copy_btn)
        fav_btn = QPushButton(_("Add to Favorites"))
        fav_btn.clicked.connect(lambda: self._add_selected_to_favorites(self._all_tree))
        btn.addWidget(fav_btn)
        close = QPushButton(_("Close")); close.clicked.connect(self.close); btn.addWidget(close)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_all()

    # ==================================================================
    # Favorites tab
    # ==================================================================
    def _build_favorites_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        info = QLabel(
            _("Preferred adapters regardless of type. "
              "Directories are auto-added when seen in recents.")
        )
        info.setStyleSheet("font-style: italic; font-size: 8pt;")
        info.setWordWrap(True)
        layout.addWidget(info)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(_("Filter")))
        self._fav_filter = QLineEdit()
        self._fav_filter.textChanged.connect(self._refresh_favorites)
        filter_row.addWidget(self._fav_filter)
        layout.addLayout(filter_row)

        target_row = QHBoxLayout()
        target_row.addWidget(QLabel(_("Target Field")))
        self._fav_target_combo = QLineEdit()
        self._fav_target_combo.setReadOnly(True)
        self._fav_target_combo.hide()
        # Use checkbox+buttons style controls to keep this lightweight.
        self._fav_target = "controlnet"
        self._fav_target_cn_btn = QPushButton(_("ControlNet"))
        self._fav_target_ip_btn = QPushButton(_("IP Adapter"))
        self._fav_target_src_btn = QPushButton(_("Source Prompt"))
        self._fav_target_cn_btn.clicked.connect(lambda: self._set_favorite_target("controlnet"))
        self._fav_target_ip_btn.clicked.connect(lambda: self._set_favorite_target("ipadapter"))
        self._fav_target_src_btn.clicked.connect(lambda: self._set_favorite_target("source_prompt"))
        target_row.addWidget(self._fav_target_cn_btn)
        target_row.addWidget(self._fav_target_ip_btn)
        target_row.addWidget(self._fav_target_src_btn)
        self._fav_append_toggle = QCheckBox(_("Append (unchecked = Replace)"))
        self._fav_append_toggle.setChecked(False)
        target_row.addWidget(self._fav_append_toggle)
        target_row.addStretch()
        layout.addLayout(target_row)
        self._set_favorite_target("controlnet")

        self._fav_tree = self._make_tree([_("Favorite Adapter"), _("Created")])
        self._fav_tree.itemDoubleClicked.connect(lambda: self._select_favorite())
        layout.addWidget(self._fav_tree)

        btn = QHBoxLayout()
        use_btn = QPushButton(_("Use Favorite"))
        use_btn.clicked.connect(self._select_favorite)
        btn.addWidget(use_btn)
        remove_btn = QPushButton(_("Remove"))
        remove_btn.clicked.connect(self._remove_favorite)
        btn.addWidget(remove_btn)
        copy_btn = QPushButton(_("Copy"))
        copy_btn.clicked.connect(lambda: self._copy_selected_path(self._fav_tree))
        btn.addWidget(copy_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn.addWidget(close_btn)
        btn.addStretch()
        layout.addLayout(btn)

        self._refresh_favorites()

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
        hdr.sectionClicked.connect(lambda col, t=tree: toggle_sort(t, col))
        return tree

    # ==================================================================
    # Refresh lists
    # ==================================================================
    def _copy_selected_path(self, tree: QTreeWidget) -> None:
        items = tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a row first"))
            return
        path = items[0].text(0)
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(path)
            self._app_actions.toast(_("Copied path to clipboard"))

    def _refresh_kind(self, kind: _AdapterKind) -> None:
        ft = (self._filters[kind.key].text() or "").lower()
        data = self._cached_kind(kind)
        if ft:
            data = [(n, t, c) for n, t, c in data if ft in n.lower()]
        tree = self._trees[kind.key]
        tree.clear()
        for n, t, c in data:
            QTreeWidgetItem(tree, [n, t, c])
        tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _refresh_all(self) -> None:
        ft = (self._all_filter.text() or "").lower()
        data = [
            (fp, _get_adapter_type(fp, is_controlnet=False), _get_file_creation_date(fp))
            for fp in RecentAdaptersState._recent_adapter_files_split
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
        RecentAdaptersWindow._source_prompt_cache = None
        RecentAdaptersWindow._favorites_cache = None
        RecentAdaptersWindow._cache_timestamp = None
        for kind in self._kinds:
            self._refresh_kind(kind)
        self._refresh_favorites()
        self._update_cache_status()

    # ------------------------------------------------------------------
    # Cache builders
    # ------------------------------------------------------------------
    def _cached_kind(self, kind: _AdapterKind) -> list[tuple[str, str, str]]:
        rows = getattr(RecentAdaptersWindow, kind.cache_attr)
        if rows is None:
            rows = [
                (fp, kind.type_label(fp), _get_file_creation_date(fp))
                for fp in kind.recent_files()
            ]
            setattr(RecentAdaptersWindow, kind.cache_attr, rows)
            RecentAdaptersWindow._cache_timestamp = time.time()
        return rows

    def _cached_favorites(self) -> list[tuple[str, str, str]]:
        if RecentAdaptersWindow._favorites_cache is None:
            RecentAdaptersWindow._favorites_cache = []
            for fp in RecentAdaptersState._favorite_adapters:
                RecentAdaptersWindow._favorites_cache.append(
                    (fp, _get_file_creation_date(fp))
                )
            RecentAdaptersWindow._cache_timestamp = time.time()
        return RecentAdaptersWindow._favorites_cache

    def _update_cache_status(self) -> None:
        prefix = _("Cache")
        if RecentAdaptersWindow._cache_timestamp is None:
            text = f"{prefix}: {_('Not loaded')}"
        else:
            ts = datetime.fromtimestamp(RecentAdaptersWindow._cache_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            text = f"{prefix}: {ts}"
        for lbl in self._cache_labels.values():
            lbl.setText(text)

    def _refresh_favorites(self) -> None:
        if not hasattr(self, "_fav_tree"):
            return
        ft = (self._fav_filter.text() or "").lower()
        data = self._cached_favorites()
        if ft:
            data = [(n, c) for n, c in data if ft in n.lower()]
        self._fav_tree.clear()
        for n, c in data:
            QTreeWidgetItem(self._fav_tree, [n, c])
        self._fav_tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _set_favorite_target(self, target: str) -> None:
        self._fav_target = target
        selected_style = "font-weight: bold;"
        default_style = ""
        self._fav_target_cn_btn.setStyleSheet(selected_style if target == "controlnet" else default_style)
        self._fav_target_ip_btn.setStyleSheet(selected_style if target == "ipadapter" else default_style)
        self._fav_target_src_btn.setStyleSheet(selected_style if target == "source_prompt" else default_style)

    # ==================================================================
    # Selection callbacks
    # ==================================================================
    def _select_kind(self, kind: _AdapterKind, replace: bool = True) -> None:
        items = self._trees[kind.key].selectedItems()
        if not items:
            return
        fp = items[0].text(0)
        kind.record_recent(fp)
        self._app_actions.set_adapter_from_adapters_window(fp, adapter_type=kind.key, replace=replace)
        self.close()

    def _select_all(self, is_controlnet: bool, replace: bool) -> None:
        items = self._all_tree.selectedItems()
        if not items:
            return
        fp = items[0].text(0)
        if is_controlnet:
            RecentAdaptersState.add_recent_controlnet(fp)
        else:
            RecentAdaptersState.add_recent_ipadapter(fp)
        self._app_actions.set_adapter_from_adapters_window(fp, is_controlnet=is_controlnet, replace=replace)
        self.close()

    def _select_favorite(self) -> None:
        items = self._fav_tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a row first"))
            return
        fp = items[0].text(0)
        replace = not self._fav_append_toggle.isChecked()
        target = getattr(self, "_fav_target", "controlnet")
        self._app_actions.set_adapter_from_adapters_window(
            fp, adapter_type=target, replace=replace
        )
        self.close()

    def _remove_favorite(self) -> None:
        items = self._fav_tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a row first"))
            return
        fp = items[0].text(0)
        if os.path.isdir(fp):
            self._app_actions.toast(_("Directories are auto-favorited and cannot be removed here"))
            return
        if RecentAdaptersState.remove_favorite_adapter(fp, save=True):
            RecentAdaptersWindow._favorites_cache = None
            self._refresh_favorites()
            self._app_actions.toast(_("Removed from favorites"))
        else:
            self._app_actions.toast(_("Item was not in favorites"))

    def _add_selected_to_favorites(self, tree: QTreeWidget) -> None:
        items = tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a row first"))
            return
        fp = items[0].text(0)
        if RecentAdaptersState.add_favorite_adapter(fp, save=True):
            RecentAdaptersWindow._favorites_cache = None
            self._refresh_favorites()
            self._app_actions.toast(_("Added to favorites"))
        else:
            self._app_actions.toast(_("Already in favorites"))

    # ==================================================================
    # Configuration
    # ==================================================================
    def _save_config(self) -> None:
        try:
            mi = max(1, self._max_recent_spin.value())
            ms = max(1, self._max_split_spin.value())
            app_info_cache.set(RecentAdaptersState.MAX_RECENT_ITEMS_KEY, mi)
            app_info_cache.set(RecentAdaptersState.MAX_RECENT_SPLIT_ITEMS_KEY, ms)
            self._apply_limits(mi, ms)
            logger.info(f"Saved config: max_recent_items={mi}, max_recent_split_items={ms}")
        except Exception as e:
            logger.error(f"Failed to save config: {e}")

    def _reset_config(self) -> None:
        mi = RecentAdaptersState.DEFAULT_MAX_RECENT_ITEMS
        ms = RecentAdaptersState.DEFAULT_MAX_RECENT_SPLIT_ITEMS
        self._max_recent_spin.setValue(mi)
        self._max_split_spin.setValue(ms)
        self._save_config()

    @staticmethod
    def _apply_limits(max_items: int, max_split: int) -> None:
        if len(RecentAdaptersState._recent_controlnets) > max_items:
            RecentAdaptersState._recent_controlnets = RecentAdaptersState._recent_controlnets[:max_items]
        if len(RecentAdaptersState._recent_ipadapters) > max_items:
            RecentAdaptersState._recent_ipadapters = RecentAdaptersState._recent_ipadapters[:max_items]
        if len(RecentAdaptersState._recent_source_prompts) > max_items:
            RecentAdaptersState._recent_source_prompts = RecentAdaptersState._recent_source_prompts[:max_items]
        if len(RecentAdaptersState._recent_adapter_files_split) > max_split:
            RecentAdaptersState._recent_adapter_files_split = RecentAdaptersState._recent_adapter_files_split[:max_split]

    def closeEvent(self, event) -> None:  # noqa: N802
        RecentAdaptersWindow._instance = None
        super().closeEvent(event)
