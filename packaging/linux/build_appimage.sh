#!/usr/bin/env bash
# packaging/linux/build_appimage.sh
#
# Builds muLLM-x86_64.AppImage — a self-contained Linux executable.
#
# Prerequisites:
#   - Python 3.11 installed at /usr/bin/python3.11 (or adjust PYTHON below)
#   - appimagetool in PATH — download from:
#       https://github.com/AppImage/AppImageKit/releases
#       wget -O appimagetool https://github.com/AppImage/AppImageKit/releases/download/continuous/appimagetool-x86_64.AppImage
#       chmod +x appimagetool && sudo mv appimagetool /usr/local/bin/
#
# Usage (from repo root):
#   bash packaging/linux/build_appimage.sh
#
# Output: muLLM-x86_64.AppImage

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
APPDIR="$REPO_ROOT/muLLM.AppDir"

# Detect Python 3.11+
PYTHON="${PYTHON:-$(command -v python3.11 2>/dev/null || command -v python3 2>/dev/null)}"
VERSION="$(cd "$REPO_ROOT" && "$PYTHON" -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
PYTHON_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "==> Using Python $PYTHON_VERSION at $PYTHON"

if [[ "$PYTHON_VERSION" < "3.11" ]]; then
    echo "ERROR: Python 3.11+ required (found $PYTHON_VERSION)"
    exit 1
fi

cd "$REPO_ROOT"

echo "==> Setting up AppDir structure…"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# ── Bundle Python (symlink to system Python to keep size down) ─────────────────
echo "==> Linking Python interpreter…"
cp "$PYTHON" "$APPDIR/usr/bin/python3"
# Copy required shared libraries
ldd "$PYTHON" | awk '/=> \// { print $3 }' | while read -r lib; do
    [ -f "$lib" ] && cp --no-clobber "$lib" "$APPDIR/usr/lib/" 2>/dev/null || true
done

# ── Install muLLM and dependencies into AppDir ─────────────────────────────────
echo "==> Installing muLLM $VERSION into AppDir…"
"$PYTHON" -m pip install \
    --target="$APPDIR/usr/lib/python3" \
    --no-warn-script-location \
    --quiet \
    "mullm==$VERSION"

# Also copy the repo's router/ in case this is a dev build
if [ -d "$REPO_ROOT/router" ]; then
    echo "==> Bundling local router/ (dev build)…"
    cp -r "$REPO_ROOT/router" "$APPDIR/usr/lib/python3/"
fi
if [ -d "$REPO_ROOT/config" ]; then
    cp -r "$REPO_ROOT/config" "$APPDIR/usr/lib/python3/"
fi

# ── Desktop file and icon ──────────────────────────────────────────────────────
echo "==> Installing desktop metadata…"
cp "$SCRIPT_DIR/mullm.desktop" "$APPDIR/"

# Icon: use SVG/PNG from repo if it exists, else write a minimal placeholder
ICON_SRC="$REPO_ROOT/router/static/icon.png"
if [ -f "$ICON_SRC" ]; then
    cp "$ICON_SRC" "$APPDIR/usr/share/icons/hicolor/256x256/apps/mullm.png"
    cp "$ICON_SRC" "$APPDIR/mullm.png"
else
    echo "  WARNING: No icon found at $ICON_SRC"
    echo "  Add a 256x256 PNG as router/static/icon.png to include a proper icon."
    # Create a 1x1 transparent PNG as placeholder so appimagetool doesn't fail
    printf '\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82' \
        > "$APPDIR/mullm.png"
    cp "$APPDIR/mullm.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/mullm.png"
fi

# ── AppRun entrypoint ─────────────────────────────────────────────────────────
echo "==> Writing AppRun…"
cat > "$APPDIR/AppRun" << 'APPRUN'
#!/bin/bash
# muLLM AppImage entry point
SELF_DIR="$(dirname "$(readlink -f "$0")")"
export PYTHONPATH="$SELF_DIR/usr/lib/python3:${PYTHONPATH:-}"
export PATH="$SELF_DIR/usr/bin:$PATH"
export LD_LIBRARY_PATH="$SELF_DIR/usr/lib:${LD_LIBRARY_PATH:-}"

# If no arguments, start the server and open the browser
if [ $# -eq 0 ]; then
    exec "$SELF_DIR/usr/bin/python3" -m router.main &
    SERVER_PID=$!
    sleep 2
    if command -v xdg-open &>/dev/null; then
        xdg-open http://localhost:6856/setup
    elif command -v firefox &>/dev/null; then
        firefox http://localhost:6856/setup
    fi
    wait "$SERVER_PID"
else
    exec "$SELF_DIR/usr/bin/python3" -m router.cli "$@"
fi
APPRUN
chmod +x "$APPDIR/AppRun"

# ── Build AppImage ─────────────────────────────────────────────────────────────
echo "==> Running appimagetool…"
OUTPUT="$REPO_ROOT/muLLM-${VERSION}-x86_64.AppImage"
ARCH=x86_64 appimagetool "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"

echo ""
echo "==> Done!"
echo "    Output: $OUTPUT"
echo ""
echo "    Test it:"
echo "      $OUTPUT                  # start server + open browser"
echo "      $OUTPUT --serve          # server only"
echo "      $OUTPUT --status         # health check"
echo ""
echo "    Install system-wide (optional):"
echo "      sudo cp $OUTPUT /usr/local/bin/mullm.AppImage"
echo "      sudo cp packaging/linux/mullm.desktop /usr/share/applications/"
