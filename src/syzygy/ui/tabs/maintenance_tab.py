"""Maintenance tab – dashboard of housekeeping actions, each streaming into TaskDialog."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import QProcess, Slot
from PySide6.QtWidgets import QApplication, QGridLayout, QLabel, QVBoxLayout, QWidget

from syzygy.core import flatpak, maintenance, self_update
from syzygy.core.maintenance import MaintenanceStats
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, MAUVE, PEACH, TEAL
from syzygy.ui.widgets.page import SCOPE_FLATPAK, SCOPE_PACKAGES, BasePage
from syzygy.ui.widgets.sidebar import SidebarItem, SidebarSplit, heading


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

_CATEGORY_COLORS = {"DNF": BLUE, "RPM": BLUE, "Boot": PEACH, "Logs": TEAL, "Flatpak": MAUVE,
                    "Syzygy": GREEN}
SYZYGY_KEY = "syzygy-update"


class MaintenanceTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_PACKAGES, SCOPE_FLATPAK})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Maintenance", "Housekeeping with live output", parent)
        self._cards: dict[str, ActionCard] = {}
        self._categories: dict[str, str] = {a.key: a.category for a in ACTIONS}
        self._install = self_update.get_install_info()

        self.split = SidebarSplit(sidebar_width=200)
        self.split.selected.connect(self._filter)

        content = QWidget()
        scroll, column = self.make_scroll_column()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.addWidget(scroll)
        self.grid = QGridLayout()
        self.grid.setSpacing(12)
        for action in ACTIONS:
            card = ActionCard(action.title, action.description)
            card.add_badge(action.category, _CATEGORY_COLORS.get(action.category, BLUE))
            if action.use_pkexec:
                card.add_badge("admin", PEACH)
            btn = card.add_button(action.button, primary=not action.danger,
                                  danger=action.danger)
            btn.clicked.connect(lambda _c=False, a=action: self._run(a))
            self.track(btn)
            self._cards[action.key] = card
        self._cards[SYZYGY_KEY] = self._build_update_card()
        self._categories[SYZYGY_KEY] = "Syzygy"
        column.addLayout(self.grid)
        note = QLabel("Actions marked “admin” ask for your password via polkit. Output streams "
                      "live; you can copy it from the dialog.")
        note.setObjectName("hintText")
        note.setWordWrap(True)
        column.addWidget(note)
        column.addStretch()
        self.split.add_page("grid", content)
        self.root.addWidget(self.split, stretch=1)

        categories: dict[str, int] = {}
        for category in self._categories.values():
            categories[category] = categories.get(category, 0) + 1
        self.split.set_items([
            heading("Categories"),
            SidebarItem("all", "All tasks", "grid", len(self._cards)),
            *[SidebarItem(cat, cat, "grid", count) for cat, count in categories.items()],
        ])

    @Slot(str)
    def _filter(self, key: str) -> None:
        for card in self._cards.values():
            self.grid.removeWidget(card)
            card.hide()
        visible = [k for k, cat in self._categories.items() if key == "all" or cat == key]
        for index, card_key in enumerate(visible):
            card = self._cards[card_key]
            self.grid.addWidget(card, index // 2, index % 2)
            card.show()

    # ================================================================== self update
    def _build_update_card(self) -> ActionCard:
        info = self._install
        card = ActionCard("Update Syzygy", "")
        card.add_badge("Syzygy", GREEN)
        self.update_btn = card.add_button("Update Syzygy", primary=True)
        self.update_btn.clicked.connect(self._self_update)
        self.track(self.update_btn)
        if info.mode == self_update.MODE_SYSTEM and info.updater:
            card.add_badge("admin", PEACH)
            card.set_description(f"Download the latest '{info.ref}' from GitHub and reinstall "
                                 "– no git checkout needed.")
            card.set_meta(f"Installed {info.version} in {info.prefix}")
        elif info.mode == self_update.MODE_DEV:
            card.set_description("Developer install (editable). Update with: "
                                 "git pull && ./build.sh --dev")
            card.set_meta(f"Checkout: {info.checkout}")
            self.lock(self.update_btn, "Developer installs update through git")
        else:
            card.set_description("Install system-wide with ./build.sh to enable one-click "
                                 "updates.")
            self.lock(self.update_btn, "Not a system install")
        return card

    @Slot()
    def refresh(self) -> None:
        self.set_status("Measuring cache and journal size…")
        self.run_query("stats", maintenance.get_stats, self._on_stats)
        if self._install.mode == self_update.MODE_SYSTEM:
            info = self._install
            self.run_query("latest", lambda: self_update.latest_version(info),
                           self._on_latest)

    def _on_latest(self, value: object) -> None:
        card = self._cards[SYZYGY_KEY]
        info = self._install
        if value is None:
            card.set_meta(f"Installed {info.version} · couldn't reach GitHub")
        elif value == info.version:
            card.set_meta(f"Installed {info.version} · latest release {value} "
                          "(updating still pulls the newest commits)")
        else:
            card.set_meta(f"Installed {info.version} → {value} available on GitHub")
            card.set_accent("green")

    @Slot()
    def _self_update(self) -> None:
        info = self._install
        if info.updater is None:
            return
        self.run_task(
            "Updating Syzygy", self_update.cmd_self_update(info), use_pkexec=True,
            success_message="Syzygy updated",
            confirm=f"Download the latest <b>{info.ref}</b> from GitHub and reinstall Syzygy?",
            on_done=self._offer_restart, refresh_after=False,
        )

    def _offer_restart(self, success: bool) -> None:
        if not success:
            return
        if self.confirm("Restart Syzygy",
                        "Syzygy was updated. Restart now to use the new version?"):
            QProcess.startDetached(sys.executable, ["-m", "syzygy"])
            QApplication.quit()

    def _on_stats(self, value: object) -> None:
        assert isinstance(value, MaintenanceStats)
        self._cards["clean"].set_meta(f"Current DNF cache: {value.dnf_cache}")
        if value.journal:
            self._cards["journal"].set_meta(f"Journal currently uses {value.journal}")
        self._cards["initramfs"].set_meta(f"{value.kernels_installed} kernel(s) installed")
        if value.grub_cfg_exists is False:
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
