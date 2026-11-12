"""One-click system tweaks: definitions, live state detection, commands – pure logic, no Qt."""

from __future__ import annotations

import logging
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from syzygy.core.devices import get_secure_boot_state
from syzygy.core.system import runner

logger = logging.getLogger(__name__)

CPUINFO = Path("/proc/cpuinfo")
# x86-64-v3 = Haswell-class: the CachyOS COPR kernel is built for it.
_X86_64_V3_FLAGS = {"avx", "avx2", "bmi1", "bmi2", "f16c", "fma", "movbe", "xsave"}

GAMING_PACKAGES = ("steam", "lutris", "gamemode", "mangohud", "gamescope", "protontricks", "wine")
HYPRLAND_PACKAGES = ("hyprland", "waybar", "wofi", "swaync", "grim", "slurp", "wl-clipboard",
                     "xdg-desktop-portal-hyprland", "xdg-desktop-portal-gtk", "hyprpicker")


def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


# ---------------------------------------------------------------------- probes
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

def installed_rpms(names: tuple[str, ...]) -> set[str]:
    """One rpm call for many names instead of N subprocesses."""
    result = runner.run(["rpm", "-q", "--qf", "%{NAME}\n", *names], timeout=15)
    return {ln.strip() for ln in result.stdout.splitlines() if ln.strip() in names}

def is_flatpak_installed(app_id: str) -> bool:
    return runner.run(["flatpak", "info", app_id], timeout=8).returncode == 0

def is_dnf_fast_mirrors_enabled() -> bool:
    conf = Path("/etc/dnf/dnf.conf")
    if not conf.exists(): return False
    try:
        text = conf.read_text(encoding="utf-8", errors="ignore").lower()
        return "max_parallel_downloads" in text and "fastestmirror" in text
    except Exception: return False

def cpu_supports_x86_64_v3(cpuinfo: Path = CPUINFO) -> bool:
    try:
        for line in cpuinfo.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("flags"):
                flags = set(line.partition(":")[2].split())
                # lzcnt is reported as "abm" on many CPUs
                return _X86_64_V3_FLAGS <= flags and ("abm" in flags or "lzcnt" in flags)
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------- commands
def cmd_set_dnf_parallel_downloads() -> list[str]:
    script = r'''set -e
CONF=/etc/dnf/dnf.conf
if ! grep -q '^max_parallel_downloads=' "$CONF" 2>/dev/null; then echo 'max_parallel_downloads=10' >> "$CONF"
else sed -i 's/^max_parallel_downloads=.*/max_parallel_downloads=10/' "$CONF"; fi
if ! grep -q '^fastestmirror=' "$CONF" 2>/dev/null; then echo 'fastestmirror=True' >> "$CONF"
else sed -i 's/^fastestmirror=.*/fastestmirror=True/' "$CONF"; fi
echo "Updated $CONF:"; grep -E '^(max_parallel_downloads|fastestmirror)=' "$CONF"'''
    return ["bash", "-c", script]

def cmd_install_multimedia_codecs() -> list[str]:
    return [_dnf(), "swap", "-y", "ffmpeg-free", "ffmpeg", "--allowerasing"]

def cmd_install_gaming_meta() -> list[str]:
    return [_dnf(), "install", "-y", *GAMING_PACKAGES]

def cmd_install_protonup_qt() -> list[str]:
    return ["flatpak", "install", "-y", "--noninteractive", "flathub", "net.davidotek.pupgui2"]

def cmd_enable_cachyos_kernel() -> list[str]:
    return ["bash", "-c", f"set -e; {_dnf()} copr enable -y bieszczaders/kernel-cachyos; setsebool -P domain_kernel_load_modules 1; {_dnf()} install -y kernel-cachyos kernel-cachyos-devel-matched || {_dnf()} install -y kernel-cachyos"]

def cmd_install_hyprland_stack() -> list[str]:
    return ["bash", "-c", f"set -e; {_dnf()} copr enable -y solopasha/hyprland; {_dnf()} install -y {' '.join(HYPRLAND_PACKAGES)}"]


# ---------------------------------------------------------------------- registry
@dataclass(slots=True, frozen=True)
class TweakState:
    active: bool
    available: bool = True  # False → prerequisites missing; button disabled
    note: str = ""  # shown under the description (prerequisite / warning)
    warning: str = ""  # shown in the confirmation dialog


@dataclass(slots=True, frozen=True)
class Tweak:
    id: str
    title: str
    description: str
    action_label: str
    command: Callable[[], list[str]]
    use_pkexec: bool
    probe: Callable[[], TweakState]
    scopes: tuple[str, ...] = field(default=("packages",))


@dataclass(slots=True, frozen=True)
class _Env:
    rpmfusion_free: bool
    rpmfusion_nonfree: bool
    flathub: bool


def _env() -> _Env:
    present = installed_rpms(("rpmfusion-free-release", "rpmfusion-nonfree-release"))
    flathub = False
    if shutil.which("flatpak"):
        out = runner.run(["flatpak", "remotes", "--columns=name"], timeout=10).stdout
        flathub = "flathub" in {ln.strip() for ln in out.splitlines()}
    return _Env("rpmfusion-free-release" in present, "rpmfusion-nonfree-release" in present,
                flathub)


def _probe_parallel() -> TweakState:
    return TweakState(active=is_dnf_fast_mirrors_enabled())


def _probe_codecs(env: _Env) -> TweakState:
    if is_rpm_installed("ffmpeg"):
        return TweakState(active=True)
    if not env.rpmfusion_free:
        return TweakState(False, False, "Requires RPM Fusion Free – enable it in the Repos tab.")
    return TweakState(active=False)


def _probe_gaming(env: _Env) -> TweakState:
    present = installed_rpms(GAMING_PACKAGES)
    missing = [p for p in GAMING_PACKAGES if p not in present]
    if not missing:
        return TweakState(active=True)
    if not env.rpmfusion_nonfree:
        return TweakState(False, False,
                          "Steam comes from RPM Fusion Nonfree – enable it in the Repos tab.")
    note = f"Missing: {', '.join(missing)}" if present else ""
    return TweakState(active=False, note=note)


def _probe_protonup(env: _Env) -> TweakState:
    if shutil.which("flatpak") is None:
        return TweakState(False, False, "Flatpak is not installed.")
    if is_flatpak_installed("net.davidotek.pupgui2"):
        return TweakState(active=True)
    if not env.flathub:
        return TweakState(False, False, "Requires the Flathub remote – add it in the Repos tab.")
    return TweakState(active=False)


def _probe_cachyos() -> TweakState:
    if is_rpm_installed("kernel-cachyos"):
        return TweakState(active=True, note="Select it as default in the Kernels tab.")
    if not cpu_supports_x86_64_v3():
        return TweakState(False, False,
                          "This CPU lacks x86-64-v3 (AVX2) – the CachyOS kernel won't boot.")
    secure_boot = get_secure_boot_state()
    if secure_boot:
        return TweakState(
            active=False,
            note="Secure Boot is enabled: the CachyOS kernel is unsigned and won't boot "
                 "unless you disable Secure Boot or enroll your own key.",
            warning="Secure Boot is ENABLED. The CachyOS kernel is not signed by Fedora, so "
                    "it will not boot until Secure Boot is disabled or a MOK is enrolled. "
                    "Your current kernel stays installed and remains the safe default.",
        )
    return TweakState(active=False)


def _probe_hyprland() -> TweakState:
    present = installed_rpms(HYPRLAND_PACKAGES)
    if "hyprland" in present:
        missing = [p for p in HYPRLAND_PACKAGES if p not in present]
        return TweakState(active=True, note=f"Missing extras: {', '.join(missing)}" if missing
                          else "")
    return TweakState(active=False)


def build_registry(env_factory: Callable[[], _Env] = _env) -> list[Tweak]:
    env_cache: list[_Env] = []

    def env() -> _Env:
        if not env_cache:
            env_cache.append(env_factory())
        return env_cache[0]

    return [
        Tweak("dnf-speed", "Faster DNF downloads",
              "Sets max_parallel_downloads=10 and fastestmirror=True in /etc/dnf/dnf.conf.",
              "Apply", cmd_set_dnf_parallel_downloads, True, _probe_parallel, ("repos",)),
        Tweak("codecs", "Full multimedia codecs",
              "Swaps Fedora's patent-free ffmpeg-free for RPM Fusion's full ffmpeg "
              "(H.264/HEVC/AAC playback and encoding).",
              "Install", cmd_install_multimedia_codecs, True, lambda: _probe_codecs(env())),
        Tweak("gaming", "Gaming Meta",
              "Steam, Lutris, GameMode, MangoHud, Gamescope, Protontricks and Wine.",
              "Install", cmd_install_gaming_meta, True, lambda: _probe_gaming(env())),
        Tweak("protonup", "ProtonUp-Qt",
              "Install and update Proton-GE / Wine-GE builds for Steam and Lutris (Flatpak).",
              "Install", cmd_install_protonup_qt, False, lambda: _probe_protonup(env()),
              ("flatpak",)),
        Tweak("cachyos", "CachyOS kernel",
              "Performance-tuned kernel (BORE scheduler, x86-64-v3 build) from the "
              "bieszczaders/kernel-cachyos COPR. Your Fedora kernel stays installed.",
              "Install", cmd_enable_cachyos_kernel, True, _probe_cachyos,
              ("packages", "repos", "kernels")),
        Tweak("hyprland", "Hyprland desktop stack",
              "Hyprland compositor with Waybar, Wofi, SwayNC, screenshot tools and portals "
              "(solopasha/hyprland COPR). Pick it at the login screen afterwards.",
              "Install", cmd_install_hyprland_stack, True, _probe_hyprland,
              ("packages", "repos")),
    ]


def probe_all(registry: list[Tweak]) -> dict[str, TweakState]:
    states: dict[str, TweakState] = {}
    for tweak in registry:
        try:
            states[tweak.id] = tweak.probe()
        except Exception as exc:  # noqa: BLE001 – one broken probe must not hide the rest
            logger.exception("Probe %s failed", tweak.id)
            states[tweak.id] = TweakState(False, True, f"Could not detect state: {exc}")
    return states
