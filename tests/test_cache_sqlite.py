import pytest

from router import cache


@pytest.fixture(autouse=True)
def isolated_sqlite_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(cache.settings, "cache_dir", tmp_path)
    monkeypatch.setattr(cache.settings, "semantic_cache_backend", "sqlite")
    monkeypatch.setattr(cache.settings, "log_query_content", True)
    monkeypatch.setattr(cache.settings, "cache_cosine_threshold", 0.95)
    monkeypatch.setattr(cache, "_sqlite_conn", None)
    monkeypatch.setattr(cache, "_sqlite_path", None)
    monkeypatch.setattr(cache, "_redis_client", None)
    monkeypatch.setattr(cache, "_redis_unavailable", True)
    yield
    if cache._sqlite_conn is not None:
        cache._sqlite_conn.close()
    cache._sqlite_conn = None
    cache._sqlite_path = None


@pytest.mark.asyncio
async def test_sqlite_semantic_cache_store_lookup_scan_delete(monkeypatch):
    async def fake_embed(text: str):
        if "padding" in text or "margin" in text:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]

    monkeypatch.setattr(cache, "_embed", fake_embed)

    stored = await cache.store(
        "What is margin vs padding in CSS?",
        "Margin is outside the border; padding is inside it.",
        {"tier": "local", "session_id": "s1"},
    )

    assert stored is True
    assert cache.is_available() is True
    assert cache.count_entries() == 1

    hit = await cache.lookup("Explain CSS padding and margin", category="css_facts")
    assert hit is not None
    response, meta = hit
    assert "outside" in response
    assert meta["cache_backend"] == "sqlite"
    assert meta["cache_similarity"] >= 0.95

    entries = cache.scan_entries()
    assert entries[0]["metadata"]["session_id"] == "s1"

    assert cache.delete_entries_by_session("s1") == 1
    assert cache.count_entries() == 0


@pytest.mark.asyncio
async def test_sqlite_semantic_cache_honors_privacy_mode(monkeypatch):
    monkeypatch.setattr(cache.settings, "log_query_content", False)

    async def fake_embed(_text: str):
        raise AssertionError("privacy mode should not embed")

    monkeypatch.setattr(cache, "_embed", fake_embed)

    assert await cache.store("secret", "do not store", {}) is False
    assert cache.count_entries() == 0


@pytest.mark.asyncio
async def test_semantic_cache_off_disables_lookup_and_store(monkeypatch):
    monkeypatch.setattr(cache.settings, "semantic_cache_backend", "off")

    async def fake_embed(_text: str):
        raise AssertionError("off backend should not embed")

    monkeypatch.setattr(cache, "_embed", fake_embed)

    assert cache.is_available() is False
    assert await cache.lookup("anything") is None
    assert await cache.store("anything", "response", {}) is False
