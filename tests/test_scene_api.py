import pytest
from httpx import ASGITransport, AsyncClient

from router.config import settings
from router.main import app
from router.scene_api import classify_asset, parse_scene_action


def test_scene_action_cache_key_is_exact_for_coordinates():
    a = parse_scene_action("move sword to 0 0 0", selected="sword")
    b = parse_scene_action("move sword to 0,1,0", selected="sword")

    assert a["action"] == {"action": "move", "x": 0.0, "y": 0.0, "z": 0.0}
    assert b["action"] == {"action": "move", "x": 0.0, "y": 1.0, "z": 0.0}
    assert a["cache_policy"] == "exact-only"
    assert a["cache_key"] != b["cache_key"]


def test_asset_classification_enables_dojo_and_siege():
    sword = classify_asset("ornate-crystal-sabre", "curved fantasy sword")
    siege = classify_asset("meshy-ballista", "wooden siege weapon")
    catapult = classify_asset("meshy-catapult", "wooden siege weapon")
    explicit = classify_asset("steampunk-artifact", "ornate brass object", {"asset_type": "sword", "tags": ["hero"]})

    assert "weapon" in sword["categories"]
    assert sword["can_try"]["dojo"] is True
    assert "siege" in siege["categories"]
    assert siege["can_try"]["siege"] is True
    assert "creature" not in catapult["categories"]
    assert explicit["category"] == "weapon"
    assert explicit["can_try"]["dojo"] is True
    assert "hero" in explicit["tags"]


@pytest.mark.asyncio
async def test_scene_assets_endpoint_returns_metadata(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    glb = asset_dir / "test-sword.glb"
    glb.write_bytes(b"glTF fake")
    glb.with_suffix(".json").write_text(
        '{"source":"test","prompt":"a test sword pointed up","tags":["hero"]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/3d-assets?category=weapon")

    assert response.status_code == 200
    data = response.json()
    asset = next(item for item in data["assets"] if item["name"] == "test-sword")
    assert data["total"] >= 1
    assert asset["can_try"]["dojo"] is True
    assert data["storage"]["backend"] == settings.asset_storage_backend
    assert "packaged_root" in data["storage"]


@pytest.mark.asyncio
async def test_scene_asset_file_route_respects_custom_root(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    glb = asset_dir / "test-sword.glb"
    glb.write_bytes(b"glTF fake")
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/assets/3d/test-sword.glb")

    assert response.status_code == 200
    assert response.content == b"glTF fake"


@pytest.mark.asyncio
async def test_scene_asset_gzip_compression_creates_variant(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    glb = asset_dir / "test-sword.glb"
    glb.write_bytes(b"glTF fake glTF fake glTF fake")
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/scene/assets/test-sword/compress", json={"method": "gzip"})

    assert response.status_code == 200
    data = response.json()
    assert data["method"] == "gzip"
    assert data["output"] == "test-sword.glb.gz"
    assert (asset_dir / "test-sword.glb.gz").exists()


@pytest.mark.asyncio
async def test_scene_optimize_is_shape_preserving_decimate_alias(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    glb = asset_dir / "test-sword.glb"
    glb.write_bytes(b"glTF fake glTF fake glTF fake " * 20)
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        optimize = await client.post("/api/3d/optimize", json={"name": "test-sword", "method": "auto"})
        legacy = await client.post("/api/3d/decimate", json={"name": "test-sword", "keep_ratio": 0.1})

    assert optimize.status_code == 200
    data = optimize.json()
    assert data["method"] == "gzip"
    assert data["geometry_modified"] is False
    assert data["shape_preserving"] is True
    assert data["output"] == "test-sword.glb.gz"
    assert (asset_dir / "test-sword.glb.gz").exists()

    assert legacy.status_code == 200
    assert legacy.json()["already_exists"] is True
    assert legacy.json()["geometry_modified"] is False


@pytest.mark.asyncio
async def test_scene_storage_endpoint_reports_options(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))
    monkeypatch.setattr(settings, "asset_storage_backend", "s3")
    monkeypatch.setattr(settings, "asset_compression", "meshopt")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/scene/storage")

    assert response.status_code == 200
    data = response.json()
    assert data["backend"] == "s3"
    assert data["compression"] == "meshopt"
    assert "azure_blob" in data["storage_options"]
    assert "draco" in data["compression_options"]


@pytest.mark.asyncio
async def test_setup_assets_endpoint_saves_configured_root(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(settings, "asset_root", str(tmp_path / "old-assets"))

    new_root = tmp_path / "external-drive-assets"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/setup/assets", json={"root": str(new_root)})

    assert response.status_code == 200
    data = response.json()
    assert data["saved"] is True
    assert data["root"] == str(new_root)
    assert (new_root / "3d").exists()
    assert 'root = "' in (tmp_path / "mullm.toml").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_meshy_provider_routes_support_dry_run_without_key():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        providers = await client.get("/api/3d/providers")
        text = await client.post(
            "/api/3d/text",
            json={
                "prompt": "upright bronze sword",
                "dry_run": True,
                "model_type": "lowpoly",
                "target_polycount": 6000,
                "should_remesh": True,
            },
        )
        image = await client.post("/api/3d/image", json={"image_url": "https://example.test/sword.png", "dry_run": True})
        refine = await client.post("/api/3d/refine", json={"preview_task_id": "task-preview", "dry_run": True})
        status = await client.get("/api/3d/status/task-preview?dry_run=true")

    assert providers.status_code == 200
    assert providers.json()["providers"]["meshy"]["provider"] == "meshy"
    assert text.status_code == 200
    assert text.json()["provider"] == "meshy"
    assert text.json()["submitted"] is False
    assert text.json()["json"]["model_type"] == "lowpoly"
    assert image.status_code == 200
    assert image.json()["json"]["image_url"] == "https://example.test/sword.png"
    assert refine.status_code == 200
    assert refine.json()["json"]["preview_task_id"] == "task-preview"
    assert status.status_code == 200
    assert status.json()["endpoint"].endswith("/task-preview")


@pytest.mark.asyncio
async def test_meshy_routes_fail_closed_for_missing_input():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/3d/text", json={"prompt": "", "dry_run": True})

    assert response.status_code == 412


# ── /api/scene/action POST route ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scene_action_route_parses_move_command():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/scene/action", json={"text": "move sword to 1 2 3", "selected": "sword"})

    assert response.status_code == 200
    data = response.json()
    assert data["action"]["action"] == "move"
    assert data["action"]["x"] == 1.0
    assert data["action"]["y"] == 2.0
    assert data["action"]["z"] == 3.0
    assert data["cache_policy"] == "exact-only"


@pytest.mark.asyncio
async def test_scene_action_route_empty_text_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/scene/action", json={"text": "   "})

    assert response.status_code == 400


# ── DELETE /api/3d-assets/{name} ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_delete_3d_asset_removes_glb_and_json(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    glb = asset_dir / "test-sword.glb"
    glb.write_bytes(b"glTF fake")
    meta = asset_dir / "test-sword.json"
    meta.write_text('{"source":"test"}', encoding="utf-8")
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/3d-assets/test-sword")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert not glb.exists()
    assert not meta.exists()


@pytest.mark.asyncio
async def test_delete_3d_asset_missing_returns_ok_false(tmp_path, monkeypatch):
    asset_dir = tmp_path / "3d"
    asset_dir.mkdir()
    monkeypatch.setattr(settings, "asset_root", str(tmp_path))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.delete("/api/3d-assets/nonexistent-asset")

    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is False
    assert data["deleted"] == []


# ── /api/3d/generate (world providers, dry_run) ──────────────────────────────


@pytest.mark.asyncio
async def test_generate_3d_asset_dry_run_returns_submission():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/3d/generate",
            json={
                "prompt": "ancient stone tower",
                "kind": "text_to_3d",
                "provider": "sana_wm",
                "dry_run": True,
            },
        )

    assert response.status_code == 200
    data = response.json()
    # dry_run → not submitted
    assert data["submitted"] is False


@pytest.mark.asyncio
async def test_generate_3d_asset_empty_prompt_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/3d/generate",
            json={"prompt": "", "dry_run": True},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_generate_3d_asset_invalid_kind_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/3d/generate",
            json={"prompt": "something", "kind": "invalid_mode", "dry_run": True},
        )

    assert response.status_code == 400


# ── /api/3d/download error paths ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_download_3d_asset_missing_url_returns_400():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/3d/download", json={"name": "my-sword"})

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_import_comfyui_3d_asset_rejects_invalid_filename():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/3d/import-comfyui",
            json={"filename": "../bad.glb", "name": "bad"},
        )

    assert response.status_code == 400
