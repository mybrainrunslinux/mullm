"""
VRAM guard tests — prevents loading two large models simultaneously.

Policy:
  - "large" model = anything ≥ 10GB VRAM (30b class)
  - Only ONE large model may be loaded at a time
  - Embedding models (< 1GB) are exempt — always kept
  - Small models (9b class, < 10GB) coexist freely with one large model
  - When a large model needs to load, any OTHER large model is evicted first

Steady-state goal on RTX 5090 (32GB):
  qwen3-coder-65k (large, ~21GB) + OmniCoder-9b (small, ~6GB) + nomic-embed (0.6GB) = 27.6GB  ✓
"""
from __future__ import annotations

import asyncio
import pytest


LARGE_THRESHOLD_BYTES = 10 * 1024**3  # 10 GB — separates 30b-class from 9b-class
EMBED_THRESHOLD_BYTES = 1 * 1024**3   # 1 GB  — embed models always exempt


# ---------------------------------------------------------------------------
# Async mock helpers
# ---------------------------------------------------------------------------

class _MockPS:
    def __init__(self, loaded):
        self._loaded = loaded
    def raise_for_status(self): pass
    def json(self):
        return {"models": self._loaded}


class _MockOk:
    def raise_for_status(self): pass
    def json(self): return {"done": True}


class _AsyncClient:
    def __init__(self, ps_data):
        self._ps = ps_data
        self.evicted: list[str] = []

    async def __aenter__(self): return self
    async def __aexit__(self, *_): pass

    async def get(self, url, **_):
        if "/api/ps" in url:
            return _MockPS(self._ps)
        raise ValueError(url)

    async def post(self, url, json=None, **_):
        if json and json.get("keep_alive") == 0:
            self.evicted.append(json.get("model", ""))
        return _MockOk()


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_no_eviction_when_only_small_models_loaded(monkeypatch):
    """9b + embed loaded, adding 30b-65k — embed stays, 9b stays, no eviction."""
    import httpx
    from router import vram_guard

    loaded = [
        {"name": "OmniCoder-9b",          "size_vram": 6 * 1024**3},
        {"name": "nomic-embed-text",       "size_vram": int(0.6 * 1024**3)},
    ]
    client = _AsyncClient(loaded)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(vram_guard, "_total_vram_bytes", lambda: 32 * 1024**3)

    freed = _run(vram_guard.ensure_vram_headroom(
        "qwen3-coder-65k:latest", required_bytes=21 * 1024**3
    ))
    assert freed == []
    assert client.evicted == []


def test_evicts_existing_large_model_before_loading_another_large(monkeypatch):
    """30b loaded. Loading 30b-65k must evict 30b first — never two large at once."""
    import httpx
    from router import vram_guard

    loaded = [
        {"name": "qwen3-coder:30b",  "size_vram": 21 * 1024**3},
        {"name": "nomic-embed-text", "size_vram": int(0.6 * 1024**3)},
    ]
    client = _AsyncClient(loaded)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(vram_guard, "_total_vram_bytes", lambda: 32 * 1024**3)

    freed = _run(vram_guard.ensure_vram_headroom(
        "qwen3-coder-65k:latest", required_bytes=21 * 1024**3
    ))
    assert "qwen3-coder:30b" in freed
    assert any("30b" in m for m in client.evicted)


def test_embed_model_never_evicted(monkeypatch):
    """Embedding models are tiny — they must never be touched by the guard."""
    import httpx
    from router import vram_guard

    loaded = [
        {"name": "nomic-embed-text:latest", "size_vram": int(0.6 * 1024**3)},
        {"name": "qwen3-coder:30b",          "size_vram": 21 * 1024**3},
    ]
    client = _AsyncClient(loaded)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(vram_guard, "_total_vram_bytes", lambda: 32 * 1024**3)

    freed = _run(vram_guard.ensure_vram_headroom(
        "qwen3-coder-65k:latest", required_bytes=21 * 1024**3
    ))
    assert not any("embed" in m.lower() for m in freed)
    assert not any("embed" in m.lower() for m in client.evicted)


def test_target_model_never_evicted(monkeypatch):
    """The model we're about to load is never evicted to make room for itself."""
    import httpx
    from router import vram_guard

    loaded = [
        {"name": "qwen3-coder-65k:latest", "size_vram": 21 * 1024**3},
    ]
    client = _AsyncClient(loaded)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(vram_guard, "_total_vram_bytes", lambda: 32 * 1024**3)

    freed = _run(vram_guard.ensure_vram_headroom(
        "qwen3-coder-65k:latest", required_bytes=21 * 1024**3
    ))
    assert "qwen3-coder-65k:latest" not in freed


def test_steady_state_fits_without_eviction(monkeypatch):
    """9b + 30b-65k + embed = 27.6GB — no eviction on subsequent calls."""
    import httpx
    from router import vram_guard

    loaded = [
        {"name": "qwen3-coder-65k:latest",  "size_vram": 21 * 1024**3},
        {"name": "OmniCoder-9b",             "size_vram": 6 * 1024**3},
        {"name": "nomic-embed-text:latest",  "size_vram": int(0.6 * 1024**3)},
    ]
    client = _AsyncClient(loaded)
    monkeypatch.setattr(httpx, "AsyncClient", lambda **_: client)
    monkeypatch.setattr(vram_guard, "_total_vram_bytes", lambda: 32 * 1024**3)

    # Any subsequent request for either model should require zero evictions
    for model in ("qwen3-coder-65k:latest", "OmniCoder-9b"):
        freed = _run(vram_guard.ensure_vram_headroom(model, required_bytes=21 * 1024**3))
        assert freed == [], f"Unexpected eviction for {model}: {freed}"
