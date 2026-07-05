#!/usr/bin/env bash
# Install muLLM as a macOS LaunchAgent (runs at login, no root needed).
# Toggle: install_service.sh install | uninstall | status

set -e

PLIST_SRC="$(dirname "$0")/mullm.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.0101technology.mullm.plist"
LABEL="com.0101technology.mullm"

# Detect mullm-server location (brew or pip)
MULLM_BIN=$(command -v mullm-server 2>/dev/null || echo "/usr/local/bin/mullm-server")

case "${1:-install}" in
  install)
    cp "$PLIST_SRC" "$PLIST_DST"
    sed -i '' "s|/usr/local/bin/mullm-server|$MULLM_BIN|g" "$PLIST_DST"
    launchctl load -w "$PLIST_DST"
    echo "muLLM service installed and started."
    echo "Logs: tail -f /tmp/mullm.log"
    echo "Stop: launchctl unload $PLIST_DST"
    ;;
  uninstall)
    launchctl unload -w "$PLIST_DST" 2>/dev/null || true
    rm -f "$PLIST_DST"
    echo "muLLM service removed."
    ;;
  status)
    launchctl list | grep mullm || echo "muLLM service not running."
    ;;
  *)
    echo "Usage: $0 [install|uninstall|status]"
    ;;
esac
