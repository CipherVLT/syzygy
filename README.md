# Syzygy

Modern package & system manager for Fedora Linux.

Built with **Python 3.11+** and **PySide6**.



## Features

| Tab | Description |
|-----|-------------|
| **Search** | Search & install RPM + Flatpak packages |
| **Installed** | Browse installed packages, user-installed filter |
| **Updates** | Check & apply RPM / Flatpak updates |
| **Flatpak** | Manage apps & runtimes, remove unused |
| **Maintenance** | Autoremove, clean cache, rebuild RPM DB, regenerate initramfs |
| **Repos** | Enable/disable repos, RPM Fusion, Flathub, COPR |
| **Kernels** | List kernels, set default, remove, upgrade |
| **Devices** | fwupd firmware updates + PCI hardware summary |
| **FPM** | Flatpak remotes, local bundles, permission overrides |
| **Tweaks** | DNF speed, codecs, Gaming Meta, ProtonUp-Qt, CachyOS, Hyprland |

## System Dependencies (Fedora)

```bash
sudo dnf install python3-pyside6 polkit flatpak fwupd grubby dracut
```

## Quick Start

```bash
# From source
python -m venv .venv
source .venv/bin/activate
pip install -e .
syzygy
```

## Architecture

```
src/syzygy/
├── core/          # Pure logic (no Qt) – dnf, flatpak, kernels, etc.
├── workers/       # QRunnable + Signals (non-blocking)
└── ui/
    ├── widgets/   # Reusable dialogs (TaskDialog)
    └── tabs/      # One file per tab
```

- All privileged actions use `pkexec` (PolicyKit)
- UI never blocks – long commands run in `QThreadPool`
- Catppuccin Mocha dark theme

## Project Status

- **Core backend modules**: Complete
- **Workers + TaskDialog**: Complete
- **Main window + theming**: Complete
- **Tab UIs**: Scaffold present; full vertical-slice implementations were developed in the original conversation and can be restored from there into `ui/tabs/*.py`

## License

MIT
