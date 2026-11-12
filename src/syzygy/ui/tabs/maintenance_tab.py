"""Maintenance tab – dashboard of housekeeping actions, each streaming into TaskDialog."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QGridLayout, QLabel, QWidget

from syzygy.core import flatpak, maintenance
from syzygy.core.maintenance import MaintenanceStats
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, MAUVE, PEACH, TEAL
from syzygy.ui.widgets.page import SCOPE_FLATPAK, SCOPE_PACKAGES, BasePage


@dataclass(frozen=True)
class MaintenanceAction:
    key: str
    title: str
    description: str
    button: str
    command: Callable[[], list[str]]
    use_pkexec: bool
    category: str
    confirm: str | None = None
    scope: str | None = None
    danger: bool = False


ACTIONS: tuple[MaintenanceAction, ...] = (
    MaintenanceAction(
        "autoremove", "Remove unused packages",
        "Uninstall dependencies that nothing needs any more (dnf autoremove).",
        "Autoremove", maintenance.cmd_autoremove, True, "DNF",
        confirm="Remove all packages DNF considers unneeded?<br><br>Review the list in the "
                "output window – packages you rely on but never installed explicitly can show "
                "up here.",
        scope=SCOPE_PACKAGES,
    ),
    MaintenanceAction(
        "clean", "Clean package cache",
        "Delete downloaded packages and cached metadata. The next DNF run re-downloads "
        "metadata.",
        "Clean cache", maintenance.cmd_clean_cache, True, "DNF",
    ),
    MaintenanceAction(
        "check", "Check package database",
        "Look for broken dependencies, duplicates and obsoleted packages (read-only).",
        "Run check", maintenance.cmd_dnf_check, False, "DNF",
    ),
    MaintenanceAction(
        "rpmdb", "Rebuild RPM database",
        "Fixes 'rpmdb open failed' and similar corruption errors.",
        "Rebuild", maintenance.cmd_rebuild_rpm_db, True, "RPM",
        confirm="Rebuild the RPM database?<br><br>Don't run other package operations until "
                "it finishes.",
    ),
    MaintenanceAction(
        "initramfs", "Regenerate initramfs",
        "Rebuild the boot images for every installed kernel with dracut – after driver, "
        "LUKS or plymouth changes.",
        "Regenerate", maintenance.cmd_regenerate_initramfs, True, "Boot",
        confirm="Regenerate the initramfs for all installed kernels?<br><br>This takes a few "
                "minutes; don't power off while it runs.",
    ),
    MaintenanceAction(
        "grub", "Update GRUB configuration",
        "Regenerate /boot/grub2/grub.cfg (correct path for BIOS and UEFI on Fedora 34+).",
        "Update GRUB", maintenance.cmd_update_grub, True, "Boot",
        confirm="Regenerate /boot/grub2/grub.cfg with grub2-mkconfig?",
    ),
    MaintenanceAction(
        "journal", "Trim system journal",
        "Delete journal entries older than two weeks.",
        "Vacuum", maintenance.cmd_vacuum_journal, True, "Logs",
    ),
    MaintenanceAction(
        "flatpak-unused", "Remove unused Flatpak runtimes",
        "Uninstall runtimes and extensions no installed app uses any more.",
        "Clean up", flatpak.cmd_uninstall_unused, False, "Flatpak", scope=SCOPE_FLATPAK,
    ),
    MaintenanceAction(
        "flatpak-repair", "Repair Flatpak installation",
        "Verify the system Flatpak installation and re-download damaged objects.",
        "Repair", lambda: flatpak.cmd_repair("system"), True, "Flatpak", scope=SCOPE_FLATPAK,
    ),
)

_CATEGORY_COLORS = {"DNF": BLUE, "RPM": BLUE, "Boot": PEACH, "Logs": TEAL, "Flatpak": MAUVE}


class MaintenanceTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_PACKAGES, SCOPE_FLATPAK})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Maintenance", "Housekeeping with live output", parent)
        self._cards: dict[str, ActionCard] = {}

        scroll, column = self.make_scroll_column()
        grid = QGridLayout()
        grid.setSpacing(10)
        for index, action in enumerate(ACTIONS):
            card = ActionCard(action.title, action.description)
            card.add_badge(action.category, _CATEGORY_COLORS.get(action.category, BLUE))
            if action.use_pkexec:
                card.add_badge("admin", PEACH)
            btn = card.add_button(action.button, primary=not action.danger,
                                  danger=action.danger)
            btn.clicked.connect(lambda _c=False, a=action: self._run(a))
            self.track(btn)
            self._cards[action.key] = card
            grid.addWidget(card, index // 2, index % 2)
        column.addLayout(grid)
        note = QLabel("Actions marked “admin” ask for your password via polkit. Output streams "
                      "live; you can copy it from the dialog.")
        note.setObjectName("hintText")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addStretch()
        self.root.addWidget(scroll, stretch=1)

    @Slot()
    def refresh(self) -> None:
        self.set_status("Measuring cache and journal size…")
        self.run_query("stats", maintenance.get_stats, self._on_stats)

    def _on_stats(self, value: object) -> None:
        assert isinstance(value, MaintenanceStats)
        self._cards["clean"].set_meta(f"Current DNF cache: {value.dnf_cache}")
        if value.journal:
            self._cards["journal"].set_meta(f"Journal currently uses {value.journal}")
        self._cards["initramfs"].set_meta(f"{value.kernels_installed} kernel(s) installed")
        if not value.grub_cfg_exists:
            self._cards["grub"].set_meta("⚠ /boot/grub2/grub.cfg not found – is this a "
                                         "systemd-boot system?")
        parts = [f"DNF cache {value.dnf_cache}"]
        if value.journal:
            parts.append(f"journal {value.journal}")
        parts.append(f"{value.kernels_installed} kernels")
        self.set_status("   ·   ".join(parts))

    def _run(self, action: MaintenanceAction) -> None:
        self.run_task(
            action.title,
            action.command(),
            use_pkexec=action.use_pkexec,
            confirm=action.confirm,
            scope=action.scope,
            success_message=f"{action.title} – done",
            failure_message=f"{action.title} – failed",
        )
