"""Firmware (fwupd), PCI/GPU summary and Secure Boot state – pure logic, no Qt."""

from __future__ import annotations

import json
import logging
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

PCI_SYSFS = Path("/sys/bus/pci/devices")
USB_SYSFS = Path("/sys/bus/usb/devices")
NET_SYSFS = Path("/sys/class/net")
MODULE_SYSFS = Path("/sys/module")
ASOUND_CARDS = Path("/proc/asound/cards")
SECURE_BOOT_VAR = Path(
    "/sys/firmware/efi/efivars/SecureBoot-8be4df61-93ca-11d2-aa0d-00e098032b8c"
)
_PCI_SLOT_RE = re.compile(r"^[0-9a-f]{2,4}:[0-9a-f]{2}[:.][0-9a-f]", re.IGNORECASE)
_GPU_CLASSES = ("VGA compatible controller", "3D controller", "Display controller")
_NET_CLASSES = ("Network controller", "Ethernet controller", "Wireless")


@dataclass(slots=True, frozen=True)
class FwupdDevice:
    name: str
    device_id: str
    current_version: str = ""
    available_version: str = ""
    has_update: bool = False
    summary: str = ""
    vendor: str = ""
    updatable: bool = False


@dataclass(slots=True, frozen=True)
class GpuInfo:
    slot: str
    description: str
    vendor: str  # "nvidia" | "amd" | "intel" | "other"
    driver: str = ""
    modules: str = ""


@dataclass(slots=True, frozen=True)
class FirmwareReport:
    available: bool  # fwupdmgr installed
    devices: list[FwupdDevice]
    errors: tuple[str, ...] = ()

    @property
    def updates(self) -> list[FwupdDevice]:
        return [d for d in self.devices if d.has_update]


# ---------------------------------------------------------------------- fwupd
def _parse_fwupd_json(raw: str) -> list[FwupdDevice]:
    devices: list[FwupdDevice] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Failed to parse fwupd JSON: %s", exc)
        return devices
    items = data if isinstance(data, list) else data.get("Devices", data.get("devices", []))
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("Name") or item.get("name") or "Unknown device"
        version = item.get("Version") or item.get("version") or ""
        releases = item.get("Releases") or item.get("releases") or []
        flags = [str(f).lower() for f in item.get("Flags") or item.get("flags") or []]
        available = ""
        if releases and isinstance(releases[0], dict):
            available = releases[0].get("Version") or releases[0].get("version") or ""
        devices.append(FwupdDevice(
            name=name,
            device_id=item.get("DeviceId") or item.get("device_id") or "",
            current_version=version,
            available_version=available,
            has_update=bool(available and available != version),
            summary=item.get("Summary") or "",
            vendor=item.get("Vendor") or "",
            updatable="updatable" in flags,
        ))
    return devices


def list_fwupd_devices() -> list[FwupdDevice]:
    result = runner.run(["fwupdmgr", "get-devices", "--json"], timeout=60)
    return _parse_fwupd_json(result.stdout) if result.stdout.strip() else []


def list_fwupd_updates() -> list[FwupdDevice]:
    # Exit 2 means "no updates available" – not an error.
    result = runner.run(["fwupdmgr", "get-updates", "--json"], timeout=60)
    if not result.stdout.strip().startswith(("{", "[")):
        return []
    return [d for d in _parse_fwupd_json(result.stdout) if d.has_update]


def get_firmware_report() -> FirmwareReport:
    if shutil.which("fwupdmgr") is None:
        return FirmwareReport(available=False, devices=[])
    errors: list[str] = []
    devices = list_fwupd_devices()
    try:
        updates = {d.device_id: d for d in list_fwupd_updates()}
    except Exception as exc:  # noqa: BLE001
        updates, errors = {}, [str(exc)]
    merged = [updates.get(d.device_id, d) for d in devices]
    known = {d.device_id for d in devices}
    merged.extend(u for did, u in updates.items() if did not in known)
    merged.sort(key=lambda d: (not d.has_update, not d.updatable, d.name.lower()))
    return FirmwareReport(available=True, devices=merged, errors=tuple(errors))


# ---------------------------------------------------------------------- PCI / GPU
def _pci_blocks(output: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for line in output.splitlines():
        if _PCI_SLOT_RE.match(line):
            blocks.append([line])
        elif blocks and line.strip():
            blocks[-1].append(line)
    return blocks


def parse_gpus(lspci_output: str) -> list[GpuInfo]:
    gpus: list[GpuInfo] = []
    for block in _pci_blocks(lspci_output):
        head = block[0]
        if not any(cls in head for cls in _GPU_CLASSES):
            continue
        slot, _, rest = head.partition(" ")
        desc = rest.split(": ", 1)[-1]
        lower = desc.lower()
        vendor = ("nvidia" if "nvidia" in lower else "amd" if ("amd" in lower or "ati " in lower)
                  else "intel" if "intel" in lower else "other")
        driver = modules = ""
        for line in block[1:]:
            key, _, value = line.strip().partition(":")
            if key == "Kernel driver in use":
                driver = value.strip()
            elif key == "Kernel modules":
                modules = value.strip()
        gpus.append(GpuInfo(slot=slot, description=desc, vendor=vendor, driver=driver,
                            modules=modules))
    return gpus


def summarize_pci(lspci_output: str) -> str:
    keep = [
        "\n".join(block) for block in _pci_blocks(lspci_output)
        if any(cls in block[0] for cls in (*_GPU_CLASSES, *_NET_CLASSES))
    ]
    return "\n\n".join(keep) if keep else lspci_output[:4000]


def get_lspci() -> str:
    if shutil.which("lspci") is None:
        return ""
    return runner.run(["lspci", "-Dnnk"], timeout=15).stdout


def get_pci_summary() -> str:
    output = get_lspci()
    return summarize_pci(output) if output else "lspci not available (sudo dnf install pciutils)"


# ---------------------------------------------------------------------- full PCI inventory
_PCI_HEAD_RE = re.compile(r"^(\S+)\s+(.+?)\s+\[([0-9a-fA-F]{4})\]:\s+(.*)$")
_PCI_IDS_RE = re.compile(r"\[([0-9a-fA-F]{4}):([0-9a-fA-F]{4})\]")
_PCI_REV_RE = re.compile(r"\s*\(rev ([0-9a-fA-F]+)\)\s*$")


@dataclass(slots=True, frozen=True)
class PciDevice:
    slot: str  # 0000:01:00.0
    class_name: str  # "VGA compatible controller"
    class_code: str  # "0300"
    description: str  # "NVIDIA Corporation AD104 [GeForce RTX 4070]"
    vendor_id: str = ""
    device_id: str = ""
    revision: str = ""
    subsystem: str = ""
    driver: str = ""
    modules: str = ""

    @property
    def category(self) -> str:
        return self.class_name or f"PCI Class {self.class_code}"

    @property
    def is_gpu(self) -> bool:
        return self.class_code.startswith("03")


def parse_pci_devices(lspci_output: str) -> list[PciDevice]:
    """Parse ``lspci -Dnnk`` (also accepts output without -D)."""
    devices: list[PciDevice] = []
    for block in _pci_blocks(lspci_output):
        match = _PCI_HEAD_RE.match(block[0])
        if not match:
            continue
        slot, class_name, class_code, rest = match.groups()
        revision = ""
        rev = _PCI_REV_RE.search(rest)
        if rev:
            revision = rev.group(1)
            rest = rest[: rev.start()]
        vendor_id = device_id = ""
        ids = _PCI_IDS_RE.findall(rest)
        if ids:
            vendor_id, device_id = ids[-1]
            rest = rest[: rest.rfind("[" + vendor_id)].rstrip()
        driver = modules = subsystem = ""
        for line in block[1:]:
            key, _, value = line.strip().partition(":")
            value = value.strip()
            if key == "Kernel driver in use":
                driver = value
            elif key == "Kernel modules":
                modules = value
            elif key == "Subsystem":
                subsystem = _PCI_IDS_RE.sub("", value).strip()
        if slot.count(":") == 1:
            slot = f"0000:{slot}"
        devices.append(PciDevice(
            slot=slot, class_name=class_name.strip(), class_code=class_code.lower(),
            description=rest.strip(), vendor_id=vendor_id.lower(), device_id=device_id.lower(),
            revision=revision, subsystem=subsystem, driver=driver, modules=modules,
        ))
    return devices


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace").strip()
    except OSError:
        return ""


def module_version(module: str, sysfs: Path = MODULE_SYSFS) -> str:
    """Out-of-tree modules (nvidia …) expose a version; in-tree ones follow the kernel."""
    if not module:
        return ""
    version = _read(sysfs / module / "version")
    if version:
        return version
    if shutil.which("modinfo"):
        out = runner.run(["modinfo", "-F", "version", module], timeout=5).stdout.strip()
        if out:
            return out
    return f"in-kernel ({platform.release()})" if (sysfs / module).exists() else ""


@dataclass(slots=True, frozen=True)
class PciDetails:
    enabled: bool | None
    driver_version: str
    iommu_group: str
    link: str  # "16.0 GT/s PCIe x16"
    numa_node: str


def get_pci_details(device: PciDevice, sysfs: Path = PCI_SYSFS) -> PciDetails:
    base = sysfs / device.slot
    enable = _read(base / "enable")
    iommu = ""
    try:
        iommu = (base / "iommu_group").resolve().name if (base / "iommu_group").exists() else ""
    except OSError:
        iommu = ""
    speed, width = _read(base / "current_link_speed"), _read(base / "current_link_width")
    link = f"{speed} x{width}" if speed and width and width != "0" else ""
    numa = _read(base / "numa_node")
    return PciDetails(
        enabled=None if enable == "" else enable == "1",
        driver_version=module_version(device.driver),
        iommu_group=iommu,
        link=link,
        numa_node="" if numa in ("", "-1") else numa,
    )


# ---------------------------------------------------------------------- USB (sysfs, no tools)
USB_CLASSES = {
    "01": "Audio", "02": "Communications", "03": "HID (Human Interface Device)",
    "05": "Physical", "06": "Imaging", "07": "Printer", "08": "Mass Storage", "09": "Hub",
    "0a": "CDC Data", "0b": "Smart Card", "0d": "Content Security", "0e": "Video",
    "0f": "Personal Healthcare", "10": "Audio/Video", "11": "Billboard", "dc": "Diagnostic",
    "e0": "Wireless Controller", "ef": "Miscellaneous", "fe": "Application Specific",
    "ff": "Vendor Specific",
}


@dataclass(slots=True, frozen=True)
class UsbDevice:
    path: str  # sysfs name, e.g. "1-4.2"
    bus: str
    devnum: str
    vendor_id: str
    product_id: str
    manufacturer: str
    product: str
    class_code: str
    speed: str = ""
    usb_version: str = ""
    drivers: tuple[str, ...] = field(default_factory=tuple)

    @property
    def class_name(self) -> str:
        return USB_CLASSES.get(self.class_code, f"USB Class {self.class_code.upper()}")

    @property
    def name(self) -> str:
        label = " ".join(p for p in (self.manufacturer, self.product) if p)
        return label or f"USB device {self.vendor_id}:{self.product_id}"


def list_usb_devices(sysfs: Path = USB_SYSFS) -> list[UsbDevice]:
    if not sysfs.is_dir():
        return []
    devices: list[UsbDevice] = []
    for entry in sorted(sysfs.iterdir(), key=lambda p: p.name):
        name = entry.name
        if ":" in name or name.startswith("usb"):
            continue  # interfaces and root hubs
        vendor = _read(entry / "idVendor").lower()
        if not vendor:
            continue
        interfaces = sorted(sysfs.glob(f"{name}:*"))
        iface_classes = [_read(i / "bInterfaceClass").lower() for i in interfaces]
        drivers = tuple(sorted({
            (i / "driver").resolve().name for i in interfaces if (i / "driver").exists()
        }))
        dev_class = _read(entry / "bDeviceClass").lower()
        if dev_class in ("", "00", "ef"):
            useful = [c for c in iface_classes if c and c != "09"]
            dev_class = useful[0] if useful else (iface_classes[0] if iface_classes else "00")
        speed = _read(entry / "speed")
        devices.append(UsbDevice(
            path=name,
            bus=_read(entry / "busnum"),
            devnum=_read(entry / "devnum"),
            vendor_id=vendor,
            product_id=_read(entry / "idProduct").lower(),
            manufacturer=_read(entry / "manufacturer"),
            product=_read(entry / "product"),
            class_code=dev_class,
            speed=f"{speed} Mb/s" if speed else "",
            usb_version=_read(entry / "version"),
            drivers=drivers,
        ))
    return devices


# ---------------------------------------------------------------------- audio / network
@dataclass(slots=True, frozen=True)
class AudioCard:
    index: str
    card_id: str
    driver: str
    name: str


def parse_asound_cards(text: str) -> list[AudioCard]:
    cards: list[AudioCard] = []
    for line in text.splitlines():
        match = re.match(r"^\s*(\d+)\s+\[([^\]]+)\]:\s*(\S+)\s+-\s+(.*)$", line)
        if match:
            index, card_id, driver, name = match.groups()
            cards.append(AudioCard(index, card_id.strip(), driver, name.strip()))
    return cards


def get_audio_server() -> str:
    if shutil.which("pactl") is None:
        return ""
    for line in runner.run(["pactl", "info"], timeout=5).stdout.splitlines():
        if line.startswith("Server Name:"):
            return line.partition(":")[2].strip()
    return ""


@dataclass(slots=True, frozen=True)
class NetInterface:
    name: str
    mac: str
    state: str
    driver: str
    wireless: bool
    speed: str = ""


def list_net_interfaces(sysfs: Path = NET_SYSFS) -> list[NetInterface]:
    if not sysfs.is_dir():
        return []
    result: list[NetInterface] = []
    for entry in sorted(sysfs.iterdir(), key=lambda p: p.name):
        if entry.name == "lo" or not (entry / "device").exists():
            continue  # skip loopback and virtual interfaces (bridges, tun, veth…)
        driver_link = entry / "device" / "driver"
        speed = _read(entry / "speed")
        result.append(NetInterface(
            name=entry.name,
            mac=_read(entry / "address"),
            state=_read(entry / "operstate"),
            driver=driver_link.resolve().name if driver_link.exists() else "",
            wireless=(entry / "wireless").exists() or (entry / "phy80211").exists(),
            speed=f"{speed} Mb/s" if speed and not speed.startswith("-") else "",
        ))
    return result


@dataclass(slots=True, frozen=True)
class HardwareReport:
    gpus: list[GpuInfo]
    pci_summary: str
    secure_boot: bool | None
    pci: list[PciDevice] = field(default_factory=list)
    usb: list[UsbDevice] = field(default_factory=list)
    audio_cards: list[AudioCard] = field(default_factory=list)
    audio_server: str = ""
    interfaces: list[NetInterface] = field(default_factory=list)
    lspci_raw: str = ""


def get_hardware_report() -> HardwareReport:
    output = get_lspci()
    return HardwareReport(
        gpus=parse_gpus(output),
        pci_summary=summarize_pci(output) if output else "lspci not available "
        "(sudo dnf install pciutils)",
        secure_boot=get_secure_boot_state(),
        pci=parse_pci_devices(output),
        usb=list_usb_devices(),
        audio_cards=parse_asound_cards(_read(ASOUND_CARDS)),
        audio_server=get_audio_server(),
        interfaces=list_net_interfaces(),
        lspci_raw=output,
    )


def gpu_driver_advice(gpu: GpuInfo) -> str:
    if gpu.vendor == "nvidia":
        if gpu.driver == "nvidia":
            return "Proprietary NVIDIA driver active."
        if gpu.driver == "nouveau":
            return ("Using the open-source nouveau driver. For gaming/CUDA install the "
                    "proprietary driver (RPM Fusion akmod-nvidia, or NVIDIA's official .run "
                    "installer – planned).")
        return "No NVIDIA kernel driver bound."
    if gpu.vendor == "amd":
        return "amdgpu (Mesa) is the right driver." if gpu.driver == "amdgpu" else ""
    if gpu.vendor == "intel":
        return "Intel graphics use Mesa (i915/xe) – nothing to install."
    return ""


# ---------------------------------------------------------------------- Secure Boot
def get_secure_boot_state() -> bool | None:
    """True/False when known, None on legacy BIOS or when it can't be determined."""
    try:
        data = SECURE_BOOT_VAR.read_bytes()
        if len(data) >= 5:
            return data[4] == 1  # 4 bytes of attributes, then the value
    except OSError:
        pass
    if shutil.which("mokutil"):
        out = runner.run(["mokutil", "--sb-state"], timeout=5).stdout.lower()
        if "enabled" in out:
            return True
        if "disabled" in out:
            return False
    return None


# ---------------------------------------------------------------------- commands
# fwupd authorizes through its own polkit policy (daemon side) → no pkexec needed.
# --no-reboot-check / --no-unreported-check avoid interactive prompts (no TTY in TaskDialog).
_FWUPD_NONINTERACTIVE = ["--no-unreported-check", "--no-reboot-check"]


def cmd_fwupd_refresh() -> list[str]:
    return ["fwupdmgr", "refresh", "--force"]

def cmd_fwupd_update() -> list[str]:
    return ["fwupdmgr", "update", "-y", *_FWUPD_NONINTERACTIVE]

def cmd_fwupd_update_device(device_id: str) -> list[str]:
    return ["fwupdmgr", "update", "-y", *_FWUPD_NONINTERACTIVE, device_id]
