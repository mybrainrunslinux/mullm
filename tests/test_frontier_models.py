from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from router import cloud
from router.config import CLOUD_MODEL_PRICING
from router.frontier_models import FRONTIER_MODELS


@pytest.mark.parametrize("model", [m for m in FRONTIER_MODELS if m.startswith("gpt-")])
async def test_openai_frontier_sdk_and_http_use_responses(monkeypatch, model):
    import openai

    create = AsyncMock(return_value=SimpleNamespace(
        output_text="answer", usage=SimpleNamespace(input_tokens=10, output_tokens=20)))
    monkeypatch.setattr(cloud.settings, "openai_api_key", "test")
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: SimpleNamespace(
        responses=SimpleNamespace(create=create)))
    result = await cloud._openai_complete("question", model, 128, 0.2, "system")
    assert result.text == "answer"
    assert result.cost > 0
    assert create.call_args.kwargs == {
        "model": model, "input": "question", "max_output_tokens": 128, "instructions": "system"}

    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        "output": [{"content": [{"type": "output_text", "text": "answer"}]}],
        "usage": {"input_tokens": 10, "output_tokens": 20}})
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(cloud, "_get_client", lambda: SimpleNamespace(post=post))
    monkeypatch.setattr(cloud, "_provider_key", lambda _: "test")
    raw = await cloud._raw_openai("question", model, 128, 0.2, "system")
    assert post.call_args.args[0].endswith("/responses")
    assert "temperature" not in post.call_args.kwargs["json"]
    assert raw["cost"] == result.cost


@pytest.mark.parametrize("model", [m for m in FRONTIER_MODELS if m.startswith("claude-")])
async def test_anthropic_frontier_payload(monkeypatch, model):
    import anthropic

    create = AsyncMock(return_value=SimpleNamespace(
        content=[SimpleNamespace(type="thinking", thinking="internal"),
                 SimpleNamespace(type="text", text="answer")], stop_reason="end_turn",
        usage=SimpleNamespace(input_tokens=10, output_tokens=20)))
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", "test")
    monkeypatch.setattr(anthropic, "AsyncAnthropic", lambda **kw: SimpleNamespace(
        messages=SimpleNamespace(create=create)))
    result = await cloud._anthropic_complete("question", model, 128, 0.2)
    assert result.text == "answer"
    assert "temperature" not in create.call_args.kwargs
    assert result.cost > 0


@pytest.mark.parametrize("model,limit,multiplier", [
    ("gpt-6-astra", 272_000, 2), ("gpt-6.1-sol", 272_000, 2),
    ("claude-haiku-5-5", 100_000, 5),
])
def test_long_context_billing_boundary(model, limit, multiplier):
    rate = CLOUD_MODEL_PRICING[model]["cost_per_m_input"]
    assert cloud._pricing_cost(model, limit, 0) == pytest.approx(limit * rate / 1e6)
    assert cloud._pricing_cost(model, limit + 1, 0) == pytest.approx((limit + 1) * rate * multiplier / 1e6)


@pytest.mark.parametrize("model,before,after,old,new", [
    ("gemini-4-argon", "2026-11-30", "2026-12-01", 12, 24),
    ("gemini-3.8-flash", "2026-12-31", "2027-01-01", 4.5, 9),
])
def test_google_price_changes_are_dated(model, before, after, old, new):
    from datetime import datetime, timezone
    from router.frontier_models import standard_cost
    def cost(day):
        return standard_cost(model, CLOUD_MODEL_PRICING[model], 1_000_000, 1_000_000,
                             at=datetime.fromisoformat(day).replace(tzinfo=timezone.utc))
    assert cost(before) == old
    assert cost(after) == new


async def test_google_raw_bills_thinking_and_omits_argon_sampling(monkeypatch):
    response = SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
        "candidates": [{"content": {"parts": [{"text": "answer"}]}}],
        "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5, "thoughtsTokenCount": 20}})
    post = AsyncMock(return_value=response)
    monkeypatch.setattr(cloud, "_get_client", lambda: SimpleNamespace(post=post))
    monkeypatch.setattr(cloud, "_provider_key", lambda _: "test")
    result = await cloud._raw_google("test", "gemini-4-argon", 128)
    assert result["tokens_out"] == 25
    assert "temperature" not in post.call_args.kwargs["json"]["generationConfig"]


@pytest.mark.parametrize("provider,base,model,path", [
    ("openai", "https://api.openai.com", "gpt-6.1-sol", "/v1/responses"),
    ("google", "https://generativelanguage.googleapis.com/v1beta/openai", "gemini-3.8-flash", "/chat/completions"),
    ("glm", "https://api.z.ai/api/paas/v4", "glm-5.3", "/chat/completions"),
])
async def test_backend_transport_preserves_provider_paths(monkeypatch, provider, base, model, path):
    from router.backends.openai_compat import OpenAICompatBackend
    responses = path.endswith("responses")
    data = ({"output": [{"content": [{"type": "output_text", "text": "answer"}]}],
             "usage": {"input_tokens": 10, "output_tokens": 5}} if responses else
            {"choices": [{"message": {"content": "answer"}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})
    post = AsyncMock(return_value=SimpleNamespace(raise_for_status=lambda: None, json=lambda: data))
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return SimpleNamespace(post=post)
        async def __aexit__(self, *args): pass
    monkeypatch.setattr("router.backends.openai_compat.httpx.AsyncClient", Client)
    backend = OpenAICompatBackend(provider, base, "test", model, api_path="/v1" if responses else "")
    result = await backend.generate([{"role": "user", "content": "hello"}], max_tokens=128)
    assert post.call_args.args[0] == base + path
    assert result.text == "answer"
    assert result.cost_usd > 0
    if provider == "glm":
        assert post.call_args.kwargs["json"]["thinking"] == {"type": "enabled"}
    if responses:
        assert post.call_args.kwargs["json"]["max_output_tokens"] == 128
