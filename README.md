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
git clone https://github.com/CipherVLT/syzygy.git
cd syzygy
./build.sh          # installs system-wide (asks for your sudo password once)
syzygy              # or launch "Syzygy" from your app launcher
```

No git yet (fresh install)? Download the source archive instead:

```bash
curl -L https://github.com/CipherVLT/syzygy/archive/main.tar.gz | tar xz
cd syzygy-main && ./build.sh
```

After installing, the cloned folder is no longer needed: Syzygy lives in `/opt/syzygy`
with a launcher in `/usr/local/bin` and a desktop entry + icon in `/usr/local/share`.

**Updating** – no `git pull` required:

- In the app: **Maintenance → Syzygy → Update Syzygy** (shows when a newer version exists,
  offers a restart afterwards), or
- in a terminal: `sudo syzygy-update` (latest `main`), `sudo syzygy-update v0.3.0` (a tag).

**Other options**

| Command | What it does |
|---|---|
| `./build.sh --run` | install, then launch |
| `./build.sh --update` | same as `sudo syzygy-update` |
| `./build.sh --uninstall` | remove everything except your settings (`~/.config/Syzygy`) |
| `./build.sh --dev [--run]` | developer mode: editable install into `./.venv`, no sudo |

`make install`, `make run`, `make update`, `make uninstall`, `make dev`, `make dev-run`,
`make clean` wrap the same commands.

If Qt reports it cannot load the `xcb` platform plugin on X11, install
`sudo dnf install xcb-util-cursor`.

## Themes

Click the **◐** pill (top right) to cycle **Glass → Mocha → Latte**; the choice is remembered.

- **Glass** – translucent dark acrylic. Qt paints semi-transparent surfaces; the frosted
  *blur* comes from your Wayland compositor. Enable blur there (e.g. Hyprland:
  `decoration { blur { enabled = true } }`) and it applies to Syzygy (app-id `syzygy`).
  Without compositor blur it renders as tinted see-through glass.
- **Mocha / Latte** – opaque Catppuccin dark / light.
- `SYZYGY_GLASS=0 syzygy` starts with translucency disabled (for X11 without a compositor or
  if your desktop draws translucent windows badly).

Shortcuts: `Ctrl+F` search · `F5` refresh tab · `Alt+1…0` jump to tab ·
`Ctrl+Tab` / `Ctrl+PgDn` next tab · `Ctrl+Q` quit.

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

- **All 10 tabs implemented** – every system call runs off the UI thread; privileged RPM/boot
  actions go through `pkexec`, Flatpak and fwupd use their own polkit policies.
- **Core backend** (`syzygy.core`): pure Python, no Qt – unit-testable.
- **Shared UI**: `BasePage` (lazy loading, background queries, one-transaction-at-a-time),
  `TaskDialog` with live output, `PackageCard`, `ActionCard`, Catppuccin Mocha/Latte themes.
- Shortcuts: `Ctrl+F` search, `F5` refresh current tab, `Ctrl+Q` quit.
- Planned: NVIDIA driver setup via NVIDIA's official `.run` installer.

## License

MIT
