"""System maintenance commands and dashboard metrics – pure logic, no Qt."""

from __future__ import annotations

import logging
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

from syzygy.core.installed import human_size
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

DNF_CACHE_DIRS = (Path("/var/cache/libdnf5"), Path("/var/cache/dnf"))
# Fedora 34+ (BIOS and UEFI): the real config lives here; /boot/efi/EFI/fedora/grub.cfg is a
# stub that must NOT be overwritten.
GRUB_CFG = Path("/boot/grub2/grub.cfg")


def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


# ---------------------------------------------------------------------- commands
def cmd_autoremove() -> list[str]:
    return [_dnf(), "autoremove", "-y"]

def cmd_clean_cache() -> list[str]:
    return [_dnf(), "clean", "all"]

def cmd_rebuild_rpm_db() -> list[str]:
    return ["rpm", "--rebuilddb"]

def cmd_regenerate_initramfs() -> list[str]:
    return ["dracut", "-f", "--regenerate-all"]

def cmd_update_grub() -> list[str]:
    return ["grub2-mkconfig", "-o", str(GRUB_CFG)]

def cmd_dnf_check() -> list[str]:
    """Report dependency problems / duplicates in the RPM database (read-only, no root)."""
    return [_dnf(), "check"]

def cmd_vacuum_journal(keep: str = "2weeks") -> list[str]:
    return ["journalctl", f"--vacuum-time={keep}"]


# ---------------------------------------------------------------------- metrics
@dataclass(slots=True, frozen=True)
class MaintenanceStats:
    dnf_cache: str = ""
    journal: str = ""
    kernels_installed: int = 0
    # None = can't tell: /boot/grub2 is root-only (0700) on Fedora, so users can't stat it.
    grub_cfg_exists: bool | None = None


def _dir_size(path: Path) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
        for name in files:
            try:
                total += (Path(root) / name).lstat().st_size
            except OSError:
                continue
    return total


def get_dnf_cache_size() -> str:
    total = sum(_dir_size(d) for d in DNF_CACHE_DIRS if d.is_dir())
    return human_size(total) or "empty"


def get_journal_usage() -> str:
    result = runner.run(["journalctl", "--disk-usage"], timeout=15)
    match = re.search(r"take up ([\d.,]+\s*\S+)", result.stdout)
    return match.group(1) if match else ""


def grub_cfg_state(path: Path = GRUB_CFG) -> bool | None:
    try:
        return path.exists()
    except PermissionError:
        return None
    except OSError:
        return False


def get_stats() -> MaintenanceStats:
    kernels = runner.run(["rpm", "-q", "kernel-core"], timeout=10)
    count = len([ln for ln in kernels.stdout.splitlines() if ln.startswith("kernel-core")])
    return MaintenanceStats(
        dnf_cache=get_dnf_cache_size(),
        journal=get_journal_usage(),
        kernels_installed=count,
        grub_cfg_exists=grub_cfg_state(),
    )
