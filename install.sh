#!/usr/bin/env bash
# muLLM installer — uv-managed venv with Python + CUDA version fallback.
#
# Usage:
#   ./install.sh                       # auto-detect best Python + CUDA
#   ./install.sh --python 3.14         # prefer specific Python
#   ./install.sh --cuda 13.3           # prefer specific CUDA version
#   ./install.sh --no-venv             # install into current active env
#   ./install.sh --service             # also install systemd user service
#
# Python fallback order (unless --python): 3.14 → 3.13 → 3.12 → 3.11
# CUDA fallback order  (unless --cuda):   13.3 → 13.0 → 12.8  (13.2 skipped)
set -euo pipefail

MULLM_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONSTRAINTS="$MULLM_DIR/constraints.txt"
VENV_DIR="$MULLM_DIR/.venv"
CREATE_VENV=1
INSTALL_SERVICE=0
PYTHON_OVERRIDE=""
CUDA_OVERRIDE=""

# ── Parse args ────────────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    --no-venv)   CREATE_VENV=0; shift ;;
    --service)   INSTALL_SERVICE=1; shift ;;
    --python)    PYTHON_OVERRIDE="$2"; shift 2 ;;
    --cuda)      CUDA_OVERRIDE="$2"; shift 2 ;;
    *)           shift ;;
  esac
done

# ── Require uv ────────────────────────────────────────────────────────────────
if ! command -v uv &>/dev/null; then
  echo "uv not found — installing (recommended over pip/conda)..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
fi
echo "uv $(uv --version)"

# ── Pick Python version ───────────────────────────────────────────────────────
if [ -n "$PYTHON_OVERRIDE" ]; then
  PYTHON_VER="$PYTHON_OVERRIDE"
  echo "Using requested Python $PYTHON_VER"
else
  # Try each version in preference order; use first one uv can provide
  PYTHON_VER=""
  for ver in 3.14 3.13 3.12 3.11; do
    if uv python find "$ver" &>/dev/null 2>&1; then
      PYTHON_VER="$ver"
      break
    fi
  done
  if [ -z "$PYTHON_VER" ]; then
    echo "WARNING: could not auto-detect Python via uv — falling back to system python3"
    PYTHON_VER="$(python3 --version 2>/dev/null | awk '{print $2}' | cut -d. -f1,2)"
  fi
  echo "Auto-selected Python $PYTHON_VER"
fi

# Warn about pre-release Python
if [[ "$PYTHON_VER" == 3.14* ]]; then
  echo "NOTE: Python 3.14 is RC/pre-release. torch/transformers may lack wheels."
  echo "      The muLLM server core (FastAPI, pydantic, httpx) should work fine."
  echo "      GPU inference (torch) may need: --python 3.12 if install fails."
fi

# ── Create/reuse venv ─────────────────────────────────────────────────────────
if [ "$CREATE_VENV" -eq 1 ]; then
  if [ -d "$VENV_DIR" ]; then
    VENV_PYTHON="$VENV_DIR/bin/python"
    EXISTING_VER=$("$VENV_PYTHON" --version 2>/dev/null | awk '{print $2}' | cut -d. -f1,2)
    if [ "$EXISTING_VER" = "$PYTHON_VER" ]; then
      echo "Reusing existing venv at $VENV_DIR (Python $EXISTING_VER)"
    else
      echo "Recreating venv (was Python $EXISTING_VER, want $PYTHON_VER)..."
      rm -rf "$VENV_DIR"
      uv venv "$VENV_DIR" --python "$PYTHON_VER"
    fi
  else
    echo "Creating fresh venv at $VENV_DIR (Python $PYTHON_VER)..."
    uv venv "$VENV_DIR" --python "$PYTHON_VER"
  fi
  # shellcheck disable=SC1091
  source "$VENV_DIR/bin/activate"
fi

echo "Python: $(python --version)"

# ── Install with security constraints ────────────────────────────────────────
if [ -f "$CONSTRAINTS" ]; then
  echo "Installing with CVE constraints ($CONSTRAINTS)..."
  if ! uv pip install -c "$CONSTRAINTS" -e "$MULLM_DIR"; then
    echo "WARNING: constrained install failed — retrying without constraints (check manually)"
    uv pip install -e "$MULLM_DIR"
  fi
else
  echo "WARNING: constraints.txt not found — installing without CVE pins"
  uv pip install -e "$MULLM_DIR"
fi

# ── GPU / PyTorch ─────────────────────────────────────────────────────────────
EXISTING_CUDA=$(python -c "import torch; print(torch.version.cuda)" 2>/dev/null || echo "none")
if [ "$EXISTING_CUDA" != "none" ]; then
  echo "PyTorch already present (CUDA $EXISTING_CUDA) — skipping torch install"
else
  # Pick CUDA wheel to install
  if [ -n "$CUDA_OVERRIDE" ]; then
    CUDA_VER="$CUDA_OVERRIDE"
  else
    # Detect installed CUDA from nvcc or nvidia-smi
    NVCC_VER=$(nvcc --version 2>/dev/null | grep -oP 'V\K[\d.]+' | head -1 || echo "")
    if [ -n "$NVCC_VER" ]; then
      CUDA_MAJOR=$(echo "$NVCC_VER" | cut -d. -f1)
      CUDA_MINOR=$(echo "$NVCC_VER" | cut -d. -f2)
      CUDA_VER="$CUDA_MAJOR.$CUDA_MINOR"
      # Skip 13.2 — known issues; fall back
      if [ "$CUDA_VER" = "13.2" ]; then
        echo "CUDA 13.2 detected — skipping (known issues), using 13.0 wheels"
        CUDA_VER="13.0"
      fi
    else
      CUDA_VER="12.8"
      echo "Could not detect CUDA version — defaulting to CUDA $CUDA_VER wheels"
    fi
  fi

  # Map CUDA version to torch index URL
  case "$CUDA_VER" in
    13.3|13.*)
      echo "CUDA 13.x detected — using CUDA 12.8 PyTorch wheels (13.x not yet in official wheels)"
      TORCH_INDEX="https://download.pytorch.org/whl/cu128"
      ;;
    12.8)  TORCH_INDEX="https://download.pytorch.org/whl/cu128" ;;
    12.6)  TORCH_INDEX="https://download.pytorch.org/whl/cu126" ;;
    12.4)  TORCH_INDEX="https://download.pytorch.org/whl/cu124" ;;
    12.1)  TORCH_INDEX="https://download.pytorch.org/whl/cu121" ;;
    *)
      echo "CUDA $CUDA_VER: no known wheel index, using cu128 as fallback"
      TORCH_INDEX="https://download.pytorch.org/whl/cu128"
      ;;
  esac

  echo "Installing PyTorch (CUDA $CUDA_VER → $TORCH_INDEX)..."
  if ! uv pip install torch==2.7.0 torchvision torchaudio --index-url "$TORCH_INDEX"; then
    echo "WARNING: PyTorch install failed (possibly no wheel for Python $PYTHON_VER + CUDA $CUDA_VER)"
    echo "         The muLLM server will still run without GPU acceleration."
    echo "         Try: ./install.sh --python 3.12 --cuda 12.8"
  fi
fi

# ── Systemd service (Linux, optional) ────────────────────────────────────────
if [ "$INSTALL_SERVICE" -eq 1 ]; then
  PYTHON_BIN="$VENV_DIR/bin/python"
  SERVICE_FILE="$HOME/.config/systemd/user/mullm.service"
  mkdir -p "$(dirname "$SERVICE_FILE")"
  cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=muLLM local LLM router
After=network.target

[Service]
Type=simple
WorkingDirectory=$MULLM_DIR
ExecStart=$PYTHON_BIN -m router.main
Restart=on-failure
RestartSec=5
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=default.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable mullm
  echo "Systemd user service installed. Start: systemctl --user start mullm"
fi

echo ""
echo "Done!"
echo "  Python: $(python --version)"
echo "  venv:   $VENV_DIR"
echo ""
echo "Next steps:"
echo "  source $VENV_DIR/bin/activate"
echo "  mullm --serve          # start the server"
echo "  mullm --health         # check server health"
echo ""
echo "Re-install options:"
echo "  ./install.sh --python 3.14    # try Python 3.14"
echo "  ./install.sh --python 3.12    # fall back to 3.12 (best torch support)"
echo "  ./install.sh --cuda 12.8      # force CUDA 12.8 wheels"
echo "  ./install.sh --service        # add systemd service"
