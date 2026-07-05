"""Append-only operational audit events."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

AUDIT_PATH = Path("cache/data/audit_log.jsonl")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def audit_event(event: str, **fields: Any) -> None:
    record = {
        "ts": round(time.time(), 3),
        "event": event,
        **fields,
    }
    AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")


def read_events(limit: int = 1000) -> list[dict[str, Any]]:
    if not AUDIT_PATH.exists():
        return []
    rows: list[dict[str, Any]] = []
    with AUDIT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows[-limit:]


def purge_events_before(cutoff_ts: float) -> int:
    if not AUDIT_PATH.exists():
        return 0
    kept: list[str] = []
    removed = 0
    with AUDIT_PATH.open("r", encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if float(row.get("ts", 0) or 0) < cutoff_ts:
                removed += 1
            else:
                kept.append(line)
    AUDIT_PATH.write_text("".join(kept), encoding="utf-8")
    return removed


def purge_all_events() -> int:
    count = len(read_events(limit=1_000_000))
    if AUDIT_PATH.exists():
        AUDIT_PATH.unlink()
    return count
