"""Rustora-style top navigation: a row of rounded command pills driving a QStackedWidget."""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QWidget,
)


class NavPills(QObject):
    """Controller owning ``bar`` (the pill row) and ``stack`` (the pages).

    Mirrors the parts of the QTabWidget API the main window uses.
    """

    currentChanged = Signal(int)  # noqa: N815 – Qt naming

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.bar = QWidget()
        self.bar.setObjectName("navBar")
        self._layout = QHBoxLayout(self.bar)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self.stack = QStackedWidget()
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        self._group.idClicked.connect(self.setCurrentIndex)

    def addTab(self, widget: QWidget, label: str) -> int:  # noqa: N802
        index = self.stack.addWidget(widget)
        btn = QPushButton(label)
        btn.setObjectName("navPill")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._group.addButton(btn, index)
        self._layout.insertWidget(self._layout.count() - 1, btn)
        self._buttons.append(btn)
        if index == 0:
            btn.setChecked(True)
        return index

    def count(self) -> int:
        return self.stack.count()

    def currentIndex(self) -> int:  # noqa: N802
        return self.stack.currentIndex()

    def currentWidget(self) -> QWidget:  # noqa: N802
        return self.stack.currentWidget()

    def setCurrentIndex(self, index: int) -> None:  # noqa: N802
        if not 0 <= index < self.stack.count():
            return
        self._buttons[index].setChecked(True)
        if index != self.stack.currentIndex():
            self.stack.setCurrentIndex(index)
            self.currentChanged.emit(index)

    def setCurrentWidget(self, widget: QWidget) -> None:  # noqa: N802
        self.setCurrentIndex(self.stack.indexOf(widget))

    def step(self, delta: int) -> None:
        if self.stack.count():
            self.setCurrentIndex((self.stack.currentIndex() + delta) % self.stack.count())
