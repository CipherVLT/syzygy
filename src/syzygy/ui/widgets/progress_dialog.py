from __future__ import annotations

from PySide6.QtCore import Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout,
)


class TaskDialog(QDialog):
    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.resize(720, 480)
        self.setMinimumSize(560, 360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        self.header = QLabel(title)
        self.header.setStyleSheet("font-size: 16px; font-weight: 700; color: #89b4fa;")
        layout.addWidget(self.header)

        self.status_lbl = QLabel("Running…")
        self.status_lbl.setStyleSheet("color: #a6adc8;")
        layout.addWidget(self.status_lbl)

        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFont("JetBrains Mono", 10))
        self.output.setStyleSheet(
            "background-color: #11111b; color: #cdd6f4; border-radius: 6px; padding: 8px;"
        )
        layout.addWidget(self.output, stretch=1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.btn_close = QPushButton("Close")
        self.btn_close.setEnabled(False)
        self.btn_close.clicked.connect(self.accept)
        btn_row.addWidget(self.btn_close)
        layout.addLayout(btn_row)

    @Slot(str)
    def append_line(self, line: str) -> None:
        self.output.moveCursor(QTextCursor.MoveOperation.End)
        self.output.insertPlainText(line + "\n")
        self.output.moveCursor(QTextCursor.MoveOperation.End)

    def set_running(self, message: str = "Running…") -> None:
        self.status_lbl.setText(message)
        self.status_lbl.setStyleSheet("color: #89b4fa;")
        self.btn_close.setEnabled(False)

    def set_success(self, message: str = "Task Completed Successfully") -> None:
        self.header.setText(message)
        self.header.setStyleSheet("font-size: 16px; font-weight: 700; color: #a6e3a1;")
        self.status_lbl.setText("Finished successfully")
        self.status_lbl.setStyleSheet("color: #a6e3a1;")
        self.btn_close.setEnabled(True)

    def set_failure(self, message: str = "Task Failed") -> None:
        self.header.setText(message)
        self.header.setStyleSheet("font-size: 16px; font-weight: 700; color: #f38ba8;")
        self.status_lbl.setText("Finished with errors")
        self.status_lbl.setStyleSheet("color: #f38ba8;")
        self.btn_close.setEnabled(True)
