"""Installed tab – browse/filter installed RPMs and Flatpak apps, remove with live output."""

from __future__ import annotations

import logging
from html import escape

from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from syzygy.core import dnf, installed
from syzygy.core.installed import InstalledInventory
from syzygy.core.models import Package, PackageSource
from syzygy.ui.widgets.package_card import ACTION_REMOVE, PackageCard, package_key
from syzygy.ui.widgets.task_runner import CommandTask
from syzygy.workers.function_worker import FunctionWorker

logger = logging.getLogger(__name__)

SOURCE_ALL = 0
SOURCE_RPM = 1
SOURCE_FLATPAK = 2


class InstalledTab(QWidget):
    """Lists installed software; loads lazily the first time the tab is shown."""

    status_message = Signal(str, int)
    packages_changed = Signal()

    PAGE_SIZE = 150  # ~2,000 RPMs is common – build cards in pages, not all at once
    FILTER_DEBOUNCE_MS = 200

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._pool = QThreadPool.globalInstance()
        self._inventory: InstalledInventory | None = None
        self._loaded_once = False
        self._loading = False
        self._request_id = 0
        self._workers: list[FunctionWorker] = []
        self._filtered: list[Package] = []
        self._shown = 0
        self._cards: dict[str, PackageCard] = {}
        self._busy_key: str | None = None

        self._filter_timer = QTimer(self)
        self._filter_timer.setSingleShot(True)
        self._filter_timer.setInterval(self.FILTER_DEBOUNCE_MS)
        self._filter_timer.timeout.connect(self._refilter)

        self._build_ui()
        self._update_status_label()

    # ================================================================== UI
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        header = QHBoxLayout()
        title = QLabel("Installed Software")
        title.setObjectName("pageTitle")
        header.addWidget(title)
        header.addStretch()
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Re-read the RPM database and Flatpak installations")
        self.refresh_btn.clicked.connect(self.reload)
        header.addWidget(self.refresh_btn)
        root.addLayout(header)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name, summary or app ID…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._on_filter_text)
        controls.addWidget(self.filter_edit, stretch=1)

        self.source_combo = QComboBox()
        self.source_combo.addItems(["RPM + Flatpak", "RPM only", "Flatpak only"])
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        controls.addWidget(self.source_combo)

        self.user_only = QCheckBox("User-installed only")
        self.user_only.setChecked(True)
        self.user_only.setToolTip(
            "Hide RPMs that were pulled in as dependencies or by the installer.\n"
            "Flatpak apps are always shown."
        )
        self.user_only.toggled.connect(self._on_user_only_toggled)
        controls.addWidget(self.user_only)
        root.addLayout(controls)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(4)
        self.progress.hide()
        root.addWidget(self.progress)

        self.status_lbl = QLabel()
        self.status_lbl.setObjectName("statusText")
        root.addWidget(self.status_lbl)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        contents = QWidget()
        contents.setObjectName("scrollContents")
        self.list_layout = QVBoxLayout(contents)
        self.list_layout.setContentsMargins(0, 0, 6, 0)
        self.list_layout.setSpacing(8)

        self.empty_lbl = QLabel("Loading installed software…")
        self.empty_lbl.setObjectName("emptyState")
        self.empty_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_lbl.setWordWrap(True)
        self.list_layout.addWidget(self.empty_lbl)

        self.more_btn = QPushButton()
        self.more_btn.clicked.connect(self._show_more)
        self.more_btn.hide()
        self.list_layout.addWidget(self.more_btn, alignment=Qt.AlignmentFlag.AlignHCenter)
        self.list_layout.addStretch()

        self.scroll.setWidget(contents)
        root.addWidget(self.scroll, stretch=1)

    # ================================================================== loading
    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802 – Qt override
        super().showEvent(event)
        if not self._loaded_once:
            self._loaded_once = True
            self.reload()

    @Slot()
    def reload(self) -> None:
        """Reload the inventory in the background; current cards stay visible meanwhile."""
        if not self._loaded_once:
            return  # first showEvent will load; don't spend startup time on a hidden tab
        self._request_id += 1
        self._loading = True
        self.progress.show()
        self.refresh_btn.setEnabled(False)
        self._update_status_label()

        self._workers = [w for w in self._workers if not w.done]
        worker = FunctionWorker(installed.load_inventory, request_id=self._request_id)
        worker.signals.result.connect(self._on_inventory)
        worker.signals.failed.connect(self._on_inventory_failed)
        self._workers.append(worker)
        self._pool.start(worker)

    @Slot(int, object)
    def _on_inventory(self, request_id: int, inventory: object) -> None:
        if request_id != self._request_id:
            return
        assert isinstance(inventory, InstalledInventory)
        self._inventory = inventory
        self._finish_loading()

        supported = inventory.user_installed is not None
        self.user_only.setEnabled(supported)
        if not supported:
            self.user_only.setChecked(False)
            self.user_only.setToolTip(
                "DNF could not report user-installed packages "
                "(dnf repoquery --userinstalled failed)."
            )
        for error in inventory.errors:
            self.status_message.emit(f"Installed: {error}", 8000)
        self._apply_filters(keep_scroll=True)

    @Slot(int, str)
    def _on_inventory_failed(self, request_id: int, message: str) -> None:
        if request_id != self._request_id:
            return
        self._finish_loading()
        self.empty_lbl.setText(f"Could not read installed software:\n{message}")
        self.empty_lbl.show()
        self.status_message.emit(f"Installed: {message}", 8000)

    def _finish_loading(self) -> None:
        self._loading = False
        self.progress.hide()
        self.refresh_btn.setEnabled(self._busy_key is None)

    # ================================================================== filtering / rendering
    @Slot(str)
    def _on_filter_text(self, _text: str) -> None:
        self._filter_timer.start()

    @Slot(int)
    def _on_source_changed(self, _index: int) -> None:
        self._refilter()

    @Slot(bool)
    def _on_user_only_toggled(self, _checked: bool) -> None:
        self._refilter()

    @Slot()
    def _refilter(self) -> None:
        self._apply_filters(keep_scroll=False)

    def _apply_filters(self, *, keep_scroll: bool = False) -> None:
        inv = self._inventory
        if inv is None:
            return
        source = self.source_combo.currentIndex()
        pool: list[Package] = []
        if source in (SOURCE_ALL, SOURCE_RPM):
            rpms = inv.rpms
            if self.user_only.isChecked() and inv.user_installed is not None:
                rpms = [p for p in rpms if inv.is_user_installed(p)]
            pool.extend(rpms)
        if source in (SOURCE_ALL, SOURCE_FLATPAK):
            pool.extend(inv.flatpaks)
        if source == SOURCE_ALL:
            pool.sort(key=lambda p: p.name.lower())

        self._filtered = installed.filter_packages(pool, self.filter_edit.text())
        scroll_pos = self.scroll.verticalScrollBar().value() if keep_scroll else 0
        previously_shown = self._shown if keep_scroll else 0
        self._clear_cards()
        self._shown = 0
        self._append_cards(max(self.PAGE_SIZE, previously_shown))
        if keep_scroll:
            QTimer.singleShot(0, lambda: self.scroll.verticalScrollBar().setValue(scroll_pos))
        else:
            self.scroll.verticalScrollBar().setValue(0)

    def _clear_cards(self) -> None:
        for card in self._cards.values():
            self.list_layout.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def _append_cards(self, count: int) -> None:
        assert self._inventory is not None
        insert_at = self.list_layout.indexOf(self.empty_lbl)
        batch = self._filtered[self._shown : self._shown + count]
        for pkg in batch:
            card = PackageCard(pkg)
            reason = self._inventory.lock_reason(pkg)
            if reason:
                card.set_locked(reason)
            card.set_actions_enabled(self._busy_key is None)
            if card.key == self._busy_key:
                card.set_busy("Removing…")
            card.action_requested.connect(self._on_action)
            self.list_layout.insertWidget(insert_at, card)
            insert_at += 1
            self._cards[card.key] = card
        self._shown += len(batch)

        remaining = len(self._filtered) - self._shown
        self.more_btn.setVisible(remaining > 0)
        self.more_btn.setText(f"Show {min(self.PAGE_SIZE, remaining)} more ({remaining} left)")

        if self._filtered:
            self.empty_lbl.hide()
        else:
            self.empty_lbl.setText(
                "Nothing matches the current filter."
                if self.filter_edit.text().strip()
                else "No installed packages to show."
            )
            self.empty_lbl.show()
        self._update_status_label()

    @Slot()
    def _show_more(self) -> None:
        self._append_cards(self.PAGE_SIZE)

    def _update_status_label(self) -> None:
        inv = self._inventory
        if inv is None:
            self.status_lbl.setText("Reading RPM database…" if self._loading else "")
            return
        rpm_total = len(inv.rpms)
        user_total = len(inv.user_installed) if inv.user_installed is not None else None
        parts = [f"Showing {self._shown} of {len(self._filtered)}"]
        summary = f"{rpm_total:,} RPMs"
        if user_total is not None:
            summary += f" ({user_total:,} user-installed)"
        summary += f" · {len(inv.flatpaks)} Flatpak apps"
        parts.append(summary)
        if self._loading:
            parts.append("refreshing…")
        self.status_lbl.setText("   ·   ".join(parts))

    # ================================================================== removal
    @Slot(object, str)
    def _on_action(self, pkg: Package, action: str) -> None:
        if self._busy_key is not None or action != ACTION_REMOVE:
            return
        inv = self._inventory
        if inv is not None and (reason := inv.lock_reason(pkg)):
            QMessageBox.information(self, "Cannot remove", reason)
            return

        is_flatpak = pkg.source is PackageSource.FLATPAK
        if is_flatpak:
            target = pkg.app_id or pkg.name
            command = dnf.cmd_remove_flatpak(
                target, branch=pkg.branch or "", installation=pkg.installation
            )
            detail = (
                f"Flatpak app <code>{escape(target)}</code> "
                f"({escape(pkg.installation or 'system')} installation, "
                f"branch {escape(pkg.branch or 'stable')}).<br><br>"
                "Its user data in ~/.var/app is kept. Unused runtimes can be cleaned up "
                "from the Flatpak tab."
            )
        else:
            command = installed.cmd_remove_installed_rpm(pkg)
            target = command[-1]
            detail = (
                f"RPM <code>{escape(target)}</code>.<br><br>"
                "DNF will also remove packages that depend on it – review the transaction "
                "in the output window."
            )

        answer = QMessageBox.question(
            self,
            "Remove package",
            f"Remove <b>{escape(pkg.name)}</b>?<br><br>{detail}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return

        task = CommandTask(
            self,
            f"Removing {pkg.name}",
            command,
            use_pkexec=not is_flatpak,  # Flatpak authorizes via its own polkit helper
            success_message=f"{pkg.name} removed",
            failure_message=f"Could not remove {pkg.name}",
        )
        task.done.connect(self._on_task_done)
        self._set_busy(package_key(pkg))
        self.status_message.emit(f"Removing {pkg.name}…", 0)
        task.start()

    def _set_busy(self, key: str | None) -> None:
        self._busy_key = key
        self.refresh_btn.setEnabled(key is None and not self._loading)
        for card_key, card in self._cards.items():
            card.set_actions_enabled(key is None)
            card.set_busy("Removing…" if card_key == key else None)

    @Slot(bool, str)
    def _on_task_done(self, success: bool, message: str) -> None:
        self._set_busy(None)
        self.status_message.emit("Package removed" if success else message, 5000)
        if success:
            dnf.invalidate_caches()
            self.packages_changed.emit()
            self.reload()
