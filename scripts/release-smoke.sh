#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${MULLM_RELEASE_SMOKE_DIR:-}"
KEEP_WORKDIR="${MULLM_RELEASE_SMOKE_KEEP:-0}"
PORT="${MULLM_RELEASE_SMOKE_PORT:-}"
SERVER_PID=""

if [[ -z "$WORKDIR" ]]; then
  WORKDIR="$(mktemp -d -t mullm-release-smoke.XXXXXX)"
fi

cleanup() {
  if [[ -n "$SERVER_PID" ]] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
  fi
  if [[ "$KEEP_WORKDIR" != "1" ]]; then
    rm -rf "$WORKDIR"
  else
    echo "Kept release-smoke workdir: $WORKDIR"
  fi
}
trap cleanup EXIT

if [[ -z "$PORT" ]]; then
  PORT="$(
    python - <<'PY'
import socket

with socket.socket() as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
  )"
fi

BUILD_VENV="$WORKDIR/build-venv"
RUN_VENV="$WORKDIR/run-venv"
DIST_DIR="$WORKDIR/dist"
STATE_DIR="$WORKDIR/state"
SERVER_LOG="$WORKDIR/mullm-server.log"

echo "==> Building wheel from $ROOT"
python -m venv "$BUILD_VENV"
"$BUILD_VENV/bin/python" -m pip install --upgrade pip build >/dev/null
"$BUILD_VENV/bin/python" -m build --wheel --outdir "$DIST_DIR" "$ROOT"

WHEEL="$(find "$DIST_DIR" -maxdepth 1 -name 'mullm-*.whl' | sort | tail -n 1)"
if [[ -z "$WHEEL" ]]; then
  echo "No wheel produced in $DIST_DIR" >&2
  exit 1
fi

echo "==> Installing wheel into fresh venv"
python -m venv "$RUN_VENV"
"$RUN_VENV/bin/python" -m pip install --upgrade pip >/dev/null
if [[ -f "$ROOT/constraints.txt" ]]; then
  "$RUN_VENV/bin/python" -m pip install -c "$ROOT/constraints.txt" "$WHEEL"
else
  "$RUN_VENV/bin/python" -m pip install "$WHEEL"
fi

echo "==> Checking installed CLI"
"$RUN_VENV/bin/mullm" --version
"$RUN_VENV/bin/mullm" --help >/dev/null

echo "==> Starting installed server on temporary port $PORT"
(
  cd "$WORKDIR"
  MULLM_PORT="$PORT" \
  MULLM_STATE_DIR="$STATE_DIR" \
  MULLM_ENABLE_STUDIO=true \
  MULLM_SERVER_RELOAD=false \
  "$RUN_VENV/bin/mullm-server" >"$SERVER_LOG" 2>&1
) &
SERVER_PID="$!"

BASE_URL=""
for scheme in https http; do
  url="$scheme://127.0.0.1:$PORT"
  for _ in $(seq 1 60); do
    if curl -fsSk "$url/health" >/dev/null 2>&1; then
      BASE_URL="$url"
      break 2
    fi
    if ! kill -0 "$SERVER_PID" 2>/dev/null; then
      echo "Server exited early. Log:" >&2
      cat "$SERVER_LOG" >&2 || true
      exit 1
    fi
    sleep 1
  done
done

if [[ -z "$BASE_URL" ]]; then
  echo "Server did not become healthy. Log:" >&2
  cat "$SERVER_LOG" >&2 || true
  exit 1
fi

echo "==> Probing HTTP/UI assets at $BASE_URL"
export BASE_URL
"$RUN_VENV/bin/python" - <<'PY'
import json
import os
import ssl
import sys
import urllib.request

base = os.environ["BASE_URL"].rstrip("/")
ctx = ssl._create_unverified_context() if base.startswith("https://") else None


def fetch(path: str, *, method: str = "GET", body: bytes | None = None) -> tuple[int, bytes]:
    req = urllib.request.Request(base + path, data=body, method=method)
    if body is not None:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, context=ctx, timeout=20) as response:
        return response.status, response.read()


checks = [
    ("/health", b'"status":"ok"'),
    ("/setup", b"setup"),
    ("/chat", b"chat"),
    ("/swords", b"three"),
    ("/api/settings", b'"providers"'),
    ("/api/musaic/status", b'"ffmpeg_available"'),
    ("/.well-known/agent.json", b'"skills"'),
    ("/.well-known/ai-plugin.json", b'"name_for_model":"mullm"'),
    ("/mcp/tools", b'"mullm_query"'),
    ("/static/three/three.module.js", b"REVISION"),
    ("/code/ready/bamboo-village.html", b"<html"),
]

for path, needle in checks:
    status, body = fetch(path)
    if status != 200 or needle.lower() not in body.lower():
        print(f"release smoke failed for {path}: status={status}, bytes={len(body)}", file=sys.stderr)
        sys.exit(1)

payload = json.dumps(
    {
        "content": "What is the difference between margin and padding in CSS?",
        "force_tier": "groundtruth",
        "skip_cache": True,
    }
).encode()
status, body = fetch("/query", method="POST", body=payload)
data = json.loads(body)
if status != 200 or data.get("tier") != "groundtruth" or data.get("groundtruth_category") != "css_facts":
    print(f"groundtruth smoke failed: status={status} body={data!r}", file=sys.stderr)
    sys.exit(1)

rpc_payload = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "classify",
        "params": {"content": "Implement a CLI unblock command with tests."},
    }
).encode()
status, body = fetch("/rpc", method="POST", body=rpc_payload)
rpc_data = json.loads(body)
if status != 200 or rpc_data.get("jsonrpc") != "2.0" or "result" not in rpc_data:
    print(f"JSON-RPC smoke failed: status={status} body={rpc_data!r}", file=sys.stderr)
    sys.exit(1)

mcp_payload = json.dumps(
    {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "mullm_query",
            "arguments": {
                "content": "What is the difference between margin and padding in CSS?",
                "force_tier": "groundtruth",
                "skip_cache": True,
            },
        },
    }
).encode()
status, body = fetch("/mcp/call", method="POST", body=mcp_payload)
mcp_data = json.loads(body)
if status != 200 or mcp_data.get("result", {}).get("metadata", {}).get("tier") != "groundtruth":
    print(f"MCP smoke failed: status={status} body={mcp_data!r}", file=sys.stderr)
    sys.exit(1)

status, body = fetch("/cache/clear", method="DELETE")
cache_clear = json.loads(body)
if status != 200 or cache_clear.get("cleared") is not True:
    print(f"semantic cache smoke failed: status={status} body={cache_clear!r}", file=sys.stderr)
    sys.exit(1)

print(
    json.dumps(
        {
            "base_url": base,
            "cache": "ok",
            "health": "ok",
            "setup": "ok",
            "chat": "ok",
            "swords": "ok",
            "mcp": "ok",
            "rpc": "ok",
            "a2a": "ok",
            "groundtruth_category": data.get("groundtruth_category"),
            "model_used": data.get("model_used"),
        },
        sort_keys=True,
    )
)
PY

echo "==> Runtime state created under $STATE_DIR"
find "$STATE_DIR" -maxdepth 3 -type f | sort
if [[ ! -f "$STATE_DIR/cache/data/semantic_cache.sqlite3" ]]; then
  echo "Expected SQLite semantic cache at $STATE_DIR/cache/data/semantic_cache.sqlite3" >&2
  exit 1
fi
echo "==> Release smoke passed"
