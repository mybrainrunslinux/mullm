#!/usr/bin/env bash
# Install muLLM as a user-level systemd service (no root required).
# Toggle: install_service.sh install | uninstall | status

set -e

UNIT="mullm.service"
UNIT_SRC="$(dirname "$0")/$UNIT"
UNIT_DIR="$HOME/.config/systemd/user"

case "${1:-install}" in
  install)
    mkdir -p "$UNIT_DIR"
    cp "$UNIT_SRC" "$UNIT_DIR/$UNIT"
    sed -i "s|%h|$HOME|g" "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
    systemctl --user enable --now mullm
    echo "muLLM service installed and started."
    echo "Logs: journalctl --user -u mullm -f"
    echo "Stop: systemctl --user stop mullm"
    ;;
  uninstall)
    systemctl --user disable --now mullm 2>/dev/null || true
    rm -f "$UNIT_DIR/$UNIT"
    systemctl --user daemon-reload
    echo "muLLM service removed."
    ;;
  status)
    systemctl --user status mullm
    ;;
  *)
    echo "Usage: $0 [install|uninstall|status]"
    ;;
esac
