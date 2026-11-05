import asyncio
import time
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from router import cloud, policy
from router.config import Settings, settings
from router.models import QueryRequest


def test_privacy_environment_and_deadline_validation(monkeypatch):
    monkeypatch.setenv("DISABLE_CLOUD", "1")
    assert Settings(_env_file=None).disable_cloud
    with pytest.raises(ValidationError):
        Settings(request_timeout_seconds=30, _env_file=None)


@pytest.mark.parametrize("method,args", [
    ("_raw_openai", ("private", "gpt-6-astra")),
    ("_raw_anthropic", ("private", "claude-opus-5-5")),
    ("_openai_complete", ("private", "gpt-6-astra", 32, 0.4)),
    ("_anthropic_complete", ("private", "claude-opus-5-5", 32, 0.4)),
    ("execute_cloud", ("private",)),
    ("generate_image", ("private",)),
])
async def test_privacy_blocks_before_transport(monkeypatch, method, args):
    monkeypatch.setattr(settings, "disable_cloud", True)
    with pytest.raises(RuntimeError, match="Cloud inference disabled"):
        await getattr(cloud, method)(*args)


async def test_privacy_blocks_streaming_and_remote_backend(monkeypatch):
    from router.backends.openai_compat import OpenAICompatBackend
    monkeypatch.setattr(settings, "disable_cloud", True)
    with pytest.raises(RuntimeError, match="Cloud inference disabled"):
        await anext(cloud.stream_openai("private"))
    backend = OpenAICompatBackend("test", "https://example.org/v1", "test", "test")
    with pytest.raises(RuntimeError, match="Cloud inference disabled"):
        await backend.generate([{"role": "user", "content": "private"}])
    policy.require_inference_allowed("http://127.0.0.1:11434")


@pytest.mark.parametrize("powerup", [False, True])
async def test_query_deadline_cancels_work_and_releases_slot(monkeypatch, powerup):
    from router import main
    cancelled = asyncio.Event()
    async def slow(*args):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
    monkeypatch.setattr(main, "_query_impl", slow)
    monkeypatch.setattr(settings, "request_timeout_seconds", 0.03)
    start = time.monotonic()
    with pytest.raises(HTTPException) as error:
        await main.query(None, QueryRequest(content="x", powerup=powerup, powerup_confirmed=True))
    assert error.value.status_code == 504
    assert time.monotonic() - start < 0.5
    await asyncio.wait_for(cancelled.wait(), 0.5)
    await asyncio.sleep(0)
    assert not main._active_query_tasks


async def test_query_capacity_does_not_start_more_work(monkeypatch):
    from router import main
    started = asyncio.Event()
    async def slow(*args):
        started.set()
        await asyncio.sleep(30)
    impl = AsyncMock(side_effect=slow)
    monkeypatch.setattr(main, "_query_impl", impl)
    monkeypatch.setattr(settings, "max_concurrent_queries", 1)
    first = asyncio.create_task(main.query(None, QueryRequest(content="x")))
    await started.wait()
    try:
        with pytest.raises(HTTPException) as error:
            await main.query(None, QueryRequest(content="y"))
        assert error.value.status_code == 503
        assert impl.call_count == 1
    finally:
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        await asyncio.sleep(0)


async def test_actual_handler_cancels_pipeline_and_cleans_request(monkeypatch):
    from starlette.requests import Request
    from router import main
    cancelled = asyncio.Event()
    async def slow(*args, **kwargs):
        try:
            await asyncio.sleep(30)
        finally:
            cancelled.set()
    async def receive():
        return {"type": "http.request", "body": b'{}', "more_body": False}
    monkeypatch.setattr("router.tiers.execute_pipeline", slow)
    monkeypatch.setattr(settings, "dev_mode", True)
    monkeypatch.setattr(settings, "request_timeout_seconds", 0.03)
    with pytest.raises(HTTPException) as error:
        await main.query(Request({"type": "http"}, receive), QueryRequest(content="x", request_id="deadline-test"))
    assert error.value.status_code == 504
    await asyncio.wait_for(cancelled.wait(), 0.5)
    await asyncio.sleep(0)
    assert "deadline-test" not in main._cancel_events


async def test_cloud_media_and_native_backend_respect_privacy(monkeypatch):
    from router import image_api, main, meshy
    from router.backends.anthropic import AnthropicBackend
    monkeypatch.setattr(settings, "disable_cloud", True)
    for call in (
        image_api._generate_openai("private", "gpt-image-1", "1024x1024"),
        image_api._generate_google("private", "gemini"),
        main._tts_synthesize_bytes({"text": "private", "backend": "openai"}),
        AnthropicBackend("test").generate([{"role": "user", "content": "private"}]),
    ):
        with pytest.raises(RuntimeError, match="Cloud inference disabled"):
            await call
    with pytest.raises(RuntimeError, match="Cloud inference disabled"):
        meshy._headers()
