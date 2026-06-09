"""
RunsWindow -- queue and history viewer for image generation runs.

Queue tab: live view of the currently running job and pending jobs.
History tab: searchable log of past run configurations with restore.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QPushButton, QTabWidget, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)

from lib.multi_display_qt import SmartDialog
from utils.app_info_cache import app_info_cache
from utils.logging_setup import get_logger
from utils.runner_app_config import RunnerAppConfig
from utils.translations import I18N

if TYPE_CHECKING:
    from ui_qt.app_actions import AppActions

_ = I18N._
logger = get_logger("ui_qt.runs_window")

_QUEUE_REFRESH_MS = 2000


def _fmt_timestamp(ts: str) -> str:
    try:
        return ts[:19].replace("T", " ")
    except Exception:
        return str(ts)


def _short(value: str, max_len: int = 40) -> str:
    s = str(value or "")
    return s if len(s) <= max_len else s[:max_len - 1] + "…"


class RunsWindow(SmartDialog):
    """PySide6 queue + history browser for image generation runs."""

    def __init__(self, parent, app_actions: AppActions):
        super().__init__(parent=parent, title=_("Runs"), geometry="900x560")
        self._app = parent
        self._app_actions = app_actions

        self._tabs = QTabWidget()
        queue_page = QWidget()
        history_page = QWidget()
        self._tabs.addTab(queue_page, _("Queue"))
        self._tabs.addTab(history_page, _("History"))

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.addWidget(self._tabs)

        self._build_queue_tab(queue_page)
        self._build_history_tab(history_page)

        QShortcut(QKeySequence("Escape"), self, self.close)

        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._refresh_queue)
        self._refresh_timer.start(_QUEUE_REFRESH_MS)

        self._tabs.currentChanged.connect(self._on_tab_changed)

        self._refresh_queue()
        self.show()

    # ==================================================================
    # Queue tab
    # ==================================================================

    def _build_queue_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        self._queue_status_label = QLabel(_("Status: Idle"))
        self._queue_status_label.setStyleSheet("font-weight: bold;")
        layout.addWidget(self._queue_status_label)

        self._running_tree = self._make_tree(
            [_("Workflow"), _("Model"), _("N"), _("Total"), _("Status")],
            page,
        )
        self._running_tree.setMaximumHeight(80)
        layout.addWidget(QLabel(_("Currently Running")))
        layout.addWidget(self._running_tree)

        layout.addWidget(QLabel(_("Pending Jobs")))
        self._pending_tree = self._make_tree(
            [_("#"), _("Workflow"), _("Model"), _("N"), _("Total"), _("Positive Tags")],
            page,
        )
        layout.addWidget(self._pending_tree)

        self._queue_preset_label = QLabel("")
        self._queue_preset_label.setStyleSheet("font-style: italic;")
        layout.addWidget(self._queue_preset_label)

        layout.addWidget(QLabel(_("Server Staging Queue")))
        self._staging_tree = self._make_tree(
            [_("#"), _("Workflow"), _("Args")],
            page,
        )
        self._staging_tree.setMaximumHeight(120)
        layout.addWidget(self._staging_tree)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton(_("Refresh"))
        refresh_btn.clicked.connect(self._refresh_queue)
        btn_row.addWidget(refresh_btn)
        cancel_btn = QPushButton(_("Cancel Current Run"))
        cancel_btn.clicked.connect(self._cancel_run)
        btn_row.addWidget(cancel_btn)
        cancel_all_btn = QPushButton(_("Cancel All"))
        cancel_all_btn.clicked.connect(self._cancel_all)
        btn_row.addWidget(cancel_all_btn)
        cancel_staging_btn = QPushButton(_("Cancel Staging"))
        cancel_staging_btn.setToolTip(_("Clear the server staging queue"))
        cancel_staging_btn.clicked.connect(self._cancel_staging)
        btn_row.addWidget(cancel_staging_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh_queue(self) -> None:
        app = self._app
        job_queue = getattr(app, "job_queue", None)
        current_run = getattr(app, "current_run", None)

        # -- running job --
        self._running_tree.clear()
        is_running = job_queue is not None and job_queue.job_running
        if is_running and current_run is not None and not current_run.is_complete:
            args = current_run.args
            status = _("Running")
            if current_run.is_cancelled:
                status = _("Cancelled")
            wf = str(getattr(args, "workflow_tag", ""))
            model = _short(str(getattr(args, "model_tags", "")), 30)
            n = str(getattr(args, "n_latents", ""))
            total = str(getattr(args, "total", ""))
            item = QTreeWidgetItem(self._running_tree, [wf, model, n, total, status])
            item.setForeground(4, self.palette().highlight().color())
            self._queue_status_label.setText(_("Status: Running"))
        else:
            self._queue_status_label.setText(_("Status: Idle"))

        # -- pending jobs --
        self._pending_tree.clear()
        if job_queue is not None:
            for idx, run_config in enumerate(job_queue.pending_jobs):
                wf = str(getattr(run_config, "workflow_tag", ""))
                model = _short(str(getattr(run_config, "model_tags", "")), 30)
                n = str(getattr(run_config, "n_latents", ""))
                total = str(getattr(run_config, "total", ""))
                pos = _short(str(getattr(run_config, "positive_prompt", "") or ""), 40)
                QTreeWidgetItem(self._pending_tree, [str(idx + 1), wf, model, n, total, pos])

        # -- preset schedules --
        preset_queue = getattr(app, "job_queue_preset_schedules", None)
        if preset_queue is not None and preset_queue.has_pending():
            text = preset_queue.pending_text() or ""
            self._queue_preset_label.setText(text)
        else:
            self._queue_preset_label.setText("")

        # -- server staging queue --
        self._staging_tree.clear()
        staging = getattr(app, "server_staging_queue", None)
        if staging is not None:
            for idx, (wf_type, req_args) in enumerate(staging._requests):
                wf = str(wf_type.name if hasattr(wf_type, "name") else wf_type or "")
                args_str = _short(str(req_args), 60)
                QTreeWidgetItem(self._staging_tree, [str(idx + 1), wf, args_str])

    def _cancel_run(self) -> None:
        try:
            self._app_actions.cancel()
        except Exception as e:
            logger.warning(f"Cancel failed: {e}")
        self._refresh_queue()

    def _cancel_all(self) -> None:
        try:
            self._app_actions.cancel()
            job_queue = getattr(self._app, "job_queue", None)
            if job_queue is not None:
                job_queue.cancel()
            preset_queue = getattr(self._app, "job_queue_preset_schedules", None)
            if preset_queue is not None:
                preset_queue.cancel()
            staging = getattr(self._app, "server_staging_queue", None)
            if staging is not None:
                staging.cancel()
        except Exception as e:
            logger.warning(f"Cancel all failed: {e}")
        self._refresh_queue()

    def _cancel_staging(self) -> None:
        staging = getattr(self._app, "server_staging_queue", None)
        if staging is not None:
            staging.cancel()
        self._refresh_queue()

    # ==================================================================
    # History tab
    # ==================================================================

    def _build_history_tab(self, page: QWidget) -> None:
        layout = QVBoxLayout(page)
        layout.setSpacing(8)

        frow = QHBoxLayout()
        frow.addWidget(QLabel(_("Filter")))
        self._hist_filter = QLineEdit()
        self._hist_filter.setPlaceholderText(_("workflow, model, or tags…"))
        self._hist_filter.textChanged.connect(self._refresh_history)
        frow.addWidget(self._hist_filter)
        layout.addLayout(frow)

        self._hist_tree = self._make_tree(
            [_("Time"), _("Workflow"), _("Model"), _("Positive Tags"), _("N"), _("Total")],
            page,
        )
        self._hist_tree.itemDoubleClicked.connect(self._restore_selected)
        layout.addWidget(self._hist_tree)

        btn_row = QHBoxLayout()
        restore_btn = QPushButton(_("Restore to Sidebar"))
        restore_btn.clicked.connect(self._restore_selected)
        btn_row.addWidget(restore_btn)
        refresh_btn = QPushButton(_("Refresh"))
        refresh_btn.clicked.connect(self._refresh_history)
        btn_row.addWidget(refresh_btn)
        close_btn = QPushButton(_("Close"))
        close_btn.clicked.connect(self.close)
        btn_row.addWidget(close_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._refresh_history()

    def _refresh_history(self) -> None:
        ft = (self._hist_filter.text() or "").lower()
        self._hist_tree.clear()
        self._hist_data: list[dict] = []

        idx = 0
        while True:
            try:
                entry = app_info_cache.get_history(idx)
            except Exception:
                break
            ts = _fmt_timestamp(entry.get("timestamp", ""))
            wf = str(entry.get("workflow_type", ""))
            model = _short(str(entry.get("model_tags", "")), 35)
            tags = _short(str(entry.get("positive_tags", "")), 50)
            n = str(entry.get("n_latents", ""))
            total = str(entry.get("total", ""))

            if ft and not any(ft in v.lower() for v in [wf, model, tags]):
                idx += 1
                continue

            QTreeWidgetItem(self._hist_tree, [ts, wf, model, tags, n, total])
            self._hist_data.append(entry)
            idx += 1

    def _restore_selected(self) -> None:
        items = self._hist_tree.selectedItems()
        if not items:
            self._app_actions.toast(_("Select a history entry first"))
            return
        row = self._hist_tree.indexOfTopLevelItem(items[0])
        if row < 0 or row >= len(self._hist_data):
            return
        entry = self._hist_data[row]
        try:
            cfg = RunnerAppConfig.from_dict(entry)
            self._app.runner_app_config = cfg
            self._app_actions.set_widgets_from_config()
            self._app_actions.toast(_("Config restored to sidebar"))
        except Exception as e:
            logger.warning(f"Failed to restore config: {e}")
            self._app_actions.toast(_("Failed to restore config"))

    # ==================================================================
    # Helpers
    # ==================================================================

    def _make_tree(self, headers: list[str], parent: QWidget) -> QTreeWidget:
        tree = QTreeWidget(parent)
        tree.setHeaderLabels(headers)
        tree.setRootIsDecorated(False)
        tree.setAlternatingRowColors(True)
        tree.setSortingEnabled(False)
        hdr = tree.header()
        hdr.setStretchLastSection(True)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for i in range(1, len(headers) - 1):
            hdr.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        return tree

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:
            self._refresh_history()

    def closeEvent(self, event):
        self._refresh_timer.stop()
        super().closeEvent(event)
