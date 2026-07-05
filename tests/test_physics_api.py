from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from router.main import app


def _physics_payload(tier: str) -> dict:
    return {
        "tier": tier,
        "duration_seconds": 0.25,
        "fps": 12,
        "objects": [
            {
                "id": "ball",
                "mass": 1.0,
                "shape": "sphere",
                "radius": 0.5,
                "pos": [0.0, 2.0, 0.0],
                "vel": [0.2, 0.0, 0.0],
                "material": "reactive metal",
            }
        ],
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("tier", ["soft_body", "fluid", "gas", "mixed", "chemical"])
async def test_advanced_physics_tiers_run_from_clean_install(tier):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post("/api/physics/simulate", json=_physics_payload(tier))

    assert response.status_code == 200
    data = response.json()
    assert data["tier"] == tier
    assert data["frames_emitted"] > 0
    assert data["frames"][0]["objects"][0]["id"] == "ball"
    assert any("built-in deterministic gameplay approximation" in warning for warning in data["warnings"])


@pytest.mark.asyncio
async def test_physics_presets_do_not_advertise_unavailable_tiers():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.get("/api/physics/presets")

    assert response.status_code == 200
    tiers = {tier["id"]: tier for tier in response.json()["tiers"]}
    for tier in ["soft_body", "fluid", "gas", "mixed", "chemical"]:
        assert tiers[tier]["implemented"] is True
        assert "approximation" in tiers[tier]["description"].lower()


def test_physics_page_exposes_advanced_tiers_as_approximations():
    html = (Path(__file__).resolve().parents[1] / "router" / "physics.html").read_text(encoding="utf-8")

    assert "showStubNotice" not in html
    assert "badge:'approx'" in html
    assert "Built-in deterministic gameplay approximation" in html
