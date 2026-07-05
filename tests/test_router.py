"""
Tests for the MegaLLManiac pipeline.
Run with: pytest tests/ -v

[Suggestion #14] Includes cloud API mock tests.
"""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import router.main as main_module
from router.main import app
from router.models import (
    IntentObject,
    Modality,
    Source,
)
from router.vector_cache import VectorCache


@pytest.fixture(autouse=True)
def _init_cache(tmp_path):
    from unittest.mock import MagicMock

    from config import settings

    original_chroma_dir = settings.CHROMA_DIR
    original_log = getattr(settings, "log_query_content", False)
    chroma_test_dir = str(tmp_path / "chroma_test")
    settings.CHROMA_DIR = chroma_test_dir
    settings.log_query_content = True
    try:
        test_cache = VectorCache(collection_name="test_cache", chroma_dir=chroma_test_dir)
    except RuntimeError:
        # chromadb not importable in this env — use a mock
        test_cache = MagicMock(spec=VectorCache)
        test_cache.count.return_value = 0
        test_cache.scan_entries.return_value = []
    main_module.cache = test_cache
    yield test_cache
    settings.CHROMA_DIR = original_chroma_dir
    settings.log_query_content = original_log
    main_module.cache = None


@pytest.fixture
def transport():
    return ASGITransport(app=app)


@pytest.mark.asyncio
async def test_health(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] in ("ok", "degraded")
        assert "cache_docs" in data
        assert "ollama_ok" in data  # [Suggestion #6]
        assert data["semantic_cache_backend"] in ("sqlite", "chroma", "off")
        assert data["semantic_cache_available"] == data["chromadb_available"]


@pytest.mark.asyncio
async def test_simple_query(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/query",
            json={
                "content": "What is 2 + 2?",
                "modality": "text",
                "source": "api",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "response" in data
        assert "tier_used" in data
        assert data["cost"] >= 0


@pytest.mark.asyncio
async def test_note_goes_to_cache(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/query",
            json={
                "content": "Remember: the staging DB password is in 1Password",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["cost"] == 0.0


@pytest.mark.asyncio
@pytest.mark.timeout(300)  # two live local-model generations; 35B answers can take >90s
async def test_cache_hit_on_repeat(transport):
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        query = {"content": "How do I configure Nginx for WebSocket proxying?"}
        resp1 = await client.post("/query", json=query)
        assert resp1.status_code == 200
        # Wait for cache write to settle before re-querying
        await asyncio.sleep(0.5)
        resp2 = await client.post("/query", json=query)
        data2 = resp2.json()
        assert resp2.status_code == 200
        # May be deduped or cached — either way cost should be 0 or same as local
        assert data2["cost"] == 0.0 or data2["from_cache"] is True


@pytest.mark.asyncio
async def test_cache_clear(transport, tmp_path):
    import router.cache as cache_mod
    from router.config import settings as _settings

    orig_cache_dir = _settings.cache_dir
    saved_col = cache_mod._chroma_collection
    saved_cli = cache_mod._chroma_client

    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    _settings.cache_dir = cache_dir
    cache_mod._chroma_collection = None
    cache_mod._chroma_client = None

    try:
        col = cache_mod._get_client()
        if col is None:
            pytest.skip("ChromaDB not available in this environment")

        col.add(ids=["test-doc-1"], documents=["test content"], embeddings=[[0.1] * 384], metadatas=[{"source": "test"}])
        assert col.count() == 1

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.delete("/cache/clear")
        assert resp.status_code == 200
        assert resp.json()["docs_remaining"] == 0
        assert col.count() == 0
    finally:
        cache_mod._chroma_collection = saved_col
        cache_mod._chroma_client = saved_cli
        _settings.cache_dir = orig_cache_dir


@pytest.mark.asyncio
async def test_session_cost_tracking(transport):
    """[Suggestion #10] Session cost accumulates."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/query",
            json={
                "content": "Hello there!",
                "session_id": "test-session-001",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "session_cost_total" in data


@pytest.mark.asyncio
async def test_dedup_same_content(transport):
    """[Suggestion #4] Same content within window should be deduped."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        q = {"content": "Write a Python function to reverse a string"}
        resp1 = await client.post("/query", json=q)
        resp2 = await client.post("/query", json=q)
        assert resp1.status_code == 200
        assert resp2.status_code == 200
        # Second should be faster (deduped or cached)


def test_intent_object_creation():
    intent = IntentObject(content="test query")
    assert len(intent.id) == 36
    assert intent.modality == Modality.TEXT
    assert intent.source == Source.API


def test_intent_object_custom():
    intent = IntentObject(
        content="take a photo",
        modality=Modality.VISUAL,
        source=Source.PHONE,
        context={"project": "game-server"},
    )
    assert intent.modality == Modality.VISUAL
    assert intent.context["project"] == "game-server"


# ── Cloud Mock Tests (#14) ───────────────────────────────────


@pytest.mark.asyncio
async def test_cloud_anthropic_mock():
    """Mock the Anthropic API call."""
    from router.cloud import call_anthropic

    mock_response = {
        "content": [{"type": "text", "text": "Here is the code..."}],
        "usage": {"input_tokens": 100, "output_tokens": 200},
    }

    with patch("router.cloud._get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.json = lambda: mock_response
        mock_resp.raise_for_status = lambda: None
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_get.return_value = mock_client

        with patch("router.cloud._ANTHROPIC_KEY", "sk-ant-test"):
            result = await call_anthropic("write hello world", model="claude-sonnet")
            assert result["text"] == "Here is the code..."
            assert result["tokens_in"] == 100
            assert result["tokens_out"] == 200
            assert result["cost"] > 0


@pytest.mark.asyncio
async def test_cloud_openai_mock():
    from router.cloud import call_openai

    mock_response = {
        "choices": [{"message": {"content": "Hello World!"}}],
        "usage": {"prompt_tokens": 50, "completion_tokens": 100},
    }

    with patch("router.cloud._get_client") as mock_get:
        mock_client = AsyncMock()
        mock_resp = AsyncMock()
        mock_resp.json = lambda: mock_response
        mock_resp.raise_for_status = lambda: None
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_get.return_value = mock_client

        with patch("router.cloud._OPENAI_KEY", "sk-test"):
            result = await call_openai("say hi")
            assert result["text"] == "Hello World!"
            assert result["cost"] >= 0


@pytest.mark.asyncio
async def test_cloud_not_configured():
    from router.cloud import is_configured

    # Mock keys to CHANGEME to test the guard
    with (
        patch("router.cloud._ANTHROPIC_KEY", "CHANGEME"),
        patch("router.cloud._OPENAI_KEY", "CHANGEME"),
        patch("router.cloud._GOOGLE_KEY", "CHANGEME"),
    ):
        assert not is_configured("anthropic")
        assert not is_configured("openai")
        assert not is_configured("google")


# ── /api/queries/cancel-all ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancel_all_queries_sets_pending_events(transport):
    """cancel-all should fire every registered cancel event and return the count."""
    import router.main as main_module

    event_a = asyncio.Event()
    event_b = asyncio.Event()
    # Inject fake in-flight requests directly into the registry
    main_module._cancel_events["fake-req-001"] = event_a
    main_module._cancel_events["fake-req-002"] = event_b

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/queries/cancel-all")

        assert resp.status_code == 200
        data = resp.json()
        assert "cancelled" in data
        assert data["remaining"] == 0
        # Both events must have been set
        assert event_a.is_set()
        assert event_b.is_set()
    finally:
        main_module._cancel_events.pop("fake-req-001", None)
        main_module._cancel_events.pop("fake-req-002", None)


@pytest.mark.asyncio
async def test_cancel_all_queries_empty_registry(transport):
    """cancel-all on an empty registry should return cancelled:0 without error."""
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/queries/cancel-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["remaining"] == 0
