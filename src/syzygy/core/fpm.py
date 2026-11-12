"""Flatpak remotes, local bundle/ref installs and permission overrides – pure logic, no Qt."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path

from syzygy.core.system import runner

logger = logging.getLogger(__name__)

REMOTE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
APP_ID_RE = re.compile(r"^[A-Za-z_][\w-]*(\.[A-Za-z_][\w-]*){2,}$")
# Values accepted by `flatpak override --filesystem=`.
FILESYSTEM_PRESETS = ("home", "host", "host-os", "host-etc", "xdg-download", "xdg-documents",
                      "xdg-pictures", "xdg-music", "xdg-videos", "xdg-config", "xdg-run/gvfs")


@dataclass(slots=True, frozen=True)
class FlatpakRemote:
    name: str
    title: str = ""
    url: str = ""
    options: str = ""
    is_enabled: bool = True

    @property
    def installation(self) -> str:
        return "user" if "user" in self.options.split(",") else "system"


def list_flatpak_remotes() -> list[FlatpakRemote]:
    result = runner.run(["flatpak", "remotes", "--show-disabled", "--columns=name,title,url,options"], timeout=15)
    remotes: list[FlatpakRemote] = []
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name\t"): continue
        parts = line.split("\t")
        name = parts[0].strip()
        if not name: continue
        title = parts[1].strip() if len(parts)>1 else ""
        url = parts[2].strip() if len(parts)>2 else ""
        options = parts[3].strip() if len(parts)>3 else ""
        is_enabled = "disabled" not in options.lower()
        remotes.append(FlatpakRemote(name=name, title=title or name, url=url, options=options, is_enabled=is_enabled))
    return remotes


def is_valid_remote_name(name: str) -> bool:
    return bool(REMOTE_NAME_RE.match(name.strip()))


def is_valid_remote_url(url: str) -> bool:
    url = url.strip()
    return url.startswith(("https://", "http://", "file://", "oci+https://")) or url.endswith(
        ".flatpakrepo"
    )


def is_valid_filesystem(value: str) -> bool:
    value = value.strip()
    if not value or any(ch in value for ch in "\n\t"):
        return False
    base = value.split(":", 1)[0]  # allow ":ro", ":rw", ":create" suffixes
    return base in FILESYSTEM_PRESETS or base.startswith(("/", "~/", "xdg-"))


def get_app_overrides(app_id: str, *, user: bool = True) -> str:
    if not app_id: return ""
    scope = ["--user"] if user else []
    result = runner.run(["flatpak", "override", *scope, "--show", app_id], timeout=10)
    return result.stdout.strip() or "(no overrides)"


def bundle_kind(path: str) -> str | None:
    suffix = Path(path).suffix.lower()
    return {".flatpakref": "ref", ".flatpak": "bundle", ".flatpakrepo": "repo"}.get(suffix)


# ---------------------------------------------------------------------- commands
# All of these run unprivileged: system remotes/installs go through flatpak's polkit helper and
# overrides default to the per-user scope (like Flatseal), which needs no authorization.
def cmd_add_remote(name: str, url: str, *, user: bool = False) -> list[str]:
    return ["flatpak", "remote-add", "--if-not-exists", *(["--user"] if user else []), name, url]

def cmd_remove_remote(name: str, installation: str = "system") -> list[str]:
    return ["flatpak", "remote-delete", "--force", f"--{installation}", name]

def cmd_toggle_remote(name: str, enable: bool, installation: str = "system") -> list[str]:
    return ["flatpak", "remote-modify", f"--{installation}",
            "--enable" if enable else "--disable", name]

def cmd_install_flatpakref(path: str) -> list[str]:
    """Install a local .flatpakref (``--from``) or single-file .flatpak bundle (``--bundle``)."""
    kind = bundle_kind(path)
    if kind == "bundle":
        return ["flatpak", "install", "-y", "--noninteractive", "--bundle", path]
    if kind == "repo":
        name = re.sub(r"[^A-Za-z0-9_.-]", "-", Path(path).stem) or "remote"
        return ["flatpak", "remote-add", "--if-not-exists", name, path]
    return ["flatpak", "install", "-y", "--noninteractive", "--from", path]

def cmd_grant_filesystem_override(app_id: str, fs_path: str, *, user: bool = True) -> list[str]:
    return ["flatpak", "override", *(["--user"] if user else []), f"--filesystem={fs_path}", app_id]

def cmd_revoke_filesystem_override(app_id: str, fs_path: str, *, user: bool = True) -> list[str]:
    return ["flatpak", "override", *(["--user"] if user else []), f"--nofilesystem={fs_path}",
            app_id]

def cmd_reset_overrides(app_id: str, *, user: bool = True) -> list[str]:
    return ["flatpak", "override", *(["--user"] if user else []), "--reset", app_id]
