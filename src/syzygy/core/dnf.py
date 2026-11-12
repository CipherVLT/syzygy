from __future__ import annotations

import logging
import platform
import re
import shutil
from collections.abc import Iterable
from dataclasses import replace
from functools import lru_cache

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
    if result.stdout.strip():
        packages = _parse_qf(result.stdout)
    else:
        result = runner.run([binary, "search", query], timeout=25)
        packages = _parse_classic_search(result.stdout)
    return rank_packages(dedupe_packages(packages), query)[:limit]


def _parse_qf(output: str, limit: int | None = None) -> list[Package]:
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
        if limit is not None and len(packages) >= limit:
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
        [
            "flatpak", "search",
            "--columns=name,application,version,branch,remotes,description",
            query,
        ],
        timeout=20,
    )
    installed_ids = get_installed_flatpak_ids()
    packages: list[Package] = []
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name\t"):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        app_id = parts[1].strip()
        if not app_id:
            continue
        version = parts[2].strip() if len(parts) > 2 else ""
        branch = parts[3].strip() if len(parts) > 3 else "stable"
        remote = _pick_remote(parts[4] if len(parts) > 4 else "")
        description = parts[5].strip() if len(parts) > 5 else ""
        status = PackageStatus.INSTALLED if app_id in installed_ids else PackageStatus.AVAILABLE
        packages.append(Package(
            name=name or app_id, version=version, summary=description,
            source=PackageSource.FLATPAK, status=status, repo=remote,
            app_id=app_id, branch=branch,
        ))
    return rank_packages(dedupe_packages(packages), query)[:limit]


def _pick_remote(raw: str) -> str:
    """`flatpak search` lists every remote carrying an app (comma separated); prefer Flathub."""
    remotes = [r.strip() for r in raw.split(",") if r.strip()]
    if not remotes:
        return "flathub"
    return "flathub" if "flathub" in remotes else remotes[0]


_NATIVE_ARCHES = {platform.machine(), "noarch", ""}


def _package_key(pkg: Package) -> tuple[bool, str]:
    is_flatpak = pkg.source is PackageSource.FLATPAK
    return is_flatpak, (pkg.app_id or pkg.name) if is_flatpak else pkg.name


def _preference(pkg: Package) -> tuple[bool, bool, bool]:
    return (
        pkg.status is PackageStatus.INSTALLED,
        pkg.arch in _NATIVE_ARCHES,
        (pkg.branch or "stable") == "stable",
    )


def dedupe_packages(packages: Iterable[Package]) -> list[Package]:
    """Collapse multilib (i686/x86_64), multi-version and multi-branch duplicates.

    Keeps first-seen order; for each name prefers installed > native arch > stable branch.
    """
    best: dict[tuple[bool, str], Package] = {}
    for pkg in packages:
        key = _package_key(pkg)
        current = best.get(key)
        if current is None or _preference(pkg) > _preference(current):
            best[key] = pkg
    return list(best.values())


def rank_packages(packages: Iterable[Package], query: str) -> list[Package]:
    """Exact name match first, then prefix matches, then substring, then summary-only hits."""
    q = query.strip().lower()

    def key(pkg: Package) -> tuple[int, int, str]:
        name = pkg.name.lower()
        app_id = (pkg.app_id or "").lower()
        if name == q or app_id.rsplit(".", 1)[-1] == q:
            tier = 0
        elif name.startswith(q):
            tier = 1
        elif q in name or q in app_id:
            tier = 2
        else:
            tier = 3
        return tier, len(name), name

    return sorted(packages, key=key)


def invalidate_caches() -> None:
    """Drop cached installed-package sets; call after any install/remove transaction."""
    get_installed_names.cache_clear()
    get_installed_flatpak_ids.cache_clear()


def refresh_statuses(packages: Iterable[Package]) -> list[Package]:
    """Re-query what is installed (bypassing caches) and return packages with corrected status."""
    invalidate_caches()
    rpm_names = get_installed_names()
    flatpak_ids = get_installed_flatpak_ids()
    refreshed: list[Package] = []
    for pkg in packages:
        if pkg.source is PackageSource.FLATPAK:
            installed = (pkg.app_id or "") in flatpak_ids
        else:
            installed = pkg.name in rpm_names
        status = PackageStatus.INSTALLED if installed else PackageStatus.AVAILABLE
        refreshed.append(pkg if pkg.status is status else replace(pkg, status=status))
    return refreshed


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

def cmd_install_flatpak(app_id: str, remote: str = "flathub") -> list[str]:
    return ["flatpak", "install", "-y", "--noninteractive", remote or "flathub", app_id]

def cmd_remove_flatpak(app_id: str, *, branch: str = "", installation: str = "") -> list[str]:
    """Uninstall a Flatpak app.

    ``branch`` disambiguates when several branches are installed (``ID//BRANCH``), and
    ``installation`` targets the right scope – a ``--user`` install is invisible to ``--system``.
    """
    cmd = ["flatpak", "uninstall", "-y", "--noninteractive"]
    if installation == "user":
        cmd.append("--user")
    elif installation == "system":
        cmd.append("--system")
    cmd.append(f"{app_id}//{branch}" if branch else app_id)
    return cmd

def cmd_update_flatpak(app_id: str) -> list[str]:
    return ["flatpak", "update", "-y", app_id]

def cmd_update_all_flatpaks() -> list[str]:
    return ["flatpak", "update", "-y"]
