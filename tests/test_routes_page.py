import pytest

from router.main import routes_inventory_api, routes_page, serve_page


@pytest.mark.asyncio
async def test_urls_page_lists_pages_and_api_routes():
    text = await routes_page()

    assert "A live route inventory for parity testing" in text
    assert "/chat" in text
    assert "/query" in text
    assert "/api/routes" in text
    assert "available" in text
    assert "registered" in text


@pytest.mark.asyncio
async def test_routes_inventory_api():
    data = await routes_inventory_api()

    paths = {item["path"] for item in data["pages"] + data["api"]}
    assert "/urls" in paths
    assert "/query" in paths
    assert data["total"] >= len(paths)


@pytest.mark.asyncio
async def test_packaged_studio_page_loads_with_provider_gating(monkeypatch):
    from fastapi.responses import FileResponse

    from router import page_registry

    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "enable_studio", False)

    response = await serve_page("comfyui")
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("comfyui.html")


@pytest.mark.asyncio
async def test_scene_route_aliases_legacy_studio_page(monkeypatch):
    from fastapi.responses import FileResponse

    from router import page_registry

    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)

    response = await serve_page("scene")
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("studio.html")


def test_setup_page_surfaces_comfyui_model_inventory():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "router" / "setup.html").read_text(encoding="utf-8")

    assert 'id="comfyui-models"' in html
    assert "function renderComfyModels(data)" in html
    assert "fetch(API + '/api/comfyui/models')" in html
    assert "LoRAs" in html


def test_setup_page_uses_desktop_width_content_column():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "router" / "setup.html").read_text(encoding="utf-8")

    assert "--setup-content-max:1120px" in html
    assert "@media(min-width:1440px){:root{--setup-content-max:1240px}}" in html
    assert ".card{background:var(--bg2);border:1px solid var(--border);border-radius:12px;padding:24px;width:100%;max-width:var(--setup-content-max)" in html
    assert ".mode-tabs{display:grid;grid-template-columns:1fr 1fr;gap:10px;width:100%;max-width:var(--setup-content-max)" in html


def test_chat_upload_limits_are_enforced_before_submit():
    from pathlib import Path

    html = (Path(__file__).resolve().parents[1] / "router" / "chat.html").read_text(encoding="utf-8")

    assert "const MAX_FILES = 10;" in html
    assert "const MAX_TOTAL_SIZE = 500 * 1024 * 1024;" in html
    assert "const MAX_FILE_SIZE = 50 * 1024 * 1024;" in html
    assert "function attachSelectedFiles(files)" in html
    assert "attachSelectedFiles(fileInput.files);" in html
    assert "attachSelectedFiles(e.dataTransfer.files);" in html
    assert "File Handling (20 files" not in html
