from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Optional


class PackageSource(Enum):
    DNF = auto()
    FLATPAK = auto()
    COPR = auto()
    LOCAL = auto()
    UNKNOWN = auto()


class PackageStatus(Enum):
    INSTALLED = auto()
    AVAILABLE = auto()
    UPDATABLE = auto()
    REMOVED = auto()
    UNKNOWN = auto()


@dataclass(slots=True, frozen=True)
class Package:
    name: str
    version: str
    summary: str = ""
    source: PackageSource = PackageSource.UNKNOWN
    status: PackageStatus = PackageStatus.UNKNOWN
    repo: str = ""
    size: Optional[str] = None
    arch: str = ""
    app_id: Optional[str] = None
    branch: Optional[str] = None
    runtime: Optional[str] = None
    # Flatpak installation the ref lives in ("system" / "user"); empty when unknown / RPM.
    installation: str = ""


@dataclass(slots=True, frozen=True)
class Repository:
    id: str
    name: str
    enabled: bool
    url: Optional[str] = None
    metalink: Optional[str] = None
    file_path: Optional[Path] = None
    description: str = ""


@dataclass(slots=True, frozen=True)
class KernelPackage:
    name: str
    version: str
    vendor: str
    summary: str = ""
    available: bool = True


class SchedulerType(Enum):
    CFS = "cfs"
    SCX = "scx"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class SchedulerInfo:
    current: str
    available: list[str] = field(default_factory=list)
    extra_flags: str = ""


@dataclass(slots=True, frozen=True)
class DeviceInfo:
    name: str
    bus_id: str
    vendor_id: str
    device_id: str
    driver: str
    driver_version: str = ""
    enabled: bool = False
    started: bool = False
    class_name: str = ""


@dataclass(slots=True)
class CommandResult:
    success: bool
    returncode: int
    stdout: str
    stderr: str
    command: list[str]
    timed_out: bool = False
    error_message: Optional[str] = None
