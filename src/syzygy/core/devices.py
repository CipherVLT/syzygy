from __future__ import annotations
import json, logging, re
from dataclasses import dataclass
from typing import Optional
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

@dataclass(slots=True, frozen=True)
class FwupdDevice:
    name: str
    device_id: str
    current_version: str = ""
    available_version: str = ""
    has_update: bool = False
    summary: str = ""

def list_fwupd_devices() -> list[FwupdDevice]:
    result = runner.run(["fwupdmgr", "get-devices", "--json"], timeout=30)
    if result.stdout.strip().startswith("{") or result.stdout.strip().startswith("["):
        return _parse_fwupd_json(result.stdout)
    return _parse_fwupd_text(result.stdout)

def list_fwupd_updates() -> list[FwupdDevice]:
    result = runner.run(["fwupdmgr", "get-updates"], timeout=30)
    return [FwupdDevice(name=d.name, device_id=d.device_id, current_version=d.current_version,
                        available_version=d.available_version or "newer", has_update=True, summary=d.summary)
            for d in _parse_fwupd_text(result.stdout)]

def _parse_fwupd_json(raw: str) -> list[FwupdDevice]:
    devices: list[FwupdDevice] = []
    try:
        data = json.loads(raw)
        items = data if isinstance(data, list) else data.get("Devices", data.get("devices", []))
        for item in items:
            name = item.get("Name") or item.get("name") or "Unknown device"
            device_id = item.get("DeviceId") or item.get("device_id") or ""
            version = item.get("Version") or item.get("version") or ""
            releases = item.get("Releases") or item.get("releases") or []
            available, has_update = "", False
            if releases:
                available = releases[0].get("Version") or releases[0].get("version") or ""
                has_update = bool(available and available != version)
            devices.append(FwupdDevice(name=name, device_id=device_id, current_version=version,
                                       available_version=available, has_update=has_update))
    except Exception as exc:
        logger.warning("Failed to parse fwupd JSON: %s", exc)
    return devices

def _parse_fwupd_text(raw: str) -> list[FwupdDevice]:
    devices: list[FwupdDevice] = []
    current: dict[str, str] = {}
    for line in raw.splitlines():
        line = line.rstrip()
        if not line:
            if current.get("name"):
                devices.append(FwupdDevice(name=current.get("name","Unknown"), device_id=current.get("device_id",""),
                    current_version=current.get("version",""), available_version=current.get("available",""),
                    has_update=bool(current.get("available")), summary=current.get("summary","")))
                current = {}
            continue
        if ":" in line:
            key, _, value = line.partition(":")
            key, value = key.strip().lower(), value.strip()
            if key in ("name", "device name"): current["name"] = value
            elif key in ("device id", "deviceid", "guid"): current["device_id"] = value
            elif key == "version": current["version"] = value
            elif key in ("update version", "new version", "available"): current["available"] = value
            elif key == "summary": current["summary"] = value
    if current.get("name"):
        devices.append(FwupdDevice(name=current.get("name","Unknown"), device_id=current.get("device_id",""),
            current_version=current.get("version",""), available_version=current.get("available",""),
            has_update=bool(current.get("available")), summary=current.get("summary","")))
    return devices

def get_pci_summary() -> str:
    result = runner.run(["lspci", "-nnk"], timeout=10)
    if not result.stdout: return "Unable to query PCI devices"
    interesting, capture, buffer = [], False, []
    for line in result.stdout.splitlines():
        if re.match(r"^[0-9a-f]{2}:[0-9a-f]{2}\.[0-9a-f]", line):
            if buffer and capture: interesting.append("\n".join(buffer))
            buffer = [line]
            capture = any(k in line for k in ("VGA compatible controller","3D controller","Display controller","Network controller","Ethernet controller","Wireless"))
        else:
            if capture: buffer.append(line)
    if buffer and capture: interesting.append("\n".join(buffer))
    return "\n\n".join(interesting) if interesting else result.stdout[:2000]

def cmd_fwupd_refresh() -> list[str]:
    return ["fwupdmgr", "refresh"]

def cmd_fwupd_update() -> list[str]:
    return ["fwupdmgr", "update", "-y"]

def cmd_fwupd_update_device(device_id: str) -> list[str]:
    return ["fwupdmgr", "update", "-y", device_id]
