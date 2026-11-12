"""Firmware (fwupd), PCI/GPU summary and Secure Boot state – pure logic, no Qt."""

from __future__ import annotations

import json
import logging
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

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
    return runner.run(["lspci", "-nnk"], timeout=15).stdout


def get_pci_summary() -> str:
    output = get_lspci()
    return summarize_pci(output) if output else "lspci not available (sudo dnf install pciutils)"


@dataclass(slots=True, frozen=True)
class HardwareReport:
    gpus: list[GpuInfo]
    pci_summary: str
    secure_boot: bool | None


def get_hardware_report() -> HardwareReport:
    output = get_lspci()
    return HardwareReport(
        gpus=parse_gpus(output),
        pci_summary=summarize_pci(output) if output else "lspci not available "
        "(sudo dnf install pciutils)",
        secure_boot=get_secure_boot_state(),
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
