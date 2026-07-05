#!/usr/bin/env bash
# Check ComfyUI status, installed custom nodes, and available 3D models
set -euo pipefail

COMFY_PORT=8188
COMFY_URL="http://localhost:$COMFY_PORT"
COMFY_DIRS=(
  "${COMFYUI_DIR:-}"
  "/opt/comfyui"
  "$HOME/ComfyUI"
  "$HOME/comfyui"
  "/opt/ComfyUI"
  "$HOME/.local/share/ComfyUI"
)

echo "=== ComfyUI Status Check ==="
echo ""

# Find ComfyUI install
COMFY_DIR=""
for d in "${COMFY_DIRS[@]}"; do
  if [ -n "$d" ] && [ -f "$d/main.py" ]; then
    COMFY_DIR="$d"
    break
  fi
done

if [ -n "$COMFY_DIR" ]; then
  echo "Found ComfyUI at: $COMFY_DIR"
  _py=$(ls "$COMFY_DIR"/venv/bin/python "$COMFY_DIR"/.venv/bin/python 2>/dev/null | head -1)
  echo "Python: ${_py:-no venv found}"
else
  echo "ComfyUI NOT found in standard locations"
fi
echo ""

# Check if running
if curl -sf "$COMFY_URL/system_stats" > /tmp/comfy_stats.json 2>/dev/null; then
  echo "Running: YES ($COMFY_URL)"
  python3 -c "import json; d=json.load(open('/tmp/comfy_stats.json')); print('  VRAM:', d.get('devices', [{}])[0].get('vram_total', '?'), 'total,', d.get('devices', [{}])[0].get('vram_free', '?'), 'free')" 2>/dev/null || true
else
  echo "Running: NO"
  pgrep -a python | grep -i comfy | head -3 || echo "  No comfyui process found"
fi
echo ""

# Check 3D generation nodes
if [ -n "$COMFY_DIR" ]; then
  echo "=== Custom Nodes (3D/Image/Video) ==="
  NODES_DIR="$COMFY_DIR/custom_nodes"
  for node in \
    "ComfyUI-HunYuanDiT" "ComfyUI_HunYuan3D" "ComfyUI-Hunyuan3D" \
    "ComfyUI-Trellis" "ComfyUI_Trellis" \
    "ComfyUI-TripoSG" "ComfyUI-TripoSR" \
    "ComfyUI-InstantMesh" \
    "ComfyUI-VideoHelperSuite" "ComfyUI-AnimateDiff-Evolved" \
    "ComfyUI-GGUF" "ComfyUI-Manager" \
    "RigNet" "ComfyUI-RigNet" \
    "ComfyUI_IPAdapter_plus" "ComfyUI-ControlNet-Aux"; do
    if [ -d "$NODES_DIR/$node" ]; then
      echo "  [x] $node"
    else
      echo "  [ ] $node"
    fi
  done
  echo ""

  echo "=== Models (checkpoints, 3D) ==="
  for subdir in checkpoints loras unet vae clip diffusion_models; do
    count=$(find "$COMFY_DIR/models/$subdir" -name "*.safetensors" -o -name "*.ckpt" -o -name "*.pt" 2>/dev/null | wc -l)
    if [ "$count" -gt 0 ]; then
      echo "  $subdir: $count file(s)"
      find "$COMFY_DIR/models/$subdir" -name "*.safetensors" -o -name "*.ckpt" 2>/dev/null | head -5 | sed 's/^/    /'
    fi
  done
fi
echo ""
echo "Done."
