import json

import pytest

from router import cache


class FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.store[key] = value
        return True


@pytest.mark.asyncio
async def test_redis_exact_cache_precedes_chromadb(monkeypatch):
    fake = FakeRedis()
    query = "repeat exactly"
    fake.store[cache._redis_key(query)] = json.dumps(
        {"response": "redis answer", "metadata": {"tier": "local"}}
    )

    monkeypatch.setattr(cache, "_redis_client", fake)
    monkeypatch.setattr(cache, "_redis_unavailable", False)

    async def fail_embed(_text):
        raise AssertionError("Chroma embedding should not run on Redis exact hit")

    monkeypatch.setattr(cache, "_embed", fail_embed)

    response, meta = await cache.lookup(query, category="code")

    assert response == "redis answer"
    assert meta["cache_backend"] == "redis_exact"
    assert meta["cache_similarity"] == 1.0


@pytest.mark.asyncio
async def test_store_writes_redis_exact_when_content_logging_allowed(monkeypatch):
    fake = FakeRedis()
    monkeypatch.setattr(cache, "_redis_client", fake)
    monkeypatch.setattr(cache, "_redis_unavailable", False)
    monkeypatch.setattr(cache.settings, "log_query_content", True)
    monkeypatch.setattr(cache.settings, "semantic_cache_backend", "chroma")
    monkeypatch.setattr(cache, "_get_client", lambda: None)

    ok = await cache.store("cache me", "cached response", {"tier": "local"})

    assert ok is False
    stored = json.loads(fake.store[cache._redis_key("cache me")])
    assert stored["response"] == "cached response"
    assert stored["metadata"]["tier"] == "local"
