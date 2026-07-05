"""Persistent local policy state for budgets and retention."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from router.config import settings

POLICY_PATH = Path("cache/data/budget_policy.json")

DEFAULT_POLICY: dict[str, Any] = {
    "mode": "normal",  # normal | local_only | unlimited
    "daily_limit": None,
    "weekly_limit": None,
    "retention_days": 90,
    "updated_at": None,
}


def _coerce_policy(data: dict[str, Any]) -> dict[str, Any]:
    policy = {**DEFAULT_POLICY, **data}
    if policy["mode"] not in {"normal", "local_only", "unlimited"}:
        policy["mode"] = "normal"
    for key in ("daily_limit", "weekly_limit"):
        if policy.get(key) is not None:
            policy[key] = max(0.0, float(policy[key]))
    policy["retention_days"] = max(1, int(policy.get("retention_days") or 90))
    return policy


def load_policy() -> dict[str, Any]:
    if not POLICY_PATH.exists():
        return _coerce_policy({})
    try:
        return _coerce_policy(json.loads(POLICY_PATH.read_text(encoding="utf-8")))
    except Exception:
        return _coerce_policy({})


def save_policy(updates: dict[str, Any]) -> dict[str, Any]:
    policy = _coerce_policy({**load_policy(), **updates, "updated_at": round(time.time(), 3)})
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(json.dumps(policy, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return policy


def effective_daily_limit() -> float:
    policy = load_policy()
    if policy["mode"] == "unlimited":
        return float("inf")
    return float(policy["daily_limit"] if policy["daily_limit"] is not None else settings.budget_hard)


def effective_weekly_limit() -> float:
    policy = load_policy()
    if policy["mode"] == "unlimited":
        return float("inf")
    return float(policy["weekly_limit"] if policy["weekly_limit"] is not None else settings.budget_weekly)


def local_only_forced() -> bool:
    return load_policy()["mode"] == "local_only"

