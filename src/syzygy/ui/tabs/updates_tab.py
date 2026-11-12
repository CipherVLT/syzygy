"""Updates tab – pending RPM + Flatpak updates with selective or bulk upgrade."""

from __future__ import annotations

from collections.abc import Sequence
from html import escape

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from syzygy.core import updates
from syzygy.core.updates import SOURCE_FLATPAK, SOURCE_RPM, UpdateItem, UpdateReport
from syzygy.ui.widgets.page import (
    SCOPE_FLATPAK,
    SCOPE_KERNELS,
    SCOPE_PACKAGES,
    SCOPE_REPOS,
    BasePage,
    SortItem,
    check_item,
    make_table,
)

COL_CHECK, COL_NAME, COL_VERSION, COL_REPO, COL_TYPE, COL_NOTES = range(6)

# (title, command, use_pkexec, scope)
Step = tuple[str, list[str], bool, str]


class UpdatesTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_PACKAGES, SCOPE_FLATPAK, SCOPE_REPOS})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Updates", "DNF · COPR · Flatpak", parent, refresh_label=None)
        self._report: UpdateReport | None = None
        self._by_key: dict[str, UpdateItem] = {}
        self._populating = False

        self.check_btn = self.add_header_button(
            "Check for updates", self.check_now,
            tooltip="Refresh repository metadata and look for updates",
        )
        self.update_all_btn = self.add_header_button(
            "Update everything", self.update_everything, primary=True
        )

        self.table = make_table(["", "Name", "New version", "Repo / Remote", "Type", "Notes"])
        self.table.itemChanged.connect(self._on_item_changed)
        self.root.addWidget(self.table, stretch=1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self.select_all_btn = QPushButton("Select all")
        self.select_all_btn.clicked.connect(lambda: self._set_all_checked(True))
        self.select_none_btn = QPushButton("Select none")
        self.select_none_btn.clicked.connect(lambda: self._set_all_checked(False))
        actions.addWidget(self.select_all_btn)
        actions.addWidget(self.select_none_btn)
        actions.addStretch()
        self.update_rpms_btn = QPushButton("Update all RPMs")
        self.update_rpms_btn.clicked.connect(self.update_all_rpms)
        self.update_flatpaks_btn = QPushButton("Update all Flatpaks")
        self.update_flatpaks_btn.clicked.connect(self.update_all_flatpaks)
        self.update_selected_btn = QPushButton("Update selected")
        self.update_selected_btn.setProperty("primary", True)
        self.update_selected_btn.clicked.connect(self.update_selected)
        for btn in (self.update_rpms_btn, self.update_flatpaks_btn, self.update_selected_btn):
            actions.addWidget(btn)
        self.root.addLayout(actions)

        self.track(self.select_all_btn, self.select_none_btn, self.update_rpms_btn,
                   self.update_flatpaks_btn, self.update_selected_btn)
        self.set_status("Updates are checked when you open this tab.")
        self._sync_buttons()

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self._load(refresh_metadata=False)

    @Slot()
    def check_now(self) -> None:
        self._load(refresh_metadata=True)

    def _load(self, *, refresh_metadata: bool) -> None:
        self.set_status(
            "Refreshing metadata and checking for updates…" if refresh_metadata
            else "Checking for updates…"
        )
        self.check_btn.setEnabled(False)
        self.run_query(
            "updates",
            lambda: updates.check_all(refresh=refresh_metadata),
            self._on_report,
            self._on_error,
        )

    def _on_error(self, message: str) -> None:
        self.check_btn.setEnabled(not self.busy)
        self.set_status(f"Update check failed: {message}", level="error")

    def _on_report(self, report: object) -> None:
        assert isinstance(report, UpdateReport)
        self._report = report
        self.check_btn.setEnabled(not self.busy)
        self._populate(report)

        parts: list[str] = []
        total = len(report.rpm) + len(report.flatpak)
        if total == 0:
            parts.append("✔ Your system is up to date.")
        else:
            parts.append(f"{len(report.rpm)} RPM update{'s' if len(report.rpm) != 1 else ''}")
            parts.append(f"{len(report.flatpak)} Flatpak update"
                         f"{'s' if len(report.flatpak) != 1 else ''}")
        if report.reboot_required:
            parts.append("includes kernel/system packages – reboot afterwards")
        parts.extend(f"⚠ {e}" for e in report.errors)
        level = "error" if report.errors else "warning" if report.reboot_required else "info"
        self.set_status("   ·   ".join(parts), level=level)
        self._sync_buttons()

    def _populate(self, report: UpdateReport) -> None:
        self._populating = True
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        self._by_key.clear()
        for item in [*report.rpm, *report.flatpak]:
            row = self.table.rowCount()
            self.table.insertRow(row)
            check = check_item(True)
            check.setData(Qt.ItemDataRole.UserRole, item.key)
            self.table.setItem(row, COL_CHECK, check)
            name = item.name if item.source == SOURCE_RPM else f"{item.name}  ({item.app_id})"
            self.table.setItem(row, COL_NAME, SortItem(name))
            self.table.setItem(row, COL_VERSION, SortItem(item.version or item.branch))
            remote = item.repo
            if item.source == SOURCE_FLATPAK and item.installation == "user":
                remote = f"{remote} (user)"
            self.table.setItem(row, COL_REPO, SortItem(remote))
            kind = "RPM" if item.source == SOURCE_RPM else "Flatpak"
            if item.source == SOURCE_RPM and item.repo.lower().startswith("copr"):
                kind = "COPR"
            self.table.setItem(row, COL_TYPE, SortItem(kind))
            notes = SortItem("⟳ reboot" if item.needs_reboot else "", item.needs_reboot)
            if item.needs_reboot:
                notes.setToolTip("Takes full effect after a reboot")
            self.table.setItem(row, COL_NOTES, notes)
            self._by_key[item.key] = item
        self.table.setSortingEnabled(True)
        self._populating = False

    # ================================================================== selection
    def _checked_items(self) -> list[UpdateItem]:
        result: list[UpdateItem] = []
        for row in range(self.table.rowCount()):
            check = self.table.item(row, COL_CHECK)
            if check is not None and check.checkState() == Qt.CheckState.Checked:
                item = self._by_key.get(check.data(Qt.ItemDataRole.UserRole))
                if item is not None:
                    result.append(item)
        return result

    def _set_all_checked(self, checked: bool) -> None:
        self._populating = True
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for row in range(self.table.rowCount()):
            check = self.table.item(row, COL_CHECK)
            if check is not None:
                check.setCheckState(state)
        self._populating = False
        self._sync_buttons()

    @Slot(object)
    def _on_item_changed(self, _item: object) -> None:
        if not self._populating:
            self._sync_buttons()

    def _sync_buttons(self) -> None:
        if self.busy:
            return
        report = self._report
        rpm = bool(report and report.rpm)
        flatpak = bool(report and report.flatpak)
        self.update_rpms_btn.setEnabled(rpm)
        self.update_flatpaks_btn.setEnabled(flatpak)
        self.update_all_btn.setEnabled(rpm or flatpak)
        selected = len(self._checked_items())
        self.update_selected_btn.setEnabled(selected > 0)
        self.update_selected_btn.setText(f"Update selected ({selected})" if selected
                                         else "Update selected")

    def on_busy_changed(self, busy: bool) -> None:
        self.table.setEnabled(not busy)
        self.check_btn.setEnabled(not busy)
        if not busy:
            self._sync_buttons()

    # ================================================================== actions
    def _rpm_step(self, items: Sequence[UpdateItem]) -> Step:
        title = "Upgrading all RPM packages" if not items else f"Upgrading {len(items)} RPM(s)"
        return title, updates.cmd_upgrade_rpms(items), True, SCOPE_PACKAGES

    def _flatpak_step(self, items: Sequence[UpdateItem]) -> Step:
        title = "Updating all Flatpaks" if not items else f"Updating {len(items)} Flatpak(s)"
        # Flatpak authorizes system refs through its own polkit helper – never pkexec.
        return title, updates.cmd_update_flatpaks(items), False, SCOPE_FLATPAK

    def _run_chain(self, steps: list[Step]) -> None:
        """Run steps one after another; stop at the first failure, refresh at the end."""
        if not steps:
            self.refresh()
            return
        title, command, use_pkexec, scope = steps[0]
        rest = steps[1:]

        def next_step(success: bool) -> None:
            if success and scope == SCOPE_PACKAGES:
                self.system_changed.emit(SCOPE_KERNELS)  # kernel packages may have changed
            if success and rest:
                self._run_chain(rest)
            else:
                self.refresh()

        self.run_task(title, command, use_pkexec=use_pkexec, scope=scope,
                      success_message=f"{title} – done", on_done=next_step,
                      refresh_after=False)

    def _reboot_note(self, items: Sequence[UpdateItem]) -> str:
        if any(i.needs_reboot for i in items):
            return ("<br><br><b>Includes kernel/system packages</b> – reboot when the update "
                    "finishes.")
        return ""

    @Slot()
    def update_selected(self) -> None:
        chosen = self._checked_items()
        rpms = [i for i in chosen if i.source == SOURCE_RPM]
        flatpaks = [i for i in chosen if i.source == SOURCE_FLATPAK]
        if not chosen:
            return
        names = ", ".join(escape(i.name) for i in chosen[:8])
        more = f" and {len(chosen) - 8} more" if len(chosen) > 8 else ""
        if not self.confirm("Update selected",
                            f"Update <b>{len(chosen)}</b> item(s): {names}{more}?"
                            f"{self._reboot_note(rpms)}"):
            return
        steps: list[Step] = []
        if rpms:
            steps.append(self._rpm_step(rpms))
        if flatpaks:
            steps.append(self._flatpak_step(flatpaks))
        self._run_chain(steps)

    @Slot()
    def update_all_rpms(self) -> None:
        rpms = self._report.rpm if self._report else []
        if self.confirm("Update all RPMs",
                        f"Upgrade all <b>{len(rpms)}</b> RPM package(s) with DNF?"
                        f"{self._reboot_note(rpms)}"):
            self._run_chain([self._rpm_step([])])

    @Slot()
    def update_all_flatpaks(self) -> None:
        self._run_chain([self._flatpak_step([])])

    @Slot()
    def update_everything(self) -> None:
        report = self._report
        if report is None:
            return
        if not self.confirm(
            "Update everything",
            f"Upgrade <b>{len(report.rpm)}</b> RPM(s) and <b>{len(report.flatpak)}</b> "
            f"Flatpak(s)?{self._reboot_note(report.rpm)}",
        ):
            return
        steps: list[Step] = []
        if report.rpm:
            steps.append(self._rpm_step([]))
        if report.flatpak:
            steps.append(self._flatpak_step([]))
        self._run_chain(steps)
