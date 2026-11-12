from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

_SIZE_RE = re.compile(r"^\s*([\d.,]+)\s*([kKMGT]?i?B|bytes?)?\s*$")
_UNITS = {
    "": 1, "b": 1, "byte": 1, "bytes": 1,
    # flatpak uses GLib's g_format_size → SI (1000-based) units
    "kb": 1000, "mb": 1000**2, "gb": 1000**3, "tb": 1000**4,
    "kib": 1024, "mib": 1024**2, "gib": 1024**3, "tib": 1024**4,
}


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

    @property
    def size_bytes(self) -> int:
        return parse_size(self.size)

    @property
    def ref(self) -> str:
        """``ID/ARCH/BRANCH`` – unambiguous even with several branches/arches installed."""
        return f"{self.application}/{self.arch}/{self.branch}"


def parse_size(text: str) -> int:
    """'1.2 GB' → 1200000000. Handles both ',' and '.' decimals (localized output)."""
    match = _SIZE_RE.match(text.replace("\xa0", " ")) if text else None
    if not match:
        return 0
    number = match.group(1).replace(",", ".")
    unit = (match.group(2) or "").lower()
    try:
        return int(float(number) * _UNITS.get(unit, 1))
    except ValueError:
        return 0


def list_installed_apps() -> list[FlatpakEntry]:
    return _list("--app")

def list_installed_runtimes() -> list[FlatpakEntry]:
    return _list("--runtime")

def _list(kind: str) -> list[FlatpakEntry]:
    result = runner.run(["flatpak", "list", kind, "--columns=name,application,version,branch,arch,origin,installation,size"], timeout=25)
    entries: list[FlatpakEntry] = []
    is_runtime = kind == "--runtime"
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name\t"): continue
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


def format_bytes(num: int) -> str:
    size = float(num)
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1000 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1000
    return ""


def _scope_flag(installation: str) -> list[str]:
    if installation == "user":
        return ["--user"]
    if installation == "system":
        return ["--system"]
    return []  # custom installations: let flatpak resolve


def cmd_uninstall(
    app_or_runtime_id: str, *, branch: str = "", arch: str = "", installation: str = ""
) -> list[str]:
    target = app_or_runtime_id
    if branch or arch:
        target = f"{app_or_runtime_id}/{arch}/{branch}"
    return ["flatpak", "uninstall", "-y", "--noninteractive", *_scope_flag(installation), target]

def cmd_uninstall_entry(entry: FlatpakEntry) -> list[str]:
    return cmd_uninstall(
        entry.application, branch=entry.branch, arch=entry.arch, installation=entry.installation
    )

def cmd_uninstall_unused() -> list[str]:
    return ["flatpak", "uninstall", "--unused", "-y", "--noninteractive"]

def cmd_repair(installation: str = "system") -> list[str]:
    """``flatpak repair`` – the system installation needs root (run with pkexec)."""
    return ["flatpak", "repair", *_scope_flag(installation)]

def cmd_update_all() -> list[str]:
    return ["flatpak", "update", "-y", "--noninteractive"]
