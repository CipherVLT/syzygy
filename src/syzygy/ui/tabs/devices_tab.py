"""Devices tab – fwupd firmware updates and a GPU / PCI hardware summary."""

from __future__ import annotations

from html import escape

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from syzygy.core import devices
from syzygy.core.devices import FirmwareReport, FwupdDevice, HardwareReport
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, PEACH, RED, SURFACE1, YELLOW
from syzygy.ui.widgets.page import SCOPE_FIRMWARE, BasePage

_VENDOR_COLORS = {"nvidia": GREEN, "amd": RED, "intel": BLUE, "other": SURFACE1}


class DevicesTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_FIRMWARE})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Devices", "Firmware (fwupd) · GPUs · PCI", parent)
        self._firmware: FirmwareReport | None = None
        self._fw_cards: list[QWidget] = []
        self._hw_cards: list[QWidget] = []

        self.metadata_btn = self.add_header_button(
            "Refresh firmware metadata", self._refresh_metadata,
            tooltip="Download the latest LVFS metadata (fwupdmgr refresh --force)",
        )
        self.update_all_btn = self.add_header_button("Update all firmware", self._update_all,
                                                     primary=True)

        self.tabs = QTabWidget()
        self.tabs.setObjectName("subTabs")

        # ---- firmware page
        fw_page = QWidget()
        fw_layout = QVBoxLayout(fw_page)
        fw_layout.setContentsMargins(0, 8, 0, 0)
        row = QHBoxLayout()
        self.show_all = QCheckBox("Show non-updatable devices")
        self.show_all.toggled.connect(lambda _c: self._render_firmware())
        row.addWidget(self.show_all)
        row.addStretch()
        fw_layout.addLayout(row)
        fw_scroll, self.fw_column = self.make_scroll_column()
        self.fw_column.addStretch()
        fw_layout.addWidget(fw_scroll, stretch=1)
        self.tabs.addTab(fw_page, "Firmware")

        # ---- hardware page
        hw_page = QWidget()
        hw_layout = QVBoxLayout(hw_page)
        hw_layout.setContentsMargins(0, 8, 0, 0)
        self.hw_column = QVBoxLayout()
        self.hw_column.setSpacing(10)
        hw_layout.addLayout(self.hw_column)
        self.pci_text = QPlainTextEdit()
        self.pci_text.setReadOnly(True)
        self.pci_text.setPlaceholderText("lspci -nnk output…")
        hw_layout.addWidget(self.pci_text, stretch=1)
        self.tabs.addTab(hw_page, "Hardware")

        self.root.addWidget(self.tabs, stretch=1)
        self.track(self.show_all)

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Querying fwupd and PCI devices…")
        self.run_query("firmware", devices.get_firmware_report, self._on_firmware)
        self.run_query("hardware", devices.get_hardware_report, self._on_hardware)

    def _on_firmware(self, value: object) -> None:
        assert isinstance(value, FirmwareReport)
        self._firmware = value
        self._render_firmware()
        if not value.available:
            self.set_status("fwupd is not installed (sudo dnf install fwupd).", level="warning")
            self.lock(self.metadata_btn, "fwupd is not installed")
            self.lock(self.update_all_btn, "fwupd is not installed")
            return
        count = len(value.updates)
        text = (f"{count} firmware update{'s' if count != 1 else ''} available" if count
                else "✔ All firmware is up to date")
        self.set_status(text + "".join(f"   ·   ⚠ {e}" for e in value.errors),
                        level="warning" if count else "info")
        if count:
            self.update_all_btn.setProperty("syzygyLocked", False)
            self.update_all_btn.setToolTip("")
            self.update_all_btn.setEnabled(not self.busy)
        else:
            self.lock(self.update_all_btn, "No firmware updates available")

    def _clear(self, cards: list[QWidget], layout: QVBoxLayout) -> None:
        for card in cards:
            layout.removeWidget(card)
            card.deleteLater()
        cards.clear()

    def _render_firmware(self) -> None:
        self._clear(self._fw_cards, self.fw_column)
        report = self._firmware
        if report is None:
            return
        shown = [d for d in report.devices
                 if self.show_all.isChecked() or d.updatable or d.has_update]
        for device in shown:
            card = self._firmware_card(device)
            self.fw_column.insertWidget(self.fw_column.count() - 1, card)
            self._fw_cards.append(card)
        if not shown:
            card = ActionCard(
                "No updatable devices" if report.available else "fwupd not available",
                "fwupd found no devices with LVFS-updatable firmware. Tick “Show non-updatable "
                "devices” to list everything fwupd knows about." if report.available else
                "Install fwupd to manage firmware: sudo dnf install fwupd",
            )
            self.fw_column.insertWidget(0, card)
            self._fw_cards.append(card)

    def _firmware_card(self, device: FwupdDevice) -> ActionCard:
        card = ActionCard(device.name, device.summary)
        if device.has_update:
            card.add_badge("Update available", YELLOW)
        elif device.updatable:
            card.add_badge("Up to date", GREEN)
        if device.vendor:
            card.add_badge(device.vendor, SURFACE1)
        version = device.current_version or "unknown"
        meta = f"Current version {version}"
        if device.has_update:
            meta += f"   →   {device.available_version}"
        card.set_meta(meta)
        if device.has_update and device.device_id:
            btn = card.add_button("Update", primary=True)
            btn.clicked.connect(lambda _c=False, d=device: self._update_device(d))
            self.track(btn)
        return card

    def _on_hardware(self, value: object) -> None:
        assert isinstance(value, HardwareReport)
        self._clear(self._hw_cards, self.hw_column)
        for gpu in value.gpus:
            card = ActionCard(gpu.description)
            card.add_badge(gpu.vendor.upper() if gpu.vendor != "other" else "GPU",
                           _VENDOR_COLORS.get(gpu.vendor, SURFACE1))
            card.add_badge(f"driver: {gpu.driver or 'none'}",
                           GREEN if gpu.driver else RED)
            card.set_description(devices.gpu_driver_advice(gpu))
            card.set_meta(f"{gpu.slot}   ·   modules: {gpu.modules or '—'}")
            self.hw_column.addWidget(card)
            self._hw_cards.append(card)

        sb = ActionCard("Secure Boot")
        if value.secure_boot is None:
            sb.add_badge("Unknown / legacy BIOS", SURFACE1)
        elif value.secure_boot:
            sb.add_badge("Enabled", GREEN)
            sb.set_description("Only signed kernels and modules load. Out-of-tree drivers "
                               "(akmod-nvidia, CachyOS kernel) need a MOK key enrolled.")
        else:
            sb.add_badge("Disabled", PEACH)
        self.hw_column.addWidget(sb)
        self._hw_cards.append(sb)
        self.pci_text.setPlainText(value.pci_summary)

    # ================================================================== actions
    # fwupd authorizes via its daemon's polkit policy, so these run without pkexec.
    @Slot()
    def _refresh_metadata(self) -> None:
        self.run_task("Refreshing firmware metadata", devices.cmd_fwupd_refresh(),
                      use_pkexec=False, success_message="Firmware metadata refreshed")

    @Slot()
    def _update_all(self) -> None:
        count = len(self._firmware.updates) if self._firmware else 0
        self.run_task(
            "Updating firmware", devices.cmd_fwupd_update(), use_pkexec=False,
            scope=SCOPE_FIRMWARE, success_message="Firmware updated – reboot if requested",
            confirm=f"Install <b>{count}</b> firmware update(s)?<br><br>Keep laptops on AC "
                    "power. Some updates are applied during the next reboot.",
        )

    def _update_device(self, device: FwupdDevice) -> None:
        self.run_task(
            f"Updating {device.name}", devices.cmd_fwupd_update_device(device.device_id),
            use_pkexec=False, scope=SCOPE_FIRMWARE,
            success_message=f"{device.name} updated – reboot if requested",
            confirm=f"Update firmware of <b>{escape(device.name)}</b> from "
                    f"{escape(device.current_version)} to "
                    f"{escape(device.available_version)}?<br><br>Keep laptops on AC power.",
        )

