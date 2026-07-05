import pytest
from httpx import ASGITransport, AsyncClient

from router.config import settings
from router.main import app
from router.world_providers import GenerationRequest, RodinProvider, SanaWmProvider, TripoProvider


def test_tripo_submission_is_redacted_and_configurable(monkeypatch):
    monkeypatch.setattr(settings, "tripo_api_key", "tripokey")
    monkeypatch.setattr(settings, "tripo_base_url", "https://tripo.example.test")

    submission = TripoProvider().build_submission(
        GenerationRequest(
            prompt="ornate upright sword",
            options={"version": "3.1", "texture_quality": "detailed"},
        )
    )

    assert submission.endpoint == "https://tripo.example.test/v1/3d-models/tripo/text-to-3d/3.1/"
    assert submission.json["prompt"] == "ornate upright sword"
    assert submission.json["pbr"] is True
    assert submission.redacted()["headers"]["Authorization"] == "<redacted>"


def test_rodin_submission_uses_hyper3d_contract(monkeypatch):
    monkeypatch.setattr(settings, "rodin_api_key", "rodinkey")
    monkeypatch.setattr(settings, "rodin_base_url", "https://api.hyper3d.test")

    submission = RodinProvider().build_submission(
        GenerationRequest(
            prompt="wooden ballista siege weapon",
            options={"geometry_file_format": "glb", "quality": "high"},
        )
    )

    assert submission.endpoint == "https://api.hyper3d.test/api/v2/rodin"
    assert submission.data["material"] == "PBR"
    assert submission.data["quality"] == "high"
    assert submission.files_required is False


def test_sana_wm_defaults_to_local_custom_contract(monkeypatch):
    monkeypatch.setattr(settings, "sana_wm_base_url", "")
    monkeypatch.setattr(settings, "sana_wm_local_path", "/models/sana-wm")

    submission = SanaWmProvider().build_submission(
        GenerationRequest(
            prompt="snowy city race world",
            kind="world",
            options={"camera_path": "forward", "scene_objects": [{"type": "road"}]},
        )
    )

    assert submission.method == "LOCAL"
    assert submission.endpoint == "/models/sana-wm"
    assert submission.json["decompose_scene"] is True
    assert submission.json["scene_objects"][0]["type"] == "road"


@pytest.mark.asyncio
async def test_world_provider_status_and_dry_run_endpoint(monkeypatch):
    monkeypatch.setattr(settings, "tripo_api_key", "tripokey")
    monkeypatch.setattr(settings, "tripo_base_url", "https://tripo.example.test")

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/world/providers")
        assert status.status_code == 200
        assert "tripo" in status.json()["providers"]

        generated = await client.post(
            "/api/3d/generate",
            json={"provider": "tripo", "prompt": "upright sword", "dry_run": True},
        )
        assert generated.status_code == 200
        data = generated.json()
        assert data["submitted"] is False
        assert data["submission"]["headers"]["Authorization"] == "<redacted>"


@pytest.mark.asyncio
async def test_world_generate_rejects_missing_provider_key(monkeypatch):
    monkeypatch.setattr(settings, "rodin_api_key", None)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        generated = await client.post(
            "/api/world/generate",
            json={"provider": "rodin", "prompt": "desert city", "dry_run": True},
        )

    assert generated.status_code == 412
    assert "RODIN_API_KEY" in generated.json()["detail"]
