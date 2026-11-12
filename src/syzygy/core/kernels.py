"""Installed kernels, boot default (grubby) and safe removal – pure logic, no Qt."""

from __future__ import annotations

import logging
import platform
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

DNF_CONF = Path("/etc/dnf/dnf.conf")
EFIVARS = Path("/sys/firmware/efi/efivars")
_LOADER_GUID = "4a67b082-0a4c-41cf-b6c7-440b29bb8c4f"  # systemd-boot loader interface

BACKEND_SYSTEMD_BOOT = "systemd-boot"
BACKEND_GRUBBY = "grubby"
BACKEND_GRUB = "grub2-set-default"
DEFAULT_INSTALLONLY_LIMIT = 3
# Packages built per kernel version (same VERSION-RELEASE.ARCH as the -core package).
_KERNEL_PREFIXES = ("kernel",)
# Same version scheme but not part of a bootable kernel – removing them breaks other things
# (kernel-headers is required by glibc-devel).
_NEVER_REMOVE = frozenset({
    "kernel-headers", "kernel-tools", "kernel-tools-libs", "kernel-srpm-macros",
    "kernel-cross-headers",
})


def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


@dataclass(slots=True, frozen=True)
class KernelEntry:
    version: str  # VERSION-RELEASE.ARCH == `uname -r` for this kernel
    package_name: str
    is_running: bool
    is_default: bool
    install_date: str = ""
    flavor: str = "kernel"  # "kernel", "kernel-cachyos", …
    # Exact NEVRAs installed for this kernel (core, modules, modules-extra, devel, meta…).
    packages: tuple[str, ...] = field(default_factory=tuple)


@dataclass(slots=True, frozen=True)
class KernelReport:
    kernels: list[KernelEntry]
    running: str
    default: str | None  # None when the boot default can't be read without root
    installonly_limit: int
    boot_backend: str | None = None  # how "Set as default" will be applied


def version_key(version: str) -> tuple[tuple[int, int | str], ...]:
    """Natural sort key so 6.11 > 6.9 (plain string sorting gets this wrong)."""
    parts = re.split(r"(\d+)", version)
    return tuple((0, int(p)) if p.isdigit() else (1, p) for p in parts if p)


def _read_efivar(name: str, efivars: Path = EFIVARS) -> str | None:
    """Read a systemd-boot UTF-16 EFI variable (readable by normal users)."""
    try:
        data = (efivars / f"{name}-{_LOADER_GUID}").read_bytes()
    except OSError:
        return None
    return data[4:].decode("utf-16-le", "ignore").rstrip("\x00").strip() or None


def detect_boot_backend(efivars: Path = EFIVARS) -> str | None:
    if _read_efivar("LoaderInfo", efivars) and shutil.which("bootctl"):
        return BACKEND_SYSTEMD_BOOT
    if shutil.which("grubby"):
        return BACKEND_GRUBBY
    if shutil.which("grub2-set-default"):
        return BACKEND_GRUB
    return None


def _get_default_kernel(backend: str | None = None, efivars: Path = EFIVARS) -> str | None:
    """Default boot entry as a path or BLS id containing the kernel version, or None."""
    if backend == BACKEND_SYSTEMD_BOOT:
        entry = _read_efivar("LoaderEntryDefault", efivars)
        if entry:
            return entry.removesuffix(".conf")
    if shutil.which("grubby"):
        result = runner.run(["grubby", "--default-kernel"], timeout=10)
        if result.success and result.stdout.strip():
            return result.stdout.strip()
    return None  # GRUB's grubenv lives in root-only /boot/grub2


def is_default_entry(default: str | None, version: str) -> bool:
    """Match "/boot/vmlinuz-VER" (grubby) or "<machine-id>-VER" (BLS entry id)."""
    if not default:
        return False
    default = default.removesuffix(".conf")
    return default.endswith("-" + version) or default.endswith("vmlinuz-" + version)


def get_installonly_limit(conf: Path = DNF_CONF) -> int:
    try:
        for line in conf.read_text(encoding="utf-8", errors="ignore").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "installonly_limit" and value.strip().isdigit():
                return int(value.strip())
    except OSError:
        pass
    return DEFAULT_INSTALLONLY_LIMIT


def parse_kernel_packages(
    rpm_output: str, running: str, default_kernel: str | None
) -> list[KernelEntry]:
    """Group ``rpm -qa`` lines (NAME, VR.ARCH, INSTALLTIME, NEVRA) into kernels."""
    rows: list[tuple[str, str, str, str]] = []
    for line in rpm_output.splitlines():
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) >= 4 and parts[0].startswith(_KERNEL_PREFIXES):
            rows.append((parts[0], parts[1], parts[2], parts[3]))

    cores = [
        (n, vra, date) for n, vra, date, _ in rows
        if n.endswith("-core") and not n.endswith("-modules-core")  # kernel-modules-core ≠ kernel
    ]
    flavors = {n[: -len("-core")] for n, _v, _d in cores}
    entries: list[KernelEntry] = []
    for name, vra, date in cores:
        flavor = name[: -len("-core")]
        # Longer flavors that share our prefix (kernel-cachyos vs kernel) own their packages.
        rivals = [f for f in flavors if f != flavor and f.startswith(flavor + "-")]
        members = tuple(sorted(
            nevra for n, v, _d, nevra in rows
            if v == vra
            and (n == flavor or n.startswith(flavor + "-"))
            and n not in _NEVER_REMOVE
            and not any(n == r or n.startswith(r + "-") for r in rivals)
        ))
        is_default = is_default_entry(default_kernel, vra)
        entries.append(KernelEntry(
            version=vra,
            package_name=f"{name}-{vra}",
            is_running=vra == running,
            is_default=is_default,
            install_date=date,
            flavor=flavor,
            packages=members,
        ))
    entries.sort(key=lambda k: version_key(k.version), reverse=True)
    return entries


def get_kernel_report() -> KernelReport:
    result = runner.run(
        ["rpm", "-qa", "kernel*", "--qf",
         "%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\t%{INSTALLTIME:date}\t"
         "%{NAME}-%{VERSION}-%{RELEASE}.%{ARCH}\n"],
        timeout=20,
    )
    running = platform.release()
    backend = detect_boot_backend()
    default = _get_default_kernel(backend)
    return KernelReport(
        kernels=parse_kernel_packages(result.stdout, running, default),
        running=running,
        default=default,
        installonly_limit=get_installonly_limit(),
        boot_backend=backend,
    )


def list_installed_kernels() -> list[KernelEntry]:
    return get_kernel_report().kernels


def removal_block_reason(entry: KernelEntry, report: KernelReport) -> str | None:
    if entry.is_running:
        return "This is the running kernel – reboot into another kernel first."
    if len(report.kernels) <= 1:
        return "This is the only installed kernel."
    return None


# ---------------------------------------------------------------------- commands
_SET_DEFAULT_SCRIPT = r"""set -e
V="$1"
# systemd-boot: point LoaderEntryDefault at this kernel's BLS entry
if [ -d /sys/firmware/efi ] && command -v bootctl >/dev/null 2>&1 \
        && bootctl is-installed >/dev/null 2>&1; then
    for d in /boot/loader/entries /efi/loader/entries /boot/efi/loader/entries; do
        for f in "$d"/*"$V".conf; do
            if [ -e "$f" ]; then
                echo "systemd-boot entry: $f"
                exec bootctl set-default "$(basename "$f")"
            fi
        done
    done
fi
# GRUB with grubby (Fedora default)
if command -v grubby >/dev/null 2>&1; then
    exec grubby --set-default "/boot/vmlinuz-$V"
fi
# GRUB without grubby: saved_entry = BLS entry id
if command -v grub2-set-default >/dev/null 2>&1; then
    for f in /boot/loader/entries/*"$V".conf; do
        if [ -e "$f" ]; then
            ID="$(basename "$f" .conf)"
            echo "GRUB entry: $ID"
            grub2-set-default "$ID"
            echo "Default set (grub2-set-default)."
            exit 0
        fi
    done
    echo "No boot entry for $V in /boot/loader/entries" >&2
    exit 1
fi
echo "No boot-loader tool found (grubby, bootctl or grub2-set-default)." >&2
echo "Install grubby with: sudo dnf install grubby" >&2
exit 1
"""


def cmd_set_default_kernel(version: str) -> list[str]:
    """Works with grubby, plain GRUB (grub2-set-default) and systemd-boot (bootctl)."""
    return ["bash", "-c", _SET_DEFAULT_SCRIPT, "syzygy-set-default", version]

def cmd_remove_kernel_entry(entry: KernelEntry) -> list[str]:
    """Remove exactly the packages of this kernel build – never a glob over all kernels."""
    targets = list(entry.packages) or [entry.package_name]
    return [_dnf(), "remove", "-y", *targets]

def cmd_remove_kernel(version: str) -> list[str]:
    # Kept for compatibility; prefer cmd_remove_kernel_entry (exact NEVRAs, no "No match" errors).
    return [_dnf(), "remove", "-y", f"kernel-core-{version}"]

def cmd_install_latest_kernel() -> list[str]:
    return [_dnf(), "upgrade", "-y", "kernel*"]
