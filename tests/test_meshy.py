"""Tests for router.meshy — Meshy 3D generation adapter.

All tests mock the Meshy HTTP API; no real network calls are made.
"""

from __future__ import annotations

import httpx
import pytest

import router.meshy as meshy

# ── helpers ──────────────────────────────────────────────────────────────────


def _make_mock_client(status_code: int, body: dict) -> type:
    """Return a mock httpx.AsyncClient class that always returns the given response."""

    class _Transport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code, json=body)

    class _MockClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = _Transport()
            super().__init__(*args, **kwargs)

    return _MockClient


# ── text_to_3d ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_text_to_3d_dry_run_does_not_call_api():
    result = await meshy.text_to_3d(prompt="upright bronze sword", dry_run=True)
    assert result["provider"] == "meshy"
    assert result["submitted"] is False
    assert "endpoint" in result
    assert result["json"]["prompt"] == "upright bronze sword"
    assert result["json"]["ai_model"] == "latest"


@pytest.mark.asyncio
async def test_text_to_3d_lowpoly_uses_meshy_server_side_mode():
    result = await meshy.text_to_3d(prompt="game-ready bronze sword", dry_run=True, model_type="lowpoly")

    assert result["json"]["model_type"] == "lowpoly"
    assert result["json"]["ai_model"] == "latest"
    assert "target_polycount" not in result["json"]


@pytest.mark.asyncio
async def test_text_to_3d_remesh_payload_can_target_polycount():
    result = await meshy.text_to_3d(
        prompt="upright siege sword",
        dry_run=True,
        should_remesh=True,
        topology="triangle",
        target_polycount=12_000,
    )

    assert result["json"]["should_remesh"] is True
    assert result["json"]["topology"] == "triangle"
    assert result["json"]["target_polycount"] == 12_000


@pytest.mark.asyncio
async def test_text_to_3d_empty_prompt_raises():
    with pytest.raises(meshy.MeshyError, match="prompt is required"):
        await meshy.text_to_3d(prompt="", dry_run=False)


@pytest.mark.asyncio
async def test_text_to_3d_success(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(202, {"result": "task-abc123"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.text_to_3d(prompt="a golden shield", style="realistic")

    assert result["provider"] == "meshy"
    assert result["task_id"] == "task-abc123"
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_text_to_3d_non_2xx_returns_error_dict(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(422, {"detail": "bad prompt"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.text_to_3d(prompt="bad input")

    assert "error" in result
    assert "422" in result["error"]


@pytest.mark.asyncio
async def test_text_to_3d_no_key_returns_error_dict():
    monkeypatch_key = ""
    import unittest.mock as mock

    with mock.patch.object(meshy, "_MESHY_KEY", monkeypatch_key):
        result = await meshy.text_to_3d(prompt="dragon", dry_run=False)

    assert "error" in result
    assert "MESHY_API_KEY" in result["error"]


# ── image_to_3d ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_image_to_3d_dry_run_with_url():
    result = await meshy.image_to_3d(image_url="https://example.test/sword.png", dry_run=True)
    assert result["provider"] == "meshy"
    assert result["submitted"] is False
    assert result["json"]["image_url"] == "https://example.test/sword.png"
    assert result["json"]["enable_pbr"] is True
    assert result["json"]["ai_model"] == "latest"
    assert result["json"]["should_texture"] is True


@pytest.mark.asyncio
async def test_image_to_3d_empty_inputs_raises():
    with pytest.raises(meshy.MeshyError, match="image_url or image_path is required"):
        await meshy.image_to_3d(image_url="", image_path="", dry_run=False)


@pytest.mark.asyncio
async def test_image_to_3d_data_uri_redacted_in_dry_run(tmp_path, monkeypatch):
    """When image_path is supplied the dry-run output redacts the data URI."""
    from router.config import settings

    monkeypatch.setattr(settings, "cache_dir", str(tmp_path))
    img = tmp_path / "sword.png"
    img.write_bytes(b"\x89PNG fake image data")

    result = await meshy.image_to_3d(image_path=str(img), dry_run=True)

    assert result["submitted"] is False
    assert result["json"]["image_url"] == "<data-uri>"


@pytest.mark.asyncio
async def test_image_to_3d_path_outside_allowed_roots_raises(tmp_path, monkeypatch):
    """Paths outside the allowed roots must raise MeshyError."""
    from router.config import settings

    # Point cache_dir somewhere else entirely
    monkeypatch.setattr(settings, "cache_dir", str(tmp_path / "cache"))
    evil_dir = tmp_path / "evil"
    evil_dir.mkdir()
    evil_img = evil_dir / "evil.png"
    evil_img.write_bytes(b"\x89PNG")

    with pytest.raises(meshy.MeshyError, match="image_path must be under"):
        await meshy.image_to_3d(image_path=str(evil_img), dry_run=True)


@pytest.mark.asyncio
async def test_image_to_3d_success(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(200, {"result": "img-task-789"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.image_to_3d(image_url="https://example.test/shield.png")

    assert result["provider"] == "meshy"
    assert result["task_id"] == "img-task-789"
    assert result["status"] == "queued"


@pytest.mark.asyncio
async def test_refine_task_dry_run_supports_pbr_and_texture_prompt():
    result = await meshy.refine_task("preview-123", dry_run=True, texture_prompt="brushed steel and leather grip")

    assert result["json"]["mode"] == "refine"
    assert result["json"]["preview_task_id"] == "preview-123"
    assert result["json"]["enable_pbr"] is True
    assert result["json"]["texture_prompt"] == "brushed steel and leather grip"


@pytest.mark.asyncio
async def test_image_to_3d_non_2xx_raises_meshy_error(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(503, {"detail": "service down"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    with pytest.raises(meshy.MeshyError, match="503"):
        await meshy.image_to_3d(image_url="https://example.test/sword.png")


# ── poll_task ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_poll_task_dry_run():
    result = await meshy.poll_task("task-preview-99", endpoint="text-to-3d", dry_run=True)
    assert result["submitted"] is False
    assert "task-preview-99" in result["endpoint"]
    # text-to-3d uses v2
    assert "/v2/" in result["endpoint"]


@pytest.mark.asyncio
async def test_poll_task_image_endpoint_uses_v1(monkeypatch):
    result = await meshy.poll_task("img-task-42", endpoint="image-to-3d", dry_run=True)
    assert "/v1/" in result["endpoint"]


@pytest.mark.asyncio
async def test_poll_task_empty_task_id_raises():
    with pytest.raises(meshy.MeshyError, match="task_id is required"):
        await meshy.poll_task("", dry_run=False)


@pytest.mark.asyncio
async def test_poll_task_succeeded(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(
        200,
        {
            "status": "SUCCEEDED",
            "model_urls": {"glb": "https://cdn.meshy.ai/model.glb"},
            "thumbnail_url": "https://cdn.meshy.ai/thumb.png",
            "texture_urls": {},
        },
    )
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.poll_task("task-done-123")

    assert result["provider"] == "meshy"
    assert result["status"] == "complete"
    assert result["model_urls"]["glb"] == "https://cdn.meshy.ai/model.glb"


@pytest.mark.asyncio
async def test_poll_task_failed(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(200, {"status": "FAILED", "error": "generation failed"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.poll_task("task-fail-456")

    assert result["provider"] == "meshy"
    assert "error" in result


@pytest.mark.asyncio
async def test_poll_task_in_progress(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(200, {"status": "IN_PROGRESS", "progress": 42})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.poll_task("task-wip-789")

    assert result["status"] == "in_progress"


@pytest.mark.asyncio
async def test_poll_task_http_error_raises(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(404, {"detail": "not found"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    with pytest.raises(meshy.MeshyError, match="404"):
        await meshy.poll_task("task-missing")


@pytest.mark.asyncio
async def test_poll_task_no_key_returns_error_dict():
    import unittest.mock as mock

    with mock.patch.object(meshy, "_MESHY_KEY", ""):
        result = await meshy.poll_task("task-abc", dry_run=False)

    assert "error" in result


# ── refine_task ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_refine_task_dry_run():
    result = await meshy.refine_task("preview-task-001", dry_run=True)
    assert result["submitted"] is False
    assert result["json"]["preview_task_id"] == "preview-task-001"
    assert result["json"]["mode"] == "refine"


@pytest.mark.asyncio
async def test_refine_task_empty_id_raises():
    with pytest.raises(meshy.MeshyError, match="preview_task_id is required"):
        await meshy.refine_task("", dry_run=False)


@pytest.mark.asyncio
async def test_refine_task_success(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-test-key")
    MockClient = _make_mock_client(202, {"result": "refine-task-xyz"})
    monkeypatch.setattr(meshy.httpx, "AsyncClient", MockClient)

    result = await meshy.refine_task("preview-task-abc")

    assert result["provider"] == "meshy"
    assert result["step"] == "refine"
    assert result["task_id"] == "refine-task-xyz"


# ── status() helper ──────────────────────────────────────────────────────────


def test_status_returns_correct_shape():
    s = meshy.status()
    assert s["provider"] == "meshy"
    assert "capabilities" in s
    assert "text_to_3d" in s["capabilities"]
    assert "image_to_3d" in s["capabilities"]


def test_configured_false_when_no_key(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "")
    assert meshy.configured() is False


def test_configured_true_when_key_set(monkeypatch):
    monkeypatch.setattr(meshy, "_MESHY_KEY", "sk-real-key")
    assert meshy.configured() is True
