"""Tests for /api/image/generate and /api/video/generate (ComfyUI-backed).

The happy-path integration test lives in test_comfyui_api.py. This file
covers error paths and edge-cases that are not exercised there:
  - Empty prompt → 400
  - 'content' accepted as alias for 'prompt'
  - Width/height clamped to 256-2048
  - Frames clamped to 1-32
  - ComfyUI upstream returns 5xx → propagated error
  - ComfyUI unreachable → /api/comfyui/status returns running:False (graceful degrade)
"""

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from router.config import settings
from router.main import app


class _SuccessTransport(httpx.AsyncBaseTransport):
    """Minimal ComfyUI mock that always succeeds."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/system_stats":
            return httpx.Response(200, json={"devices": [{"name": "Mock GPU", "vram_total": 8_000_000_000}]})
        if request.url.path == "/object_info/CheckpointLoaderSimple":
            return httpx.Response(
                200,
                json={
                    "CheckpointLoaderSimple": {
                        "input": {"required": {"ckpt_name": [["sd_xl_base_1.0.safetensors"]]}}
                    }
                },
            )
        if request.url.path == "/object_info/UnetLoaderGGUF":
            return httpx.Response(200, json={"UnetLoaderGGUF": {"input": {"required": {"unet_name": [[]]}}}})
        if request.url.path == "/prompt":
            return httpx.Response(200, json={"prompt_id": "img-vid-ok"})
        return httpx.Response(404, text="not found")


class _ErrorTransport(httpx.AsyncBaseTransport):
    """ComfyUI mock that returns 5xx for /prompt."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.url.path == "/prompt":
            return httpx.Response(503, text="ComfyUI overloaded")
        return httpx.Response(404, text="not found")


class _UnreachableTransport(httpx.AsyncBaseTransport):
    """ComfyUI mock that always raises a connection error."""

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")


@pytest.fixture
def comfy_ok(monkeypatch):
    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _SuccessTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("router.comfyui_api.httpx.AsyncClient", MockClient)
    monkeypatch.setattr(settings, "comfyui_base_url", "http://127.0.0.1:8189")


@pytest.fixture
def comfy_error(monkeypatch):
    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _ErrorTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("router.comfyui_api.httpx.AsyncClient", MockClient)
    monkeypatch.setattr(settings, "comfyui_base_url", "http://127.0.0.1:8189")


@pytest.fixture
def comfy_unreachable(monkeypatch):
    class MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _UnreachableTransport()
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("router.comfyui_api.httpx.AsyncClient", MockClient)
    monkeypatch.setattr(settings, "comfyui_base_url", "http://127.0.0.1:8189")


# ── /api/image/generate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_generate_empty_prompt_returns_400(comfy_ok):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/image/generate", json={"prompt": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_image_generate_accepts_content_alias(comfy_ok):
    """'content' field is accepted as an alias for 'prompt'."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/image/generate", json={"content": "a glowing crystal sword"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "comfyui"
    assert data["job_id"] == "img-vid-ok"


@pytest.mark.asyncio
async def test_image_generate_response_shape(comfy_ok):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/image/generate", json={"prompt": "upright sword", "seed": 7})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "comfyui"
    assert data["status"] == "queued"
    assert "poll_url" in data
    assert data["poll_url"].startswith("/api/image/")


@pytest.mark.asyncio
async def test_image_generate_width_height_clamped(comfy_ok):
    """Extreme width/height values should be clamped, not rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # Request absurd dimensions — endpoint should clamp, not 4xx
        resp = await client.post(
            "/api/image/generate",
            json={"prompt": "tiny sword", "width": 99999, "height": 1},
        )
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_image_generate_comfyui_5xx_propagates(comfy_error):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/image/generate", json={"prompt": "a sword", "seed": 1})
    assert resp.status_code == 503


# ── /api/video/generate ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_video_generate_empty_prompt_returns_400(comfy_ok):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/video/generate", json={"prompt": ""})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_video_generate_accepts_content_alias(comfy_ok):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/video/generate", json={"content": "rotating sword"})
    assert resp.status_code == 200
    assert resp.json()["provider"] == "comfyui"


@pytest.mark.asyncio
async def test_video_generate_response_shape(comfy_ok):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/video/generate", json={"prompt": "rotating sword", "seed": 2, "frames": 8})
    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "comfyui"
    assert data["status"] == "queued"
    assert "poll_url" in data


@pytest.mark.asyncio
async def test_video_generate_frames_clamped(comfy_ok):
    """frames > 32 should be clamped to 32, not rejected."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/video/generate", json={"prompt": "explosion", "frames": 9999})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_video_generate_comfyui_5xx_propagates(comfy_error):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/video/generate", json={"prompt": "a battle", "seed": 3})
    assert resp.status_code == 503


# ── /api/comfyui/status graceful degrade ─────────────────────────────────────


@pytest.mark.asyncio
async def test_comfyui_status_graceful_degrade_when_unreachable(comfy_unreachable):
    """When ComfyUI is unreachable the status endpoint returns running:False without raising."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/comfyui/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["running"] is False
    assert "install_hint" in data
