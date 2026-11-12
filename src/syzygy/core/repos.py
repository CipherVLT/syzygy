from __future__ import annotations
import logging, platform, re, shutil, subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional
from syzygy.core.models import Repository
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

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

def _run_repolist() -> str:
    for binary in ("dnf5", "dnf"):
        result = runner.run([binary, "repolist", "--all"], timeout=30)
        if result.stdout.strip(): return result.stdout
    return ""

def list_repositories() -> list[Repository]:
    output = _run_repolist()
    repos: list[Repository] = []
    for line in output.splitlines():
        if not line.strip() or line.lower().startswith("repo id"): continue
        parts = re.split(r"\s{2,}", line.strip())
        if len(parts) < 3: continue
        repo_id, name, status = parts[0].strip(), parts[1].strip(), parts[2].strip().lower()
        repos.append(Repository(id=repo_id, name=name, enabled=status.startswith("enabled"), description=name))
    return repos

def cmd_enable_repo(repo_id: str) -> list[str]:
    if _has_dnf5(): return ["dnf5", "config-manager", "setopt", f"{repo_id}.enabled=1"]
    return ["dnf", "config-manager", "--set-enabled", repo_id]

def cmd_disable_repo(repo_id: str) -> list[str]:
    if _has_dnf5(): return ["dnf5", "config-manager", "setopt", f"{repo_id}.enabled=0"]
    return ["dnf", "config-manager", "--set-disabled", repo_id]

def cmd_install_rpmfusion_free() -> list[str]:
    v = get_fedora_version()
    return ["dnf", "install", "-y", f"https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-{v}.noarch.rpm"]

def cmd_install_rpmfusion_nonfree() -> list[str]:
    v = get_fedora_version()
    return ["dnf", "install", "-y", f"https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-{v}.noarch.rpm"]

def cmd_add_flathub() -> list[str]:
    return ["flatpak", "remote-add", "--if-not-exists", "flathub", "https://dl.flathub.org/repo/flathub.flatpakrepo"]

def cmd_add_copr(copr_slug: str) -> list[str]:
    return ["dnf", "copr", "enable", "-y", copr_slug]

def cmd_remove_copr(copr_slug: str) -> list[str]:
    return ["dnf", "copr", "remove", "-y", copr_slug]
