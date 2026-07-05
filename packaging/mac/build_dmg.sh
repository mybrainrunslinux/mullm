#!/usr/bin/env bash
# packaging/mac/build_dmg.sh
#
# Builds muLLM.app (via PyInstaller) and packages it as muLLM-<version>-mac.dmg
#
# Prerequisites (run once):
#   brew install create-dmg
#   pip install pyinstaller pillow
#
# Usage:
#   bash packaging/mac/build_dmg.sh
#
# Run this on a real Mac (Intel or Apple Silicon).
# For a universal binary that works on both, run on each arch and use
#   lipo to merge — or use a GitHub Actions matrix (see PRELAUNCH.md).
#
# NOTE: icon and background assets are required but not in the repo.
#   packaging/mac/icon.icns     — app icon (create with iconutil)
#   packaging/mac/dmg_bg.png    — 540x380 DMG background (optional, see below)
# If they don't exist, the build will warn and continue without them.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VERSION="$(cd "$REPO_ROOT" && python3 -c 'import tomllib; print(tomllib.load(open("pyproject.toml","rb"))["project"]["version"])')"
APP_NAME="muLLM"
DMG_NAME="${APP_NAME}-${VERSION}-mac.dmg"

cd "$REPO_ROOT"

echo "==> Installing build tools…"
pip install pyinstaller pillow --quiet

# ── PyInstaller build ──────────────────────────────────────────────────────────
echo "==> Building ${APP_NAME}.app with PyInstaller…"

PYINSTALLER_ARGS=(
    --onefile
    --windowed
    --name "$APP_NAME"
    --noconfirm
    --clean
    # Include the muLLM router package so inline pipeline works without a server
    --hidden-import "router.main"
    --hidden-import "router.cli"
    packaging/mac/launcher.py
)

# Add icon if it exists
ICON_PATH="packaging/mac/icon.icns"
if [ -f "$ICON_PATH" ]; then
    PYINSTALLER_ARGS+=(--icon "$ICON_PATH")
else
    echo "  WARNING: $ICON_PATH not found — building without custom icon"
    echo "  To create one: see packaging/mac/make_icon.sh (TODO)"
fi

pyinstaller "${PYINSTALLER_ARGS[@]}"

echo "==> Built: dist/${APP_NAME}.app"

# ── DMG packaging ─────────────────────────────────────────────────────────────
echo "==> Packaging as ${DMG_NAME}…"

# Remove previous DMG if it exists
rm -f "$DMG_NAME"

CREATE_DMG_ARGS=(
    --volname "$APP_NAME"
    --window-size 540 380
    --icon-size 128
    --icon "${APP_NAME}.app" 140 190
    --hide-extension "${APP_NAME}.app"
    --app-drop-link 400 190
    --no-internet-enable
)

# Add background image if present
BG_PATH="packaging/mac/dmg_bg.png"
if [ -f "$BG_PATH" ]; then
    CREATE_DMG_ARGS+=(--background "$BG_PATH")
else
    echo "  INFO: $BG_PATH not found — using default background"
    echo "  To add one: create a 540x380 PNG with amber/slate branding"
fi

create-dmg "${CREATE_DMG_ARGS[@]}" "$DMG_NAME" "dist/"

echo ""
echo "==> Done!"
echo "    Output: $(pwd)/${DMG_NAME}"
echo ""
echo "    Test the DMG:"
echo "      open ${DMG_NAME}"
echo "    Notarize for Gatekeeper (requires Apple Developer account):"
echo "      xcrun notarytool submit ${DMG_NAME} --apple-id you@example.com --team-id TEAMID --wait"
echo "      xcrun stapler staple ${DMG_NAME}"
