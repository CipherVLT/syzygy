"""Kernels tab – installed kernels, Running/Default badges, boot default and safe removal."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from syzygy.core import kernels, maintenance
from syzygy.core.kernels import KernelEntry, KernelReport
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, PEACH, SURFACE1
from syzygy.ui.widgets.page import SCOPE_KERNELS, SCOPE_PACKAGES, BasePage


class KernelsTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_KERNELS, SCOPE_PACKAGES})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Kernels", "Boot default via grubby", parent)
        self._report: KernelReport | None = None
        self._cards: list[ActionCard] = []

        self.add_header_button("Update GRUB", self._update_grub,
                               tooltip="Regenerate /boot/grub2/grub.cfg")
        self.add_header_button("Install latest kernel", self._upgrade, primary=True,
                               tooltip="dnf upgrade 'kernel*'")

        scroll, self.column = self.make_scroll_column()
        self.column.addStretch()
        self.root.addWidget(scroll, stretch=1)

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Reading installed kernels…")
        self.run_query("kernels", kernels.get_kernel_report, self._on_report)

    def _on_report(self, value: object) -> None:
        assert isinstance(value, KernelReport)
        self._report = value
        self._render(value)

        parts = [f"Running {value.running}", f"{len(value.kernels)} installed",
                 f"DNF keeps the newest {value.installonly_limit} (installonly_limit)"]
        if value.default is None:
            parts.append("default boot entry unknown – grubby needs admin rights to read it")
            self.set_status("   ·   ".join(parts), level="warning")
        else:
            self.set_status("   ·   ".join(parts))

    def _clear(self) -> None:
        for card in self._cards:
            self.column.removeWidget(card)
            card.deleteLater()
        self._cards.clear()

    def _render(self, report: KernelReport) -> None:
        self._clear()
        layout: QVBoxLayout = self.column
        for index, entry in enumerate(report.kernels):
            card = ActionCard(entry.version)
            if entry.is_running:
                card.add_badge("Running", GREEN)
                card.set_accent("green")
            if entry.is_default:
                card.add_badge("Default", BLUE)
                if not entry.is_running:
                    card.set_accent("blue")
            if entry.flavor != "kernel":
                card.add_badge(entry.flavor.removeprefix("kernel-"), PEACH)
            if index == 0:
                card.add_badge("Newest", SURFACE1)
            pkgs = ", ".join(p.rsplit("-", 2)[0] for p in entry.packages) or entry.package_name
            card.set_meta(f"Installed {entry.install_date}   ·   {pkgs}")

            default_btn = card.add_button("Set as default")
            default_btn.clicked.connect(lambda _c=False, e=entry: self._set_default(e))
            remove_btn = card.add_button("Remove", danger=True)
            remove_btn.clicked.connect(lambda _c=False, e=entry: self._remove(e))
            self.track(default_btn, remove_btn)

            if entry.is_default:
                self.lock(default_btn, "Already the default boot entry")
            reason = kernels.removal_block_reason(entry, report)
            if reason:
                self.lock(remove_btn, reason)

            layout.insertWidget(layout.count() - 1, card)
            self._cards.append(card)

        if not report.kernels:
            empty = ActionCard("No kernels found",
                               "rpm reported no kernel-core packages – is this a container?")
            layout.insertWidget(0, empty)
            self._cards.append(empty)

    # ================================================================== actions
    def _set_default(self, entry: KernelEntry) -> None:
        self.run_task(
            f"Setting default kernel {entry.version}",
            kernels.cmd_set_default_kernel(entry.version),
            use_pkexec=True, scope=SCOPE_KERNELS,
            success_message=f"{entry.version} will boot by default",
            confirm=f"Boot <b>{escape(entry.version)}</b> by default from now on?",
        )

    def _remove(self, entry: KernelEntry) -> None:
        report = self._report
        if report is None:
            return
        reason = kernels.removal_block_reason(entry, report)
        if reason:
            self.set_status(reason, level="warning")
            return
        pkgs = "<br>".join(f"• <code>{escape(p)}</code>" for p in entry.packages) or escape(
            entry.package_name)
        default_note = ("<br><br><b>This is the default boot entry.</b> Set another kernel as "
                        "default first, or GRUB falls back to the first menu entry."
                        if entry.is_default else "")
        self.run_task(
            f"Removing kernel {entry.version}",
            kernels.cmd_remove_kernel_entry(entry),
            use_pkexec=True, scope=SCOPE_KERNELS,
            success_message=f"Kernel {entry.version} removed",
            confirm=f"Remove kernel <b>{escape(entry.version)}</b> and its modules?<br><br>"
                    f"{pkgs}{default_note}",
            on_done=lambda ok: ok and self.system_changed.emit(SCOPE_PACKAGES),
        )

    @Slot()
    def _upgrade(self) -> None:
        self.run_task(
            "Installing latest kernel", kernels.cmd_install_latest_kernel(), use_pkexec=True,
            scope=SCOPE_KERNELS, success_message="Kernel packages up to date – reboot to use "
                                                 "a new kernel",
            on_done=lambda ok: ok and self.system_changed.emit(SCOPE_PACKAGES),
        )

    @Slot()
    def _update_grub(self) -> None:
        self.run_task(
            "Updating GRUB configuration", maintenance.cmd_update_grub(), use_pkexec=True,
            success_message="GRUB configuration updated",
            confirm="Regenerate /boot/grub2/grub.cfg with grub2-mkconfig?",
        )
