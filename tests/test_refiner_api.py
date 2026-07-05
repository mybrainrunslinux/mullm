from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from router.main import app
from router import page_registry


@pytest.mark.asyncio
async def test_refiner_status_and_plan_are_available():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/refiner/status")
        plan = await client.post("/api/refiner/plan", json={"target": "lighting", "quality": "balanced"})

    assert status.status_code == 200
    assert "lighting" in status.json()["targets"]
    assert plan.status_code == 200
    data = plan.json()
    assert data["target"] == "lighting"
    assert any(step["step"] == "reference-lock" for step in data["steps"])


@pytest.mark.asyncio
async def test_lighting_page_is_served_when_studio_enabled(monkeypatch):
    monkeypatch.setattr(page_registry.settings, "ui_mode", "regular")
    monkeypatch.setattr(page_registry.settings, "enable_studio", True)
    page = Path(__file__).resolve().parents[1] / "router" / "lighting.html"

    assert page_registry.page_allowed("lighting") is True
    assert "Lighting Studio" in page.read_text(encoding="utf-8")
