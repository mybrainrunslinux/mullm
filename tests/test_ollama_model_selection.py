import pytest

from router.models import IntentCategory, IntentObject, QueryRequest, TierLabel
from router.tiers import _select_ollama_model


@pytest.mark.asyncio
async def test_select_ollama_model_falls_back_to_installed_text_model(monkeypatch):
    async def fake_installed_models():
        return ["nomic-embed-text:latest", "llama3.2:3b"]

    monkeypatch.setattr("router.tiers._ollama_installed_models", fake_installed_models)
    req = QueryRequest(content="Explain margin vs padding.", model="missing-model:latest")
    intent = IntentObject(content=req.content, category=IntentCategory.CONVERSATION)

    assert await _select_ollama_model(req, intent) == "llama3.2:3b"


@pytest.mark.asyncio
async def test_select_ollama_model_prefers_installed_coder_for_code(monkeypatch):
    async def fake_installed_models():
        return ["qwen3:4b", "qwen3-coder:7b"]

    monkeypatch.setattr("router.tiers._ollama_installed_models", fake_installed_models)
    req = QueryRequest(content="Write a Python function.", model="missing-model:latest")
    intent = IntentObject(content=req.content, category=IntentCategory.CODE)

    assert await _select_ollama_model(req, intent) == "qwen3-coder:7b"


@pytest.mark.asyncio
async def test_select_ollama_model_uses_local_multi_model_when_forced(monkeypatch):
    async def fake_installed_models():
        return ["omnicoder:9b", "qwen3-coder:30b"]

    monkeypatch.setenv("MULLM_OLLAMA_MULTI_MODEL", "qwen3-coder:30b")
    monkeypatch.setattr("router.tiers._ollama_installed_models", fake_installed_models)
    req = QueryRequest(content="Write a Python patch.", force_tier=TierLabel.LOCAL_MULTI)
    intent = IntentObject(content=req.content, category=IntentCategory.CODE)

    assert await _select_ollama_model(req, intent) == "qwen3-coder:30b"
