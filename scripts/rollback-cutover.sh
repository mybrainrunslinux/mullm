#!/usr/bin/env bash
# Roll back a muLLM 1.0.0 cutover: stop the new server on 6856 and put the
# legacy snapshot back on 6856 exactly as it was. The /mullm/1.0.0 install is
# left on disk (harmless) so rolling forward again is instant.
#
#   DRY RUN (default):   bash scripts/rollback-cutover.sh
#   REAL RUN:            CONFIRM=yes bash scripts/rollback-cutover.sh
set -euo pipefail

LEGACY="$(ls -d /mullm/legacy-* 2>/dev/null | sort | tail -1 || true)"
BIN="$HOME/.local/bin"
RUN() { if [ "${CONFIRM:-no}" = "yes" ]; then "$@"; else echo "DRY-RUN: $*"; fi; }

[ -n "$LEGACY" ] || { echo "no /mullm/legacy-* snapshot found"; exit 1; }
echo "== rollback to $LEGACY (CONFIRM=${CONFIRM:-no}) =="

for port in 6856 26856; do
  PID="$(ss -tlnp 2>/dev/null | grep ":$port " | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
  if [ -n "$PID" ]; then echo "stopping $port (pid $PID)"; RUN kill "$PID"; fi
done
RUN sleep 3

# Relaunch the legacy snapshot on the ORIGINAL port
RUN bash -c "MULLM_PORT=6856 nohup '$LEGACY/start-legacy.sh' > '$LEGACY/server-rollback.log' 2>&1 &"

# Point the CLI back at the legacy venv
RUN rm -f "$BIN/mullm" "$BIN/mullm-server"
RUN bash -c "printf '#!/usr/bin/env bash\nexec %s/venv/bin/mullm \"\$@\"\n' '$LEGACY' > '$BIN/mullm'"
RUN bash -c "printf '#!/usr/bin/env bash\nMULLM_PORT=6856 exec %s/start-legacy.sh\n' '$LEGACY' > '$BIN/mullm-server'"
RUN chmod +x "$BIN/mullm" "$BIN/mullm-server"

if [ "${CONFIRM:-no}" = "yes" ]; then
  sleep 12
  curl -sk https://127.0.0.1:6856/health | head -c 200; echo
  echo "== ROLLBACK COMPLETE — legacy install serving 6856 again =="
else
  echo "== DRY RUN COMPLETE =="
fi
