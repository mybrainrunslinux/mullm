#!/usr/bin/env bash
# Start a local ComfyUI server for muLLM image/3D generation.
#
# Search order matches check_comfyui.sh: /opt/comfyui is preferred because
# muLLM's default profiles (SDXL base/turbo + Touch-of-Realism LoRA) are
# installed there by scripts/setup_comfyui.sh.
set -euo pipefail

PORT="${COMFYUI_PORT:-8188}"
LISTEN="${COMFYUI_LISTEN:-127.0.0.1}"
LOG="${COMFYUI_LOG:-/tmp/comfyui.log}"

COMFY_DIRS=(
  "${COMFYUI_DIR:-}"
  "/opt/comfyui"
  "$HOME/ComfyUI"
  "$HOME/comfyui"
  "/opt/ComfyUI"
  "$HOME/.local/share/ComfyUI"
)

COMFY_DIR=""
for d in "${COMFY_DIRS[@]}"; do
  [ -n "$d" ] && [ -f "$d/main.py" ] && { COMFY_DIR="$d"; break; }
done
if [ -z "$COMFY_DIR" ]; then
  echo "ComfyUI not found. Set COMFYUI_DIR or run scripts/setup_comfyui.sh." >&2
  exit 1
fi

# Accept either venv layout.
PY=""
for v in "$COMFY_DIR/venv/bin/python" "$COMFY_DIR/.venv/bin/python"; do
  [ -x "$v" ] && { PY="$v"; break; }
done
if [ -z "$PY" ]; then
  echo "No venv found in $COMFY_DIR (looked for venv/ and .venv/)." >&2
  exit 1
fi

if curl -sf "http://127.0.0.1:$PORT/system_stats" > /dev/null 2>&1; then
  echo "ComfyUI already running at http://127.0.0.1:$PORT"
  exit 0
fi

echo "Starting ComfyUI from $COMFY_DIR (python: $PY)..."
# --reserve-vram keeps headroom for a co-resident ollama model.
nohup "$PY" "$COMFY_DIR/main.py" \
  --listen "$LISTEN" \
  --port "$PORT" \
  --reserve-vram "${COMFYUI_RESERVE_VRAM:-16}" \
  --preview-method auto \
  --disable-xformers \
  > "$LOG" 2>&1 &
echo "PID: $!"

for _ in $(seq 1 30); do
  sleep 2
  if curl -sf "http://127.0.0.1:$PORT/system_stats" > /dev/null 2>&1; then
    echo "Up: http://127.0.0.1:$PORT"
    exit 0
  fi
  printf '.'
done
echo
echo "Slow start — check $LOG"
tail -5 "$LOG"
exit 1
