"""
Smoke tests for the OpenAI-compatible /v1/chat/completions endpoint.

Two test layers:
  1. Pydantic schema tests — verify ChatCompletionRequest accepts/rejects the
     specific payload shapes that each coding CLI sends.
  2. Endpoint smoke tests — POST to /v1/chat/completions via ASGI transport
     (no live server, no Ollama, no cloud) with execute_pipeline mocked.

CLIs tested:
  - Claude Code (Anthropic CLI)
  - Codex (OpenAI CLI)
  - Aider
  - Continue.dev (VS Code / JetBrains extension)
  - Cursor (AI-first editor)
  - Cline (VS Code extension, formerly Claude Dev)
  - Zed AI (Zed editor)
  - GitHub Copilot (proxy mode)
  - Tabby (self-hosted — as an OpenAI-compat client forwarding to muLLM)

Backend coverage notes (no separate .py files needed):
  - vLLM    — registered via OpenAICompatBackend in registry.py:62-70
  - TabbyAPI — registered via OpenAICompatBackend in registry.py:72-83
  - LiteLLM  — registered via OpenAICompatBackend in registry.py:85-96

Known compatibility gap (model whitelist):
  The endpoint validates model names against CLOUD_MODEL_PRICING | {"mullm-auto"}.
  Some CLIs default to model strings not in this list (e.g., Cline uses
  "claude-3-5-sonnet-20241022"). Those requests will receive HTTP 400 unless
  the user configures the CLI to use a model ID in the whitelist (e.g.,
  "claude-sonnet-4-6") or the whitelist is extended.
"""
from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from router.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatCompletionChoice,
    ChatMessage,
    ModelInfo,
    ModelsListResponse,
    PipelineResult,
    TierLabel,
)
from router.config import CLOUD_MODEL_PRICING


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _parse(payload: dict) -> ChatCompletionRequest:
    """Parse a raw dict as ChatCompletionRequest; raises ValidationError on failure."""
    return ChatCompletionRequest.model_validate(payload)


def _fake_pipeline_result(model: str = "gpt-4o-mini") -> PipelineResult:
    """Return a minimal valid PipelineResult for mocking execute_pipeline."""
    return PipelineResult(
        response="mocked response",
        tier=TierLabel.LOCAL,
        cost=0.0,
        tokens_used=5,
        latency_ms=1.0,
        model_used=model,
    )


# ---------------------------------------------------------------------------
# Layer 1 — Pydantic schema tests (no HTTP, no app import)
# ---------------------------------------------------------------------------

class TestChatCompletionRequestSchema(unittest.TestCase):
    """Verify the schema accepts extra fields silently (Pydantic v2 default)."""

    def test_extra_fields_ignored(self):
        """All CLIs send fields not in our schema; they must be ignored, not rejected."""
        req = _parse({
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": "hello"}],
            "tools": [],
            "tool_choice": "none",
            "n": 1,
            "seed": 42,
            "stop": ["<|endoftext|>"],
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
            "logprobs": True,
            "response_format": {"type": "json_object"},
        })
        self.assertEqual(req.model, "gpt-4o-mini")

    def test_multipart_content_text(self):
        """CLIs (Claude Code, Continue.dev) send content as typed-part lists."""
        req = _parse({
            "model": "claude-sonnet-4-6",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Review this code."},
                        {"type": "text", "text": "def foo(): pass"},
                    ],
                }
            ],
        })
        self.assertIn("Review this code.", req.messages[0].text())

    def test_conversation_history(self):
        """All CLIs send multi-turn history."""
        req = _parse({
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": "You are a coding assistant."},
                {"role": "user", "content": "What is a closure?"},
                {"role": "assistant", "content": "A closure captures surrounding scope."},
                {"role": "user", "content": "Give me a Python example."},
            ],
        })
        self.assertEqual(len(req.messages), 4)
        self.assertEqual(req.messages[-1].role, "user")

    def test_missing_messages_raises(self):
        with self.assertRaises(ValidationError):
            _parse({"model": "gpt-4o-mini", "messages": []})

    def test_temperature_out_of_range_raises(self):
        with self.assertRaises(ValidationError):
            _parse({
                "model": "gpt-4o-mini",
                "messages": [{"role": "user", "content": "hi"}],
                "temperature": 3.5,
            })

    def test_all_cloud_models_parse(self):
        for model_id in CLOUD_MODEL_PRICING:
            with self.subTest(model=model_id):
                req = _parse({
                    "model": model_id,
                    "messages": [{"role": "user", "content": "ping"}],
                })
                self.assertEqual(req.model, model_id)

    def test_mullm_auto_model_parses(self):
        req = _parse({
            "model": "mullm-auto",
            "messages": [{"role": "user", "content": "hello"}],
        })
        self.assertEqual(req.model, "mullm-auto")


# ---------------------------------------------------------------------------
# Layer 2 — Endpoint smoke tests via ASGI transport + mocked pipeline
# ---------------------------------------------------------------------------

@pytest.fixture
def fake_pipeline():
    """Patch execute_pipeline on the tiers module to avoid real model calls."""
    mock = AsyncMock(return_value=_fake_pipeline_result())
    with patch("router.tiers.execute_pipeline", mock):
        yield mock


@pytest.fixture
def app():
    from router.main import app as _app
    return _app


def _user_msg(text: str) -> dict:
    return {"role": "user", "content": text}


def _sys_msg(text: str) -> dict:
    return {"role": "system", "content": text}


# ---------------------------------------------------------------------------
# Claude Code
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_claude_code_basic(app, fake_pipeline):
    """Claude Code sends claude-* model IDs, stream=true, max_tokens."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "claude-haiku-4-5",
            "messages": [_sys_msg("You are a helpful assistant."), _user_msg("Explain async/await.")],
            "stream": False,
            "max_tokens": 4096,
        })
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "chat.completion"
    assert data["choices"][0]["message"]["role"] == "assistant"
    assert data["choices"][0]["finish_reason"] == "stop"


@pytest.mark.asyncio
async def test_claude_code_stream(app, fake_pipeline):
    """Claude Code streaming — verify SSE chunks are emitted."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "claude-haiku-4-5",
            "messages": [_user_msg("Hello")],
            "stream": True,
        })
    assert r.status_code == 200
    assert "text/event-stream" in r.headers.get("content-type", "")
    assert "data: " in r.text
    assert "[DONE]" in r.text


@pytest.mark.asyncio
async def test_claude_code_multipart_content(app, fake_pipeline):
    """Claude Code sends content as typed-part list."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "claude-sonnet-4-6",
            "messages": [
                {
                    "role": "user",
                    "content": [{"type": "text", "text": "Review this snippet."}],
                }
            ],
        })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Codex (OpenAI CLI)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_codex_basic(app, fake_pipeline):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [_user_msg("Write a quicksort in Python.")],
            "temperature": 0.2,
            "max_tokens": 2048,
            "n": 1,   # extra field — must be ignored
        })
    assert r.status_code == 200
    assert r.json()["object"] == "chat.completion"


@pytest.mark.asyncio
async def test_codex_zero_temperature(app, fake_pipeline):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o-mini",
            "messages": [_user_msg("ping")],
            "temperature": 0.0,
        })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Aider
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_aider_stream_with_history(app, fake_pipeline):
    """Aider sends full history, stream=true, stop sequences."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [
                _sys_msg("Act as an expert programmer."),
                _user_msg("Show me a Python class."),
                {"role": "assistant", "content": "class Foo: pass"},
                _user_msg("Now add a method."),
            ],
            "stream": True,
            "temperature": 0.0,
            "stop": ["<|endoftext|>"],
            "presence_penalty": 0.0,
            "frequency_penalty": 0.0,
        })
    assert r.status_code == 200
    assert "data: " in r.text


# ---------------------------------------------------------------------------
# Continue.dev
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_continue_dev_with_tools(app, fake_pipeline):
    """Continue.dev sends tools and tool_choice — must be ignored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o-mini",
            "messages": [_user_msg("What files are in src/?")],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "read_file",
                        "description": "Read a file",
                        "parameters": {"type": "object", "properties": {"path": {"type": "string"}}},
                    },
                }
            ],
            "tool_choice": "auto",
            "stream": True,
        })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Cursor
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cursor_with_seed_and_response_format(app, fake_pipeline):
    """Cursor sends seed and response_format — must be accepted and ignored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [_user_msg("Return a JSON schema.")],
            "temperature": 0.1,
            "seed": 42,
            "response_format": {"type": "json_object"},
        })
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_cursor_stream(app, fake_pipeline):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [_user_msg("Generate a Fibonacci function.")],
            "stream": True,
        })
    assert r.status_code == 200
    assert "data: " in r.text


# ---------------------------------------------------------------------------
# Cline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_cline_with_claude_model(app, fake_pipeline):
    """Cline's claude-* model IDs are in the whitelist when using versioned names."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "claude-sonnet-4-6",  # must be a CLOUD_MODEL_PRICING key
            "messages": [
                _sys_msg("You are Cline, an AI coding assistant."),
                _user_msg("Create a Flask API endpoint."),
            ],
            "stream": True,
            "max_tokens": 8096,
            "tools": [{"type": "function", "function": {"name": "list_files"}}],
            "tool_choice": "auto",
        })
    assert r.status_code == 200


def test_cline_default_model_not_in_whitelist():
    """
    Cline defaults to 'claude-3-5-sonnet-20241022' — a model ID NOT in
    CLOUD_MODEL_PRICING. This is a known compatibility gap: users must
    configure Cline to use a model ID from the muLLM whitelist (e.g.,
    'claude-sonnet-4-6') or the endpoint returns HTTP 400.
    """
    cline_default = "claude-3-5-sonnet-20241022"
    assert cline_default not in CLOUD_MODEL_PRICING, (
        f"If {cline_default!r} was added to CLOUD_MODEL_PRICING, update this test. "
        "This test documents the compatibility gap, not a bug to fix."
    )


# ---------------------------------------------------------------------------
# Zed AI
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_zed_ai_basic(app, fake_pipeline):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o-mini",
            "messages": [
                _user_msg("What is a closure?"),
                {"role": "assistant", "content": "A closure captures surrounding scope."},
                _user_msg("Give me a Python example."),
            ],
            "stream": False,
            "max_tokens": 1024,
        })
    assert r.status_code == 200
    data = r.json()
    assert "choices" in data
    assert data["choices"][0]["message"]["content"] == "mocked response"


# ---------------------------------------------------------------------------
# GitHub Copilot (proxy mode)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_copilot_proxy_with_logprobs(app, fake_pipeline):
    """Copilot may send logprobs — must be accepted and ignored."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o",
            "messages": [
                _sys_msg("You are GitHub Copilot."),
                _user_msg("Complete: def add(a, b):"),
            ],
            "temperature": 0.0,
            "stream": True,
            "logprobs": True,
            "top_logprobs": 5,
        })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# Tabby (self-hosted — forwarding to muLLM as OpenAI-compat client)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_tabby_client_basic(app, fake_pipeline):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "gpt-4o-mini",
            "messages": [_user_msg("Write a unit test for this function.")],
            "stream": False,
            "temperature": 0.0,
            "max_tokens": 512,
        })
    assert r.status_code == 200


# ---------------------------------------------------------------------------
# /v1/models endpoint
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_models_list_endpoint(app):
    """All CLIs that enumerate models call GET /v1/models."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/v1/models")
    assert r.status_code == 200
    data = r.json()
    assert data["object"] == "list"
    assert isinstance(data["data"], list)
    assert len(data["data"]) > 0
    model_ids = [m["id"] for m in data["data"]]
    assert "mullm-auto" in model_ids


# ---------------------------------------------------------------------------
# Model whitelist — unknown models must return 400
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unknown_model_returns_400(app, fake_pipeline):
    """An unregistered model name must be rejected with HTTP 400."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/v1/chat/completions", json={
            "model": "no-such-model-xyz",
            "messages": [_user_msg("hello")],
        })
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Response shape — unit tests on Pydantic models, no HTTP
# ---------------------------------------------------------------------------

class TestResponseShape(unittest.TestCase):
    def _make_response(self) -> ChatCompletionResponse:
        return ChatCompletionResponse(
            id="chatcmpl-abc123",
            model="gpt-4o-mini",
            choices=[
                ChatCompletionChoice(
                    index=0,
                    message=ChatMessage(role="assistant", content="Hello!"),
                    finish_reason="stop",
                )
            ],
            usage=ChatCompletionUsage(
                prompt_tokens=10,
                completion_tokens=5,
                total_tokens=15,
            ),
        )

    def test_response_object_field(self):
        r = self._make_response()
        self.assertEqual(r.object, "chat.completion")

    def test_response_choice_finish_reason(self):
        r = self._make_response()
        self.assertEqual(r.choices[0].finish_reason, "stop")

    def test_response_usage_totals(self):
        r = self._make_response()
        self.assertEqual(r.usage.total_tokens, 15)

    def test_models_list_response_shape(self):
        resp = ModelsListResponse(
            data=[
                ModelInfo(id="mullm-auto", owned_by="mullm"),
                ModelInfo(id="gpt-4o-mini", owned_by="openai"),
            ]
        )
        self.assertEqual(resp.object, "list")
        self.assertEqual(len(resp.data), 2)


# ---------------------------------------------------------------------------
# Backend coverage — verify settings attributes exist (registry.py wires them)
# ---------------------------------------------------------------------------

class TestBackendCoverage(unittest.TestCase):
    """
    vLLM, TabbyAPI, and LiteLLM are all registered via the generic
    OpenAICompatBackend in router/backends/registry.py. No separate
    tabbyapi.py / vllm.py / litellm.py files are needed or created —
    the architecture deliberately avoids redundant subclasses when a
    single generic class parameterised by constructor args suffices.

    These tests confirm the settings keys that drive the conditional
    registration are present and correctly named.
    """

    def test_vllm_settings_exist(self):
        from router.config import settings
        self.assertTrue(hasattr(settings, "vllm_base_url"))
        self.assertTrue(hasattr(settings, "vllm_model"))

    def test_tabbyapi_settings_exist(self):
        from router.config import settings
        self.assertTrue(hasattr(settings, "tabbyapi_base_url"))
        self.assertTrue(hasattr(settings, "tabbyapi_model"))
        self.assertTrue(hasattr(settings, "tabbyapi_api_key"))

    def test_litellm_settings_exist(self):
        from router.config import settings
        self.assertTrue(hasattr(settings, "litellm_base_url"))
        self.assertTrue(hasattr(settings, "litellm_model"))
        self.assertTrue(hasattr(settings, "litellm_api_key"))

    def test_openai_compat_backend_instantiates_for_vllm(self):
        from router.backends.openai_compat import OpenAICompatBackend
        b = OpenAICompatBackend("vllm", "http://127.0.0.1:8000", None, "meta-llama/Llama-3-8b")
        self.assertEqual(b.provider_name, "vllm")

    def test_openai_compat_backend_instantiates_for_tabbyapi(self):
        from router.backends.openai_compat import OpenAICompatBackend
        b = OpenAICompatBackend("tabbyapi", "http://127.0.0.1:5000/v1", "key", "Qwen2.5-Coder-32B")
        self.assertEqual(b.provider_name, "tabbyapi")

    def test_openai_compat_backend_instantiates_for_litellm(self):
        from router.backends.openai_compat import OpenAICompatBackend
        b = OpenAICompatBackend("litellm", "http://127.0.0.1:4000", "key", "gpt-4o-mini")
        self.assertEqual(b.provider_name, "litellm")

    def test_vllm_registered_in_registry_source(self):
        """registry.py must contain the vllm registration block."""
        import inspect
        from router.backends import registry
        src = inspect.getsource(registry.init_backends)
        self.assertIn("vllm", src)
        self.assertIn("tabbyapi", src)
        self.assertIn("litellm", src)


if __name__ == "__main__":
    unittest.main()
