"""Pending RPM + Flatpak updates – pure logic, no Qt."""

from __future__ import annotations

import fnmatch
import logging
import shutil
from collections.abc import Iterable
from dataclasses import dataclass

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

SOURCE_RPM = "rpm"
SOURCE_FLATPAK = "flatpak"

# Updating these only takes full effect after a reboot (new kernel, libc, init, firmware, GPU).
REBOOT_PATTERNS = (
    "kernel", "kernel-*", "glibc", "glibc-*", "systemd", "systemd-*", "linux-firmware*",
    "*-firmware", "dbus", "dbus-broker", "dbus-daemon", "mesa-*", "akmod-nvidia*",
    "xorg-x11-drv-nvidia*", "nvidia-*", "grub2-*", "shim-*", "dracut*",
)
_HEADER_PREFIXES = ("last metadata", "obsoleting", "security:", "updating and loading",
                    "repositories loaded", "available upgrades", "upgrades")


@dataclass(slots=True, frozen=True)
class UpdateItem:
    name: str
    version: str
    source: str
    arch: str = ""
    repo: str = ""
    app_id: str = ""
    branch: str = ""
    installation: str = ""
    needs_reboot: bool = False

    @property
    def key(self) -> str:
        if self.source == SOURCE_FLATPAK:
            return f"flatpak:{self.app_id}//{self.branch}@{self.installation}"
        return f"rpm:{self.name}.{self.arch}"

    @property
    def target(self) -> str:
        """Argument passed to dnf / flatpak to update exactly this item."""
        if self.source == SOURCE_FLATPAK:
            return f"{self.app_id}//{self.branch}" if self.branch else self.app_id
        return f"{self.name}.{self.arch}" if self.arch else self.name


@dataclass(slots=True, frozen=True)
class UpdateReport:
    rpm: list[UpdateItem]
    flatpak: list[UpdateItem]
    errors: tuple[str, ...] = ()

    @property
    def reboot_required(self) -> bool:
        return any(item.needs_reboot for item in self.rpm)


def needs_reboot(name: str) -> bool:
    return any(fnmatch.fnmatchcase(name, pat) for pat in REBOOT_PATTERNS)


def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


def parse_check_update(output: str) -> list[UpdateItem]:
    """Parse ``dnf check-update`` / ``dnf5 check-upgrade`` stdout.

    Lines look like ``firefox.x86_64   140.0-1.fc43   updates``. dnf4 appends an
    "Obsoleting Packages" section whose entries are indented – those are skipped.
    """
    seen: set[str] = set()
    items: list[UpdateItem] = []
    in_obsoletes = False
    for raw in output.splitlines():
        if not raw.strip():
            continue
        lower = raw.strip().lower()
        if lower.startswith("obsoleting"):
            in_obsoletes = True
            continue
        if raw[0].isspace() or in_obsoletes or lower.startswith(_HEADER_PREFIXES):
            continue
        parts = raw.split()
        if len(parts) < 3 or "." not in parts[0]:
            continue
        name, _, arch = parts[0].rpartition(".")
        key = f"{name}.{arch}"
        if not name or key in seen:
            continue
        seen.add(key)
        items.append(UpdateItem(
            name=name, arch=arch, version=parts[1], repo=parts[2], source=SOURCE_RPM,
            needs_reboot=needs_reboot(name),
        ))
    items.sort(key=lambda i: (not i.needs_reboot, i.name.lower()))
    return items


def check_rpm_updates(*, refresh: bool = False) -> list[UpdateItem]:
    cmd = [_dnf(), "check-update", "--quiet"]
    if refresh:
        cmd.append("--refresh")
    result = runner.run(cmd, timeout=300)
    # Exit 100 = updates available, 0 = none; anything else is a real error.
    if result.timed_out or result.returncode not in (0, 100):
        detail = (result.stderr or result.stdout or result.error_message or "").strip()
        raise RuntimeError(detail.splitlines()[-1] if detail else "dnf check-update failed")
    return parse_check_update(result.stdout)


def parse_flatpak_updates(output: str, installation: str) -> list[UpdateItem]:
    items: list[UpdateItem] = []
    for line in output.splitlines():
        if not line.strip() or line.lower().startswith("name\t"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2 or not parts[1]:
            continue
        items.append(UpdateItem(
            name=parts[0] or parts[1],
            app_id=parts[1],
            version=parts[2] if len(parts) > 2 else "",
            branch=parts[3] if len(parts) > 3 else "",
            repo=parts[4] if len(parts) > 4 else "",
            installation=installation,
            source=SOURCE_FLATPAK,
        ))
    return items


def check_flatpak_updates() -> list[UpdateItem]:
    if shutil.which("flatpak") is None:
        return []
    items: list[UpdateItem] = []
    for installation in ("system", "user"):
        result = runner.run(
            ["flatpak", "remote-ls", "--updates", f"--{installation}",
             "--columns=name,application,version,branch,origin"],
            timeout=120,
        )
        # A user installation without remotes just exits non-zero – not an error worth showing.
        if result.success:
            items.extend(parse_flatpak_updates(result.stdout, installation))
    items.sort(key=lambda i: i.name.lower())
    return items


def check_all(*, refresh: bool = False) -> UpdateReport:
    errors: list[str] = []
    try:
        rpm = check_rpm_updates(refresh=refresh)
    except Exception as exc:  # noqa: BLE001 – still report Flatpak updates
        logger.exception("RPM update check failed")
        rpm, errors = [], [f"RPM: {exc}"]
    try:
        flatpak = check_flatpak_updates()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Flatpak update check failed")
        flatpak = []
        errors.append(f"Flatpak: {exc}")
    return UpdateReport(rpm=rpm, flatpak=flatpak, errors=tuple(errors))


# ---------------------------------------------------------------------- commands
def cmd_upgrade_rpms(items: Iterable[UpdateItem] = ()) -> list[str]:
    """Upgrade the given RPMs, or everything when ``items`` is empty."""
    return [_dnf(), "upgrade", "-y", *(i.target for i in items)]


def cmd_update_flatpaks(items: Iterable[UpdateItem] = ()) -> list[str]:
    """Update the given Flatpak refs, or everything when ``items`` is empty.

    Runs unprivileged: system refs are authorized by flatpak's own polkit helper.
    """
    return ["flatpak", "update", "-y", "--noninteractive", *(i.target for i in items)]
