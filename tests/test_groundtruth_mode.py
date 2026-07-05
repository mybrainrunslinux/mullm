import pytest
from httpx import ASGITransport, AsyncClient

from router.config import settings
from router.main import app
from router.models import IntentObject, PipelineResult, QueryRequest, TierLabel
from router.tiers import run_groundtruth


@pytest.mark.asyncio
async def test_groundtruth_legacy_mode_fallback(monkeypatch):
    monkeypatch.setattr(settings, "groundtruth_mode", "legacy")

    result = await run_groundtruth(QueryRequest(content="what is http 404"))

    assert result is not None
    assert result.tier == TierLabel.GROUNDTRUTH
    assert result.groundtruth_category == "legacy-realtime"


@pytest.mark.asyncio
async def test_groundtruth_registry_mode_default(monkeypatch):
    monkeypatch.setattr(settings, "groundtruth_mode", "registry")

    result = await run_groundtruth(QueryRequest(content="what is http 404"))

    assert result is not None
    assert result.tier == TierLabel.GROUNDTRUTH
    assert result.groundtruth_category != "legacy-realtime"


@pytest.mark.asyncio
async def test_setup_groundtruth_mode_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "groundtruth_mode", "registry")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/setup/groundtruth", json={"mode": "legacy"})

    assert response.status_code == 200
    assert response.json()["mode"] == "legacy"
    assert settings.groundtruth_mode == "legacy"
    assert 'mode = "legacy"' in (tmp_path / "mullm.toml").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_forced_local_tier_bypasses_groundtruth(monkeypatch):
    import router.tiers as tiers

    async def fake_run_local(request: QueryRequest, intent: IntentObject) -> PipelineResult:
        return PipelineResult(
            response="local answer",
            tier=TierLabel.LOCAL,
            cost=0.0,
            tokens_used=2,
            latency_ms=1.0,
            model_used="test-local",
            cached=False,
            session_id=request.session_id,
            intent=intent,
        )

    async def fake_store(*args, **kwargs):
        return None

    monkeypatch.setattr(settings, "groundtruth_mode", "registry")
    monkeypatch.setattr(tiers, "run_local", fake_run_local)
    monkeypatch.setattr(tiers.cache, "store", fake_store)

    result = await tiers.execute_pipeline(
        QueryRequest(
            content="What is the difference between margin and padding in CSS?",
            force_tier=TierLabel.LOCAL,
            skip_cache=True,
        )
    )

    assert result.tier == TierLabel.LOCAL
    assert result.model_used == "test-local"
    assert result.groundtruth_category is None
