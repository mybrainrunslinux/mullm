import pytest

from router.backends.protocol import BackendResponse, register_backend
from router.models import IntentCategory, IntentObject, QueryRequest
from router.tiers import _select_registered_local_backend, run_local, stream_local


class FakeLocalBackend:
    provider_name = "tabbyapi"

    async def generate(self, messages, model=None, **kwargs):
        assert messages[-1]["content"] == "hello"
        assert kwargs["temperature"] >= 0
        return BackendResponse(text="fake local answer", input_tokens=2, output_tokens=3, model=model or "fake-model", provider="tabbyapi")

    async def stream(self, messages, model=None, **kwargs):
        yield "fake "
        yield "stream"

    async def health(self):
        return True


def test_select_registered_local_backend_respects_priority(monkeypatch):
    register_backend("tabbyapi", FakeLocalBackend())
    monkeypatch.setenv("MULLM_LOCAL_BACKEND_PRIORITY", "tabbyapi,ollama")

    assert _select_registered_local_backend() == "tabbyapi"


def test_select_registered_local_backend_falls_back_to_ollama(monkeypatch):
    monkeypatch.setenv("MULLM_LOCAL_BACKEND_PRIORITY", "vllm,ollama")

    assert _select_registered_local_backend() == "ollama"


@pytest.mark.asyncio
async def test_run_local_uses_registered_non_ollama_backend(monkeypatch):
    register_backend("tabbyapi", FakeLocalBackend())
    monkeypatch.setenv("MULLM_LOCAL_BACKEND_PRIORITY", "tabbyapi,ollama")
    req = QueryRequest(content="hello", model="fake-model")
    intent = IntentObject(content=req.content, category=IntentCategory.CONVERSATION)

    result = await run_local(req, intent)

    assert result.response == "fake local answer"
    assert result.model_used == "fake-model"
    assert result.tokens_used == 5
    assert result.tier.value == "local"


@pytest.mark.asyncio
async def test_stream_local_uses_registered_non_ollama_backend(monkeypatch):
    register_backend("tabbyapi", FakeLocalBackend())
    monkeypatch.setenv("MULLM_LOCAL_BACKEND_PRIORITY", "tabbyapi,ollama")
    req = QueryRequest(content="hello")
    intent = IntentObject(content=req.content, category=IntentCategory.CONVERSATION)

    chunks = [chunk async for chunk in stream_local(req, intent)]

    assert "".join(chunks) == "fake stream"
