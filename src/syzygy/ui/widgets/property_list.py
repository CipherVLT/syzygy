"""Key/value detail card with alternating row highlights (Rustora device-detail style)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget


class PropertyList(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("propertyCard")
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(10, 10, 10, 10)
        self._layout.setSpacing(2)

    def set_rows(self, rows: list[tuple[str, str]], *, accent_values: set[str] = frozenset()) -> None:
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for index, (key, value) in enumerate(rows):
            row = QFrame()
            row.setObjectName("propRow")
            row.setProperty("alt", index % 2 == 0)
            h = QHBoxLayout(row)
            h.setContentsMargins(12, 9, 12, 9)
            key_lbl = QLabel(key)
            key_lbl.setObjectName("propKey")
            value_lbl = QLabel(value or "—")
            value_lbl.setObjectName("propValue")
            value_lbl.setProperty("accent", value in accent_values)
            value_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            value_lbl.setWordWrap(True)
            h.addWidget(key_lbl)
            h.addWidget(value_lbl, stretch=1)
            self._layout.addWidget(row)
