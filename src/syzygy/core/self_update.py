"""How Syzygy itself is installed, and how to update it – pure logic, no Qt."""

from __future__ import annotations

import logging
import re
import shutil
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import syzygy

logger = logging.getLogger(__name__)

MODE_SYSTEM = "system"  # ./build.sh → /opt/syzygy/venv, updated by syzygy-update
MODE_DEV = "dev"  # ./build.sh --dev → editable install inside a git checkout
MODE_OTHER = "other"  # pip install somewhere else

DEFAULT_SOURCE = "https://github.com/CipherVLT/syzygy"
_VERSION_RE = re.compile(r"""__version__\s*=\s*["']([^"']+)["']""")


@dataclass(slots=True, frozen=True)
class InstallInfo:
    mode: str
    version: str
    prefix: Path | None = None  # /opt/syzygy for system installs
    checkout: Path | None = None  # git checkout for dev installs
    source: str = DEFAULT_SOURCE
    ref: str = "main"
    updater: str | None = None  # absolute path to syzygy-update


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def get_install_info(
    venv_prefix: Path | None = None, package_file: Path | None = None
) -> InstallInfo:
    venv = Path(venv_prefix or sys.prefix)
    pkg = Path(package_file or syzygy.__file__).resolve()
    version = getattr(syzygy, "__version__", "?")

    # System install: <prefix>/venv with <prefix>/source written by build.sh
    prefix = venv.parent
    if venv.name == "venv" and (prefix / "source").exists():
        updater = shutil.which("syzygy-update")
        return InstallInfo(
            mode=MODE_SYSTEM, version=version, prefix=prefix,
            source=_read(prefix / "source") or DEFAULT_SOURCE,
            ref=_read(prefix / "ref") or "main",
            updater=updater,
        )

    # Editable install from a checkout: …/src/syzygy/__init__.py with .git two levels up
    for parent in pkg.parents:
        if (parent / ".git").exists() and (parent / "pyproject.toml").exists():
            return InstallInfo(mode=MODE_DEV, version=version, checkout=parent)
    return InstallInfo(mode=MODE_OTHER, version=version)


def latest_version(info: InstallInfo, timeout: float = 8.0) -> str | None:
    """Read ``__version__`` of the configured branch on GitHub (None if unreachable)."""
    if not info.source.startswith("https://github.com/"):
        return None
    repo = info.source.removeprefix("https://github.com/").strip("/")
    url = f"https://raw.githubusercontent.com/{repo}/{info.ref}/src/syzygy/__init__.py"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 – fixed https
            text = response.read(4096).decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001 – offline is normal
        logger.info("Version check failed: %s", exc)
        return None
    match = _VERSION_RE.search(text)
    return match.group(1) if match else None


def cmd_self_update(info: InstallInfo) -> list[str]:
    """Run the system updater (it needs root; run with pkexec)."""
    if info.updater is None:
        raise RuntimeError("syzygy-update not found")
    return [info.updater]
