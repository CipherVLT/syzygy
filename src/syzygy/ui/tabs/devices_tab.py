"""Devices tab – two-column layout: category sidebar + device lists, details and driver profiles."""

from __future__ import annotations

from collections import Counter
from html import escape

from PySide6.QtCore import Slot
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from syzygy.core import devices, driver_profiles
from syzygy.core.devices import (
    FirmwareReport,
    FwupdDevice,
    HardwareReport,
    PciDetails,
    PciDevice,
    UsbDevice,
)
from syzygy.core.driver_profiles import ProfileState
from syzygy.ui.widgets.action_card import ActionCard
from syzygy.ui.widgets.badge import BLUE, GREEN, PEACH, RED, SURFACE1, YELLOW
from syzygy.ui.widgets.page import SCOPE_FIRMWARE, SCOPE_PACKAGES, BasePage
from syzygy.ui.widgets.property_list import PropertyList
from syzygy.ui.widgets.sidebar import SidebarItem, SidebarSplit, heading

_VENDOR_COLORS = {"nvidia": GREEN, "amd": RED, "intel": BLUE, "other": SURFACE1}
KEY_FIRMWARE = "firmware"
KEY_GPU = "gpu"
KEY_AUDIO = "audio"
KEY_NETWORK = "network"
KEY_RAW = "raw"


class _Column(QWidget):
    """Scrollable card column used for every right-hand page."""

    def __init__(self, page: BasePage) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.scroll, self.column = page.make_scroll_column()
        self.column.addStretch()
        layout.addWidget(self.scroll)
        self._widgets: list[QWidget] = []

    def clear(self) -> None:
        for widget in self._widgets:
            self.column.removeWidget(widget)
            widget.deleteLater()
        self._widgets.clear()

    def add(self, widget: QWidget) -> QWidget:
        self.column.insertWidget(self.column.count() - 1, widget)
        self._widgets.append(widget)
        return widget


class DevicesTab(BasePage):
    WATCH_SCOPES = frozenset({SCOPE_FIRMWARE, SCOPE_PACKAGES})

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Devices", "Firmware · PCI · USB · drivers", parent)
        self._firmware: FirmwareReport | None = None
        self._hardware: HardwareReport | None = None
        self._detail_device: PciDevice | UsbDevice | None = None
        self._pci_props: PropertyList | None = None
        self._profiles_layout: QVBoxLayout | None = None

        self.metadata_btn = self.add_header_button(
            "Refresh firmware metadata", self._refresh_metadata,
            tooltip="Download the latest LVFS metadata (fwupdmgr refresh --force)",
        )
        self.update_all_btn = self.add_header_button("Update all firmware", self._update_all,
                                                     primary=True)

        self.split = SidebarSplit()
        self.split.selected.connect(self._on_selected)

        self.fw_page = _Column(self)
        self.split.add_page("firmware", self.fw_page)

        # device list ⇄ detail share one page with an inner stack
        self.devices_stack = QStackedWidget()
        self.list_page = _Column(self)
        self.detail_page = _Column(self)
        self.devices_stack.addWidget(self.list_page)
        self.devices_stack.addWidget(self.detail_page)
        self.split.add_page("devices", self.devices_stack)

        self.info_page = _Column(self)
        self.split.add_page("info", self.info_page)

        self.raw_text = QPlainTextEdit()
        self.raw_text.setReadOnly(True)
        self.raw_text.setPlaceholderText("lspci -Dnnk output…")
        self.split.add_page("raw", self.raw_text)

        self.root.addWidget(self.split, stretch=1)
        self._rebuild_sidebar()

    # ================================================================== loading
    @Slot()
    def refresh(self) -> None:
        self.set_status("Querying fwupd, PCI and USB devices…")
        self.run_query("firmware", devices.get_firmware_report, self._on_firmware)
        self.run_query("hardware", devices.get_hardware_report, self._on_hardware)

    def _on_firmware(self, value: object) -> None:
        assert isinstance(value, FirmwareReport)
        self._firmware = value
        if not value.available:
            self.lock(self.metadata_btn, "fwupd is not installed")
            self.lock(self.update_all_btn, "fwupd is not installed")
        elif value.updates:
            self.update_all_btn.setProperty("syzygyLocked", False)
            self.update_all_btn.setToolTip("")
            self.update_all_btn.setEnabled(not self.busy)
        else:
            self.lock(self.update_all_btn, "No firmware updates available")
        self._update_status()
        self._rebuild_sidebar()

    def _on_hardware(self, value: object) -> None:
        assert isinstance(value, HardwareReport)
        self._hardware = value
        self.raw_text.setPlainText(value.lspci_raw or value.pci_summary)
        self._update_status()
        self._rebuild_sidebar()

    def _update_status(self) -> None:
        parts: list[str] = []
        fw, hw = self._firmware, self._hardware
        if fw is not None:
            if not fw.available:
                parts.append("fwupd not installed")
            else:
                n = len(fw.updates)
                parts.append(f"{n} firmware update{'s' if n != 1 else ''}" if n
                             else "firmware up to date")
        if hw is not None:
            parts.append(f"{len(hw.pci)} PCI devices")
            parts.append(f"{len(hw.usb)} USB devices")
        level = "warning" if fw is not None and fw.updates else "info"
        self.set_status("   ·   ".join(parts), level=level)

    # ================================================================== sidebar
    def _rebuild_sidebar(self) -> None:
        fw_count = len(self._firmware.updates) if self._firmware else 0
        items = [
            heading("Overview"),
            SidebarItem(KEY_FIRMWARE, "Firmware updates", "firmware", fw_count or None),
            SidebarItem(KEY_GPU, "Graphics & drivers", "devices"),
        ]
        hw = self._hardware
        if hw is not None:
            pci_counts = Counter(d.category for d in hw.pci)
            if pci_counts:
                items.append(heading("PCI Devices"))
                items += [SidebarItem(f"pci:{name}", name, "devices", count)
                          for name, count in sorted(pci_counts.items())]
            usb_counts = Counter(d.class_name for d in hw.usb)
            if usb_counts:
                items.append(heading("USB Devices"))
                items += [SidebarItem(f"usb:{name}", name, "devices", count)
                          for name, count in sorted(usb_counts.items())]
        items += [
            heading("System"),
            SidebarItem(KEY_AUDIO, "Audio", "info"),
            SidebarItem(KEY_NETWORK, "Network interfaces", "info"),
            SidebarItem(KEY_RAW, "Raw lspci", "raw"),
        ]
        self.split.set_items(items)

    @Slot(str)
    def _on_selected(self, key: str) -> None:
        if key == KEY_FIRMWARE:
            self._render_firmware()
        elif key in (KEY_AUDIO, KEY_NETWORK):
            self._render_info(key)
        elif key == KEY_GPU or key.startswith(("pci:", "usb:")):
            if (self.split.reannouncing and self._detail_device is not None
                    and self.devices_stack.currentWidget() is self.detail_page):
                return  # keep an open detail view across background refreshes
            self._render_device_list(key)

    # ================================================================== firmware page
    def _render_firmware(self) -> None:
        page = self.fw_page
        page.clear()
        report = self._firmware
        if report is None:
            page.add(ActionCard("Loading…", "Asking fwupd for devices and updates."))
            return
        if not report.available:
            page.add(ActionCard("fwupd not available",
                                "Install fwupd to manage firmware: sudo dnf install fwupd"))
            return
        updatable = [d for d in report.devices if d.updatable or d.has_update]
        for device in updatable:
            page.add(self._firmware_card(device))
        if not updatable:
            page.add(ActionCard("No updatable devices",
                                "fwupd found no devices with LVFS-updatable firmware."))
        others = [d for d in report.devices if not (d.updatable or d.has_update)]
        if others:
            names = ", ".join(d.name for d in others[:12])
            more = f" and {len(others) - 12} more" if len(others) > 12 else ""
            note = QLabel(f"Not updatable through LVFS: {names}{more}")
            note.setObjectName("hintText")
            note.setWordWrap(True)
            page.add(note)

    def _firmware_card(self, device: FwupdDevice) -> ActionCard:
        card = ActionCard(device.name, device.summary)
        if device.has_update:
            card.add_badge("Update available", YELLOW)
            card.set_accent("yellow")
        else:
            card.add_badge("Up to date", GREEN)
        if device.vendor:
            card.add_badge(device.vendor, SURFACE1)
        meta = f"Current version {device.current_version or 'unknown'}"
        if device.has_update:
            meta += f"   →   {device.available_version}"
        card.set_meta(meta)
        if device.has_update and device.device_id:
            btn = card.add_button("Update", primary=True)
            btn.clicked.connect(lambda _c=False, d=device: self._update_device(d))
            self.track(btn)
        return card

    # ================================================================== device list
    def _render_device_list(self, key: str) -> None:
        self._detail_device = None
        self.devices_stack.setCurrentWidget(self.list_page)
        page = self.list_page
        page.clear()
        hw = self._hardware
        if hw is None:
            page.add(ActionCard("Loading…", "Reading PCI and USB devices."))
            return

        title = QLabel()
        title.setObjectName("sectionTitle")
        page.add(title)

        if key == KEY_GPU:
            title.setText("Graphics & drivers")
            for device in [d for d in hw.pci if d.is_gpu]:
                page.add(self._pci_card(device))
            page.add(self._secure_boot_card(hw.secure_boot))
            return
        bus, _, category = key.partition(":")
        title.setText(f"{'PCI' if bus == 'pci' else 'USB'} · {category}")
        if bus == "pci":
            for device in [d for d in hw.pci if d.category == category]:
                page.add(self._pci_card(device))
        else:
            for usb in [d for d in hw.usb if d.class_name == category]:
                page.add(self._usb_card(usb))

    def _pci_card(self, device: PciDevice) -> ActionCard:
        card = ActionCard(device.description)
        card.add_badge(f"driver: {device.driver or 'none'}", GREEN if device.driver else SURFACE1)
        if device.is_gpu:
            vendor = driver_profiles.gpu_vendor(device.vendor_id, device.description)
            card.add_badge(vendor.upper() if vendor != "other" else "GPU",
                           _VENDOR_COLORS.get(vendor, SURFACE1))
            advice = devices.gpu_driver_advice(devices.GpuInfo(
                device.slot, device.description, vendor, device.driver, device.modules))
            card.set_description(advice)
            card.set_accent("blue")
        card.set_meta(f"{device.slot}   ·   {device.vendor_id}:{device.device_id}   ·   "
                      f"{device.class_name}")
        btn = card.add_button("Details")
        btn.clicked.connect(lambda _c=False, d=device: self._show_pci_detail(d))
        return card

    def _usb_card(self, device: UsbDevice) -> ActionCard:
        card = ActionCard(device.name)
        drivers = ", ".join(device.drivers)
        card.add_badge(f"driver: {drivers or 'none'}", GREEN if drivers else SURFACE1)
        card.set_meta(f"Bus {device.bus} Device {device.devnum}   ·   "
                      f"{device.vendor_id}:{device.product_id}   ·   {device.speed}")
        btn = card.add_button("Details")
        btn.clicked.connect(lambda _c=False, d=device: self._show_usb_detail(d))
        return card

    def _secure_boot_card(self, state: bool | None) -> ActionCard:
        card = ActionCard("Secure Boot")
        if state is None:
            card.add_badge("Unknown / legacy BIOS", SURFACE1)
        elif state:
            card.add_badge("Enabled", GREEN)
            card.set_description("Only signed kernels and modules load. Out-of-tree drivers "
                                 "(akmod-nvidia, CachyOS kernel) need a MOK key enrolled.")
        else:
            card.add_badge("Disabled", PEACH)
        return card

    # ================================================================== detail view
    def _detail_header(self, title: str) -> tuple[PropertyList, QVBoxLayout]:
        page = self.detail_page
        page.clear()
        self.devices_stack.setCurrentWidget(self.detail_page)

        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(0, 0, 0, 0)
        back = QPushButton("✕  Back")
        back.clicked.connect(self._back_to_list)
        bar_layout.addWidget(back)
        bar_layout.addStretch()
        page.add(bar)

        label = QLabel(title)
        label.setObjectName("detailTitle")
        label.setWordWrap(True)
        page.add(label)

        props = PropertyList()
        page.add(props)
        extra = QWidget()
        extra_layout = QVBoxLayout(extra)
        extra_layout.setContentsMargins(0, 6, 0, 0)
        extra_layout.setSpacing(10)
        page.add(extra)
        return props, extra_layout

    @Slot()
    def _back_to_list(self) -> None:
        self._detail_device = None
        key = self.split.current_key()
        if key:
            self._render_device_list(key)

    def _show_pci_detail(self, device: PciDevice) -> None:
        self._detail_device = device
        props, extra = self._detail_header(device.description)
        self._pci_props = props
        self._profiles_layout = None
        self._pci_rows(device, None)
        self.run_query("pci-details", lambda: devices.get_pci_details(device),
                       lambda value: self._on_pci_details(device, value))
        if device.is_gpu:
            self._profiles_layout = extra
            vendor = driver_profiles.gpu_vendor(device.vendor_id, device.description)
            heading_lbl = QLabel("Available Profiles")
            heading_lbl.setObjectName("sectionTitle")
            extra.addWidget(heading_lbl)
            self.run_query("profiles", lambda: driver_profiles.profile_states(vendor),
                           self._on_profiles)

    def _pci_rows(self, device: PciDevice, details: PciDetails | None) -> None:
        if self._pci_props is None:
            return
        yes, no = "Yes", "No"
        enabled = "…" if details is None else (
            "unknown" if details.enabled is None else yes if details.enabled else no)
        rows = [
            ("Started", yes if device.driver else no),
            ("Enabled", enabled),
            ("Driver", device.driver or "none"),
            ("Driver Version", "…" if details is None else details.driver_version),
            ("Bus ID", device.slot),
            ("Vendor ID", device.vendor_id),
            ("Device ID", device.device_id),
            ("Class", f"{device.class_name} [{device.class_code}]"),
            ("Subsystem", device.subsystem),
            ("Kernel modules", device.modules),
            ("Revision", device.revision),
        ]
        if details is not None:
            rows += [("PCIe link", details.link), ("IOMMU group", details.iommu_group)]
        self._pci_props.set_rows(rows, accent_values={yes})

    def _on_pci_details(self, device: PciDevice, value: object) -> None:
        if self._detail_device is device and isinstance(value, PciDetails):
            self._pci_rows(device, value)

    def _show_usb_detail(self, device: UsbDevice) -> None:
        self._detail_device = device
        self._profiles_layout = None
        props, _extra = self._detail_header(device.name)
        props.set_rows([
            ("Started", "Yes" if device.drivers else "No"),
            ("Drivers", ", ".join(device.drivers) or "none"),
            ("Product", device.product),
            ("Manufacturer", device.manufacturer),
            ("Vendor ID", device.vendor_id),
            ("Product ID", device.product_id),
            ("Class", f"{device.class_name} [{device.class_code}]"),
            ("Bus / Device", f"{device.bus} / {device.devnum}"),
            ("Speed", device.speed),
            ("USB version", device.usb_version),
            ("sysfs", f"/sys/bus/usb/devices/{device.path}"),
        ], accent_values={"Yes"})

    def _on_profiles(self, value: object) -> None:
        layout = self._profiles_layout
        if layout is None:
            return
        states: list[ProfileState] = list(value)  # type: ignore[call-overload]
        if not states:
            note = QLabel("No driver profiles for this GPU vendor – Mesa drivers are built in.")
            note.setObjectName("hintText")
            layout.addWidget(note)
        for state in states:
            layout.addWidget(self._profile_card(state))

    def _profile_card(self, state: ProfileState) -> ActionCard:
        p = state.profile
        card = ActionCard(p.title, p.description)
        card.set_title_link_style()
        if state.installed:
            card.add_badge(f"Installed {state.installed_version}".strip(), GREEN)
            card.set_accent("green")
        lines = [f"Package: {p.package}" if p.package else "",
                 f"Repository: {p.repository}", f"License: {p.license}"]
        if state.reason:
            lines.append(f"⚠ {state.reason}")
        elif p.note:
            lines.append(p.note)
        card.set_meta("\n".join(line for line in lines if line))

        install = card.add_button("✔  Installed" if state.installed else "⬇  Install",
                                  primary=not state.installed)
        remove = card.add_button("Remove", danger=True)
        self.track(install, remove)
        if state.installed:
            self.lock(install, "Already installed")
        elif not state.available or p.install is None:
            self.lock(install, state.reason or "Not available")
        else:
            install.clicked.connect(lambda _c=False, s=state: self._install_profile(s))
        if not state.installed or p.remove is None:
            self.lock(remove, "Not installed")
        else:
            remove.clicked.connect(lambda _c=False, s=state: self._remove_profile(s))
        return card

    def _reload_detail(self, success: bool) -> None:
        device = self._detail_device
        if success and isinstance(device, PciDevice):
            self._show_pci_detail(device)

    def _install_profile(self, state: ProfileState) -> None:
        p = state.profile
        if p.install is None:
            return
        note = f"<br><br>{escape(p.note)}" if p.note else ""
        self.run_task(
            f"Installing {p.title}", p.install(), use_pkexec=True, scope=SCOPE_PACKAGES,
            success_message=f"{p.title} installed",
            confirm=f"Install <b>{escape(p.title)}</b> from {escape(p.repository)}?{note}",
            on_done=self._reload_detail, refresh_after=False,
        )

    def _remove_profile(self, state: ProfileState) -> None:
        p = state.profile
        if p.remove is None:
            return
        self.run_task(
            f"Removing {p.title}", p.remove(), use_pkexec=True, scope=SCOPE_PACKAGES,
            success_message=f"{p.title} removed",
            confirm=f"Remove <b>{escape(p.title)}</b>?<br><br>The system falls back to the "
                    "open-source driver after a reboot.",
            on_done=self._reload_detail, refresh_after=False,
        )

    # ================================================================== audio / network
    def _render_info(self, key: str) -> None:
        page = self.info_page
        page.clear()
        hw = self._hardware
        if hw is None:
            page.add(ActionCard("Loading…"))
            return
        title = QLabel("Audio" if key == KEY_AUDIO else "Network interfaces")
        title.setObjectName("sectionTitle")
        page.add(title)
        if key == KEY_AUDIO:
            server = ActionCard("Sound server", hw.audio_server or "pactl not available")
            server.add_badge("PipeWire" if "pipewire" in hw.audio_server.lower() else "Audio",
                             BLUE)
            page.add(server)
            for card_info in hw.audio_cards:
                card = ActionCard(card_info.name)
                card.add_badge(card_info.driver, SURFACE1)
                card.set_meta(f"ALSA card {card_info.index}   ·   id {card_info.card_id}")
                page.add(card)
            return
        for iface in hw.interfaces:
            card = ActionCard(iface.name)
            up = iface.state == "up"
            card.add_badge(iface.state or "unknown", GREEN if up else SURFACE1)
            card.add_badge("Wi-Fi" if iface.wireless else "Ethernet", BLUE)
            if up:
                card.set_accent("green")
            card.set_meta(f"MAC {iface.mac}   ·   driver {iface.driver or '—'}"
                          + (f"   ·   {iface.speed}" if iface.speed else ""))
            page.add(card)
        if not hw.interfaces:
            page.add(ActionCard("No physical interfaces found"))

    # ================================================================== firmware actions
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
