import os

import pytest
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_comfyui_config_save_persists_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("COMFYUI_BASE_URL", raising=False)

    from router.comfyui_api import comfyui_config_save

    result = await comfyui_config_save({"base_url": "http://127.0.0.1:8199/"})

    assert result == {"saved": True, "base_url": "http://127.0.0.1:8199"}
    assert os.environ["COMFYUI_BASE_URL"] == "http://127.0.0.1:8199"
    assert 'comfyui_base_url = "http://127.0.0.1:8199"' in (tmp_path / "mullm.toml").read_text()


@pytest.mark.asyncio
async def test_comfyui_config_rejects_non_http_url(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from router.comfyui_api import comfyui_config_save

    with pytest.raises(HTTPException):
        await comfyui_config_save({"base_url": "file:///tmp/socket"})
