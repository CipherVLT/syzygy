from __future__ import annotations
import shutil

def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"

def cmd_autoremove() -> list[str]:
    return [_dnf(), "autoremove", "-y"]

def cmd_clean_cache() -> list[str]:
    return [_dnf(), "clean", "all"]

def cmd_rebuild_rpm_db() -> list[str]:
    return ["rpm", "--rebuilddb"]

def cmd_regenerate_initramfs() -> list[str]:
    return ["dracut", "-f", "--regenerate-all"]

def cmd_update_grub() -> list[str]:
    return ["grub2-mkconfig", "-o", "/boot/grub2/grub.cfg"]
