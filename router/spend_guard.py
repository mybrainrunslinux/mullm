"""Atomic, persistent reservations for cloud text inference.

Reservations remain charged on transport failure/cancellation: a provider may
have billed work even when no usage response reached us. Never retry for free.
"""
from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import wraps
import inspect
import sqlite3
import time
import uuid
from pathlib import Path

from router.config import settings

SESSION = ContextVar("mullm_spend_session", default="direct")
LEDGER_PATH: Path | None = None


def _connect():
    path = LEDGER_PATH or settings.cache_dir / "spend_reservations.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=1)
    conn.execute("CREATE TABLE IF NOT EXISTS charges (id TEXT PRIMARY KEY, session TEXT, ts REAL, amount REAL)")
    return conn


def reserve(amount: float) -> str:
    from router import policy
    policy.require_inference_allowed()
    now, token = time.time(), uuid.uuid4().hex
    with _connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        daily, weekly, session = conn.execute(
            "SELECT COALESCE(SUM(CASE WHEN ts>=? THEN amount ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN ts>=? THEN amount ELSE 0 END),0), "
            "COALESCE(SUM(CASE WHEN session=? THEN amount ELSE 0 END),0) FROM charges",
            (now - 86400, now - 7 * 86400, SESSION.get())).fetchone()
        limits = ((daily, policy.effective_daily_limit()), (weekly, policy.effective_weekly_limit()),
                  (session, settings.budget_hard))
        if any(spent + amount > cap for spent, cap in limits):
            raise RuntimeError("Cloud spend reservation exceeds hard budget")
        conn.execute("INSERT INTO charges VALUES (?,?,?,?)", (token, SESSION.get(), now, amount))
    return token


def settle(token: str, actual: float) -> None:
    # Preserve the reservation if usage is invalid or unexpectedly larger.
    with _connect() as conn:
        reserved = conn.execute("SELECT amount FROM charges WHERE id=?", (token,)).fetchone()[0]
        if not 0 <= actual <= reserved:
            raise RuntimeError("Provider usage exceeded reserved bound; reservation retained")
        conn.execute("UPDATE charges SET amount=? WHERE id=?", (actual, token))


def metered(fn):
    """Wrap concrete SDK/raw calls, so each retry reserves separately."""
    signature = inspect.signature(fn)
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        from router.cloud import CLOUD_MODEL_PRICING, standard_cost
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        model = bound.arguments["model"]
        pricing = CLOUD_MODEL_PRICING.get(model)
        if pricing is None:
            raise RuntimeError(f"No budget pricing for model {model}")
        prompt = bound.arguments.get("prompt", "")
        system = bound.arguments.get("system") or ""
        # UTF-8 bytes bound byte-level token counts; include framing overhead.
        tokens = len((prompt + system).encode()) + 256
        maximum = bound.arguments.get("max_tokens", 4096)
        if maximum <= 0:
            raise RuntimeError("Cloud calls require a bounded positive output limit")
        # Reserve 2x standard input/output cost to cover cache writes and framing.
        amount = 2 * standard_cost(model, pricing, tokens, maximum)
        token = await asyncio.to_thread(reserve, amount)
        result = await fn(*args, **kwargs)
        actual = result["cost"] if isinstance(result, dict) else result.cost
        await asyncio.to_thread(settle, token, 2 * float(actual))
        return result
    return wrapped


def metered_stream(fn):
    """Reserve a full bounded stream; estimates are not refunded as exact usage."""
    signature = inspect.signature(fn)
    @wraps(fn)
    async def wrapped(*args, **kwargs):
        from router.cloud import CLOUD_MODEL_PRICING, standard_cost
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        provider = fn.__name__.removeprefix("stream_")
        model = bound.arguments.get("model") or getattr(settings, "cloud_cheap_model_" + provider)
        pricing = CLOUD_MODEL_PRICING.get(model)
        if pricing is None:
            raise RuntimeError(f"No budget pricing for model {model}")
        text = bound.arguments["prompt"] + (bound.arguments.get("system") or "")
        await asyncio.to_thread(reserve, 2 * standard_cost(model, pricing, len(text.encode()) + 256, 4096))
        async for event in fn(*args, **kwargs):
            yield event
    return wrapped
