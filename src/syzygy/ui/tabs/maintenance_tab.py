from __future__ import annotations
from typing import Optional
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

class MaintenanceTab(QWidget):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        title = QLabel("Maintenance")
        title.setStyleSheet("font-size: 18px; font-weight: 700; color: #89b4fa;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        note = QLabel("Full vertical-slice implementation is in the conversation history.\nCore backend modules are complete under syzygy.core.*")
        note.setStyleSheet("color: #a6adc8;")
        note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
