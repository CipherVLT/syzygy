#!/usr/bin/env bash
# Syzygy installer.
#
#   ./build.sh                 install system-wide (default) – the checkout can be deleted after
#   ./build.sh --run           ... and launch it
#   ./build.sh --update        update the system install straight from GitHub (no git pull)
#   ./build.sh --uninstall     remove the system install
#   ./build.sh --dev [--run]   developer mode: editable install into ./.venv
#   ./build.sh --dev --desktop ... plus a per-user launcher pointing at ./.venv
#
# System layout (no files are written outside these):
#   /opt/syzygy/venv                         private Python environment with Syzygy + PySide6
#   /opt/syzygy/source, /opt/syzygy/ref      where `syzygy-update` fetches new versions from
#   /usr/local/bin/syzygy                    launcher
#   /usr/local/bin/syzygy-update             updater (also used by Maintenance → Update Syzygy)
#   /usr/local/share/applications/syzygy.desktop
#   /usr/local/share/icons/hicolor/scalable/apps/syzygy.svg
#
# Environment overrides: PYTHON=python3.13, SYZYGY_PREFIX=/opt/syzygy, SYZYGY_BINDIR=/usr/local/bin,
# SYZYGY_DATADIR=/usr/local/share, SYZYGY_REF=main (branch/tag used by updates).
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
DEV_VENV="$ROOT/.venv"
PREFIX="${SYZYGY_PREFIX:-/opt/syzygy}"
BINDIR="${SYZYGY_BINDIR:-/usr/local/bin}"
DATADIR="${SYZYGY_DATADIR:-/usr/local/share}"
DEFAULT_SOURCE="https://github.com/CipherVLT/syzygy"
REF="${SYZYGY_REF:-main}"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11

MODE=system   # system | dev | update | uninstall

case "$PREFIX" in
    */syzygy|*/syzygy/) ;;
    *) printf 'Refusing SYZYGY_PREFIX=%s – it must end in /syzygy\n' "$PREFIX" >&2; exit 1 ;;
esac
RUN=0
DESKTOP=0
APP_ARGS=()

if [[ -t 1 ]]; then
    C_OK=$'\e[1;32m' C_ERR=$'\e[1;31m' C_INFO=$'\e[1;34m' C_WARN=$'\e[1;33m' C_RST=$'\e[0m'
else
    C_OK="" C_ERR="" C_INFO="" C_WARN="" C_RST=""
fi

info() { printf '%s==>%s %s\n' "$C_INFO" "$C_RST" "$*"; }
ok()   { printf '%s✔%s  %s\n' "$C_OK" "$C_RST" "$*"; }
warn() { printf '%s!%s  %s\n' "$C_WARN" "$C_RST" "$*" >&2; }
die()  { printf '%s✘  %s%s\n' "$C_ERR" "$*" "$C_RST" >&2; exit 1; }

usage() {
    cat <<EOF
Usage: ./build.sh [--run] [--update | --uninstall | --dev [--desktop]] [-- APP_ARGS...]

  (no args)    Install Syzygy system-wide into $PREFIX (asks for your sudo password)
  --run        Launch Syzygy after installing
  --update     Update the system install to the latest '$REF' from GitHub
  --uninstall  Remove the system install
  --dev        Developer mode: editable install into ./.venv (no sudo)
  --desktop    With --dev: add a per-user app-grid launcher for ./.venv
  -h, --help   Show this help
EOF
}

while (($#)); do
    case "$1" in
        --run) RUN=1 ;;
        --dev) MODE=dev ;;
        --update) MODE=update ;;
        --uninstall) MODE=uninstall ;;
        --desktop) DESKTOP=1 ;;
        -h|--help) usage; exit 0 ;;
        --) shift; APP_ARGS=("$@"); break ;;
        *) usage >&2; die "Unknown argument: $1" ;;
    esac
    shift
done

cd "$ROOT"

# --- helpers ---------------------------------------------------------------------------------
py_ok() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" \
        2>/dev/null
}

find_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        command -v "$PYTHON" >/dev/null 2>&1 || die "PYTHON=$PYTHON not found"
        py_ok "$PYTHON" || die "PYTHON=$PYTHON is older than ${MIN_PY_MAJOR}.${MIN_PY_MINOR}"
        command -v "$PYTHON"; return
    fi
    local candidate
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && py_ok "$candidate"; then
            command -v "$candidate"; return
        fi
    done
    die "Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR} not found (on Fedora: sudo dnf install python3)"
}

SUDO=()
need_root() {
    if [[ $EUID -ne 0 ]]; then
        command -v sudo >/dev/null 2>&1 || die "sudo is required for a system-wide install"
        info "Administrator rights are needed to write to $PREFIX and $BINDIR"
        sudo -v || die "sudo authentication failed"
        SUDO=(sudo)
    fi
}

as_root() { "${SUDO[@]}" "$@"; }

source_url() {
    local url
    url="$(git -C "$ROOT" remote get-url origin 2>/dev/null || true)"
    case "$url" in
        git@github.com:*) url="https://github.com/${url#git@github.com:}" ;;
    esac
    url="${url%.git}"
    [[ "$url" == https://* ]] && echo "$url" || echo "$DEFAULT_SOURCE"
}

check_display() {
    if [[ -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
        warn "No WAYLAND_DISPLAY or DISPLAY set – Qt may fail to open a window"
    fi
}

# --- uninstall -------------------------------------------------------------------------------
if [[ $MODE == uninstall ]]; then
    need_root
    info "Removing Syzygy from $PREFIX, $BINDIR and $DATADIR"
    as_root rm -rf "$PREFIX"
    as_root rm -f "$BINDIR/syzygy" "$BINDIR/syzygy-update" \
        "$DATADIR/applications/syzygy.desktop" \
        "$DATADIR/icons/hicolor/scalable/apps/syzygy.svg"
    command -v update-desktop-database >/dev/null 2>&1 \
        && as_root update-desktop-database "$DATADIR/applications" 2>/dev/null || true
    ok "Syzygy uninstalled (your settings in ~/.config/Syzygy were kept)"
    exit 0
fi

# --- update ----------------------------------------------------------------------------------
if [[ $MODE == update ]]; then
    [[ -x "$BINDIR/syzygy-update" ]] || die "No system install found – run ./build.sh first"
    "$BINDIR/syzygy-update" || die "Update failed – see the output above"
    if ((RUN)); then check_display; exec "$BINDIR/syzygy" "${APP_ARGS[@]}"; fi
    exit 0
fi

# --- developer mode (editable ./.venv) -------------------------------------------------------
if [[ $MODE == dev ]]; then
    [[ -f pyproject.toml ]] || die "pyproject.toml not found in $ROOT"
    if [[ -x "$DEV_VENV/bin/python" ]] && ! py_ok "$DEV_VENV/bin/python"; then
        die ".venv exists but its Python is broken or too old – run 'make clean' and retry"
    fi
    if [[ ! -x "$DEV_VENV/bin/python" ]]; then
        PY="$(find_python)"
        info "Creating .venv using $("$PY" --version 2>&1)"
        "$PY" -m venv "$DEV_VENV" || die "Failed to create .venv"
    fi
    VPY="$DEV_VENV/bin/python"
    info "Upgrading pip"
    "$VPY" -m pip install -q -U pip || die "pip upgrade failed (check your network connection)"
    info "Installing Syzygy in editable mode (pip install -e .)"
    "$VPY" -m pip install -e . || die "pip install -e . failed – see the output above"
    "$VPY" -c "import syzygy, PySide6" 2>/dev/null \
        || die "Install finished but 'import syzygy, PySide6' fails inside .venv"
    ok "Developer install ready in .venv (code changes apply immediately)"

    if ((DESKTOP)); then
        APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
        mkdir -p "$APPS_DIR"
        sed "s|^Exec=.*|Exec=$DEV_VENV/bin/syzygy|" "$ROOT/data/syzygy.desktop" \
            > "$APPS_DIR/syzygy.desktop" || die "Could not write $APPS_DIR/syzygy.desktop"
        ok "Per-user launcher installed: $APPS_DIR/syzygy.desktop"
    fi
    if ((RUN)); then
        check_display
        info "Launching Syzygy (dev)"
        exec "$DEV_VENV/bin/syzygy" "${APP_ARGS[@]}"
    fi
    exit 0
fi

# --- system install (default) ----------------------------------------------------------------
[[ -f pyproject.toml ]] || die "pyproject.toml not found in $ROOT"
PY="$(find_python)"
need_root
VENV="$PREFIX/venv"

if [[ -x "$VENV/bin/python" ]] && ! py_ok "$VENV/bin/python"; then
    warn "Existing $VENV uses a broken/old Python – recreating it"
    as_root rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
    info "Creating $VENV using $("$PY" --version 2>&1)"
    as_root mkdir -p "$PREFIX"
    as_root "$PY" -m venv "$VENV" || die "Failed to create $VENV"
fi

info "Upgrading pip"
as_root "$VENV/bin/python" -m pip install -q -U pip \
    || die "pip upgrade failed (check your network connection)"

# Build from a private copy so root never writes into (or leaves root-owned files in) the
# user's checkout, and the checkout can be deleted afterwards.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
tar -C "$ROOT" --exclude=.git --exclude=.venv --exclude='__pycache__' --exclude='*.egg-info' \
    --exclude=build --exclude=dist -cf - . | tar -C "$STAGE" -xf -
chmod -R a+rX "$STAGE"

info "Installing Syzygy into $VENV"
as_root "$VENV/bin/python" -m pip install --upgrade --force-reinstall --no-deps "$STAGE" \
    || die "pip install failed – see the output above"
as_root "$VENV/bin/python" -m pip install --upgrade-strategy only-if-needed "$STAGE" \
    || die "Installing dependencies (PySide6) failed – see the output above"
as_root "$VENV/bin/python" -c "import syzygy, PySide6" 2>/dev/null \
    || die "Install finished but 'import syzygy, PySide6' fails in $VENV"

SOURCE="$(source_url)"
printf '%s\n' "$SOURCE" | as_root tee "$PREFIX/source" >/dev/null
printf '%s\n' "$REF" | as_root tee "$PREFIX/ref" >/dev/null

info "Installing launcher, updater, desktop entry and icon"
as_root install -d "$BINDIR" "$DATADIR/applications" "$DATADIR/icons/hicolor/scalable/apps"
as_root tee "$BINDIR/syzygy" >/dev/null <<EOF
#!/bin/sh
# Syzygy launcher (installed by build.sh)
exec "$VENV/bin/syzygy" "\$@"
EOF
as_root sed -e "s|@PREFIX@|$PREFIX|g" -e "s|@BINDIR@|$BINDIR|g" -e "s|@DATADIR@|$DATADIR|g" \
    "$ROOT/data/syzygy-update.sh" \
    | as_root tee "$BINDIR/syzygy-update" >/dev/null
as_root chmod 755 "$BINDIR/syzygy" "$BINDIR/syzygy-update"
sed -e "s|^Exec=.*|Exec=$BINDIR/syzygy|" -e "s|^Icon=.*|Icon=syzygy|" "$ROOT/data/syzygy.desktop" \
    | as_root tee "$DATADIR/applications/syzygy.desktop" >/dev/null
as_root install -m 644 "$ROOT/data/syzygy.svg" "$DATADIR/icons/hicolor/scalable/apps/syzygy.svg"
command -v update-desktop-database >/dev/null 2>&1 \
    && as_root update-desktop-database "$DATADIR/applications" 2>/dev/null || true
command -v gtk-update-icon-cache >/dev/null 2>&1 \
    && as_root gtk-update-icon-cache -q -t "$DATADIR/icons/hicolor" 2>/dev/null || true

# A per-user launcher from an old `--dev --desktop` run would shadow the system one.
USER_DESKTOP="${XDG_DATA_HOME:-$HOME/.local/share}/applications/syzygy.desktop"
if [[ -f "$USER_DESKTOP" ]] && grep -q "/.venv/bin/syzygy" "$USER_DESKTOP"; then
    rm -f "$USER_DESKTOP"
    info "Removed old per-user dev launcher ($USER_DESKTOP)"
fi

VERSION="$("$VENV/bin/python" -c 'import syzygy; print(syzygy.__version__)' 2>/dev/null || echo "?")"
ok "Syzygy $VERSION installed system-wide"
printf '   Launch:  %ssyzygy%s  (or from your app launcher)\n' "$C_INFO" "$C_RST"
printf '   Update:  %ssudo syzygy-update%s  or Maintenance → Update Syzygy\n' "$C_INFO" "$C_RST"
printf '   Remove:  %s./build.sh --uninstall%s\n' "$C_INFO" "$C_RST"
[[ ":$PATH:" == *":$BINDIR:"* ]] || warn "$BINDIR is not on your PATH"

if ((RUN)); then
    check_display
    info "Launching Syzygy"
    exec "$BINDIR/syzygy" "${APP_ARGS[@]}"
fi
