"""Installed-software inventory for the Installed tab – pure logic, no Qt."""

from __future__ import annotations

import fnmatch
import logging
import platform
import shutil
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from syzygy.core import flatpak
from syzygy.core.models import Package, PackageSource, PackageStatus
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

RPM_QF = "%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\t%{SIZE}\t%{VENDOR}\t%{SUMMARY}\n"
PROTECTED_DIRS = (Path("/etc/dnf/protected.d"), Path("/usr/share/dnf5/protected.d"))
# Pseudo-packages rpm lists for imported GPG keys – not removable software.
_PSEUDO_PACKAGES = {"gpg-pubkey"}

LOCK_PROTECTED = "Protected by DNF – removing it could leave the system unbootable or unmanageable"
LOCK_RUNNING_KERNEL = "Part of the running kernel – boot another kernel first (see Kernels tab)"


@dataclass(slots=True, frozen=True)
class InstalledInventory:
    rpms: list[Package] = field(default_factory=list)
    flatpaks: list[Package] = field(default_factory=list)
    # Names DNF records as explicitly installed by the user; None when DNF couldn't tell us.
    user_installed: frozenset[str] | None = None
    protected_patterns: tuple[str, ...] = ()
    running_kernel: str = ""
    errors: tuple[str, ...] = ()

    def lock_reason(self, pkg: Package) -> str | None:
        """Why this package must not be removed from the UI, or None if removal is fine."""
        if pkg.source is PackageSource.FLATPAK:
            return None
        if pkg.name.startswith("kernel") and f"{pkg.version}.{pkg.arch}" == self.running_kernel:
            return LOCK_RUNNING_KERNEL
        if any(fnmatch.fnmatchcase(pkg.name, pat) for pat in self.protected_patterns):
            return LOCK_PROTECTED
        return None

    def is_user_installed(self, pkg: Package) -> bool:
        if pkg.source is PackageSource.FLATPAK:
            return True  # apps (not runtimes) are always an explicit choice
        return self.user_installed is None or pkg.name in self.user_installed


def human_size(num_bytes: int) -> str:
    if num_bytes <= 0:
        return ""
    size = float(num_bytes)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if size < 1024 or unit == "GiB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return ""


def _source_for_vendor(vendor: str) -> PackageSource:
    # COPR builds are stamped "Fedora Copr - user <owner>" / "Fedora Copr - group <name>".
    return PackageSource.COPR if vendor.lower().startswith("fedora copr") else PackageSource.DNF


def parse_rpm_inventory(output: str) -> list[Package]:
    packages: list[Package] = []
    for line in output.splitlines():
        parts = line.split("\t")
        if len(parts) < 6:
            continue
        name, version, arch, size, vendor, summary = (p.strip() for p in parts[:6])
        if not name or name in _PSEUDO_PACKAGES:
            continue
        vendor = "" if vendor == "(none)" else vendor
        packages.append(Package(
            name=name,
            version=version,
            summary=summary,
            source=_source_for_vendor(vendor),
            status=PackageStatus.INSTALLED,
            repo=vendor,
            size=human_size(int(size)) if size.isdigit() else None,
            arch="" if arch == "(none)" else arch,
        ))
    packages.sort(key=lambda p: (p.name.lower(), p.version, p.arch))
    return packages


def list_installed_rpm_inventory() -> list[Package]:
    result = runner.run(["rpm", "-qa", "--qf", RPM_QF], timeout=60)
    if not result.success:
        raise RuntimeError(result.error_message or "rpm -qa failed")
    return parse_rpm_inventory(result.stdout)


def list_installed_flatpak_apps() -> list[Package]:
    if shutil.which("flatpak") is None:
        return []
    packages = [
        Package(
            name=entry.name or entry.application,
            version=entry.version,
            summary=entry.application,
            source=PackageSource.FLATPAK,
            status=PackageStatus.INSTALLED,
            repo=entry.origin,
            size=entry.size or None,
            arch=entry.arch,
            app_id=entry.application,
            branch=entry.branch,
            installation=entry.installation,
        )
        for entry in flatpak.list_installed_apps()
        if entry.application
    ]
    packages.sort(key=lambda p: (p.name.lower(), p.app_id or ""))
    return packages


def _dnf_bin() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


def get_user_installed_names() -> frozenset[str] | None:
    """Packages DNF marks as user-installed (not pulled in as deps), or None if unknown.

    Tries the metadata cache first (-C) so this doesn't trigger a repo refresh; only the
    @System repo is needed for --userinstalled.
    """
    base = [_dnf_bin(), "repoquery", "--userinstalled", "--qf", "%{name}\n"]
    for cmd in ([*base[:1], "-C", *base[1:]], base):
        result = runner.run(cmd, timeout=90)
        if result.success:
            names = frozenset(n.strip() for n in result.stdout.splitlines() if n.strip())
            if names:
                return names
    return None


def parse_protected(lines: Iterable[str]) -> list[str]:
    patterns: list[str] = []
    for raw in lines:
        line = raw.split("#", 1)[0].strip()
        if line:
            patterns.extend(line.split())
    return patterns


def get_protected_patterns() -> tuple[str, ...]:
    patterns: set[str] = set()
    for directory in PROTECTED_DIRS:
        if not directory.is_dir():
            continue
        for conf in sorted(directory.glob("*.conf")):
            try:
                patterns.update(parse_protected(conf.read_text(encoding="utf-8").splitlines()))
            except OSError as exc:
                logger.warning("Cannot read %s: %s", conf, exc)
    return tuple(sorted(patterns))


def load_inventory(*, include_flatpaks: bool = True) -> InstalledInventory:
    """Collect everything the Installed tab needs. Slow (seconds) – call off the UI thread."""
    errors: list[str] = []
    try:
        rpms = list_installed_rpm_inventory()
    except Exception as exc:  # noqa: BLE001 – report, keep loading Flatpaks
        logger.exception("RPM inventory failed")
        rpms, errors = [], [f"RPM: {exc}"]

    flatpaks: list[Package] = []
    if include_flatpaks:
        try:
            flatpaks = list_installed_flatpak_apps()
        except Exception as exc:  # noqa: BLE001
            logger.exception("Flatpak inventory failed")
            errors.append(f"Flatpak: {exc}")

    return InstalledInventory(
        rpms=rpms,
        flatpaks=flatpaks,
        user_installed=get_user_installed_names() if rpms else None,
        protected_patterns=get_protected_patterns(),
        running_kernel=platform.release(),
        errors=tuple(errors),
    )


def filter_packages(packages: Iterable[Package], text: str) -> list[Package]:
    """Case-insensitive match of every whitespace-separated term against name/summary/app-id."""
    terms = text.lower().split()
    if not terms:
        return list(packages)
    matched: list[Package] = []
    for pkg in packages:
        haystack = f"{pkg.name} {pkg.summary} {pkg.app_id or ''}".lower()
        if all(term in haystack for term in terms):
            matched.append(pkg)
    return matched


def cmd_remove_installed_rpm(pkg: Package) -> list[str]:
    """Remove exactly this installed build (NEVRA) – never every installonly kernel at once."""
    target = f"{pkg.name}-{pkg.version}.{pkg.arch}" if pkg.version and pkg.arch else pkg.name
    return [_dnf_bin(), "remove", "-y", target]
