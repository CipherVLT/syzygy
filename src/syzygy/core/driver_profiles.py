"""GPU driver profiles shown under a device's “Available Profiles” – pure logic, no Qt."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from dataclasses import dataclass

from syzygy.core.system import runner


def _dnf() -> str:
    return "dnf5" if shutil.which("dnf5") else "dnf"


@dataclass(frozen=True)
class DriverProfile:
    id: str
    title: str
    vendor: str  # "nvidia" | "amd" | "intel" | "any"
    package: str  # package whose presence means "installed"
    repository: str
    license: str
    description: str
    requires_repo: str = ""  # "rpmfusion-free" | "rpmfusion-nonfree" | ""
    install: Callable[[], list[str]] | None = None
    remove: Callable[[], list[str]] | None = None
    note: str = ""
    planned: bool = False


@dataclass(frozen=True)
class ProfileState:
    profile: DriverProfile
    installed: bool
    installed_version: str
    available: bool
    reason: str = ""


PROFILES: tuple[DriverProfile, ...] = (
    DriverProfile(
        id="nvidia-akmod",
        title="NVIDIA proprietary driver (akmod)",
        vendor="nvidia",
        package="akmod-nvidia",
        repository="RPM Fusion (Nonfree)",
        license="proprietary",
        description="Kernel module rebuilt automatically for every new kernel, plus CUDA/NVENC "
                    "userspace (xorg-x11-drv-nvidia-cuda).",
        requires_repo="rpmfusion-nonfree",
        install=lambda: [_dnf(), "install", "-y", "akmod-nvidia", "xorg-x11-drv-nvidia-cuda"],
        remove=lambda: [_dnf(), "remove", "-y", "akmod-nvidia", "xorg-x11-drv-nvidia-cuda",
                        "xorg-x11-drv-nvidia"],
        note="After installing, wait until `modinfo -F version nvidia` prints a version "
             "(the module builds in the background, ~5 min) before rebooting. With Secure Boot "
             "enabled the akmods key must be enrolled with mokutil.",
    ),
    DriverProfile(
        id="nvidia-run",
        title="NVIDIA official .run installer",
        vendor="nvidia",
        package="",
        repository="nvidia.com",
        license="proprietary",
        description="Install the driver straight from NVIDIA's .run package (newest releases, "
                    "independent of RPM Fusion).",
        planned=True,
        note="Planned for a future Syzygy release.",
    ),
    DriverProfile(
        id="mesa-freeworld",
        title="Mesa VA-API freeworld (HW video decode)",
        vendor="amd",
        package="mesa-va-drivers-freeworld",
        repository="RPM Fusion (Free)",
        license="MIT",
        description="Replaces Fedora's mesa-va-drivers with the build that includes H.264/HEVC "
                    "hardware decoding for AMD GPUs.",
        requires_repo="rpmfusion-free",
        install=lambda: [_dnf(), "swap", "-y", "mesa-va-drivers", "mesa-va-drivers-freeworld"],
        remove=lambda: [_dnf(), "swap", "-y", "mesa-va-drivers-freeworld", "mesa-va-drivers"],
    ),
    DriverProfile(
        id="intel-media",
        title="Intel media driver (full codecs)",
        vendor="intel",
        package="intel-media-driver",
        repository="RPM Fusion (Nonfree)",
        license="MIT",
        description="Full-featured iHD VA-API driver for Broadwell and newer, replacing Fedora's "
                    "codec-limited libva-intel-media-driver.",
        requires_repo="rpmfusion-nonfree",
        install=lambda: [_dnf(), "swap", "-y", "libva-intel-media-driver",
                         "intel-media-driver", "--allowerasing"],
        remove=lambda: [_dnf(), "swap", "-y", "intel-media-driver", "libva-intel-media-driver",
                        "--allowerasing"],
    ),
)


def gpu_vendor(vendor_id: str, description: str = "") -> str:
    vid = vendor_id.lower()
    if vid == "10de" or "nvidia" in description.lower():
        return "nvidia"
    if vid == "1002" or "amd" in description.lower() or "ati " in description.lower():
        return "amd"
    if vid == "8086" or "intel" in description.lower():
        return "intel"
    return "other"


def profiles_for(vendor: str) -> list[DriverProfile]:
    return [p for p in PROFILES if p.vendor in (vendor, "any")]


def _installed_versions(names: list[str]) -> dict[str, str]:
    names = [n for n in names if n]
    if not names:
        return {}
    result = runner.run(["rpm", "-q", "--qf", "%{NAME}\t%{VERSION}\n", *names], timeout=15)
    versions: dict[str, str] = {}
    for line in result.stdout.splitlines():
        name, _, version = line.partition("\t")
        if name in names and version:
            versions[name] = version.strip()
    return versions


def profile_states(vendor: str) -> list[ProfileState]:
    profiles = profiles_for(vendor)
    repos = _installed_versions(["rpmfusion-free-release", "rpmfusion-nonfree-release"])
    versions = _installed_versions([p.package for p in profiles])
    states: list[ProfileState] = []
    for profile in profiles:
        installed = profile.package in versions
        available, reason = True, ""
        if profile.planned:
            available, reason = False, profile.note
        elif profile.requires_repo and f"{profile.requires_repo}-release" not in repos:
            available = installed  # can still remove what's there
            reason = f"Requires {profile.repository} – enable it in the Repos tab."
        states.append(ProfileState(profile, installed, versions.get(profile.package, ""),
                                   available, reason))
    return states
