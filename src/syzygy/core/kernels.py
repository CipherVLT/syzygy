from __future__ import annotations
import logging, platform, shutil
from dataclasses import dataclass
from typing import Optional
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"

@dataclass(slots=True, frozen=True)
class KernelEntry:
    version: str
    package_name: str
    is_running: bool
    is_default: bool
    install_date: str = ""

def list_installed_kernels() -> list[KernelEntry]:
    result = runner.run(["rpm", "-q", "kernel-core", "--qf", "%{VERSION}-%{RELEASE}.%{ARCH}\t%{INSTALLTIME:date}\n"], timeout=20)
    if not result.stdout.strip(): return []
    running = platform.release()
    default_kernel = _get_default_kernel()
    entries: list[KernelEntry] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line: continue
        parts = line.split("\t")
        version = parts[0].strip()
        install_date = parts[1].strip() if len(parts) > 1 else ""
        is_running = running == version
        is_default = bool(default_kernel and (version in default_kernel or default_kernel.endswith(version)))
        entries.append(KernelEntry(version=version, package_name=f"kernel-core-{version}", is_running=is_running, is_default=is_default, install_date=install_date))
    entries.sort(key=lambda k: k.version, reverse=True)
    return entries

def _get_default_kernel() -> Optional[str]:
    result = runner.run(["grubby", "--default-kernel"], timeout=10)
    if result.success and result.stdout.strip(): return result.stdout.strip()
    return None

def cmd_set_default_kernel(version: str) -> list[str]:
    return ["grubby", "--set-default", f"/boot/vmlinuz-{version}"]

def cmd_remove_kernel(version: str) -> list[str]:
    return [_dnf(), "remove", "-y", f"kernel-core-{version}", f"kernel-modules-{version}", f"kernel-modules-core-{version}", f"kernel-modules-extra-{version}", f"kernel-{version}"]

def cmd_install_latest_kernel() -> list[str]:
    return [_dnf(), "upgrade", "-y", "kernel*"]
