from __future__ import annotations
import logging
from dataclasses import dataclass
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

@dataclass(slots=True, frozen=True)
class FlatpakRemote:
    name: str
    title: str = ""
    url: str = ""
    options: str = ""
    is_enabled: bool = True

def list_flatpak_remotes() -> list[FlatpakRemote]:
    result = runner.run(["flatpak", "remotes", "--show-disabled", "--columns=name,title,url,options"], timeout=15)
    remotes: list[FlatpakRemote] = []
    for line in result.stdout.splitlines():
        if not line.strip() or line.lower().startswith("name"): continue
        parts = line.split("\t")
        if len(parts) < 1: continue
        name = parts[0].strip()
        title = parts[1].strip() if len(parts)>1 else ""
        url = parts[2].strip() if len(parts)>2 else ""
        options = parts[3].strip() if len(parts)>3 else ""
        is_enabled = "disabled" not in options.lower()
        remotes.append(FlatpakRemote(name=name, title=title or name, url=url, options=options, is_enabled=is_enabled))
    return remotes

def get_app_overrides(app_id: str) -> str:
    if not app_id: return ""
    result = runner.run(["flatpak", "override", "--show", app_id], timeout=10)
    return result.stdout.strip() or "(no overrides)"

def cmd_add_remote(name: str, url: str) -> list[str]:
    return ["flatpak", "remote-add", "--if-not-exists", name, url]

def cmd_remove_remote(name: str) -> list[str]:
    return ["flatpak", "remote-delete", "--force", name]

def cmd_toggle_remote(name: str, enable: bool) -> list[str]:
    return ["flatpak", "remote-modify", "--enable" if enable else "--disable", name]

def cmd_install_flatpakref(path: str) -> list[str]:
    return ["flatpak", "install", "-y", path]

def cmd_grant_filesystem_override(app_id: str, fs_path: str) -> list[str]:
    return ["flatpak", "override", f"--filesystem={fs_path}", app_id]

def cmd_reset_overrides(app_id: str) -> list[str]:
    return ["flatpak", "override", "--reset", app_id]
