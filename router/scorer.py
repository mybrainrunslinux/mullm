"""
muLLM model selector and cost logger.

Responsibilities:
  - Select optimal cloud model/tier from an IntentObject
  - Append every request atomically to scoring_log.jsonl
  - Track session costs in-memory (keyed by session_id)
  - Enforce budget thresholds (warn / moderate / hard)
  - Expose session cost summaries
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

from router.config import CATEGORY_TEMP_MAP, TEMP_BALANCED, settings
from router.models import (
    IntentCategory,
    IntentObject,
    SessionCostSummary,
    TierLabel,
)
from router.storage import get_storage as _get_storage

_storage: Any = None


def _get_log_storage():
    global _storage
    if _storage is None:
        _storage = _get_storage()
    return _storage

logger = logging.getLogger("mullm.scorer")

# ---------------------------------------------------------------------------
# In-memory session cost store (thread-safe)
# ---------------------------------------------------------------------------

_session_costs: dict[str, float]    = {}
_session_counts: dict[str, int]     = {}
_store_lock = threading.Lock()

# File write lock — scoring_log.jsonl must be append-only, never corrupted
_log_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Spend velocity tracking (sliding 60s window)
# ---------------------------------------------------------------------------

_spend_window: dict[str, list[tuple[float, float]]] = defaultdict(list)  # session -> [(ts, cost)]
SPEND_VELOCITY_WARN = 0.10  # $/min


def record_spend(session_id: str, cost: float) -> dict:
    """Record spend and return velocity info."""
    now = time.time()
    window = _spend_window[session_id]
    window.append((now, cost))
    # trim to last 60s
    window[:] = [(t, c) for t, c in window if now - t < 60]
    velocity = sum(c for _, c in window)  # $/min
    return {"velocity_per_min": round(velocity, 4), "warn": velocity > SPEND_VELOCITY_WARN}


def get_velocity(session_id: str) -> dict:
    """Return current velocity info for a session without recording new spend."""
    now = time.time()
    window = _spend_window[session_id]
    window[:] = [(t, c) for t, c in window if now - t < 60]
    velocity = sum(c for _, c in window)
    return {"velocity_per_min": round(velocity, 4), "warn": velocity > SPEND_VELOCITY_WARN}


# ---------------------------------------------------------------------------
# Budget enforcement
# ---------------------------------------------------------------------------

def _budget_status(cost: float) -> str:
    from router import policy

    hard = policy.effective_daily_limit()
    if hard != float("inf") and cost >= hard:
        return "hard"
    if cost >= settings.budget_moderate:
        return "moderate"
    if cost >= settings.budget_warn:
        return "warn"
    return "ok"


def check_session_budget(session_id: str) -> SessionCostSummary:
    """Return current cost summary for *session_id* and raise if hard limit hit."""
    with _store_lock:
        total = _session_costs.get(session_id, 0.0)
        count = _session_counts.get(session_id, 0)

    status = _budget_status(total)
    from router import policy

    hard = policy.effective_daily_limit()
    remaining = float("inf") if hard == float("inf") else max(0.0, hard - total)

    return SessionCostSummary(
        session_id=session_id,
        total_cost=total,
        query_count=count,
        budget_status=status,
        remaining_budget=remaining,
    )


def get_total_spend() -> float:
    """Return process-local tracked spend across all sessions."""
    with _store_lock:
        return sum(_session_costs.values())


def get_total_query_count() -> int:
    """Return process-local tracked query count across all sessions."""
    with _store_lock:
        return sum(_session_counts.values())


def budget_snapshot() -> dict[str, Any]:
    """Return the budget payload used by cost/privacy dashboards."""
    from router import policy

    budget_policy = policy.load_policy()
    daily_spend = get_total_spend()
    weekly_spend = daily_spend
    daily_limit = policy.effective_daily_limit()
    weekly_limit = policy.effective_weekly_limit()
    daily_pct = (daily_spend / daily_limit * 100.0) if daily_limit not in (0, float("inf")) else 0.0
    weekly_pct = (weekly_spend / weekly_limit * 100.0) if weekly_limit not in (0, float("inf")) else 0.0
    status = _budget_status(daily_spend)
    hard_blocked = budget_policy["mode"] == "local_only" or status == "hard"
    return {
        "daily_spend": round(daily_spend, 8),
        "weekly_spend": round(weekly_spend, 8),
        "daily_limit": None if daily_limit == float("inf") else daily_limit,
        "weekly_limit": None if weekly_limit == float("inf") else weekly_limit,
        "effective_daily_limit": None if daily_limit == float("inf") else daily_limit,
        "effective_weekly_limit": None if weekly_limit == float("inf") else weekly_limit,
        "daily_pct": round(daily_pct, 4),
        "weekly_pct": round(weekly_pct, 4),
        "budget_status": status,
        "budget_ok": not hard_blocked,
        "hard_blocked": hard_blocked,
        "local_only": hard_blocked,
        "query_count": get_total_query_count(),
        "mode": budget_policy["mode"],
        "retention_days": budget_policy["retention_days"],
    }


def is_budget_exhausted(session_id: str) -> bool:
    """Return True if the session has reached the hard budget limit."""
    from router import policy

    if policy.local_only_forced():
        return True
    hard = policy.effective_daily_limit()
    if hard == float("inf"):
        return False
    with _store_lock:
        return _session_costs.get(session_id, 0.0) >= hard


# ---------------------------------------------------------------------------
# Tier / model selection
# ---------------------------------------------------------------------------

# Complexity → preferred tier (can be overridden by intent flags)
_COMPLEXITY_TIER: dict[int, TierLabel] = {
    1: TierLabel.LOCAL,
    2: TierLabel.LOCAL,
    3: TierLabel.LOCAL,
    4: TierLabel.CLOUD_CHEAP,
    5: TierLabel.CLOUD_FULL,
}


def select_tier(intent: IntentObject, session_id: str = "") -> TierLabel:
    """
    Choose the cheapest tier capable of handling this intent.

    Budget pressure can downgrade cloud tiers to local.
    Vision always routes to local (Ollama vision model).
    """
    if intent.needs_vision:
        return TierLabel.LOCAL

    if session_id and is_budget_exhausted(session_id):
        logger.warning("Session %s has exhausted budget — forcing LOCAL tier", session_id)
        return TierLabel.LOCAL

    base_tier = _COMPLEXITY_TIER.get(intent.complexity, TierLabel.LOCAL)

    # Downgrade cloud_full → cloud_cheap under moderate budget pressure
    if base_tier == TierLabel.CLOUD_FULL and session_id:
        summary = check_session_budget(session_id)
        if summary.budget_status in ("moderate", "hard"):
            logger.info("Budget pressure (%s) — downgrading CLOUD_FULL → CLOUD_CHEAP", summary.budget_status)
            return TierLabel.CLOUD_CHEAP

    return base_tier


def default_temperature(intent: IntentObject) -> float:
    """Return the category-appropriate sampling temperature."""
    return CATEGORY_TEMP_MAP.get(intent.category.value, TEMP_BALANCED)


# ---------------------------------------------------------------------------
# Scoring log
# ---------------------------------------------------------------------------

def log_request(
    session_id: str,
    query: str,
    response: str,
    tier: TierLabel,
    model: str,
    cost: float,
    tokens: int,
    latency_ms: float,
    intent: IntentObject | None = None,
    cached: bool = False,
    quality_escalated: bool = False,
) -> None:
    """
    Append one record to scoring_log.jsonl (append-only, never deleted).

    The query and response fields are omitted when settings.log_query_content
    is False (privacy mode).
    """
    record: dict = {
        "ts":               int(time.time()),
        "session_id":       session_id,
        "tier":             tier.value,
        "model":            model,
        "cost":             round(cost, 8),
        "cost_usd":         round(cost, 8),
        "tokens":           tokens,
        "tokens_in":        0,
        "tokens_out":       tokens,
        "latency_ms":       round(latency_ms, 2),
        "cached":           cached,
        "quality_escalated": quality_escalated,
    }
    if intent:
        record["category"]   = intent.category.value
        record["complexity"] = intent.complexity
        record["confidence"] = round(intent.confidence, 4)

    if settings.log_query_content:
        # Truncate to avoid log bloat; full response is in ChromaDB
        record["query"]    = query[:512]
        record["response"] = response[:256]

    try:
        with _log_lock:
            _get_log_storage().log(record)
    except Exception as exc:
        logger.error("Failed to write scoring log: %s", exc)

    # Update in-memory session accounting
    with _store_lock:
        _session_costs[session_id]  = _session_costs.get(session_id, 0.0) + cost
        _session_counts[session_id] = _session_counts.get(session_id, 0)  + 1

    # Spend velocity tracking
    velocity_info = record_spend(session_id, cost)
    if velocity_info["warn"]:
        logger.warning(
            "SESSION %s spend velocity high: $%.4f/min (threshold $%.2f/min)",
            session_id, velocity_info["velocity_per_min"], SPEND_VELOCITY_WARN,
        )

    # Budget warnings
    total = _session_costs[session_id]
    if total >= settings.budget_hard:
        logger.error("SESSION %s hit HARD budget limit ($%.2f)", session_id, total)
    elif total >= settings.budget_moderate:
        logger.warning("SESSION %s crossed moderate budget ($%.2f)", session_id, total)
    elif total >= settings.budget_warn:
        logger.info("SESSION %s crossed warn budget ($%.2f)", session_id, total)


# ---------------------------------------------------------------------------
# Dashboard aggregation helpers
# ---------------------------------------------------------------------------

def get_all_session_summaries() -> dict[str, SessionCostSummary]:
    """Return summaries for all known sessions."""
    with _store_lock:
        return {
            sid: SessionCostSummary(
                session_id=sid,
                total_cost=_session_costs.get(sid, 0.0),
                query_count=_session_counts.get(sid, 0),
                budget_status=_budget_status(_session_costs.get(sid, 0.0)),
                remaining_budget=check_session_budget(sid).remaining_budget,
            )
            for sid in _session_costs
        }


def read_scoring_log(limit: int = 1000) -> list[dict]:
    """Read recent scoring records from the active storage backend.

    Default v1 storage is SQLite, while legacy muLLM used JSONL. Dashboards and
    cost pages must read whichever backend is active or they will show stale
    spend data and undermine budget controls.
    """
    try:
        records = _get_log_storage().recent(limit)
        records = sorted(records or [], key=lambda r: float(r.get("ts", 0) or 0))
        return records[-limit:]
    except Exception as exc:
        logger.error("Failed to read active scoring storage: %s", exc)

    # Last-resort legacy fallback.
    log_path = settings.scoring_log
    if not log_path.exists():
        return []
    records: list[dict] = []
    try:
        with open(log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        records.append(json.loads(line))
                    except json.JSONDecodeError:
                        continue
    except OSError:
        return []
    return records[-limit:]


def read_scoring_log_for_session(session_id: str, limit: int = 100_000) -> list[dict]:
    """Return scoring records scoped to a session id for DSAR/export flows."""
    if not session_id:
        return []
    storage = _get_log_storage()
    recent_by_session = getattr(storage, "recent_by_session", None)
    if callable(recent_by_session):
        try:
            return recent_by_session(session_id, limit)
        except Exception as exc:
            logger.error("Failed to read scoped scoring storage: %s", exc)
    return [row for row in read_scoring_log(limit=limit) if str(row.get("session_id", "")) == session_id]


def purge_scoring_logs_for_session(session_id: str) -> int:
    """Best-effort scoring-log deletion scoped to a session id."""
    if not session_id:
        return 0
    storage = _get_log_storage()
    delete_by_session = getattr(storage, "delete_by_session", None)
    if callable(delete_by_session):
        try:
            removed = int(delete_by_session(session_id))
            with _store_lock:
                _session_costs.pop(session_id, None)
                _session_counts.pop(session_id, None)
            return removed
        except Exception as exc:
            logger.error("Failed to purge scoped scoring storage: %s", exc)

    path = getattr(storage, "_path", None)
    if path is None or not Path(path).exists():
        return 0
    kept: list[str] = []
    removed = 0
    with open(path, encoding="utf-8") as f:
        for line in f:
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                kept.append(line)
                continue
            if str(row.get("session_id", "")) == session_id:
                removed += 1
            else:
                kept.append(line)
    Path(path).write_text("".join(kept), encoding="utf-8")
    with _store_lock:
        _session_costs.pop(session_id, None)
        _session_counts.pop(session_id, None)
    return removed


def purge_scoring_log_before(cutoff_ts: float) -> int:
    """Best-effort scoring-log retention purge for SQLite or legacy JSONL."""
    storage = _get_log_storage()
    conn = getattr(storage, "_conn", None)
    if conn is not None:
        try:
            cur = conn.execute("DELETE FROM queries WHERE ts < ?", (cutoff_ts,))
            conn.commit()
            return int(cur.rowcount if cur.rowcount is not None else 0)
        except Exception as exc:
            logger.error("Failed to purge SQLite scoring log: %s", exc)
            return 0

    path = getattr(storage, "_path", None)
    if path is None or not Path(path).exists():
        return 0
    kept: list[str] = []
    removed = 0
    with open(path, encoding="utf-8") as f:
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
    Path(path).write_text("".join(kept), encoding="utf-8")
    return removed


def purge_all_scoring_logs() -> int:
    """Clear scoring logs and in-process budget counters."""
    storage = _get_log_storage()
    conn = getattr(storage, "_conn", None)
    if conn is not None:
        try:
            count = conn.execute("SELECT COUNT(*) FROM queries").fetchone()[0]
            conn.execute("DELETE FROM queries")
            conn.commit()
        except Exception as exc:
            logger.error("Failed to clear SQLite scoring log: %s", exc)
            count = 0
    else:
        path = getattr(storage, "_path", None)
        count = len(read_scoring_log(limit=1_000_000))
        if path is not None and Path(path).exists():
            Path(path).unlink()
    with _store_lock:
        _session_costs.clear()
        _session_counts.clear()
    return int(count)


# ---------------------------------------------------------------------------
# Compatibility exports — old scoring API
# ---------------------------------------------------------------------------

from router.models import (
    ClassificationResult,
    ModelSelection,
    Tier,
)

# Exportable log path (patchable in tests)
SCORING_LOG: str = str(settings.scoring_log)
SCORING_LOG_MAX_RECORDS: int = 50_000

_log_buffer: list[dict] = []
_buffer_lock = threading.Lock()


def _flush_log_buffer() -> None:
    """Flush buffered log records to SCORING_LOG (direct JSONL write)."""
    with _buffer_lock:
        if not _log_buffer:
            return
        pending = _log_buffer[:]
        _log_buffer.clear()
    try:
        with _log_lock:
            with open(SCORING_LOG, "a", encoding="utf-8") as f:
                for rec in pending:
                    f.write(json.dumps(rec) + "\n")
    except Exception as exc:
        logger.warning("_flush_log_buffer error: %s", exc)


def _maybe_rotate_log(log_path) -> None:
    """Trim log to SCORING_LOG_MAX_RECORDS most-recent lines."""
    p = Path(str(log_path))
    if not p.exists():
        return
    lines = p.read_text(encoding="utf-8").splitlines()
    if len(lines) > SCORING_LOG_MAX_RECORDS:
        p.write_text("\n".join(lines[-SCORING_LOG_MAX_RECORDS:]) + "\n", encoding="utf-8")


def log_outcome(
    intent_id: str = "",
    category: str = "",
    complexity: int = 1,
    model_used: str = "",
    tier_used: str = "local",
    tokens_used: int = 0,
    cost: float = 0.0,
    success: bool = True,
    latency_ms: float = 0.0,
    content_preview: str = "",
) -> None:
    """Append one outcome record to SCORING_LOG (buffered write)."""
    record = {
        "ts": int(time.time()),
        "intent_id": intent_id,
        "category": category,
        "complexity": complexity,
        "model_used": model_used,
        "tier_used": tier_used,
        "tokens_used": tokens_used,
        "cost": round(cost, 8),
        "success": success,
        "latency_ms": round(latency_ms, 2),
        "content_preview": content_preview[:256],
    }
    with _buffer_lock:
        _log_buffer.append(record)
    _flush_log_buffer()


def add_session_cost(session_id: str, cost: float) -> float:
    """Add cost to a session and return new total. Empty session_id is a no-op."""
    if not session_id:
        return 0.0
    now = time.time()
    _spend_window[session_id].append((now, cost))
    with _store_lock:
        total = _session_costs.get(session_id, 0.0) + cost
        _session_costs[session_id] = total
        return total


def get_session_cost(session_id: str) -> float:
    """Return cumulative cost for session_id, or 0.0 if unknown."""
    return _session_costs.get(session_id, 0.0)


def get_spend_velocity(session_id: str) -> dict:
    """Return spend velocity info for session in the last 60s window."""
    if not session_id:
        return {"velocity": 0.0, "window_spend": 0.0, "warning": False}
    now = time.time()
    window = _spend_window.get(session_id, [])
    recent = [(t, c) for t, c in window if now - t < 60]
    window_spend = sum(c for _, c in recent)
    velocity = window_spend  # $/60s ≈ $/min
    return {
        "velocity": round(velocity, 4),
        "window_spend": round(window_spend, 4),
        "warning": velocity > SPEND_VELOCITY_WARN,
    }


def get_success_rate(
    category: str,
    model: str,
    min_samples: int = 5,
) -> float | None:
    """Return success rate for category+model from scoring log, or None if too few samples."""
    log_path = Path(SCORING_LOG)
    if not log_path.exists():
        return None
    try:
        records = [
            json.loads(line)
            for line in log_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        filtered = [
            r for r in records
            if r.get("category") == category and r.get("model_used") == model
        ]
        if len(filtered) < min_samples:
            return None
        successes = sum(1 for r in filtered if r.get("success", True))
        return successes / len(filtered)
    except Exception:
        return None


# Category preference for cloud model selection (cheap tier)
_CATEGORY_CLOUD_PREFERENCE: dict[IntentCategory, str] = {
    IntentCategory.CODE:         "claude-sonnet-4-6",
    IntentCategory.RESEARCH:     "gemini-flash",
    IntentCategory.CREATIVE:     "claude-haiku-4-5",
    IntentCategory.CONVERSATION: "claude-haiku-4-5",
    IntentCategory.DEPLOY:       "claude-sonnet-4-6",
    IntentCategory.NOTE:         "claude-haiku-4-5",
    IntentCategory.LOOKUP:       "gemini-flash",
}


def _estimate_cost(model_name: str, tokens: int) -> float:
    from router.cloud import MODEL_IDS, _get_pricing
    canonical = MODEL_IDS.get(model_name, model_name)
    p = _get_pricing(canonical)
    total_m = tokens / 1_000_000
    return total_m * (p.get("cost_per_m_input", 0) + p.get("cost_per_m_output", 0)) / 2


def select_model(cr: ClassificationResult) -> ModelSelection:
    """Select a ModelSelection from a ClassificationResult."""
    tier = cr.suggested_tier if hasattr(cr, "suggested_tier") else Tier.LOCAL
    tokens = getattr(cr, "estimated_tokens", 1000) or 1000
    category = cr.category

    if tier in (Tier.CACHE,):
        return ModelSelection(
            model_name="cache",
            provider="local",
            tier=tier,
            estimated_cost=0.0,
        )

    if tier in (Tier.LOCAL, Tier.LOCAL_MULTI):
        from router.config import settings as _s
        model = _s.ollama_model
        return ModelSelection(
            model_name=model,
            provider="ollama",
            tier=tier,
            estimated_cost=0.0,
        )

    # Cloud tiers
    pref_model = _CATEGORY_CLOUD_PREFERENCE.get(category, "gemini-flash")
    cost = _estimate_cost(pref_model, tokens)
    provider = "anthropic" if "claude" in pref_model else ("google" if "gemini" in pref_model else "openai")

    return ModelSelection(
        model_name=pref_model,
        provider=provider,
        tier=tier,
        estimated_cost=cost,
    )


LOCAL_MODEL_MAP: dict[IntentCategory, str] = {
    cat: settings.ollama_model for cat in IntentCategory
}
