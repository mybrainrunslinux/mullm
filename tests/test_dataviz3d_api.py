import json
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from router.dataviz3d_api import infer_schema, parse_rows, scene_payload
from router.main import app


def test_dataviz3d_schema_and_scene_from_csv():
    rows = parse_rows("csv", "name,x,y,z,value\nalpha,1,2,3,9\nbeta,2,5,8,4\n")
    schema = infer_schema(rows)
    scene = scene_payload(rows, "point_cloud")

    assert schema["rows"] == 2
    assert "value" in schema["numeric"]
    assert scene["style"] == "point_cloud"
    assert len(scene["points"]) == 2
    assert scene["mappings"]["x"] in schema["columns"]


def test_dataviz3d_geojson_defaults_to_globe_fields():
    geojson = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [19.04, 47.49]}, "properties": {"place": "Budapest", "mag": 2.1}},
        ],
    }
    rows = parse_rows("geojson", json.dumps(geojson))
    scene = scene_payload(rows, "globe_points")

    assert scene["mappings"]["x"] == "longitude"
    assert scene["mappings"]["y"] == "latitude"
    assert scene["points"][0]["label"] == "Budapest"


@pytest.mark.asyncio
async def test_dataviz3d_routes_preview_export_and_page():
    payload = {
        "source_type": "json",
        "style": "bars_3d",
        "title": "Routing Spend",
        "content": json.dumps([{"tier": "local", "queries": 10, "cost": 0}, {"tier": "cloud", "queries": 2, "cost": 0.3}]),
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        styles = await client.get("/api/dataviz3d/styles")
        preview = await client.post("/api/dataviz3d/preview", json=payload)
        export = await client.post("/api/dataviz3d/export", json=payload)

    assert styles.status_code == 200
    assert preview.status_code == 200
    assert preview.json()["style"] == "bars_3d"
    assert export.status_code == 200
    assert "<!doctype html>" in export.json()["html"]
    page = Path(__file__).resolve().parents[1] / "router" / "dataviz3d.html"
    assert "Data 3D" in page.read_text(encoding="utf-8")
