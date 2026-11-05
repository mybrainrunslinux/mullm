#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="mullm-smoke-$$"
IMAGE="localhost/$NAME"
cleanup() {
  podman rm -f "$NAME" >/dev/null 2>&1 || true
  podman rmi "$IMAGE" >/dev/null 2>&1 || true
}
trap cleanup EXIT
podman build --format docker -t "$IMAGE" "$ROOT"
podman run -d --name "$NAME" -p 127.0.0.1::6856 \
  -e MULLM_API_KEY=smoke-test-only -e DISABLE_CLOUD=1 "$IMAGE"
PORT="$(podman port "$NAME" 6856/tcp | awk -F: '{print $NF}')"
for attempt in $(seq 1 60); do
  if curl -fsSk "https://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    curl -fsSk "https://127.0.0.1:$PORT/query" \
      -H 'Authorization: Bearer smoke-test-only' -H 'Content-Type: application/json' \
      -d '{"content":"What is 2+2?","force_tier":"groundtruth"}' \
      | python3 -c 'import json,sys; r=json.load(sys.stdin); assert r["tier"] == "groundtruth" and r["cost"] == 0'
    exit 0
  fi
  sleep 1
done
podman logs "$NAME"
exit 1
