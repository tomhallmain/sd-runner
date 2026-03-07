"""
ModelsWindow + LoRAInfoWindow -- model/adapter browser (PySide6 port).

Ported from ``ui/models_window.py``.  Static class-level cache data
(``_checkpoints_cache``, ``_adapters_cache``, ``_cache_timestamp``)
stays on the *original* ``ui.models_window.ModelsWindow`` so that
cache state is shared with any code that references the original class.
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from extensions.hf_hub_api import HfHubApiBackend
from lib.multi_display_qt import SmartDialog
from sd_runner.models import Model
from ui.models_window import ModelsWindow as _ModelsBackend
from ui_qt.app_style import AppStyle
from ui_qt.auth.password_utils import require_password
from utils.globals import (
    ArchitectureType,
    HfHubSortDirection,
    HfHubSortOption,
    HfHubVisualMediaTask,
    ProtectedActions,
)
from utils.translations import I18N

try:
    from lib.lora_trigger_extractor import (
        get_trigger_info, create_safetriggers_file,
        TriggerInfo, is_safetriggers_available,
    )
except ImportError:
    def is_safetriggers_available():
        return False

if TYPE_CHECKING:
    from ui.app_actions import AppActions

_ = I18N._


# ======================================================================
# Helpers
# ======================================================================

def _parse_date(date_str: str):
    """Parse a date string into a sortable tuple."""
    if not date_str or date_str == "Unknown":
        return (0, 0, 0, 0, 0)
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M")
        return (dt.year, dt.month, dt.day, dt.hour, dt.minute)
    except Exception:
        return (0, 0, 0, 0, 0)


def _sort_tree(tree: QTreeWidget, col: int) -> None:
    """Sort *tree* by *col*, toggling direction each call."""
    current = getattr(tree, "_sort_reverse", False)
    new_reverse = not current
    tree._sort_reverse = new_reverse
    order = Qt.SortOrder.DescendingOrder if new_reverse else Qt.SortOrder.AscendingOrder
    tree.sortItems(col, order)


# ======================================================================
# ModelsWindow
# ======================================================================

class ModelsWindow(SmartDialog):
    """PySide6 model and adapter browser with tabbed Checkpoints / LoRAs."""

    def __init__(self, parent: QWidget, app_actions: AppActions):
        super().__init__(parent=parent, title=_("Models"), geometry="800x450")
        self._app_actions = app_actions
        self._show_blacklisted = False
        self._hf_api: Optional[HfHubApiBackend] = None

        Model.load_all_if_unloaded()

        # --- Tabs -----------------------------------------------------------
        self._tabs = QTabWidget()

        cp_page = QWidget()
        ad_page = QWidget()
        hf_page = QWidget()
        self._tabs.addTab(cp_page, _("Checkpoints"))
        self._tabs.addTab(ad_page, _("LoRAs & Adapters"))
        self._tabs.addTab(hf_page, _("HF Hub"))

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.addWidget(self._tabs)

        # Build tabs
        self._build_checkpoints_tab(cp_page)
        self._build_adapters_tab(ad_page)
        self._build_hf_hub_tab(hf_page)

        QShortcut(QKeySequence("Escape"), self, self.close)
        self.show()

    # ------------------------------------------------------------------
    # Tab selector (for WindowLauncher.select_tab compatibility)
    # ------------------------------------------------------------------
    def select_tab(self, index: int) -> None:
        self._tabs.setCurrentIndex(index)

    # ------------------------------------------------------------------
    # Checkpoints tab
    # ------------------------------------------------------------------
    def _build_checkpoints_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        # Filter
        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(_("Filter")))
        self._cp_filter = QLineEdit()
        self._cp_filter.textChanged.connect(lambda: self._refresh_checkpoint_list())
        filter_row.addWidget(self._cp_filter)
        layout.addLayout(filter_row)

        self._cp_cache_label = QLabel("")
        layout.addWidget(self._cp_cache_label)

        # Tree
        self._cp_tree = QTreeWidget()
        self._cp_tree.setHeaderLabels([_("Model Name"), _("Architecture"), _("Created")])
        self._cp_tree.setRootIsDecorated(False)
        self._cp_tree.setAlternatingRowColors(True)
        self._cp_tree.setSortingEnabled(False)
        hdr = self._cp_tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.resizeSection(1, 120)
        hdr.resizeSection(2, 150)
        hdr.sectionClicked.connect(lambda col: _sort_tree(self._cp_tree, col))
        self._cp_tree.itemDoubleClicked.connect(lambda: self._select_checkpoint())
        layout.addWidget(self._cp_tree)

        # Buttons
        btn_row = QHBoxLayout()
        replace_btn = QPushButton(_("Replace"))
        replace_btn.clicked.connect(lambda: self._select_checkpoint(replace=True))
        btn_row.addWidget(replace_btn)
        add_btn = QPushButton(_("Add"))
        add_btn.clicked.connect(lambda: self._select_checkpoint(replace=False))
        btn_row.addWidget(add_btn)
        refresh_btn = QPushButton(_("Refresh"))
        refresh_btn.clicked.connect(self._refresh_cache)
        btn_row.addWidget(refresh_btn)
        self._cp_blacklist_btn = QPushButton(_("Show Blacklisted"))
        self._cp_blacklist_btn.clicked.connect(self._toggle_blacklisted)
        btn_row.addWidget(self._cp_blacklist_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_checkpoint_list()
        self._update_cache_status()

    # ------------------------------------------------------------------
    # Adapters tab
    # ------------------------------------------------------------------
    def _build_adapters_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel(_("Filter")))
        self._ad_filter = QLineEdit()
        self._ad_filter.textChanged.connect(lambda: self._refresh_adapter_list())
        filter_row.addWidget(self._ad_filter)
        layout.addLayout(filter_row)

        self._ad_cache_label = QLabel("")
        layout.addWidget(self._ad_cache_label)

        self._ad_tree = QTreeWidget()
        self._ad_tree.setHeaderLabels([_("LoRA/Adapter Name"), _("Architecture"), _("Created")])
        self._ad_tree.setRootIsDecorated(False)
        self._ad_tree.setAlternatingRowColors(True)
        self._ad_tree.setSortingEnabled(False)
        hdr = self._ad_tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.resizeSection(1, 120)
        hdr.resizeSection(2, 150)
        hdr.sectionClicked.connect(lambda col: _sort_tree(self._ad_tree, col))
        self._ad_tree.itemDoubleClicked.connect(lambda: self._select_adapter())
        layout.addWidget(self._ad_tree)

        btn_row = QHBoxLayout()
        replace_btn = QPushButton(_("Replace"))
        replace_btn.clicked.connect(lambda: self._select_adapter(replace=True))
        btn_row.addWidget(replace_btn)
        add_btn = QPushButton(_("Add"))
        add_btn.clicked.connect(lambda: self._select_adapter(replace=False))
        btn_row.addWidget(add_btn)
        lora_info_btn = QPushButton(_("LoRA Info"))
        lora_info_btn.clicked.connect(self._show_lora_info)
        if not is_safetriggers_available():
            lora_info_btn.setEnabled(False)
        btn_row.addWidget(lora_info_btn)
        refresh_btn = QPushButton(_("Refresh"))
        refresh_btn.clicked.connect(self._refresh_cache)
        btn_row.addWidget(refresh_btn)
        self._ad_blacklist_btn = QPushButton(_("Show Blacklisted"))
        self._ad_blacklist_btn.clicked.connect(self._toggle_blacklisted)
        btn_row.addWidget(self._ad_blacklist_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_adapter_list()
        self._update_cache_status()

    # ------------------------------------------------------------------
    # HF Hub tab
    # ------------------------------------------------------------------
    def _build_hf_hub_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)

        # Query + task + limits
        query_row = QHBoxLayout()
        query_row.addWidget(QLabel(_("Search")))
        self._hf_query = QLineEdit()
        self._hf_query.setPlaceholderText(_("e.g. flux, sdxl, controlnet, ip-adapter"))
        query_row.addWidget(self._hf_query, stretch=1)

        query_row.addWidget(QLabel(_("Task")))
        self._hf_task = QComboBox()
        for task in HfHubVisualMediaTask:
            self._hf_task.addItem(task.display(), task.value)
        query_row.addWidget(self._hf_task)

        query_row.addWidget(QLabel(_("Sort")))
        self._hf_sort = QComboBox()
        for opt in HfHubSortOption:
            self._hf_sort.addItem(opt.display(), opt.value)
        self._hf_sort.setCurrentText(HfHubSortOption.DOWNLOADS.display())
        query_row.addWidget(self._hf_sort)

        query_row.addWidget(QLabel(_("Direction")))
        self._hf_direction = QComboBox()
        for d in HfHubSortDirection:
            self._hf_direction.addItem(d.display(), d.value)
        self._hf_direction.setCurrentText(HfHubSortDirection.DESCENDING.display())
        query_row.addWidget(self._hf_direction)

        query_row.addWidget(QLabel(_("Limit")))
        self._hf_limit = QComboBox()
        for v in ["25", "50", "100", "200"]:
            self._hf_limit.addItem(v)
        self._hf_limit.setCurrentText("100")
        query_row.addWidget(self._hf_limit)
        layout.addLayout(query_row)

        # Results
        self._hf_tree = QTreeWidget()
        self._hf_tree.setHeaderLabels(
            [_("Repo"), _("Task"), _("Downloads"), _("Likes"), _("License"), _("Gated")]
        )
        self._hf_tree.setRootIsDecorated(False)
        self._hf_tree.setAlternatingRowColors(True)
        hdr = self._hf_tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hdr.resizeSection(1, 150)
        hdr.resizeSection(2, 90)
        hdr.resizeSection(3, 70)
        hdr.resizeSection(4, 110)
        hdr.resizeSection(5, 70)
        hdr.sectionClicked.connect(lambda col: _sort_tree(self._hf_tree, col))
        layout.addWidget(self._hf_tree)

        # Download controls
        dl_row = QHBoxLayout()
        dl_row.addWidget(QLabel(_("Filename")))
        self._hf_filename = QLineEdit("model.safetensors")
        dl_row.addWidget(self._hf_filename, stretch=1)

        search_btn = QPushButton(_("Search"))
        search_btn.clicked.connect(self._hf_search)
        dl_row.addWidget(search_btn)

        dl_file_btn = QPushButton(_("Download File"))
        dl_file_btn.clicked.connect(self._hf_download_file)
        dl_row.addWidget(dl_file_btn)

        dl_snapshot_btn = QPushButton(_("Download Snapshot"))
        dl_snapshot_btn.clicked.connect(self._hf_download_snapshot)
        dl_row.addWidget(dl_snapshot_btn)
        dl_row.addStretch()
        layout.addLayout(dl_row)

    def _hf_api_backend(self) -> HfHubApiBackend:
        if self._hf_api is None:
            self._hf_api = HfHubApiBackend()
        return self._hf_api

    def _hf_selected_repo(self) -> Optional[str]:
        items = self._hf_tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a model repository first"))
            return None
        return items[0].text(0)

    def _hf_search(self) -> None:
        try:
            query = (self._hf_query.text() or "").strip()
            task = HfHubVisualMediaTask.get(str(self._hf_task.currentData()))
            sort = HfHubSortOption.get(str(self._hf_sort.currentData()))
            direction = HfHubSortDirection.get(str(self._hf_direction.currentData()))
            limit = int(self._hf_limit.currentText())
            results = self._hf_api_backend().search_models(
                query=query,
                task=task,
                limit=limit,
                sort=sort,
                direction=direction,
                include_gated=True,
            )

            self._hf_tree.clear()
            for r in results:
                QTreeWidgetItem(
                    self._hf_tree,
                    [
                        r.repo_id,
                        r.task or "",
                        str(r.downloads),
                        str(r.likes),
                        r.license,
                        "yes" if r.gated else "no",
                    ],
                )
            self._app_actions.toast(_("Found {0} results").format(len(results)))
        except Exception as e:
            self._app_actions.alert(
                _("HF Hub Search Error"),
                str(e),
                kind="error",
                master=self,
            )

    def _hf_download_file(self) -> None:
        repo_id = self._hf_selected_repo()
        if repo_id is None:
            return
        filename = (self._hf_filename.text() or "").strip()
        if not filename:
            self._app_actions.toast(_("Enter a filename first"))
            return
        try:
            path = self._hf_api_backend().download_file(repo_id, filename)
            self._app_actions.alert(
                _("Download Complete"),
                _("Downloaded to:\n{0}").format(path),
                master=self,
            )
        except Exception as e:
            self._app_actions.alert(
                _("HF Hub Download Error"),
                str(e),
                kind="error",
                master=self,
            )

    def _hf_download_snapshot(self) -> None:
        repo_id = self._hf_selected_repo()
        if repo_id is None:
            return
        # Keep broad but media-adjacent default patterns for model repos.
        allow_patterns = [
            "*.safetensors", "*.ckpt", "*.bin", "*.onnx", "*.pt", "*.pth",
            "*.json", "*.txt", "*.yaml", "*.yml", "*.md",
        ]
        try:
            path = self._hf_api_backend().download_snapshot(
                repo_id,
                allow_patterns=allow_patterns,
            )
            self._app_actions.alert(
                _("Snapshot Download Complete"),
                _("Downloaded to:\n{0}").format(path),
                master=self,
            )
        except Exception as e:
            self._app_actions.alert(
                _("HF Hub Snapshot Error"),
                str(e),
                kind="error",
                master=self,
            )

    # ------------------------------------------------------------------
    # Data helpers
    # ------------------------------------------------------------------
    def _build_checkpoints_data(self) -> list[tuple[str, str, str]]:
        data = []
        for name in sorted(Model.CHECKPOINTS.keys()):
            model: Model = Model.CHECKPOINTS[name]
            if not self._show_blacklisted and model.is_blacklisted():
                continue
            arch: ArchitectureType = model.get_architecture_type()
            data.append((name, arch.display(), model.get_file_creation_date()))
        return data

    def _build_adapters_data(self) -> list[tuple[str, str, str]]:
        data = []
        for name in sorted(Model.LORAS.keys()):
            model: Model = Model.LORAS[name]
            if not self._show_blacklisted and model.is_blacklisted():
                continue
            arch: ArchitectureType = model.get_architecture_type()
            data.append((name, arch.display(), model.get_file_creation_date()))
        return data

    def _get_cached_checkpoints(self) -> list[tuple[str, str, str]]:
        if _ModelsBackend._checkpoints_cache is None:
            _ModelsBackend._checkpoints_cache = self._build_checkpoints_data()
            _ModelsBackend._cache_timestamp = time.time()
        return _ModelsBackend._checkpoints_cache

    def _get_cached_adapters(self) -> list[tuple[str, str, str]]:
        if _ModelsBackend._adapters_cache is None:
            _ModelsBackend._adapters_cache = self._build_adapters_data()
            _ModelsBackend._cache_timestamp = time.time()
        return _ModelsBackend._adapters_cache

    # ------------------------------------------------------------------
    # Refresh lists
    # ------------------------------------------------------------------
    def _refresh_checkpoint_list(self) -> None:
        ft = (self._cp_filter.text() or "").lower()
        data = self._get_cached_checkpoints()
        if ft:
            data = [(n, a, c) for n, a, c in data if ft in n.lower()]
        self._cp_tree.clear()
        for name, arch, created in data:
            QTreeWidgetItem(self._cp_tree, [name, arch, created])
        self._apply_default_sort(self._cp_tree)

    def _refresh_adapter_list(self) -> None:
        ft = (self._ad_filter.text() or "").lower()
        data = self._get_cached_adapters()
        if ft:
            data = [(n, a, c) for n, a, c in data if ft in n.lower()]
        self._ad_tree.clear()
        for name, arch, created in data:
            QTreeWidgetItem(self._ad_tree, [name, arch, created])
        self._apply_default_sort(self._ad_tree)

    @staticmethod
    def _apply_default_sort(tree: QTreeWidget) -> None:
        """Sort by architecture then name (columns 1, 0)."""
        tree.sortItems(1, Qt.SortOrder.AscendingOrder)

    def _refresh_cache(self) -> None:
        _ModelsBackend._checkpoints_cache = None
        _ModelsBackend._adapters_cache = None
        _ModelsBackend._cache_timestamp = None
        self._refresh_checkpoint_list()
        self._refresh_adapter_list()
        self._update_cache_status()

    def _update_cache_status(self) -> None:
        prefix = _("Cache")
        if _ModelsBackend._cache_timestamp is None:
            text = f"{prefix}: {_('Not loaded')}"
        else:
            ts = datetime.fromtimestamp(_ModelsBackend._cache_timestamp).strftime(
                "%Y-%m-%d %H:%M:%S"
            )
            text = f"{prefix}: {ts}"
        if hasattr(self, "_cp_cache_label"):
            self._cp_cache_label.setText(text)
        if hasattr(self, "_ad_cache_label"):
            self._ad_cache_label.setText(text)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _select_checkpoint(self, replace: bool = True) -> None:
        items = self._cp_tree.selectedItems()
        if not items:
            return
        name = items[0].text(0)
        self._app_actions.set_model_from_models_window(name, is_lora=False, replace=replace)
        self.close()

    def _select_adapter(self, replace: bool = False) -> None:
        items = self._ad_tree.selectedItems()
        if not items:
            return
        name = items[0].text(0)
        self._app_actions.set_model_from_models_window(name, is_lora=True, replace=replace)
        if replace:
            self.close()

    # ------------------------------------------------------------------
    # Blacklist toggle
    # ------------------------------------------------------------------
    @require_password(ProtectedActions.REVEAL_BLACKLIST_CONCEPTS)
    def _toggle_blacklisted(self) -> None:
        self._show_blacklisted = not self._show_blacklisted
        label = _("Hide Blacklisted") if self._show_blacklisted else _("Show Blacklisted")
        self._cp_blacklist_btn.setText(label)
        self._ad_blacklist_btn.setText(label)
        _ModelsBackend._checkpoints_cache = None
        _ModelsBackend._adapters_cache = None
        _ModelsBackend._cache_timestamp = None
        self._refresh_checkpoint_list()
        self._refresh_adapter_list()
        self._update_cache_status()

    # ------------------------------------------------------------------
    # LoRA Info
    # ------------------------------------------------------------------
    def _show_lora_info(self) -> None:
        if not is_safetriggers_available():
            self._app_actions.alert(
                _("Feature Unavailable"),
                _("LoRA trigger extraction is not available."),
                kind="warning",
                master=self,
            )
            return
        items = self._ad_tree.selectedItems()
        if not items:
            self._app_actions.alert(
                _("No Selection"),
                _("Please select a LoRA to view information."),
                kind="warning",
                master=self,
            )
            return
        model_name = items[0].text(0)
        model = Model.LORAS.get(model_name)
        if not model:
            self._app_actions.alert(
                _("Error"),
                _("Model not found: {0}").format(model_name),
                kind="error",
                master=self,
            )
            return
        LoRAInfoWindow(self, model, self._app_actions)


# ======================================================================
# LoRAInfoWindow
# ======================================================================

class LoRAInfoWindow(SmartDialog):
    """Detailed LoRA information with trigger word extraction."""

    def __init__(self, parent: QWidget, model: Model, app_actions: Any):
        super().__init__(
            parent=parent,
            title=_("LoRA Information: {0}").format(model.id),
            geometry="800x600",
        )
        self._model = model
        self._app_actions = app_actions

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)

        # --- Info grid ------------------------------------------------------
        title = QLabel(_("LoRA Information"))
        title.setStyleSheet("font-size: 16pt; font-weight: bold;")
        root.addWidget(title)

        info_pairs = [
            (_("Name:"), model.id),
            (_("Architecture:"), model.get_architecture_type().display()),
            (_("File Path:"), self._get_model_file_path()),
            (_("Created:"), model.get_file_creation_date()),
            (_("Strength:"), f"{model.lora_strength:.2f}"),
        ]
        for label_text, value_text in info_pairs:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet("font-weight: bold;")
            lbl.setFixedWidth(120)
            row.addWidget(lbl)
            val = QLabel(str(value_text))
            val.setWordWrap(True)
            row.addWidget(val, stretch=1)
            root.addLayout(row)

        # Separator
        sep = QWidget()
        sep.setFixedHeight(2)
        sep.setStyleSheet(f"background-color: {AppStyle.FG_COLOR};")
        root.addWidget(sep)

        # --- Trigger section ------------------------------------------------
        trigger_title = QLabel(_("Trigger Information"))
        trigger_title.setStyleSheet("font-size: 14pt; font-weight: bold;")
        root.addWidget(trigger_title)

        self._trigger_status = QLabel(_("Loading trigger information..."))
        root.addWidget(self._trigger_status)

        self._trigger_text = QPlainTextEdit()
        self._trigger_text.setReadOnly(True)
        root.addWidget(self._trigger_text)

        # Buttons
        btn_row = QHBoxLayout()
        self._create_file_btn = QPushButton(_("Create .safetriggers File"))
        self._create_file_btn.setEnabled(False)
        self._create_file_btn.clicked.connect(self._create_safetriggers_file)
        btn_row.addWidget(self._create_file_btn)
        btn_row.addStretch()
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        root.addLayout(btn_row)

        QShortcut(QKeySequence("Escape"), self, self.close)

        self._load_trigger_info()
        self.show()

    # ------------------------------------------------------------------
    def _get_model_file_path(self) -> str:
        try:
            lora_or_sd = "Lora" if self._model.is_lora else "Stable-diffusion"
            root_dir = os.path.join(Model.MODELS_DIR, lora_or_sd)
            if self._model.path:
                if os.path.isabs(self._model.path):
                    return self._model.path
                return os.path.join(root_dir, self._model.path)
            return os.path.join(root_dir, self._model.id)
        except Exception:
            return _("Unknown")

    def _load_trigger_info(self) -> None:
        if not is_safetriggers_available():
            self._trigger_status.setText(_("Trigger extraction not available"))
            return
        try:
            fp = self._get_model_file_path()
            if not fp.endswith(".safetensors"):
                fp += ".safetensors"
            if not os.path.exists(fp):
                self._trigger_status.setText(_("LoRA file not found"))
                return
            info = get_trigger_info(fp, force_refresh=True)
            if info.has_triggers and info.triggers:
                self._display_triggers(info)
            else:
                msg = info.error_message if info.error_message else _("No triggers found")
                self._trigger_status.setText(_("No triggers found: {0}").format(msg))
        except Exception as e:
            self._trigger_status.setText(_("Error loading triggers: {0}").format(e))

    def _display_triggers(self, info: TriggerInfo) -> None:
        self._trigger_status.setText(_("Found {0} triggers").format(info.trigger_count))
        self._create_file_btn.setEnabled(True)
        sorted_triggers = sorted(info.triggers.items(), key=lambda x: x[1], reverse=True)
        lines = [f"{'Count':>6}  {'Trigger Word/Phrase':<50}", "-" * 60]
        for trigger, count in sorted_triggers:
            lines.append(f"{count:>6}  {trigger:<50}")
        self._trigger_text.setPlainText("\n".join(lines))

    def _create_safetriggers_file(self) -> None:
        if not is_safetriggers_available():
            return
        try:
            fp = self._get_model_file_path()
            if not fp.endswith(".safetensors"):
                fp += ".safetensors"
            if not os.path.exists(fp):
                self._app_actions.alert(_("Error"), _("LoRA file not found: {0}").format(fp), kind="error", master=self)
                return
            success = create_safetriggers_file(fp)
            if success:
                st_path = fp.replace(".safetensors", ".safetriggers")
                self._app_actions.alert(_("Success"), _("Created .safetriggers file:\n{0}").format(st_path), master=self)
            else:
                self._app_actions.alert(_("Error"), _("Failed to create .safetriggers file"), kind="error", master=self)
        except Exception as e:
            self._app_actions.alert(_("Error"), _("Failed to create .safetriggers file: {0}").format(e), kind="error", master=self)
