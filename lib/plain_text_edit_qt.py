from PySide6.QtCore import QMimeData
from PySide6.QtWidgets import QPlainTextEdit


class EscapeAwarePlainTextEdit(QPlainTextEdit):
    """QPlainTextEdit that converts literal \\n escape sequences to real newlines on paste."""

    def insertFromMimeData(self, source: QMimeData) -> None:
        text = source.text()
        if '\\n' in text:
            converted = QMimeData()
            converted.setText(text.replace('\\n', '\n'))
            super().insertFromMimeData(converted)
        else:
            super().insertFromMimeData(source)
