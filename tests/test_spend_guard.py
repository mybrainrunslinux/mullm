from concurrent.futures import ThreadPoolExecutor

import pytest

from router import policy, spend_guard
from router.config import settings


def test_concurrent_reservations_cannot_exceed_cap(monkeypatch):
    monkeypatch.setattr(settings, "disable_cloud", False)
    monkeypatch.setattr(settings, "budget_hard", 1.0)
    monkeypatch.setattr(policy, "local_only_forced", lambda: False)
    monkeypatch.setattr(policy, "effective_daily_limit", lambda: 1.0)
    monkeypatch.setattr(policy, "effective_weekly_limit", lambda: 1.0)
    def request(_):
        try:
            return spend_guard.reserve(0.6)
        except RuntimeError:
            return None
    # Create schema before contention; BEGIN IMMEDIATE serializes admission.
    spend_guard._connect().close()
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(request, range(8)))
    assert len([t for t in tokens if t]) == 1
    token = next(t for t in tokens if t)
    spend_guard.settle(token, 0.1)
    assert spend_guard.reserve(0.6)


async def test_cancelled_provider_reservation_remains_charged(monkeypatch):
    import asyncio
    monkeypatch.setattr(policy, "local_only_forced", lambda: False)
    @spend_guard.metered
    async def call(prompt, model, max_tokens=4096, system=None):
        raise asyncio.CancelledError
    with pytest.raises(asyncio.CancelledError):
        await call("hello", "gpt-6-astra")
    with spend_guard._connect() as conn:
        assert conn.execute("SELECT SUM(amount) FROM charges").fetchone()[0] > 0
