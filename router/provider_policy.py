"""Persistent provider policy state for quota, backoff, and routing mode."""

from __future__ import annotations

import json
import time
from typing import Any

from router.config import settings

POLICY_PATH = settings.cache_dir / "provider_policy.json"
DEFAULT_BACKOFF_SECONDS = 300

DEFAULT_POLICY: dict[str, Any] = {
    "mode": "cost_optimize",
    "aggressiveness": "balanced",
    "daily_quota_usd": {},
    "provider_order": ["openai", "anthropic", "google", "cerebras", "deepseek", "glm"],
    "weights": {},
    "providers": {},
}


def _load() -> dict[str, Any]:
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    merged = {**DEFAULT_POLICY, **data}
    merged.setdefault("daily_quota_usd", {})
    merged.setdefault("providers", {})
    return merged


def _save(data: dict[str, Any]) -> None:
    POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    POLICY_PATH.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    try:
        POLICY_PATH.chmod(0o600)
    except OSError:
        pass


def status() -> dict[str, Any]:
    data = _load()
    now = time.time()
    providers = {}
    for name, entry in data.get("providers", {}).items():
        disabled_until = float(entry.get("disabled_until") or 0)
        providers[name] = {
            **entry,
            "available": disabled_until <= now,
            "backoff_seconds_remaining": max(0, round(disabled_until - now, 1)),
        }
    return {**data, "providers": providers, "generated_at": now}


def provider_available(provider: str) -> bool:
    entry = status().get("providers", {}).get(provider, {})
    return bool(entry.get("available", True))


def record_failure(provider: str, status_code: int | None = None, backoff_seconds: int | None = None) -> None:
    if not provider:
        return
    data = _load()
    providers = data.setdefault("providers", {})
    entry = providers.setdefault(provider, {})
    failures = int(entry.get("failure_count") or 0) + 1
    delay = backoff_seconds or min(DEFAULT_BACKOFF_SECONDS * failures, 3600)
    entry.update(
        {
            "failure_count": failures,
            "last_failure_at": time.time(),
            "last_status_code": status_code,
            "disabled_until": time.time() + delay,
        }
    )
    _save(data)


def record_success(provider: str) -> None:
    if not provider:
        return
    data = _load()
    entry = data.setdefault("providers", {}).setdefault(provider, {})
    entry.update(
        {
            "failure_count": 0,
            "last_success_at": time.time(),
            "disabled_until": 0,
        }
    )
    _save(data)


def update_policy(payload: dict[str, Any]) -> dict[str, Any]:
    data = _load()
    for key in ("mode", "aggressiveness", "daily_quota_usd", "provider_order", "weights"):
        if key in payload:
            data[key] = payload[key]
    _save(data)
    return status()
