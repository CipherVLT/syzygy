from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStatusBar,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from syzygy.ui.styles import apply_theme
from syzygy.ui.tabs.devices_tab import DevicesTab
from syzygy.ui.tabs.flatpak_tab import FlatpakTab
from syzygy.ui.tabs.fpm_tab import FpmTab
from syzygy.ui.tabs.installed_tab import InstalledTab
from syzygy.ui.tabs.kernels_tab import KernelsTab
from syzygy.ui.tabs.maintenance_tab import MaintenanceTab
from syzygy.ui.tabs.repos_tab import ReposTab
from syzygy.ui.tabs.search_tab import SearchTab
from syzygy.ui.tabs.tweaks_tab import TweaksTab
from syzygy.ui.tabs.updates_tab import UpdatesTab
from syzygy.ui.widgets.page import SCOPE_FLATPAK, SCOPE_PACKAGES, BasePage

logger = logging.getLogger(__name__)

# Scopes that change what the Search / Installed package views show.
_PACKAGE_VIEW_SCOPES = frozenset({SCOPE_PACKAGES, SCOPE_FLATPAK})


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Syzygy – Package Manager")
        self.resize(1280, 840)
        self.setMinimumSize(1024, 680)
        self._dark_theme = True
        self._setup_ui()
        self._setup_actions()
        self._setup_statusbar()
        self._wire_tabs()

    # ================================================================== layout
    def _setup_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel("Syzygy")
        title.setObjectName("pageTitle")
        top.addWidget(title)
        top.addStretch()
        self.btn_theme = QPushButton("Light")
        self.btn_theme.setToolTip("Switch between Catppuccin Mocha and Latte")
        self.btn_theme.clicked.connect(self.toggle_theme)
        top.addWidget(self.btn_theme)
        layout.addLayout(top)

        self.search_tab = SearchTab()
        self.installed_tab = InstalledTab()
        self.updates_tab = UpdatesTab()
        self.flatpak_tab = FlatpakTab()
        self.maintenance_tab = MaintenanceTab()
        self.repos_tab = ReposTab()
        self.kernels_tab = KernelsTab()
        self.devices_tab = DevicesTab()
        self.fpm_tab = FpmTab()
        self.tweaks_tab = TweaksTab()

        self.pages: list[BasePage] = [
            self.updates_tab, self.flatpak_tab, self.maintenance_tab, self.repos_tab,
            self.kernels_tab, self.devices_tab, self.fpm_tab, self.tweaks_tab,
        ]

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        for widget, label in (
            (self.search_tab, "Search"),
            (self.installed_tab, "Installed"),
            (self.updates_tab, "Updates"),
            (self.flatpak_tab, "Flatpak"),
            (self.maintenance_tab, "Maintenance"),
            (self.repos_tab, "Repos"),
            (self.kernels_tab, "Kernels"),
            (self.devices_tab, "Devices"),
            (self.fpm_tab, "FPM"),
            (self.tweaks_tab, "Tweaks"),
        ):
            self.tabs.addTab(widget, label)
        layout.addWidget(self.tabs)

    def _setup_actions(self) -> None:
        quit_action = QAction("Quit", self)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(self.close)
        self.addAction(quit_action)

        find_action = QAction("Search packages", self)
        find_action.setShortcut(QKeySequence.StandardKey.Find)
        find_action.triggered.connect(self._focus_search)
        self.addAction(find_action)

        refresh_action = QAction("Refresh current tab", self)
        refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)  # F5
        refresh_action.triggered.connect(self._refresh_current)
        self.addAction(refresh_action)

    def _setup_statusbar(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")

    # ================================================================== cross-tab wiring
    def _wire_tabs(self) -> None:
        self.search_tab.status_message.connect(self._show_status)
        self.installed_tab.status_message.connect(self._show_status)
        self.search_tab.packages_changed.connect(self._on_search_changed)
        self.installed_tab.packages_changed.connect(self._on_installed_changed)
        for page in self.pages:
            page.status_message.connect(self._show_status)
            page.system_changed.connect(self._on_system_changed)

    def _broadcast(self, scopes: frozenset[str], source: QWidget | None) -> None:
        """Tell every other tab that ``scopes`` changed so it reloads (now or when shown)."""
        logger.debug("system_changed(%s) from %s", sorted(scopes), type(source).__name__)
        for page in self.pages:
            if page is not source and scopes & page.WATCH_SCOPES:
                page.mark_stale()
        if scopes & _PACKAGE_VIEW_SCOPES:
            if source is not self.search_tab:
                self.search_tab.refresh_statuses()
            if source is not self.installed_tab:
                self.installed_tab.reload()

    @Slot(str)
    def _on_system_changed(self, scope: str) -> None:
        sender = self.sender()
        self._broadcast(frozenset({scope}), sender if isinstance(sender, QWidget) else None)

    @Slot()
    def _on_search_changed(self) -> None:
        self._broadcast(_PACKAGE_VIEW_SCOPES, self.search_tab)

    @Slot()
    def _on_installed_changed(self) -> None:
        self._broadcast(_PACKAGE_VIEW_SCOPES, self.installed_tab)

    # ================================================================== slots
    @Slot(str, int)
    def _show_status(self, message: str, timeout_ms: int) -> None:
        self.status.showMessage(message, timeout_ms)

    @Slot()
    def _focus_search(self) -> None:
        self.tabs.setCurrentWidget(self.search_tab)
        self.search_tab.focus_search()

    @Slot()
    def _refresh_current(self) -> None:
        current = self.tabs.currentWidget()
        if isinstance(current, BasePage):
            if not current.busy:
                current.refresh()
        elif current is self.installed_tab:
            self.installed_tab.reload()
        elif current is self.search_tab:
            self.search_tab.refresh_statuses()

    def _transaction_running(self) -> bool:
        return (
            any(page.busy for page in self.pages)
            or self.search_tab._busy_key is not None  # noqa: SLF001 – tab-internal state
            or self.installed_tab._busy_key is not None  # noqa: SLF001
        )

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802 – Qt override
        if self._transaction_running():
            answer = QMessageBox.warning(
                self,
                "Task still running",
                "A package or system task is still running. Quitting now may leave it "
                "half-finished.\n\nQuit anyway?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
        super().closeEvent(event)

    @Slot()
    def toggle_theme(self) -> None:
        self._dark_theme = not self._dark_theme
        app = QApplication.instance()
        if isinstance(app, QApplication):
            apply_theme(app, dark=self._dark_theme)
        self.btn_theme.setText("Dark" if not self._dark_theme else "Light")
        self.status.showMessage(
            f"Switched to {'dark' if self._dark_theme else 'light'} theme", 2500
        )
