from __future__ import annotations

import io
import json
import zipfile

import pytest
from httpx import ASGITransport, AsyncClient

from router.main import app


@pytest.mark.asyncio
async def test_composition_exports_interoperable_bundle():
    payload = {
        "title": "Flagon Call",
        "bpm": 96,
        "notes": [
            {"pitch": "D4", "beats": 1, "velocity": 90},
            {"pitch": "F#4", "beats": 0.5, "velocity": 84},
            {"pitch": "A4", "beats": 0.5, "velocity": 96},
            {"pitch": "D5", "beats": 2, "velocity": 102},
        ],
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        status = await client.get("/api/composition/status")
        rendered = await client.post("/api/composition/render", json=payload)

    assert status.status_code == 200
    assert status.json()["instruments"] == ["hammered_dulcimer_18"]
    assert rendered.status_code == 200
    assert rendered.headers["content-type"].startswith("application/zip")
    with zipfile.ZipFile(io.BytesIO(rendered.content)) as archive:
        assert set(archive.namelist()) == {
            "score.musicxml", "performance.mid", "dulcimer-courses.json", "preview.wav", "request.json"
        }
        assert archive.read("performance.mid").startswith(b"MThd")
        assert archive.read("preview.wav").startswith(b"RIFF")
        strikes = json.loads(archive.read("dulcimer-courses.json"))["strikes"]
        assert [strike["course"] for strike in strikes] == [4, 10, 12, 15]
        assert [strike["hand"] for strike in strikes] == ["R", "L", "R", "L"]


@pytest.mark.asyncio
async def test_composition_rejects_note_outside_instrument():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/composition/render",
            json={"title": "Too Low", "notes": [{"pitch": "C3", "beats": 1}]},
        )
    assert response.status_code == 422
    assert "outside hammered_dulcimer_18 range" in response.json()["detail"]
