import json
import time
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from router import audit, policy, scorer
from router.main import app


@pytest.fixture
def isolated_policy(tmp_path, monkeypatch):
    monkeypatch.setattr(policy, "POLICY_PATH", tmp_path / "budget_policy.json")
    yield


def test_budget_policy_persists_and_forces_local(isolated_policy):
    saved = policy.save_policy({"mode": "local_only", "daily_limit": 0.25, "retention_days": 7})
    assert saved["mode"] == "local_only"
    assert policy.load_policy()["daily_limit"] == 0.25
    assert scorer.is_budget_exhausted("any-session") is True


def test_audit_log_read_and_retention(tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    audit.audit_event("test.old", value=1)
    old_ts = time.time() - 10
    rows = audit.AUDIT_PATH.read_text().splitlines()
    row = json.loads(rows[0])
    row["ts"] = old_ts
    audit.AUDIT_PATH.write_text(json.dumps(row) + "\n", encoding="utf-8")
    audit.audit_event("test.new", value=2)

    removed = audit.purge_events_before(time.time() - 1)
    assert removed == 1
    remaining = audit.read_events()
    assert [r["event"] for r in remaining] == ["test.new"]


@pytest.mark.asyncio
async def test_budget_and_performance_endpoints(isolated_policy):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        cap = await client.post("/api/budget/cap?cap=1.5")
        assert cap.status_code == 200
        assert cap.json()["effective_daily_limit"] == 1.5

        budget = await client.get("/api/budget")
        assert budget.status_code == 200
        assert budget.json()["daily_limit"] == 1.5

        perf = await client.get("/api/performance?trace=1")
        assert perf.status_code == 200
        data = perf.json()
        assert "latency_p50" in data
        assert "tier_distribution" in data
        assert "query_trace" in data


@pytest.mark.asyncio
async def test_dashboard_replay_and_sankey_payload(monkeypatch):
    rows = [
        {"ts": 100.0, "tier": "local", "model": "qwen3-coder:30b", "category": "code", "latency_ms": 42, "cost": 0},
        {"ts": 101.0, "tier": "cloud_cheap", "model": "gpt-4o-mini", "category": "research", "latency_ms": 1200, "cost_usd": 0.001},
    ]
    monkeypatch.setattr(scorer, "read_scoring_log", lambda limit=10_000: rows)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get("/api/dashboard")
        assert dashboard.status_code == 200
        payload = dashboard.json()
        assert payload["tier_distribution"]["local"] == 1
        assert payload["sankey"]["cat_tier"]["code"]["local"] == 1
        assert payload["sankey"]["tier_model"]["cloud_cheap"]["gpt-4o-mini"] == 1

        replay = await client.get("/api/routing/replay?limit=1")
        assert replay.status_code == 200
        replay_payload = replay.json()
        assert replay_payload["total"] == 2
        assert replay_payload["decisions"][0]["tier_used"] == "cloud_cheap"

        active = await client.get("/api/queries/active")
        assert active.status_code == 200
        assert active.json()["count"] == 0
        assert active.json()["total"] == 0


@pytest.mark.asyncio
async def test_dashboard_filters_test_scaffolding_by_default(monkeypatch):
    rows = [
        {"ts": 100.0, "tier": "local", "model": "fake-local", "category": "conversation", "latency_ms": 1, "cost": 0},
        {"ts": 101.0, "tier": "cloud_full", "model": "fake-cloud", "category": "code", "latency_ms": 1, "cost_usd": 0.001},
        {"ts": 102.0, "tier": "local", "model": "real-local", "category": "code", "latency_ms": 50, "cost": 0},
    ]
    monkeypatch.setattr(scorer, "read_scoring_log", lambda limit=10_000: rows)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        dashboard = await client.get("/api/dashboard")
        replay = await client.get("/api/routing/replay")
        full = await client.get("/api/dashboard?include_test=true")

    payload = dashboard.json()
    assert payload["total_queries"] == 1
    assert payload["tier_distribution"] == {"local": 1}
    assert payload["sankey"]["tier_model"] == {"local": {"real-local": 1}}
    assert replay.json()["total"] == 1
    assert full.json()["total_queries"] == 3


@pytest.mark.asyncio
async def test_dashboard_empty_payload_has_stable_numeric_fields(monkeypatch):
    monkeypatch.setattr(scorer, "read_scoring_log", lambda limit=10_000: [])
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["cache_hit_rate"] == 0.0
    assert payload["estimated_cloud_cost"] == 0.0
    assert payload["tier_distribution"] == {}
    assert payload["query_trace"] == []
    assert payload["sankey"] == {"cat_tier": {}, "tier_model": {}, "total_queries": 0}


@pytest.mark.asyncio
async def test_performance_payload_has_legacy_stable_fields(monkeypatch):
    rows = [
        {"ts": time.time(), "tier": "local_multi", "model": "qwen3-coder:30b", "category": "code", "latency_ms": 2500, "cost": 0}
    ]
    monkeypatch.setattr(scorer, "read_scoring_log", lambda limit=10_000: rows)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/performance?trace=1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["model_usage"] == {"qwen3-coder:30b": 1}
    assert payload["category_distribution"] == {"code": 1}
    assert payload["slowest_queries"][0]["tier"] == "local_multi"
    assert "mcp_trace" in payload


@pytest.mark.asyncio
async def test_gpu_advisor_and_agent_compatibility_endpoints(monkeypatch):
    from router import main as main_module

    async def fake_vram_status():
        return {
            "available": True,
            "capacity_known": False,
            "pressure": "ok",
            "vram_used_gb": 1.0,
            "vram_total_gb": 0.0,
            "loaded_models": [{"name": "coder:9b", "vram_gb": 1.0}],
        }

    monkeypatch.setattr(main_module, "vram_status", fake_vram_status)
    advisor_payload = await main_module.gpu_advisor()
    agents_payload = await main_module.agents_status()

    assert "recommendation" in advisor_payload
    assert agents_payload["agents"] == []


@pytest.mark.asyncio
async def test_privacy_status_and_retention_endpoint(isolated_policy, tmp_path, monkeypatch):
    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        retention = await client.post("/api/privacy/retention", json={"days": 5})
        assert retention.status_code == 200
        assert retention.json()["retention_days"] == 5

        status = await client.get("/api/privacy/status")
        assert status.status_code == 200
        assert status.json()["retention_days"] == 5
        assert "chroma_entries" in status.json()
        assert "log_lines" in status.json()


@pytest.mark.asyncio
async def test_privacy_global_export_includes_cache_and_access_log(isolated_policy, tmp_path, monkeypatch):
    from router import cache as cache_mod
    from router import main

    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    monkeypatch.setattr(main, "_access_log_path", tmp_path / "access_log.jsonl")
    main._access_log_path.write_text('{"path":"/health"}\n', encoding="utf-8")
    monkeypatch.setattr(
        cache_mod,
        "scan_entries",
        lambda limit=100_000, offset=0: [{"id": "cache-1", "document": "answer", "metadata": {"session_id": "s1"}}],
    )
    monkeypatch.setattr(cache_mod, "_get_client", lambda: None)
    monkeypatch.setattr(scorer, "read_scoring_log", lambda limit=100_000: [{"session_id": "s1", "tier": "local"}])

    response = await main.privacy_export()
    assert response.media_type == "application/zip"
    with zipfile.ZipFile(response.path) as zf:
        names = set(zf.namelist())
        assert "cache_entries.json" in names
        assert "cache_export.jsonl" in names
        assert "chroma_export.jsonl" in names
        assert "access_log.jsonl" in names


@pytest.mark.asyncio
async def test_privacy_session_export_and_delete(isolated_policy, tmp_path, monkeypatch):
    from router import cache as cache_mod

    monkeypatch.setattr(audit, "AUDIT_PATH", tmp_path / "audit.jsonl")
    session_id = "session-abc"
    deleted = {}
    monkeypatch.setattr(scorer, "read_scoring_log_for_session", lambda sid, limit=100_000: [{"session_id": sid, "tier": "local"}])
    monkeypatch.setattr(scorer, "purge_scoring_logs_for_session", lambda sid: deleted.setdefault("scoring", 1))
    monkeypatch.setattr(cache_mod, "export_entries_by_session", lambda sid, limit=100_000: [{"id": "cache-1", "metadata": {"session_id": sid}}])
    monkeypatch.setattr(cache_mod, "delete_entries_by_session", lambda sid, limit=100_000: deleted.setdefault("cache", 1))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        status = await client.get(f"/api/privacy/session/{session_id}/status")
        assert status.status_code == 200
        assert status.json()["scoring_log_entries"] == 1
        assert status.json()["cache_entries"] == 1

        bad_delete = await client.post(f"/api/privacy/session/{session_id}/delete", json={"confirm": "DELETE_SESSION", "session_id": "other"})
        assert bad_delete.status_code == 400
        good_delete = await client.post(f"/api/privacy/session/{session_id}/delete", json={"confirm": "DELETE_SESSION", "session_id": session_id})
        assert good_delete.status_code == 200
        assert good_delete.json()["cache_entries_deleted"] == 1
        assert good_delete.json()["scoring_log_lines_deleted"] == 1

    from router import main

    export = await main.privacy_session_export(session_id)
    assert export.media_type == "application/zip"
    with zipfile.ZipFile(export.path) as zf:
        assert {"scoring_log.json", "cache_entries.json", "manifest.json"}.issubset(zf.namelist())


@pytest.mark.asyncio
async def test_cache_scan_and_entry_delete(monkeypatch):
    from router import cache as cache_mod

    monkeypatch.setattr(cache_mod, "scan_entries", lambda limit=100, offset=0: [{"id": "doc-1", "metadata": {}}])
    monkeypatch.setattr(cache_mod, "delete_entry", lambda entry_id=None, query=None: 1 if entry_id == "doc-1" else 0)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        scan = await client.get("/cache/scan")
        assert scan.status_code == 200
        assert scan.json()["count"] == 1
        deleted = await client.request("DELETE", "/cache/entry", json={"id": "doc-1"})
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True
