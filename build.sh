#!/usr/bin/env bash
# Syzygy bootstrap: create .venv, install the project in editable mode, optionally launch it.
#
#   ./build.sh            create/update .venv and install
#   ./build.sh --run      ... then launch Syzygy
#   ./build.sh --desktop  ... and install a desktop launcher for the current user
#   ./build.sh --run -- --some-app-arg   (everything after -- is passed to the app)
#
# Environment overrides:
#   PYTHON=/usr/bin/python3.13 ./build.sh    pick a specific interpreter for the venv
set -euo pipefail

ROOT="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
VENV="$ROOT/.venv"
MIN_PY_MAJOR=3
MIN_PY_MINOR=11
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
Usage: ./build.sh [--run] [--desktop] [-- APP_ARGS...]

  (no args)   Create .venv if missing, upgrade pip, pip install -e .
  --run       Launch Syzygy after a successful install
  --desktop   Install a launcher into ~/.local/share/applications (fixes the portal
              "App info not found for 'syzygy'" warning and shows Syzygy in the app grid)
  -h, --help  Show this help

Set PYTHON=/path/to/python3.x to choose the interpreter (needs >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR}).
EOF
}

while (($#)); do
    case "$1" in
        --run) RUN=1 ;;
        --desktop) DESKTOP=1 ;;
        -h|--help) usage; exit 0 ;;
        --) shift; APP_ARGS=("$@"); break ;;
        *) usage >&2; die "Unknown argument: $1" ;;
    esac
    shift
done

cd "$ROOT"
[[ -f pyproject.toml ]] || die "pyproject.toml not found in $ROOT"

py_ok() {
    "$1" -c "import sys; sys.exit(0 if sys.version_info >= ($MIN_PY_MAJOR, $MIN_PY_MINOR) else 1)" \
        2>/dev/null
}

find_python() {
    if [[ -n "${PYTHON:-}" ]]; then
        command -v "$PYTHON" >/dev/null 2>&1 || die "PYTHON=$PYTHON not found"
        py_ok "$PYTHON" || die "PYTHON=$PYTHON is older than ${MIN_PY_MAJOR}.${MIN_PY_MINOR}"
        echo "$PYTHON"; return
    fi
    local candidate
    for candidate in python3.14 python3.13 python3.12 python3.11 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && py_ok "$candidate"; then
            echo "$candidate"; return
        fi
    done
    die "Python >= ${MIN_PY_MAJOR}.${MIN_PY_MINOR} not found (on Fedora: sudo dnf install python3)"
}

# --- 1. virtualenv ---------------------------------------------------------------------------
if [[ -x "$VENV/bin/python" ]] && ! py_ok "$VENV/bin/python"; then
    die ".venv exists but its Python is broken or too old – run 'make clean' and retry"
fi

if [[ ! -x "$VENV/bin/python" ]]; then
    PY="$(find_python)"
    info "Creating virtualenv in .venv using $("$PY" --version 2>&1)"
    "$PY" -m venv "$VENV" || die "Failed to create .venv (is the python3 venv module installed?)"
    ok "Created .venv"
else
    info "Using existing .venv ($("$VENV/bin/python" --version 2>&1))"
fi

VPY="$VENV/bin/python"

# --- 2. install ------------------------------------------------------------------------------
info "Upgrading pip"
"$VPY" -m pip install -U pip || die "pip upgrade failed (check your network connection)"

info "Installing Syzygy in editable mode (pip install -e .)"
"$VPY" -m pip install -e . || die "pip install -e . failed – see the output above"

"$VPY" -c "import syzygy, PySide6" 2>/dev/null \
    || die "Install finished but 'import syzygy, PySide6' fails inside .venv"

ok "Syzygy installed into .venv"
printf '   Launch with: %s./build.sh --run%s  or  %s.venv/bin/syzygy%s\n' \
    "$C_INFO" "$C_RST" "$C_INFO" "$C_RST"

# --- 3. desktop launcher (optional) ---------------------------------------------------------
if ((DESKTOP)); then
    APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    mkdir -p "$APPS_DIR"
    # Point Exec at this checkout's venv so the launcher works without activating anything.
    sed "s|^Exec=.*|Exec=$VENV/bin/syzygy|" "$ROOT/data/syzygy.desktop" > "$APPS_DIR/syzygy.desktop" \
        || die "Could not write $APPS_DIR/syzygy.desktop"
    command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database "$APPS_DIR" || true
    ok "Desktop launcher installed: $APPS_DIR/syzygy.desktop"
fi

# --- 4. run ----------------------------------------------------------------------------------
if ((RUN)); then
    if [[ -z "${WAYLAND_DISPLAY:-}" && -z "${DISPLAY:-}" ]]; then
        warn "No WAYLAND_DISPLAY or DISPLAY set – Qt may fail to open a window"
    fi
    info "Launching Syzygy"
    if [[ -x "$VENV/bin/syzygy" ]]; then
        exec "$VENV/bin/syzygy" "${APP_ARGS[@]}"
    fi
    exec "$VPY" -m syzygy "${APP_ARGS[@]}"
fi
