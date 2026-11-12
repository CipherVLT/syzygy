"""Two-column layout: rounded pill sidebar (with section headings) + content stack."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QStackedWidget, QWidget

_KEY_ROLE = Qt.ItemDataRole.UserRole
_PAGE_ROLE = Qt.ItemDataRole.UserRole + 1


@dataclass(frozen=True)
class SidebarItem:
    key: str
    label: str
    page: str = ""  # name passed to add_page(); "" for section headings
    count: int | None = None
    section: bool = False
    tooltip: str = ""


def heading(label: str) -> SidebarItem:
    return SidebarItem(key=f"__section:{label}", label=label, section=True)


class SidebarSplit(QWidget):
    """Sidebar entries select a key; each key maps to a named page in the stack.

    Several keys may share one page (e.g. a filtered list): listen to ``selected(key)``.
    """

    selected = Signal(str)

    def __init__(self, parent: QWidget | None = None, *, sidebar_width: int = 230) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        self.sidebar = QListWidget()
        self.sidebar.setObjectName("sidebar")
        self.sidebar.setFixedWidth(sidebar_width)
        self.sidebar.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.sidebar.setWordWrap(True)
        self.sidebar.setUniformItemSizes(False)
        self.sidebar.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        layout.addWidget(self.stack, stretch=1)
        self._pages: dict[str, QWidget] = {}
        #: True while set_items() re-announces an unchanged selection after a data refresh,
        #: so pages can keep transient state (e.g. an open detail view).
        self.reannouncing = False

    # ------------------------------------------------------------------ pages
    def add_page(self, name: str, widget: QWidget) -> QWidget:
        self._pages[name] = widget
        self.stack.addWidget(widget)
        return widget

    def show_page(self, name: str) -> None:
        widget = self._pages.get(name)
        if widget is not None:
            self.stack.setCurrentWidget(widget)

    # ------------------------------------------------------------------ items
    def set_items(self, items: list[SidebarItem], *, keep_selection: bool = True) -> None:
        previous = self.current_key() if keep_selection else None
        self.sidebar.blockSignals(True)
        self.sidebar.clear()
        first_selectable: QListWidgetItem | None = None
        restore: QListWidgetItem | None = None
        for entry in items:
            text = entry.label if entry.count is None else f"{entry.label}   ·  {entry.count}"
            item = QListWidgetItem(text.upper() if entry.section else text)
            item.setData(_KEY_ROLE, entry.key)
            item.setData(_PAGE_ROLE, entry.page)
            if entry.tooltip:
                item.setToolTip(entry.tooltip)
            if entry.section:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                font = item.font()
                font.setPointSizeF(max(font.pointSizeF() - 1.5, 7.0))
                item.setFont(font)
            else:
                first_selectable = first_selectable or item
                if entry.key == previous:
                    restore = item
            self.sidebar.addItem(item)
        self.sidebar.blockSignals(False)
        if restore is not None:
            # Selection unchanged: re-select silently, then re-announce (flagged) so the page
            # re-renders with fresh data but may keep transient state.
            self.sidebar.blockSignals(True)
            self.sidebar.setCurrentItem(restore)
            self.sidebar.blockSignals(False)
            self.reannouncing = True
            try:
                self._on_current_changed(restore, None)
            finally:
                self.reannouncing = False
        elif first_selectable is not None:
            # Set silently and announce explicitly: Qt may already have made row 0 current
            # while signals were blocked, in which case no change signal would fire.
            self.sidebar.blockSignals(True)
            self.sidebar.setCurrentItem(first_selectable)
            self.sidebar.blockSignals(False)
            self._on_current_changed(first_selectable, None)

    def current_key(self) -> str | None:
        item = self.sidebar.currentItem()
        return item.data(_KEY_ROLE) if item is not None else None

    def select(self, key: str) -> None:
        for row in range(self.sidebar.count()):
            item = self.sidebar.item(row)
            if item.data(_KEY_ROLE) == key:
                self.sidebar.setCurrentItem(item)
                return

    def _on_current_changed(self, current: QListWidgetItem | None, _prev: object) -> None:
        if current is None or not current.flags() & Qt.ItemFlag.ItemIsEnabled:
            return
        self.show_page(current.data(_PAGE_ROLE))
        self.selected.emit(current.data(_KEY_ROLE))
