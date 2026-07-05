from pathlib import Path

import pytest

from router import scorer
from router.groundtruth import lookup
from router.intent import classify
from router.models import IntentCategory, IntentObject, PipelineResult, QueryRequest, TierLabel
from router.tiers import _should_store_in_cache, execute_pipeline, run_cache

ROOT = Path(__file__).resolve().parents[1]
CHAT_HTML = ROOT / "router" / "chat.html"


def test_query_request_defaults_are_safe():
    req = QueryRequest(content="What's the difference between margin and padding in CSS?")
    assert req.use_web is False
    assert req.use_jina is False
    assert req.allow_cloud_escalation is False


def test_query_request_maps_legacy_cloud_multi_to_cloud_power():
    req = QueryRequest(content="hard task", force_tier="cloud_multi")

    assert req.tier_override == TierLabel.CLOUD_POWER


def test_latest_version_queries_are_freshness_sensitive():
    result = classify("What is the latest Python version?")

    assert result.needs_web is True


@pytest.mark.asyncio
async def test_freshness_queries_skip_semantic_cache_lookup(monkeypatch):
    async def fail_lookup(*args, **kwargs):
        raise AssertionError("freshness-sensitive queries must not read semantic cache")

    monkeypatch.setattr("router.tiers.cache.lookup", fail_lookup)

    result = await run_cache(
        QueryRequest(content="What is the latest Python version?"),
        IntentObject(
            content="What is the latest Python version?",
            category=IntentCategory.LOOKUP,
            needs_web=True,
        ),
    )

    assert result is None


@pytest.mark.asyncio
async def test_forced_cache_can_probe_freshness_query_cache(monkeypatch):
    async def fake_lookup(query, category="default"):
        assert query == "What is the latest Python version?"
        assert category == "lookup"
        return "cached answer", {"cache_similarity": 1.0}

    monkeypatch.setattr("router.tiers.cache.lookup", fake_lookup)

    result = await run_cache(
        QueryRequest(content="What is the latest Python version?", force_tier="cache"),
        IntentObject(
            content="What is the latest Python version?",
            category=IntentCategory.LOOKUP,
            needs_web=True,
        ),
    )

    assert result is not None
    assert result.cached is True
    assert result.response == "cached answer"


def test_freshness_queries_are_not_stored_in_semantic_cache():
    request = QueryRequest(content="What is the latest Python version?", use_web=True)
    intent = IntentObject(content=request.content, category=IntentCategory.LOOKUP, needs_web=True)
    result = PipelineResult(
        response="fresh answer",
        tier=TierLabel.LOCAL,
        cost=0.0,
        tokens_used=3,
        latency_ms=1.0,
        model_used="fake-local",
        session_id=request.session_id,
        intent=intent,
    )

    assert _should_store_in_cache(request, intent, result) is False


def test_css_sample_card_is_groundtruth_zero_cost():
    result = lookup("What's the difference between margin and padding in CSS?")
    assert result is not None
    answer, category = result
    assert category == "css_facts"
    assert "margin" in answer.lower()
    assert "padding" in answer.lower()


def test_groundtruth_does_not_hijack_codegen_sample_card():
    result = lookup(
        "Write a complete TypeScript implementation of a B+ tree with insert, "
        "delete, range query, and serialization. Include unit tests and Big-O analysis."
    )
    assert result is None


@pytest.mark.asyncio
async def test_btree_sample_forced_cloud_reaches_cloud_runner(monkeypatch):
    from router.models import PipelineResult

    async def fake_cache(_request, _intent):
        return None

    async def fake_cloud(request, intent, cheap=True, tier=None):
        return PipelineResult(
            response="cloud implementation response",
            tier=tier or TierLabel.CLOUD_FULL,
            cost=0.001,
            tokens_used=10,
            latency_ms=1.0,
            model_used="fake-cloud",
            session_id=request.session_id,
            intent=intent,
        )

    monkeypatch.setattr("router.tiers.run_cache", fake_cache)
    monkeypatch.setattr("router.tiers.run_cloud", fake_cloud)

    result = await execute_pipeline(
        QueryRequest(
            content=(
                "Write a complete TypeScript implementation of a B+ tree with insert, "
                "delete, range query, and serialization. Include unit tests and Big-O analysis."
            ),
            force_tier="cloud_full",
            skip_cache=True,
        )
    )

    assert result.tier == TierLabel.CLOUD_FULL
    assert result.model_used == "fake-cloud"
    assert result.response == "cloud implementation response"


@pytest.mark.asyncio
async def test_forced_local_multi_reports_local_multi_alias(monkeypatch):
    from router.models import IntentObject, PipelineResult

    async def fake_run_local(request, intent):
        return PipelineResult(
            response="local multi response",
            tier=TierLabel.LOCAL,
            cost=0,
            tokens_used=3,
            latency_ms=1.0,
            model_used="qwen3-coder:30b",
            session_id=request.session_id,
            intent=intent,
        )

    monkeypatch.setattr("router.tiers.run_local", fake_run_local)
    monkeypatch.setattr("router.intent.classify", lambda content, history=None: IntentObject(content=content))

    result = await execute_pipeline(
        QueryRequest(content="medium code task", force_tier="local_multi", skip_cache=True)
    )

    assert result.tier == TierLabel.LOCAL_MULTI
    assert result.tier_used == "local_multi"


@pytest.mark.asyncio
async def test_forced_cloud_rejects_unknown_model_before_provider_call(monkeypatch):
    from router.models import IntentObject
    from router.tiers import run_cloud

    async def fail_complete(*args, **kwargs):
        raise AssertionError("unknown cloud model must not reach a real provider call")

    monkeypatch.setattr("router.tiers.cloud.complete", fail_complete)

    with pytest.raises(ValueError, match="Unknown cloud model"):
        await run_cloud(
            QueryRequest(
                content="forced cloud invalid model",
                force_tier="cloud_full",
                model="opus-on-openai-is-not-a-valid-model-id",
            ),
            IntentObject(content="forced cloud invalid model"),
            tier=TierLabel.CLOUD_FULL,
        )


def test_groundtruth_does_not_match_delete_inside_implementation_prompt():
    result = lookup("Implement delete for a balanced tree and explain the rebalancing cases.")
    assert result is None


def test_groundtruth_keeps_short_http_lookup_but_not_incidental_numbers():
    assert lookup("what is HTTP 400") == ("HTTP 400: Bad Request", "http_status")
    assert lookup("Keep it under 400 lines and include tests.") is None


def test_groundtruth_refuses_long_strategic_prompts():
    result = lookup(
        "Strategic analysis: what are the key architectural weaknesses of local-first "
        "LLM routers when they combine cache, local models, cloud fallback, and policy "
        "controls for enterprise deployments?"
    )
    assert result is None


def test_chat_does_not_fake_spend_or_default_web_search():
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "Never ticks up fake spend" in html
    ticker_block = html.split("function startCostTicker", 1)[1].split("function stopCostTicker", 1)[0]
    assert "setInterval" not in ticker_block
    assert "localStorage.getItem('mullm-web-search') === '1'" in html
    assert 'forceTier: "groundtruth"' in html
    assert "forceTierSelect.value = sp.forceTier || (sp.tier === \"free\" ? \"local\" : \"\")" in html
    assert "Only show web-search UI when the user explicitly enabled web search" in html
    assert "Titles must never create hidden model, web, or paid provider work." in html
    assert "Summarize this in exactly 3-5 words" not in html
    assert "/query/stream?content=" not in html


def test_escalate_normalizes_groundtruth_to_local_first():
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "function normalizeTierForEscalation(current)" in html
    assert 'tier.startsWith("groundtruth")) return "cache";' in html
    assert 'if (idx === -1) return "local";' in html
    assert 'showToast("Cannot escalate: original query is not available.", "error");' in html
    assert "selectedProviderAndModelForTier(target)" in html
    assert "Local escalation must not inherit cloud toolbar choices." in html


def test_chat_only_sends_provider_model_when_tier_compatible():
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "function selectedProviderAndModelForTier(tier)" in html
    assert "function tierDefaultModel(provider, tier)" in html
    assert "model: mod && (!tierModel || mod === tierModel) ? mod : \"\"" in html
    assert 'return prov === "ollama" ? { provider: prov, model: mod } : {};' in html


def test_chat_media_generation_checks_provider_before_queueing():
    html = CHAT_HTML.read_text(encoding="utf-8")
    assert "ensureGenerationProvider(genType, mode)" in html
    assert "No 3D generator is configured yet." in html
    assert "s.comfyui || s.meshy || s.tripo || s.rodin || s.sana_wm" in html
    assert "before muLLM queues a 3D asset job" in html


def test_groundtruth_has_safe_product_parity_facts():
    media = lookup("3d asset generator provider not configured setup")
    responsive = lookup("How should a vertical phone game layout work on desktop?")
    enterprise = lookup("enterprise airgapped noninteractive setup deploy")

    assert media is not None and media[1] == "css_facts"
    assert "Open Setup" not in media[0]
    assert responsive is not None and "wider screens" in responsive[0]
    assert enterprise is not None and "noninteractive config" in enterprise[0]


def test_budget_snapshot_reports_process_spend():
    session_id = "budget-snapshot-chat-safety"
    with scorer._store_lock:
        scorer._session_costs[session_id] = 1.25
        scorer._session_counts[session_id] = 2

    snap = scorer.budget_snapshot()
    assert snap["daily_spend"] >= 1.25
    assert snap["query_count"] >= 2
    assert snap["daily_limit"] == scorer.settings.budget_hard
    assert snap["budget_ok"] is True

    with scorer._store_lock:
        scorer._session_costs.pop(session_id, None)
        scorer._session_counts.pop(session_id, None)


def test_dashboard_reads_active_storage(monkeypatch):
    class FakeStorage:
        def recent(self, n):
            return [
                {"ts": 30, "cost_usd": 0.03, "tier": "cloud_cheap"},
                {"ts": 10, "cost_usd": 0.01, "tier": "groundtruth"},
                {"ts": 20, "cost_usd": 0.02, "tier": "local"},
            ]

    monkeypatch.setattr(scorer, "_storage", FakeStorage())
    rows = scorer.read_scoring_log(limit=2)
    assert [r["ts"] for r in rows] == [20, 30]
    assert [r["cost_usd"] for r in rows] == [0.02, 0.03]


@pytest.mark.asyncio
async def test_css_sample_auto_does_not_call_cloud(monkeypatch):
    async def fail_cloud(*args, **kwargs):
        raise AssertionError("CSS sample must not call cloud")

    monkeypatch.setattr("router.cloud.complete", fail_cloud)
    result = await execute_pipeline(QueryRequest(content="What's the difference between margin and padding in CSS?"))

    assert result.cost == 0.0
    assert result.tier == TierLabel.GROUNDTRUTH
    assert result.groundtruth_category == "css_facts"


@pytest.mark.asyncio
async def test_cloud_power_reports_full_when_same_model(monkeypatch):
    from router.cloud import CloudResult
    from router.tiers import run_cloud

    async def fake_complete(**kwargs):
        assert kwargs["model"] == "gemini-3.1-pro-preview"
        return CloudResult(
            text="power and full use the same configured model",
            input_tokens=3,
            output_tokens=5,
            model=kwargs["model"],
            provider="google",
        )

    monkeypatch.setattr("router.tiers.cloud.model_for_tier", lambda **_: "gemini-3.1-pro-preview")
    monkeypatch.setattr("router.tiers.cloud.complete", fake_complete)

    result = await run_cloud(
        QueryRequest(content="escalate this", force_tier="cloud_power"),
        IntentObject(content="escalate this"),
        cheap=False,
        tier=TierLabel.CLOUD_POWER,
    )

    assert result.model_used == "gemini-3.1-pro-preview"
    assert result.tier == TierLabel.CLOUD_FULL


@pytest.mark.asyncio
async def test_cloud_escalation_reports_cheap_when_all_tiers_same_model(monkeypatch):
    from router.cloud import CloudResult
    from router.tiers import run_cloud

    async def fake_complete(**kwargs):
        assert kwargs["model"] == "glm-5.1"
        return CloudResult(
            text="all cloud tiers collapse to this model",
            input_tokens=3,
            output_tokens=5,
            model=kwargs["model"],
            provider="glm",
        )

    monkeypatch.setattr("router.tiers.cloud.model_for_tier", lambda **_: "glm-5.1")
    monkeypatch.setattr("router.tiers.cloud.complete", fake_complete)

    result = await run_cloud(
        QueryRequest(content="escalate this", force_tier="cloud_power"),
        IntentObject(content="escalate this"),
        cheap=False,
        tier=TierLabel.CLOUD_POWER,
    )

    assert result.model_used == "glm-5.1"
    assert result.tier == TierLabel.CLOUD_CHEAP


@pytest.mark.asyncio
async def test_local_quality_gate_does_not_auto_spend_without_permission(monkeypatch):
    async def fake_groundtruth(_request):
        return None

    async def fake_cache(_request, _intent):
        return None

    async def fake_local(request, intent):
        from router.models import PipelineResult

        return PipelineResult(
            response="short",
            tier=TierLabel.LOCAL,
            cost=0.0,
            tokens_used=1,
            latency_ms=1.0,
            model_used="fake-local",
            session_id=request.session_id,
            intent=intent,
        )

    async def fail_cloud(*args, **kwargs):
        raise AssertionError("automatic cloud escalation is disabled by default")

    monkeypatch.setattr("router.tiers.run_groundtruth", fake_groundtruth)
    monkeypatch.setattr("router.tiers.run_cache", fake_cache)
    monkeypatch.setattr("router.tiers.run_local", fake_local)
    monkeypatch.setattr("router.tiers.cloud.complete", fail_cloud)
    monkeypatch.setattr(
        "router.tiers.scorer.select_tier",
        lambda intent, session_id="": TierLabel.LOCAL,
    )

    result = await execute_pipeline(QueryRequest(content="Answer locally please"))

    assert result.tier == TierLabel.LOCAL
    assert result.cost == 0.0
    assert result.quality_escalated is False


@pytest.mark.asyncio
async def test_forced_cloud_obeys_hard_budget(monkeypatch):
    session_id = "budget-test-chat-safety"
    with scorer._store_lock:
        scorer._session_costs[session_id] = 10_000.0
        scorer._session_counts[session_id] = 1

    async def fake_groundtruth(_request):
        return None

    async def fake_local(request, intent):
        from router.models import PipelineResult

        return PipelineResult(
            response="local because budget is exhausted",
            tier=TierLabel.LOCAL,
            cost=0.0,
            tokens_used=1,
            latency_ms=1.0,
            model_used="fake-local",
            session_id=request.session_id,
            intent=intent,
        )

    async def fail_cloud(*args, **kwargs):
        raise AssertionError("forced cloud must not bypass hard budget")

    monkeypatch.setattr("router.tiers.run_groundtruth", fake_groundtruth)
    monkeypatch.setattr("router.tiers.run_local", fake_local)
    monkeypatch.setattr("router.tiers.cloud.complete", fail_cloud)
    result = await execute_pipeline(
        QueryRequest(content="force cloud anyway", session_id=session_id, force_tier="cloud_cheap")
    )

    assert result.tier == TierLabel.LOCAL
    assert result.cost == 0.0

    with scorer._store_lock:
        scorer._session_costs.pop(session_id, None)
        scorer._session_counts.pop(session_id, None)
