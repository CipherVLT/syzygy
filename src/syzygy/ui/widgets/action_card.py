"""Generic dashboard card: title + badges, description, detail line, row of action buttons."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from syzygy.ui.widgets.badge import Badge


class ActionCard(QFrame):
    def __init__(
        self,
        title: str,
        description: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("card")  # styled globally in ui/styles.py
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(6)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self.title_lbl = QLabel(title)
        self.title_lbl.setObjectName("cardName")
        self.title_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        title_row.addWidget(self.title_lbl)
        self._badge_row = QHBoxLayout()
        self._badge_row.setSpacing(6)
        title_row.addLayout(self._badge_row)
        title_row.addStretch()
        root.addLayout(title_row)

        self.description_lbl = QLabel(description)
        self.description_lbl.setObjectName("cardSummary")
        self.description_lbl.setWordWrap(True)
        self.description_lbl.setVisible(bool(description))
        root.addWidget(self.description_lbl)

        self.meta_lbl = QLabel()
        self.meta_lbl.setObjectName("cardMeta")
        self.meta_lbl.setWordWrap(True)
        self.meta_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.meta_lbl.hide()
        root.addWidget(self.meta_lbl)

        self.button_row = QHBoxLayout()
        self.button_row.setSpacing(8)
        self.button_row.addStretch()
        root.addLayout(self.button_row)

    # ------------------------------------------------------------------ badges
    def add_badge(self, text: str, color: str) -> Badge:
        badge = Badge(text, color)
        self._badge_row.addWidget(badge)
        return badge

    def clear_badges(self) -> None:
        while self._badge_row.count():
            item = self._badge_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

    # ------------------------------------------------------------------ text
    def set_description(self, text: str) -> None:
        self.description_lbl.setText(text)
        self.description_lbl.setVisible(bool(text))

    def set_meta(self, text: str) -> None:
        self.meta_lbl.setText(text)
        self.meta_lbl.setVisible(bool(text))

    # ------------------------------------------------------------------ buttons
    def add_button(self, text: str, *, primary: bool = False, danger: bool = False) -> QPushButton:
        btn = QPushButton(text)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        if primary:
            btn.setProperty("primary", True)
        if danger:
            btn.setProperty("danger", True)
        self.button_row.addWidget(btn)
        return btn
