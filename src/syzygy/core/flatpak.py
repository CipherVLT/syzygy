from __future__ import annotations
import logging, re
from dataclasses import dataclass
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

@dataclass(slots=True, frozen=True)
class FlatpakEntry:
    name: str
    application: str
    version: str = ""
    branch: str = "stable"
    arch: str = ""
    origin: str = ""
    installation: str = "system"
    size: str = ""
    is_runtime: bool = False

def list_installed_apps() -> list[FlatpakEntry]:
    return _list("--app")

def list_installed_runtimes() -> list[FlatpakEntry]:
    return _list("--runtime")

def _list(kind: str) -> list[FlatpakEntry]:
    result = runner.run(["flatpak", "list", kind, "--columns=name,application,version,branch,arch,origin,installation,size"], timeout=25)
    entries: list[FlatpakEntry] = []
    is_runtime = kind == "--runtime"
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name"): continue
        parts = line.split("\t")
        if len(parts) < 2: continue
        entries.append(FlatpakEntry(
            name=parts[0].strip(), application=parts[1].strip() if len(parts)>1 else "",
            version=parts[2].strip() if len(parts)>2 else "", branch=parts[3].strip() if len(parts)>3 else "stable",
            arch=parts[4].strip() if len(parts)>4 else "", origin=parts[5].strip() if len(parts)>5 else "",
            installation=parts[6].strip() if len(parts)>6 else "system", size=parts[7].strip() if len(parts)>7 else "",
            is_runtime=is_runtime,
        ))
    return entries

def cmd_uninstall(app_or_runtime_id: str) -> list[str]:
    return ["flatpak", "uninstall", "-y", app_or_runtime_id]

def cmd_uninstall_unused() -> list[str]:
    return ["flatpak", "uninstall", "--unused", "-y"]

def cmd_repair() -> list[str]:
    return ["flatpak", "repair"]

def cmd_update_all() -> list[str]:
    return ["flatpak", "update", "-y"]
