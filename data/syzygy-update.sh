#!/bin/sh
# Syzygy self-updater – installed by build.sh as @BINDIR@/syzygy-update.
#
#   syzygy-update            update to the latest commit of the configured branch (main)
#   syzygy-update v0.3.0     update to a specific branch or tag
#
# Downloads the source archive from GitHub (no git needed), reinstalls Syzygy into the private
# venv, and refreshes the launcher, desktop entry, icon and this updater.
set -eu

PREFIX="@PREFIX@"
BINDIR="@BINDIR@"
DATADIR="@DATADIR@"
VENV="$PREFIX/venv"

if [ "$(id -u)" -ne 0 ]; then
    if [ -t 0 ] && command -v sudo >/dev/null 2>&1; then
        exec sudo "$0" "$@"
    fi
    exec pkexec "$0" "$@"
fi

[ -x "$VENV/bin/python" ] || { echo "Syzygy is not installed in $PREFIX" >&2; exit 1; }

SOURCE=$(cat "$PREFIX/source" 2>/dev/null || echo "https://github.com/CipherVLT/syzygy")
REF=$(cat "$PREFIX/ref" 2>/dev/null || echo "main")
REF="${1:-$REF}"
case "$SOURCE" in
    https://github.com/*) ;;
    *) echo "Unsupported update source: $SOURCE" >&2; exit 1 ;;
esac
URL="$SOURCE/archive/$REF.tar.gz"

OLD=$("$VENV/bin/python" -c 'import syzygy; print(syzygy.__version__)' 2>/dev/null || echo "?")
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "==> Downloading $URL"
curl -fsSL --retry 3 -o "$WORK/src.tar.gz" "$URL"
mkdir "$WORK/src"
tar -xzf "$WORK/src.tar.gz" -C "$WORK/src" --strip-components=1

echo "==> Installing into $VENV"
"$VENV/bin/python" -m pip install --disable-pip-version-check -q --upgrade --force-reinstall \
    --no-deps "$WORK/src"
"$VENV/bin/python" -m pip install --disable-pip-version-check -q \
    --upgrade-strategy only-if-needed "$WORK/src"

echo "==> Refreshing desktop entry, icon and updater"
if [ -f "$WORK/src/data/syzygy.desktop" ]; then
    sed -e "s|^Exec=.*|Exec=$BINDIR/syzygy|" -e "s|^Icon=.*|Icon=syzygy|" \
        "$WORK/src/data/syzygy.desktop" > "$DATADIR/applications/syzygy.desktop"
fi
if [ -f "$WORK/src/data/syzygy.svg" ]; then
    install -m 644 "$WORK/src/data/syzygy.svg" "$DATADIR/icons/hicolor/scalable/apps/syzygy.svg"
fi
if [ -f "$WORK/src/data/syzygy-update.sh" ]; then
    # Replace via rename: a running shell script must never be overwritten in place.
    # Placeholders are spelled indirectly so build.sh's substitution can't rewrite them here.
    A="@"
    sed -e "s|${A}PREFIX${A}|$PREFIX|g" -e "s|${A}BINDIR${A}|$BINDIR|g" \
        -e "s|${A}DATADIR${A}|$DATADIR|g" \
        "$WORK/src/data/syzygy-update.sh" > "$BINDIR/.syzygy-update.new"
    chmod 755 "$BINDIR/.syzygy-update.new"
    mv -f "$BINDIR/.syzygy-update.new" "$BINDIR/syzygy-update"
fi

NEW=$("$VENV/bin/python" -c 'import syzygy; print(syzygy.__version__)' 2>/dev/null || echo "?")
echo "✔  Syzygy updated: $OLD → $NEW ($REF). Restart Syzygy to use the new version."
