"""
Qt message box helpers for Qt applications.
"""
from typing import Optional

from PySide6.QtWidgets import QWidget, QMessageBox

from utils.translations import I18N

_ = I18N._


def _make_box(
    parent: Optional[QWidget],
    icon: QMessageBox.Icon,
    title: str,
    message: str,
    buttons: QMessageBox.StandardButton,
    default: QMessageBox.StandardButton,
) -> QMessageBox:
    """Create a QMessageBox with translated button labels and the given default."""
    box = QMessageBox(icon, title, message, buttons, parent)
    box.setDefaultButton(default)

    # Translate standard button labels
    _translations = {
        QMessageBox.StandardButton.Ok: _("OK"),
        QMessageBox.StandardButton.Cancel: _("Cancel"),
        QMessageBox.StandardButton.Yes: _("Yes"),
        QMessageBox.StandardButton.No: _("No"),
    }
    for btn_type, label in _translations.items():
        btn = box.button(btn_type)
        if btn is not None:
            btn.setText(label)

    return box


def qt_alert(
    parent: Optional[QWidget],
    title: str,
    message: str,
    kind: str = "info",
):
    """Show a Qt message box. kind: info, warning, error, askokcancel, askyesno, askyesnocancel."""
    if kind == "askokcancel":
        box = _make_box(
            parent, QMessageBox.Icon.Question, title, message,
            QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Ok,
        )
        return box.exec() == QMessageBox.StandardButton.Ok
    if kind == "askyesno":
        box = _make_box(
            parent, QMessageBox.Icon.Question, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        return box.exec() == QMessageBox.StandardButton.Yes
    if kind == "askyesnocancel":
        box = _make_box(
            parent, QMessageBox.Icon.Question, title, message,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
        return box.exec()
    if kind == "error":
        box = _make_box(
            parent, QMessageBox.Icon.Critical, title, message,
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        box.exec()
        return None
    if kind == "warning":
        box = _make_box(
            parent, QMessageBox.Icon.Warning, title, message,
            QMessageBox.StandardButton.Ok,
            QMessageBox.StandardButton.Ok,
        )
        box.exec()
        return None
    # info
    box = _make_box(
        parent, QMessageBox.Icon.Information, title, message,
        QMessageBox.StandardButton.Ok,
        QMessageBox.StandardButton.Ok,
    )
    box.exec()
    return None
