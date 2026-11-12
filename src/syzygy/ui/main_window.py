from __future__ import annotations

import logging

from PySide6.QtCore import Slot
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMainWindow,
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

logger = logging.getLogger(__name__)


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
        self.btn_theme.clicked.connect(self.toggle_theme)
        top.addWidget(self.btn_theme)
        layout.addLayout(top)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.search_tab = SearchTab()
        self.tabs.addTab(self.search_tab, "Search")
        self.installed_tab = InstalledTab()
        self.tabs.addTab(self.installed_tab, "Installed")
        self.tabs.addTab(UpdatesTab(), "Updates")
        self.tabs.addTab(FlatpakTab(), "Flatpak")
        self.tabs.addTab(MaintenanceTab(), "Maintenance")
        self.tabs.addTab(ReposTab(), "Repos")
        self.tabs.addTab(KernelsTab(), "Kernels")
        self.tabs.addTab(DevicesTab(), "Devices")
        self.tabs.addTab(FpmTab(), "FPM")
        self.tabs.addTab(TweaksTab(), "Tweaks")
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

    def _setup_statusbar(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status.showMessage("Ready")
        self.search_tab.status_message.connect(self._show_status)
        self.installed_tab.status_message.connect(self._show_status)
        # Keep tabs consistent when one of them changes what is installed.
        self.search_tab.packages_changed.connect(self.installed_tab.reload)
        self.installed_tab.packages_changed.connect(self.search_tab.refresh_statuses)

    @Slot(str, int)
    def _show_status(self, message: str, timeout_ms: int) -> None:
        self.status.showMessage(message, timeout_ms)

    @Slot()
    def _focus_search(self) -> None:
        self.tabs.setCurrentWidget(self.search_tab)
        self.search_tab.focus_search()

    @Slot()
    def toggle_theme(self) -> None:
        from PySide6.QtWidgets import QApplication
        self._dark_theme = not self._dark_theme
        apply_theme(QApplication.instance(), dark=self._dark_theme)
        self.btn_theme.setText("Dark" if not self._dark_theme else "Light")
        self.status.showMessage(
            f"Switched to {'dark' if self._dark_theme else 'light'} theme", 2500
        )
