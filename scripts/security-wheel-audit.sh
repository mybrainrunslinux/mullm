#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${MULLM_SECURITY_AUDIT_WORKDIR:-}"
KEEP_WORKDIR="${MULLM_SECURITY_AUDIT_KEEP_WORKDIR:-0}"

if [[ -z "$WORKDIR" ]]; then
  WORKDIR="$(mktemp -d -t mullm-security-audit.XXXXXX)"
fi

cleanup() {
  if [[ "$KEEP_WORKDIR" == "1" ]]; then
    echo "Kept security audit workdir: $WORKDIR"
  else
    rm -rf "$WORKDIR"
  fi
}
trap cleanup EXIT

DIST_DIR="$WORKDIR/dist"
VENV_DIR="$WORKDIR/venv"
RESOLVED_REQUIREMENTS="$WORKDIR/resolved-requirements.txt"

mkdir -p "$DIST_DIR"

python -m pip install --upgrade pip build >/dev/null
python -m build --wheel --outdir "$DIST_DIR" "$ROOT"

python -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV_DIR/bin/python" -m pip install -c "$ROOT/constraints.txt" "$DIST_DIR"/mullm-*.whl "pip-audit>=2.7,<3.0"

"$VENV_DIR/bin/python" -m pip freeze --all \
  | grep -viE '^(mullm|pip-audit)==|^mullm @|^pip-audit==' \
  > "$RESOLVED_REQUIREMENTS"

"$VENV_DIR/bin/python" -m pip_audit -r "$RESOLVED_REQUIREMENTS" --strict --desc --progress-spinner off
