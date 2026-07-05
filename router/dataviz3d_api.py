"""Local-first 3D data visualization helpers."""

from __future__ import annotations

import csv
import html
import io
import json
import math
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/dataviz3d", tags=["dataviz3d"])

MAX_ROWS = 10_000
MAX_TEXT_BYTES = 2_000_000

VIZ_STYLES = [
    "point_cloud",
    "bars_3d",
    "globe_points",
    "lines_3d",
    "network",
    "heat_columns",
    "surface_grid",
    "timeline_arc",
]


class DataVizRequest(BaseModel):
    source_type: str = Field("json", pattern="^(csv|json|geojson)$")
    content: str = Field(..., min_length=1, max_length=MAX_TEXT_BYTES)
    style: str = Field("point_cloud")
    title: str = Field("muLLM 3D Data Visualization", max_length=120)
    mappings: dict[str, str] = Field(default_factory=dict)


def _to_float(value: Any, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_csv(content: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(io.StringIO(content))
    rows = [dict(row) for _, row in zip(range(MAX_ROWS), reader)]
    if not rows:
        raise HTTPException(status_code=400, detail="CSV must include a header and at least one row")
    return rows


def _parse_json(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc.msg}") from exc
    if isinstance(data, dict):
        for key in ("features", "data", "rows", "items", "results"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="JSON must be an array or an object containing a rows/data/items/features array")
    rows: list[dict[str, Any]] = []
    for item in data[:MAX_ROWS]:
        rows.append(item if isinstance(item, dict) else {"value": item})
    if not rows:
        raise HTTPException(status_code=400, detail="JSON array is empty")
    return rows


def _parse_geojson(content: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(content)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid GeoJSON: {exc.msg}") from exc
    features = data.get("features") if isinstance(data, dict) else None
    if not isinstance(features, list):
        raise HTTPException(status_code=400, detail="GeoJSON must be a FeatureCollection")
    rows: list[dict[str, Any]] = []
    for feature in features[:MAX_ROWS]:
        props = feature.get("properties", {}) if isinstance(feature, dict) else {}
        geom = feature.get("geometry", {}) if isinstance(feature, dict) else {}
        coords = geom.get("coordinates", []) if isinstance(geom, dict) else []
        lon = coords[0] if isinstance(coords, list) and len(coords) >= 2 else 0
        lat = coords[1] if isinstance(coords, list) and len(coords) >= 2 else 0
        row = dict(props) if isinstance(props, dict) else {}
        row.update({"longitude": lon, "latitude": lat})
        rows.append(row)
    if not rows:
        raise HTTPException(status_code=400, detail="GeoJSON contains no point features")
    return rows


def parse_rows(source_type: str, content: str) -> list[dict[str, Any]]:
    if len(content.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(status_code=413, detail="Dataset too large for local preview")
    if source_type == "csv":
        return _parse_csv(content)
    if source_type == "geojson":
        return _parse_geojson(content)
    return _parse_json(content)


def infer_schema(rows: list[dict[str, Any]]) -> dict[str, Any]:
    columns = sorted({key for row in rows for key in row.keys()})
    numeric: list[str] = []
    categorical: list[str] = []
    for column in columns:
        values = [row.get(column) for row in rows[:200] if row.get(column) not in (None, "")]
        if values and sum(isinstance(v, int | float) or str(v).replace(".", "", 1).replace("-", "", 1).isdigit() for v in values) / len(values) >= 0.7:
            numeric.append(column)
        else:
            categorical.append(column)
    return {"rows": len(rows), "columns": columns, "numeric": numeric, "categorical": categorical}


def default_mappings(schema: dict[str, Any]) -> dict[str, str]:
    numeric = list(schema["numeric"])
    columns = list(schema["columns"])
    return {
        "x": "longitude" if "longitude" in columns else (numeric[0] if numeric else columns[0]),
        "y": "latitude" if "latitude" in columns else (numeric[1] if len(numeric) > 1 else (numeric[0] if numeric else columns[0])),
        "z": numeric[2] if len(numeric) > 2 else (numeric[0] if numeric else columns[0]),
        "size": "mag" if "mag" in columns else (numeric[0] if numeric else columns[0]),
        "label": "place" if "place" in columns else columns[0],
    }


def _normalize(values: list[float], span: float = 10.0) -> list[float]:
    low = min(values) if values else 0.0
    high = max(values) if values else 1.0
    if math.isclose(low, high):
        return [0.0 for _ in values]
    return [((value - low) / (high - low) - 0.5) * span for value in values]


def scene_payload(rows: list[dict[str, Any]], style: str, mappings: dict[str, str] | None = None) -> dict[str, Any]:
    if style not in VIZ_STYLES:
        raise HTTPException(status_code=400, detail=f"Unknown style: {style}")
    schema = infer_schema(rows)
    mapped = default_mappings(schema)
    mapped.update({k: v for k, v in (mappings or {}).items() if v})
    x_values = [_to_float(row.get(mapped["x"])) for row in rows]
    y_values = [_to_float(row.get(mapped["y"])) for row in rows]
    z_values = [_to_float(row.get(mapped["z"])) for row in rows]
    sizes = [_to_float(row.get(mapped["size"]), 1.0) for row in rows]
    xs = _normalize(x_values)
    ys = _normalize(y_values)
    zs = _normalize(z_values)
    max_size = max(sizes) if sizes else 1.0
    points = []
    for index, row in enumerate(rows):
        points.append(
            {
                "x": xs[index],
                "y": ys[index],
                "z": zs[index],
                "lat": _to_float(row.get("latitude")),
                "lon": _to_float(row.get("longitude")),
                "size": 0.08 + 0.42 * (sizes[index] / max_size if max_size else 0.0),
                "label": str(row.get(mapped["label"], f"Row {index + 1}"))[:120],
                "raw": {key: row.get(key) for key in list(row.keys())[:12]},
            }
        )
    return {"style": style, "schema": schema, "mappings": mapped, "points": points}


@router.get("/styles")
async def styles() -> dict[str, Any]:
    return {
        "styles": [
            {"id": "point_cloud", "name": "3D Point Cloud", "best_for": "Embeddings, coordinates, model metrics"},
            {"id": "bars_3d", "name": "3D Bars", "best_for": "Grouped numeric comparisons"},
            {"id": "globe_points", "name": "Globe Points", "best_for": "Latitude/longitude feeds such as earthquakes"},
            {"id": "lines_3d", "name": "3D Lines", "best_for": "Time series, trajectories, DAGs"},
            {"id": "network", "name": "Network", "best_for": "Entity relationships and dependency graphs"},
            {"id": "heat_columns", "name": "Heat Columns", "best_for": "Geospatial density or risk"},
            {"id": "surface_grid", "name": "Surface Grid", "best_for": "Scientific mesh/grid data"},
            {"id": "timeline_arc", "name": "Timeline Arc", "best_for": "Events over time with magnitude"},
        ],
        "local_only": True,
        "max_rows": MAX_ROWS,
    }


@router.get("/samples")
async def samples() -> dict[str, Any]:
    rows = [
        {"place": "Tokyo", "latitude": 35.6762, "longitude": 139.6503, "value": 92, "risk": 0.25},
        {"place": "Budapest", "latitude": 47.4979, "longitude": 19.0402, "value": 54, "risk": 0.12},
        {"place": "San Francisco", "latitude": 37.7749, "longitude": -122.4194, "value": 71, "risk": 0.41},
        {"place": "Santiago", "latitude": -33.4489, "longitude": -70.6693, "value": 63, "risk": 0.32},
    ]
    return {
        "samples": {
            "cities_json": {"source_type": "json", "content": json.dumps(rows, indent=2), "style": "globe_points"},
            "metrics_csv": {
                "source_type": "csv",
                "content": "service,latency_ms,cost_usd,queries\nlocal,42,0,830\ncloud_cheap,880,1.42,126\ncloud_full,1800,7.9,21\n",
                "style": "bars_3d",
            },
        }
    }


@router.post("/preview")
async def preview(req: DataVizRequest) -> dict[str, Any]:
    rows = parse_rows(req.source_type, req.content)
    return scene_payload(rows, req.style, req.mappings)


@router.post("/export")
async def export(req: DataVizRequest) -> dict[str, str]:
    rows = parse_rows(req.source_type, req.content)
    payload = scene_payload(rows, req.style, req.mappings)
    title = html.escape(req.title)
    data_json = json.dumps(payload).replace("</", "<\\/")
    doc = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title><style>html,body{{margin:0;height:100%;background:#061018;color:#dce7ef;font-family:Inter,system-ui,sans-serif}}#app{{height:100%}}.hud{{position:fixed;left:16px;top:16px;background:rgba(3,8,14,.76);border:1px solid #234;padding:12px;max-width:360px;border-radius:8px}}button{{background:#14b8a6;color:#001;border:0;border-radius:6px;padding:7px 10px}}</style></head>
<body><div id="app"></div><div class="hud"><strong>{title}</strong><p>This exported visualization is local-first: the dataset is embedded in this HTML file.</p><button onclick="window.__spin=!window.__spin">Pause / spin</button></div>
<script type="module">
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.160.0/build/three.module.js';
const data = {data_json}; window.__spin = true;
const app=document.getElementById('app'), scene=new THREE.Scene(), camera=new THREE.PerspectiveCamera(55,innerWidth/innerHeight,.1,1000), renderer=new THREE.WebGLRenderer({{antialias:true}});
renderer.setSize(innerWidth,innerHeight); renderer.setPixelRatio(Math.min(devicePixelRatio,2)); app.appendChild(renderer.domElement);
scene.add(new THREE.AmbientLight(0xffffff,.75)); const light=new THREE.DirectionalLight(0xffffff,1.2); light.position.set(5,8,4); scene.add(light); camera.position.set(9,7,12); camera.lookAt(0,0,0);
const root=new THREE.Group(); scene.add(root); root.add(new THREE.GridHelper(16,16,0x28445c,0x162736));
const mat = new THREE.MeshStandardMaterial({{color:0x22d3ee,roughness:.45,metalness:.2}});
for (const p of data.points) {{ const geo=data.style==='bars_3d'?new THREE.BoxGeometry(.25,Math.max(.08,p.size*8),.25):new THREE.SphereGeometry(Math.max(.04,p.size),16,10); const mesh=new THREE.Mesh(geo,mat.clone()); mesh.position.set(p.x, data.style==='bars_3d'?p.size*4:p.y, p.z); mesh.userData=p; root.add(mesh); }}
addEventListener('resize',()=>{{camera.aspect=innerWidth/innerHeight;camera.updateProjectionMatrix();renderer.setSize(innerWidth,innerHeight)}});
function tick(){{requestAnimationFrame(tick); if(window.__spin) root.rotation.y += .004; renderer.render(scene,camera)}} tick();
</script></body></html>"""
    return {"filename": "mullm-dataviz3d.html", "html": doc}
