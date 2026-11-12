from __future__ import annotations

import configparser
import fnmatch
import logging
import platform
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from syzygy.core.models import Repository
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

# dnf5 reads all of these; dnf4 only /etc/yum.repos.d.
REPO_DIRS = (Path("/etc/yum.repos.d"), Path("/etc/distro.repos.d"), Path("/usr/share/dnf5/repos.d"))
# `dnf5 config-manager setopt repo.enabled=…` writes here instead of editing the .repo file.
OVERRIDE_DIRS = (Path("/etc/dnf/repos.override.d"),)

KIND_FEDORA = "Fedora"
KIND_RPMFUSION = "RPM Fusion"
KIND_COPR = "COPR"
KIND_THIRD_PARTY = "Third-party"

COPR_SLUG_RE = re.compile(r"^@?[A-Za-z0-9_.-]+/[A-Za-z0-9_.+-]+$")
FLATHUB_URL = "https://dl.flathub.org/repo/flathub.flatpakrepo"


@lru_cache(maxsize=1)
def get_fedora_version() -> str:
    try:
        os_release = platform.freedesktop_os_release()
        version = os_release.get("VERSION_ID")
        if version: return version
    except Exception: pass
    try:
        out = subprocess.check_output(["rpm", "-E", "%fedora"], text=True, timeout=5).strip()
        if out.isdigit(): return out
    except Exception: pass
    return "41"

def _has_dnf5() -> bool:
    return shutil.which("dnf5") is not None


def _dnf() -> str:
    return "dnf5" if _has_dnf5() else "dnf"


# ---------------------------------------------------------------------- listing
def _expand_vars(text: str) -> str:
    values = {
        "releasever": get_fedora_version(),
        "basearch": platform.machine(),
        "arch": platform.machine(),
    }
    return re.sub(r"\$\{?(\w+)\}?", lambda m: values.get(m.group(1), m.group(0)), text)


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "yes", "true", "on")


def _read_ini(path: Path) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(path, encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError) as exc:
        logger.warning("Skipping unreadable repo file %s: %s", path, exc)
    return parser


def _load_overrides(dirs: tuple[Path, ...]) -> list[tuple[str, dict[str, str]]]:
    overrides: list[tuple[str, dict[str, str]]] = []
    for directory in dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.repo")):
            parser = _read_ini(path)
            for section in parser.sections():
                overrides.append((section, dict(parser[section])))
    return overrides


def list_repositories_from_files(
    repo_dirs: tuple[Path, ...] = REPO_DIRS,
    override_dirs: tuple[Path, ...] = OVERRIDE_DIRS,
) -> list[Repository]:
    overrides = _load_overrides(override_dirs)
    repos: dict[str, Repository] = {}
    for directory in repo_dirs:
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob("*.repo")):
            parser = _read_ini(path)
            for repo_id in parser.sections():
                if repo_id in repos:
                    continue  # first definition wins, like dnf
                options = dict(parser[repo_id])
                for pattern, values in overrides:  # later files override earlier ones
                    if fnmatch.fnmatchcase(repo_id, pattern):
                        options.update(values)
                name = _expand_vars(options.get("name") or repo_id)
                baseurl = (options.get("baseurl") or "").strip()
                repos[repo_id] = Repository(
                    id=repo_id,
                    name=name,
                    enabled=_truthy(options.get("enabled"), default=True),
                    url=_expand_vars(baseurl.split()[0]) if baseurl else None,
                    metalink=_expand_vars(options.get("metalink") or options.get("mirrorlist") or "")
                    or None,
                    file_path=path,
                    description=name,
                )
    return sorted(repos.values(), key=lambda r: (not r.enabled, r.id))


def _run_repolist() -> str:
    for binary in ("dnf5", "dnf"):
        result = runner.run([binary, "repolist", "--all"], timeout=30)
        if result.stdout.strip(): return result.stdout
    return ""


def _parse_repolist(output: str) -> list[Repository]:
    repos: list[Repository] = []
    for line in output.splitlines():
        if not line.strip() or line.lower().startswith("repo id"): continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 3: continue
        repo_id, name, status = parts[0].strip(), parts[1].strip(), parts[2].strip().lower()
        repos.append(Repository(id=repo_id, name=name, enabled=status.startswith("enabled"), description=name))
    return repos


def list_repositories() -> list[Repository]:
    """All configured DNF repositories (enabled first).

    Reads the .repo files directly – reliable column-free parsing, includes the file path and
    honours dnf5 overrides – and falls back to ``dnf repolist --all`` if none are found.
    """
    repos = list_repositories_from_files()
    return repos if repos else _parse_repolist(_run_repolist())


def repo_kind(repo: Repository) -> str:
    rid = repo.id.lower()
    fname = repo.file_path.name.lower() if repo.file_path else ""
    if rid.startswith("copr:") or fname.startswith("_copr"):
        return KIND_COPR
    if rid.startswith("rpmfusion") or fname.startswith("rpmfusion"):
        return KIND_RPMFUSION
    if rid.startswith(("fedora", "updates")) or fname.startswith(("fedora", "updates")):
        return KIND_FEDORA
    return KIND_THIRD_PARTY


def copr_slug_from_repo_id(repo_id: str) -> str | None:
    """``copr:copr.fedorainfracloud.org:group_kde:stable`` → ``@kde/stable``."""
    parts = repo_id.split(":")
    if len(parts) < 4 or parts[0] != "copr":
        return None
    owner, project = parts[2], ":".join(parts[3:])
    if owner.startswith("group_"):
        owner = "@" + owner[len("group_"):]
    return f"{owner}/{project}"


def is_valid_copr_slug(slug: str) -> bool:
    return bool(COPR_SLUG_RE.match(slug.strip()))


# ---------------------------------------------------------------------- one-click setups
@dataclass(slots=True, frozen=True)
class QuickSetupState:
    rpmfusion_free: bool
    rpmfusion_nonfree: bool
    flathub: str  # "missing" | "filtered" | "disabled" | "enabled"


def _rpm_installed(name: str) -> bool:
    return runner.run(["rpm", "-q", name], timeout=10).returncode == 0


def flathub_state() -> str:
    if shutil.which("flatpak") is None:
        return "missing"
    result = runner.run(
        ["flatpak", "remotes", "--show-disabled", "--columns=name,options"], timeout=15
    )
    for line in result.stdout.splitlines():
        parts = line.split("\t")
        if parts and parts[0].strip() == "flathub":
            options = parts[1].lower() if len(parts) > 1 else ""
            if "disabled" in options:
                return "disabled"
            # Fedora ships a curated, filtered Flathub via fedora-flathub-remote.
            return "filtered" if "filtered" in options else "enabled"
    return "missing"


def get_quick_setup_state() -> QuickSetupState:
    return QuickSetupState(
        rpmfusion_free=_rpm_installed("rpmfusion-free-release"),
        rpmfusion_nonfree=_rpm_installed("rpmfusion-nonfree-release"),
        flathub=flathub_state(),
    )


# ---------------------------------------------------------------------- commands
def cmd_enable_repo(repo_id: str) -> list[str]:
    if _has_dnf5(): return ["dnf5", "config-manager", "setopt", f"{repo_id}.enabled=1"]
    return ["dnf", "config-manager", "--set-enabled", repo_id]

def cmd_disable_repo(repo_id: str) -> list[str]:
    if _has_dnf5(): return ["dnf5", "config-manager", "setopt", f"{repo_id}.enabled=0"]
    return ["dnf", "config-manager", "--set-disabled", repo_id]

def cmd_install_rpmfusion_free() -> list[str]:
    v = get_fedora_version()
    return [_dnf(), "install", "-y", f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{v}.noarch.rpm"]

def cmd_install_rpmfusion_nonfree() -> list[str]:
    v = get_fedora_version()
    return [_dnf(), "install", "-y", f"https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{v}.noarch.rpm"]

def cmd_install_rpmfusion_both() -> list[str]:
    v = get_fedora_version()
    return [
        _dnf(), "install", "-y",
        f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{v}.noarch.rpm",
        f"https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{v}.noarch.rpm",
    ]

def cmd_add_flathub() -> list[str]:
    return ["flatpak", "remote-add", "--if-not-exists", "flathub", FLATHUB_URL]

def cmd_enable_full_flathub() -> list[str]:
    """Add Flathub if needed, then drop Fedora's filter and enable it (no pkexec: polkit)."""
    return [
        "bash", "-c",
        f"set -e; flatpak remote-add --if-not-exists flathub {FLATHUB_URL}; "
        "flatpak remote-modify --no-filter --enable flathub",
    ]

def cmd_add_copr(copr_slug: str) -> list[str]:
    return [_dnf(), "copr", "enable", "-y", copr_slug]

def cmd_remove_copr(copr_slug: str) -> list[str]:
    return [_dnf(), "copr", "remove", "-y", copr_slug]
