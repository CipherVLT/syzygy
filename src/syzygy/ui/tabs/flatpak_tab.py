"""Flatpak tab – installed apps and runtimes with sizes, uninstall, cleanup and repair."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QPushButton, QTableWidget, QTabWidget, QWidget

from syzygy.core import flatpak
from syzygy.core.flatpak import FlatpakEntry
from syzygy.ui.widgets.page import SCOPE_FLATPAK, BasePage, SortItem, make_table

HEADERS = ["Name", "ID", "Version", "Branch", "Origin", "Installation", "Size"]


def _load() -> tuple[list[FlatpakEntry], list[FlatpakEntry]]:
    return flatpak.list_installed_apps(), flatpak.list_installed_runtimes()


class FlatpakTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_FLATPAK})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Flatpak", "Installed apps & runtimes", parent)
        self._apps: list[FlatpakEntry] = []
        self._runtimes: list[FlatpakEntry] = []

        self.update_btn = self.add_header_button("Update all", self._update_all, primary=True)

        controls = QHBoxLayout()
        self.filter_edit = QLineEdit()
        self.filter_edit.setPlaceholderText("Filter by name or ID…")
        self.filter_edit.setClearButtonEnabled(True)
        self.filter_edit.textChanged.connect(self._render)
        controls.addWidget(self.filter_edit, stretch=1)
        self.root.addLayout(controls)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("subTabs")
        self.apps_table = make_table(HEADERS, stretch_column=1)
        self.runtimes_table = make_table(HEADERS, stretch_column=1)
        self.tabs.addTab(self.apps_table, "Apps")
        self.tabs.addTab(self.runtimes_table, "Runtimes")
        for table in (self.apps_table, self.runtimes_table):
            table.itemSelectionChanged.connect(self._sync_buttons)
        self.tabs.currentChanged.connect(lambda _i: self._sync_buttons())
        self.root.addWidget(self.tabs, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.unused_btn = QPushButton("Remove unused runtimes")
        self.unused_btn.clicked.connect(self._remove_unused)
        self.repair_btn = QPushButton("Repair")
        self.repair_btn.setToolTip("flatpak repair for the system installation (admin)")
        self.repair_btn.clicked.connect(self._repair)
        self.uninstall_btn = QPushButton("Uninstall selected")
        self.uninstall_btn.setProperty("danger", True)
        self.uninstall_btn.clicked.connect(self._uninstall_selected)
        actions.addWidget(self.unused_btn)
        actions.addWidget(self.repair_btn)
        actions.addStretch()
        actions.addWidget(self.uninstall_btn)
        self.root.addLayout(actions)

        self.track(self.unused_btn, self.repair_btn, self.uninstall_btn)
        self._sync_buttons()

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Listing installed Flatpaks…")
        self.run_query("list", _load, self._on_loaded)

    def _on_loaded(self, value: object) -> None:
        apps, runtimes = value  # type: ignore[misc]
        self._apps, self._runtimes = apps, runtimes
        self._render()

    def _render(self) -> None:
        text = self.filter_edit.text().strip().lower()
        for table, entries in ((self.apps_table, self._apps),
                               (self.runtimes_table, self._runtimes)):
            visible = [e for e in entries
                       if not text or text in e.name.lower() or text in e.application.lower()]
            self._fill(table, visible)
        self.tabs.setTabText(0, f"Apps ({len(self._apps)})")
        self.tabs.setTabText(1, f"Runtimes ({len(self._runtimes)})")

        app_bytes = sum(e.size_bytes for e in self._apps)
        rt_bytes = sum(e.size_bytes for e in self._runtimes)
        self.set_status(
            f"{len(self._apps)} apps ({flatpak.format_bytes(app_bytes)})   ·   "
            f"{len(self._runtimes)} runtimes ({flatpak.format_bytes(rt_bytes)})   ·   "
            f"total {flatpak.format_bytes(app_bytes + rt_bytes)}"
        )
        self._sync_buttons()

    @staticmethod
    def _fill(table: QTableWidget, entries: list[FlatpakEntry]) -> None:
        table.setSortingEnabled(False)
        table.setRowCount(0)
        for entry in entries:
            row = table.rowCount()
            table.insertRow(row)
            name = SortItem(entry.name or entry.application)
            name.setData(Qt.ItemDataRole.UserRole, entry)
            table.setItem(row, 0, name)
            table.setItem(row, 1, SortItem(entry.application))
            table.setItem(row, 2, SortItem(entry.version))
            table.setItem(row, 3, SortItem(entry.branch))
            table.setItem(row, 4, SortItem(entry.origin))
            table.setItem(row, 5, SortItem(entry.installation))
            size = SortItem(entry.size, entry.size_bytes)
            size.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            table.setItem(row, 6, size)
        table.setSortingEnabled(True)

    # ================================================================== selection
    def _current_table(self) -> QTableWidget:
        return self.apps_table if self.tabs.currentIndex() == 0 else self.runtimes_table

    def _selected(self) -> list[FlatpakEntry]:
        table = self._current_table()
        rows = sorted({i.row() for i in table.selectedItems()})
        entries: list[FlatpakEntry] = []
        for row in rows:
            item = table.item(row, 0)
            entry = item.data(Qt.ItemDataRole.UserRole) if item else None
            if isinstance(entry, FlatpakEntry):
                entries.append(entry)
        return entries

    def _sync_buttons(self) -> None:
        if self.busy:
            return
        count = len(self._selected())
        self.uninstall_btn.setEnabled(count > 0)
        self.uninstall_btn.setText(f"Uninstall selected ({count})" if count
                                   else "Uninstall selected")

    def on_busy_changed(self, busy: bool) -> None:
        if not busy:
            self._sync_buttons()

    # ================================================================== actions
    @Slot()
    def _uninstall_selected(self) -> None:
        entries = self._selected()
        if not entries:
            return
        runtimes = [e for e in entries if e.is_runtime]
        names = "<br>".join(f"• {escape(e.name or e.application)} "
                            f"<code>{escape(e.ref)}</code> ({escape(e.installation)})"
                            for e in entries[:10])
        warn = ("<br><br>Runtimes still used by an app cannot be removed – flatpak will refuse."
                if runtimes else "<br><br>App data in ~/.var/app is kept.")
        if not self.confirm("Uninstall Flatpaks", f"Uninstall:<br>{names}{warn}"):
            return
        # One flatpak call per installation scope (a --user ref is invisible to --system).
        by_scope: dict[str, list[FlatpakEntry]] = {}
        for entry in entries:
            by_scope.setdefault(entry.installation, []).append(entry)
        commands = []
        for scope, group in by_scope.items():
            cmd = flatpak.cmd_uninstall_entry(group[0])
            cmd = cmd[:-1] + [e.ref for e in group]  # same flags, several refs
            commands.append((scope, cmd))
        self._run_sequence(commands)

    def _run_sequence(self, commands: list[tuple[str, list[str]]]) -> None:
        if not commands:
            return
        scope, cmd = commands[0]
        rest = commands[1:]
        self.run_task(
            f"Uninstalling Flatpaks ({scope})", cmd, use_pkexec=False, scope=SCOPE_FLATPAK,
            success_message="Flatpaks uninstalled", refresh_after=not rest,
            on_done=lambda ok: self._run_sequence(rest) if ok and rest else None,
        )

    @Slot()
    def _remove_unused(self) -> None:
        self.run_task("Removing unused runtimes", flatpak.cmd_uninstall_unused(),
                      use_pkexec=False, scope=SCOPE_FLATPAK,
                      success_message="Unused runtimes removed")

    @Slot()
    def _repair(self) -> None:
        self.run_task(
            "Repairing Flatpak installation", flatpak.cmd_repair("system"), use_pkexec=True,
            scope=SCOPE_FLATPAK, success_message="Flatpak installation repaired",
            confirm="Verify the system Flatpak installation and re-download damaged objects?"
                    "<br><br>This can take a while on large installations.",
        )

    @Slot()
    def _update_all(self) -> None:
        self.run_task("Updating Flatpaks", flatpak.cmd_update_all(), use_pkexec=False,
                      scope=SCOPE_FLATPAK, success_message="Flatpaks updated")
