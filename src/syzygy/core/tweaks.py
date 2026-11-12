from __future__ import annotations
import logging, shutil
from pathlib import Path
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"

def is_copr_enabled(copr_slug: str) -> bool:
    safe = copr_slug.replace("/", ":")
    repo_dir = Path("/etc/yum.repos.d")
    if not repo_dir.exists(): return False
    for path in repo_dir.glob("*.repo"):
        name = path.name.lower()
        if safe.lower() in name or copr_slug.lower().replace("/", ".") in name: return True
        try:
            if copr_slug.lower() in path.read_text(encoding="utf-8", errors="ignore").lower(): return True
        except Exception: continue
    return False

def is_rpm_installed(pkg: str) -> bool:
    return runner.run(["rpm", "-q", pkg], timeout=8).returncode == 0

def is_flatpak_installed(app_id: str) -> bool:
    return runner.run(["flatpak", "info", app_id], timeout=8).returncode == 0

def is_dnf_fast_mirrors_enabled() -> bool:
    conf = Path("/etc/dnf/dnf.conf")
    if not conf.exists(): return False
    try:
        text = conf.read_text(encoding="utf-8", errors="ignore").lower()
        return "max_parallel_downloads" in text and "fastestmirror" in text
    except Exception: return False

def cmd_set_dnf_parallel_downloads() -> list[str]:
    script = r'''set -e
CONF=/etc/dnf/dnf.conf
if ! grep -q '^max_parallel_downloads=' "$CONF" 2>/dev/null; then echo 'max_parallel_downloads=10' >> "$CONF"
else sed -i 's/^max_parallel_downloads=.*/max_parallel_downloads=10/' "$CONF"; fi
if ! grep -q '^fastestmirror=' "$CONF" 2>/dev/null; then echo 'fastestmirror=True' >> "$CONF"
else sed -i 's/^fastestmirror=.*/fastestmirror=True/' "$CONF"; fi'''
    return ["bash", "-c", script]

def cmd_install_multimedia_codecs() -> list[str]:
    return [_dnf(), "swap", "-y", "ffmpeg-free", "ffmpeg", "--allowerasing"]

def cmd_install_gaming_meta() -> list[str]:
    return [_dnf(), "install", "-y", "steam", "lutris", "gamemode", "mangohud", "gamescope", "protontricks", "wine"]

def cmd_install_protonup_qt() -> list[str]:
    return ["flatpak", "install", "-y", "flathub", "net.davidotek.pupgui2"]

def cmd_enable_cachyos_kernel() -> list[str]:
    return ["bash", "-c", f"set -e; {_dnf()} copr enable -y bieszczaders/kernel-cachyos; setsebool -P domain_kernel_load_modules 1; {_dnf()} install -y kernel-cachyos kernel-cachyos-devel-matched || {_dnf()} install -y kernel-cachyos"]

def cmd_install_hyprland_stack() -> list[str]:
    return ["bash", "-c", f"set -e; {_dnf()} copr enable -y solopasha/hyprland; {_dnf()} install -y hyprland waybar wofi swaync grim slurp wl-clipboard xdg-desktop-portal-hyprland xdg-desktop-portal-gtk hyprpicker"]
