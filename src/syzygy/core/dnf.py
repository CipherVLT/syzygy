from __future__ import annotations

import logging
import re
import shutil
from functools import lru_cache
from typing import Optional

from syzygy.core.models import Package, PackageSource, PackageStatus
from syzygy.core.system import runner

logger = logging.getLogger(__name__)
QF_FORMAT = "%{name}\t%{version}-%{release}\t%{arch}\t%{repoid}\t%{summary}\n"


def _dnf_bin() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


@lru_cache(maxsize=1)
def get_installed_names() -> set[str]:
    result = runner.run(["rpm", "-qa", "--qf", "%{name}\n"], timeout=20)
    if not result.stdout:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


@lru_cache(maxsize=1)
def get_installed_flatpak_ids() -> set[str]:
    result = runner.run(["flatpak", "list", "--app", "--columns=application"], timeout=15)
    if not result.stdout:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def search_rpm(query: str, limit: int = 80) -> list[Package]:
    if not query.strip():
        return []
    binary = _dnf_bin()
    pattern = f"*{query}*"
    result = runner.run([binary, "repoquery", pattern, "--qf", QF_FORMAT], timeout=25)
    if not result.stdout.strip():
        result = runner.run([binary, "search", query], timeout=25)
        return _parse_classic_search(result.stdout)
    return _parse_qf(result.stdout, limit=limit)


def _parse_qf(output: str, limit: int = 80) -> list[Package]:
    installed = get_installed_names()
    packages: list[Package] = []
    for line in output.splitlines():
        if not line.strip() or line.startswith("Last metadata"):
            continue
        parts = line.split("\t")
        if len(parts) < 5:
            continue
        name, version, arch, repoid, summary = parts[:5]
        name = name.strip()
        if not name:
            continue
        source = PackageSource.DNF
        if "copr" in repoid.lower():
            source = PackageSource.COPR
        status = PackageStatus.INSTALLED if name in installed else PackageStatus.AVAILABLE
        packages.append(Package(
            name=name, version=version.strip(), summary=summary.strip(),
            source=source, status=status, repo=repoid.strip(), arch=arch.strip(),
        ))
        if len(packages) >= limit:
            break
    return packages


def _parse_classic_search(output: str) -> list[Package]:
    installed = get_installed_names()
    packages: list[Package] = []
    for line in output.splitlines():
        line = line.rstrip()
        if not line or line.startswith("====") or line.startswith("Last metadata"):
            continue
        m = re.match(r"^(\S+)\s*:\s*(.*)$", line)
        if m:
            name_arch, summary = m.groups()
            name = name_arch.split(".")[0]
            packages.append(Package(
                name=name, version="", summary=summary.strip(),
                source=PackageSource.DNF,
                status=PackageStatus.INSTALLED if name in installed else PackageStatus.AVAILABLE,
            ))
    return packages


def search_flatpak(query: str, limit: int = 60) -> list[Package]:
    if not query.strip():
        return []
    result = runner.run(
        ["flatpak", "search", "--columns=name,application,version,branch,description", query],
        timeout=20,
    )
    installed_ids = get_installed_flatpak_ids()
    packages: list[Package] = []
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        app_id = parts[1].strip() if len(parts) > 1 else ""
        version = parts[2].strip() if len(parts) > 2 else ""
        branch = parts[3].strip() if len(parts) > 3 else "stable"
        description = parts[4].strip() if len(parts) > 4 else ""
        status = PackageStatus.INSTALLED if app_id in installed_ids else PackageStatus.AVAILABLE
        packages.append(Package(
            name=name, version=version, summary=description,
            source=PackageSource.FLATPAK, status=status, repo="flathub",
            app_id=app_id, branch=branch,
        ))
        if len(packages) >= limit:
            break
    return packages


def list_installed_rpms() -> list[Package]:
    result = runner.run(
        ["rpm", "-qa", "--qf", "%{name}\t%{version}-%{release}\t%{arch}\t%{summary}\n"],
        timeout=30,
    )
    packages: list[Package] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 4:
            continue
        name, version, arch, summary = parts[:4]
        packages.append(Package(
            name=name.strip(), version=version.strip(), summary=summary.strip(),
            source=PackageSource.DNF, status=PackageStatus.INSTALLED, arch=arch.strip(),
        ))
    return packages


def get_user_installed_names() -> set[str]:
    binary = _dnf_bin()
    result = runner.run([binary, "repoquery", "--userinstalled", "--qf", "%{name}\n"], timeout=25)
    if not result.stdout:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def check_rpm_updates() -> list[Package]:
    binary = _dnf_bin()
    result = runner.run([binary, "check-update", "--quiet"], timeout=60)
    if result.returncode not in (0, 100):
        return []
    packages: list[Package] = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("Last metadata"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        name_arch = parts[0]
        name = name_arch.rsplit(".", 1)[0]
        version = parts[1] if len(parts) > 1 else ""
        repo = parts[2] if len(parts) > 2 else ""
        packages.append(Package(
            name=name, version=version, summary="", source=PackageSource.DNF,
            status=PackageStatus.UPDATABLE, repo=repo,
        ))
    return packages


def check_flatpak_updates() -> list[Package]:
    result = runner.run(
        ["flatpak", "remote-ls", "--updates", "--columns=name,application,version"], timeout=30,
    )
    packages: list[Package] = []
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        packages.append(Package(
            name=parts[0].strip(), version=parts[2].strip() if len(parts) > 2 else "",
            summary="", source=PackageSource.FLATPAK, status=PackageStatus.UPDATABLE,
            app_id=parts[1].strip(), repo="flathub",
        ))
    return packages


def cmd_install_rpm(name: str) -> list[str]:
    return ["dnf", "install", "-y", name]

def cmd_remove_rpm(name: str) -> list[str]:
    return ["dnf", "remove", "-y", name]

def cmd_update_rpm(name: str) -> list[str]:
    return ["dnf", "upgrade", "-y", name]

def cmd_update_all_rpms() -> list[str]:
    return ["dnf", "upgrade", "-y"]

def cmd_install_flatpak(app_id: str) -> list[str]:
    return ["flatpak", "install", "-y", "flathub", app_id]

def cmd_remove_flatpak(app_id: str) -> list[str]:
    return ["flatpak", "uninstall", "-y", app_id]

def cmd_update_flatpak(app_id: str) -> list[str]:
    return ["flatpak", "update", "-y", app_id]

def cmd_update_all_flatpaks() -> list[str]:
    return ["flatpak", "update", "-y"]
