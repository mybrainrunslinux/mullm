#!/usr/bin/env bash
# muLLM 1.0.0 cutover — replaces the production mullm (port 6856) with a
# freshly-built 1.0.0 wheel installed at /mullm/1.0.0, while snapshotting the
# exact prior install so it stays runnable on port 26856.
#
#   DRY RUN (default):   bash scripts/cutover-1.0.0.sh
#   REAL RUN:            CONFIRM=yes bash scripts/cutover-1.0.0.sh
#
# What it does, in order:
#   1. Snapshot the old install (source+state) to /mullm/legacy-<ts>/,
#      with its own venv, launcher (port 26856) and CLI `mullm-<ts>`.
#   2. Bump this tree to 1.0.0, build the wheel, write SHA256SUMS
#      (+ GPG-sign if a secret key exists).
#   3. Install the wheel into /mullm/1.0.0/venv, point /mullm/current at it.
#   4. Migrate assets into /mullm/storage/assets (config: archive dir on the
#      Expansion drive stays an advanced, per-install setting).
#   5. STOP the old 6856 server (the only disruptive step), start the legacy
#      snapshot on 26856 and the new 1.0.0 on 6856, replace the `mullm` /
#      `mullm-server` commands, smoke-check both ports.
#
# Rollback at any time: bash scripts/rollback-cutover.sh
set -euo pipefail

TS="$(date +%Y%m%d_%H%M%S)"
SRC_TREE="/mullm/fable/mullm0.9"
OLD_TREE="/home/peter/TODO/dev/wonton-mullm"
OLD_PID="$(ss -tlnp 2>/dev/null | grep ':6856 ' | grep -oP 'pid=\K[0-9]+' | head -1 || true)"
LEGACY="/mullm/legacy-${TS}"
NEW_ROOT="/mullm/1.0.0"
STORAGE="/mullm/storage"
BIN="$HOME/.local/bin"
RUN() { if [ "${CONFIRM:-no}" = "yes" ]; then "$@"; else echo "DRY-RUN: $*"; fi; }

echo "== muLLM 1.0.0 cutover (CONFIRM=${CONFIRM:-no}) =="
echo "old server pid on 6856: ${OLD_PID:-none}"

# ── 0. Preconditions ───────────────────────────────────────────────────────
[ -d "$SRC_TREE" ] || { echo "source tree missing"; exit 1; }
[ -d "$OLD_TREE" ] || { echo "old tree missing (already cut over?)"; exit 1; }
command -v uv >/dev/null || { echo "uv required"; exit 1; }
ss -tlnp | grep -q ':26856 ' && { echo "port 26856 busy"; exit 1; }

# ── 1. Snapshot the legacy install ─────────────────────────────────────────
echo "-- [1/5] snapshot old install -> $LEGACY"
RUN mkdir -p "$LEGACY"
RUN rsync -a --exclude='.venv*' --exclude='node_modules' --exclude='__pycache__' \
    --exclude='.git' "$OLD_TREE/" "$LEGACY/src/"
# capture the exact runtime environment of the running server
if [ -n "$OLD_PID" ]; then
  RUN bash -c "tr '\0' '\n' < /proc/$OLD_PID/environ | grep -E '^(MULLM_|OLLAMA_|ANTHROPIC|OPENAI|GOOGLE|MESHY|CIVIT)' > '$LEGACY/runtime.env'"
fi
RUN uv venv --python 3.12 "$LEGACY/venv"
RUN uv pip install --python "$LEGACY/venv/bin/python" -e "$LEGACY/src[vector-cache]"
# legacy launcher on 26856 with its own state (exact copy of the old state)
RUN bash -c "cat > '$LEGACY/start-legacy.sh' <<EOF
#!/usr/bin/env bash
set -a; source '$LEGACY/runtime.env' 2>/dev/null; set +a
export MULLM_PORT=\"\${MULLM_PORT:-26856}\"
export MULLM_STATE_DIR='$LEGACY/src/scratch/runtime-state'
export MULLM_ENV_FILE='$LEGACY/src/scratch/runtime-state/mullm.env'
exec '$LEGACY/venv/bin/mullm-server'
EOF"
RUN chmod +x "$LEGACY/start-legacy.sh"
RUN bash -c "cat > '$BIN/mullm-${TS%_*}' <<EOF
#!/usr/bin/env bash
export MULLM_SERVER_URL=https://127.0.0.1:26856
exec '$LEGACY/venv/bin/mullm' \"\$@\"
EOF"
RUN chmod +x "$BIN/mullm-${TS%_*}"

# ── 2. Mint 1.0.0 ──────────────────────────────────────────────────────────
echo "-- [2/5] version bump + wheel build + checksums"
RUN sed -i 's/^version = "0.9.0"/version = "1.0.0"/' "$SRC_TREE/pyproject.toml"
RUN sed -i 's/    version: str = "0.9.0"/    version: str = "1.0.0"/' "$SRC_TREE/router/config.py"
RUN bash -c "cd '$SRC_TREE' && .venv/bin/python -m build --wheel --outdir dist-1.0.0"
RUN bash -c "cd '$SRC_TREE/dist-1.0.0' && sha256sum *.whl > SHA256SUMS"
if gpg --list-secret-keys 2>/dev/null | grep -q sec; then
  RUN bash -c "cd '$SRC_TREE/dist-1.0.0' && gpg --detach-sign --armor SHA256SUMS"
else
  echo "   (no GPG secret key — skipping signature; SHA256SUMS still written)"
fi

# ── 3. Install /mullm/1.0.0 + /mullm/current ───────────────────────────────
echo "-- [3/5] install $NEW_ROOT"
RUN mkdir -p "$NEW_ROOT" "$STORAGE/assets" "$STORAGE/state"
RUN uv venv --python 3.12 "$NEW_ROOT/venv"
RUN bash -c "uv pip install --python '$NEW_ROOT/venv/bin/python' '$SRC_TREE'/dist-1.0.0/mullm-1.0.0-py3-none-any.whl'[vector-cache,gpu]'"
RUN cp "$SRC_TREE/.env" "$NEW_ROOT/.env"
RUN bash -c "cat > '$NEW_ROOT/mullm.toml' <<EOF
[core]
# port defaults to 6856

[studio.assets]
root = \"$STORAGE/assets\"
# Advanced cold storage (this install only — not a product default):
archive_dir = \"/run/media/peter/Expansion/assets/3d\"
EOF"
RUN ln -sfn "$NEW_ROOT" /mullm/current
RUN bash -c "cat > '$NEW_ROOT/start.sh' <<EOF
#!/usr/bin/env bash
cd '$NEW_ROOT'
export MULLM_ENV_FILE='$NEW_ROOT/.env'
export MULLM_STATE_DIR='$STORAGE/state'
export MULLM_CONFIG_PATH='$NEW_ROOT/mullm.toml'
exec '/mullm/current/venv/bin/mullm-server'
EOF"
RUN chmod +x "$NEW_ROOT/start.sh"

# ── 4. Migrate assets ──────────────────────────────────────────────────────
echo "-- [4/5] migrate assets -> $STORAGE/assets"
RUN rsync -a "$SRC_TREE/scratch/runtime-state/assets/" "$STORAGE/assets/"
RUN rsync -a --ignore-existing "$OLD_TREE/scratch/runtime-state/assets/" "$STORAGE/assets/" 2>/dev/null || true

# ── 5. The swap (disruptive part) ──────────────────────────────────────────
echo "-- [5/5] swap: stop old 6856, start legacy 26856 + new 6856, replace CLI"
if [ -n "$OLD_PID" ]; then RUN kill "$OLD_PID"; RUN sleep 3; fi
RUN bash -c "nohup '$LEGACY/start-legacy.sh' > '$LEGACY/server.log' 2>&1 &"
RUN bash -c "nohup '$NEW_ROOT/start.sh' > '$NEW_ROOT/server.log' 2>&1 &"
RUN rm -f "$BIN/mullm" "$BIN/mullm-server"
RUN bash -c "printf '#!/usr/bin/env bash\nexec /mullm/current/venv/bin/mullm \"\$@\"\n' > '$BIN/mullm'"
RUN bash -c "printf '#!/usr/bin/env bash\nexec /mullm/current/start.sh\n' > '$BIN/mullm-server'"
RUN chmod +x "$BIN/mullm" "$BIN/mullm-server"
if [ "${CONFIRM:-no}" = "yes" ]; then
  sleep 15
  echo "-- smoke checks"
  curl -sk https://127.0.0.1:6856/health | head -c 200; echo
  curl -sk https://127.0.0.1:26856/health | head -c 200; echo
  echo "== CUTOVER COMPLETE =="
  echo "  new:    https://127.0.0.1:6856   (/mullm/current -> $NEW_ROOT)"
  echo "  legacy: https://127.0.0.1:26856  ($LEGACY, CLI: mullm-${TS%_*})"
  echo "  rollback: bash $SRC_TREE/scripts/rollback-cutover.sh"
else
  echo "== DRY RUN COMPLETE — re-run with CONFIRM=yes to execute =="
fi
