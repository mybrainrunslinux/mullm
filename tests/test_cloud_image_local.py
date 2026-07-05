import pytest

from router import cloud


class _Response:
    status_code = 200


class _Client:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return _Response()


@pytest.mark.asyncio
async def test_generate_image_local_uses_comfyui_workflow(monkeypatch):
    async def fake_generate_comfyui(prompt, negative, seed, width, height):
        return {
            "job_id": "img-local-ok",
            "status": "queued",
            "provider": "comfyui",
            "poll_url": "/api/image/img-local-ok",
        }

    monkeypatch.setattr(cloud.httpx, "AsyncClient", _Client)
    monkeypatch.setattr("router.image_api._generate_comfyui", fake_generate_comfyui)

    result = await cloud.generate_image_local("a crystal sword")

    assert result["provider"] == "comfyui"
    assert result["status"] == "queued"
    assert result["poll_url"] == "/api/image/img-local-ok"
