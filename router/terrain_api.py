"""Terrain generation API — real DEM data, GLB export, OSM overlay.

Sources:
  - USGS National Map    free, keyless, 1/3 arc-second (~10m CONUS)
  - OpenTopography       free with API key, global 1m–90m
  - Mapbox Terrain-RGB   512px tiles, global, needs MAPBOX_TOKEN
  - OpenStreetMap/Overpass  free, keyless, buildings/roads/water
  - CesiumIon / Felt     provider adapters (token required)
"""

from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import struct
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import httpx
import numpy as np
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from router.asset_store import get_asset_store

router = APIRouter(prefix="/api/terrain", tags=["terrain"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_HTTPX_TIMEOUT = 30.0


def _km_to_deg(km: float, lat: float = 0.0) -> tuple[float, float]:
    """Convert a km radius to (dlat_deg, dlon_deg) for a BBox expansion."""
    dlat = km / 111.0
    cos_lat = math.cos(math.radians(lat))
    dlon = km / (111.0 * cos_lat) if cos_lat > 1e-6 else km / 111.0
    return dlat, dlon


def _bbox(lat: float, lng: float, radius_km: float) -> tuple[float, float, float, float]:
    """Return (south, west, north, east) bbox for a lat/lng center and km radius."""
    dlat, dlon = _km_to_deg(radius_km, lat)
    return lat - dlat, lng - dlon, lat + dlat, lng + dlon


def _slug(lat: float, lng: float, radius_km: float, preset: str, source: str) -> str:
    raw = f"{lat:.4f}_{lng:.4f}_{radius_km:.1f}_{preset}_{source}"
    return re.sub(r"[^A-Za-z0-9_.-]", "-", raw)[:120]


# ---------------------------------------------------------------------------
# GLB builder (manual, no trimesh dep)
# Spec: https://registry.khronos.org/glTF/specs/2.0/glTF-2.0.html#glb-file-format-specification
# ---------------------------------------------------------------------------

def _pad4(b: bytes) -> bytes:
    rem = len(b) % 4
    return b + b"\x00" * (4 - rem) if rem else b


def _build_glb(
    heights: np.ndarray,
    grid_w: int,
    grid_h: int,
    x_size_m: float,
    z_size_m: float,
    metadata: dict[str, Any] | None = None,
) -> bytes:
    """Build a binary GLB from a 2-D heightmap array using vectorised numpy.

    heights: 2-D float32 array, shape (grid_h, grid_w), values in metres.
    x_size_m / z_size_m: real-world extent in metres.
    """
    gw, gh = grid_w, grid_h
    dx = x_size_m / (gw - 1) if gw > 1 else x_size_m
    dz = z_size_m / (gh - 1) if gh > 1 else z_size_m

    # ---- Vertices (position XYZ, shape [gh*gw, 3]) ----
    col_idx = np.arange(gw, dtype=np.float32)
    row_idx = np.arange(gh, dtype=np.float32)
    col_grid, row_grid = np.meshgrid(col_idx, row_idx)  # (gh, gw)
    x_arr = col_grid * dx - x_size_m / 2.0
    z_arr = row_grid * dz - z_size_m / 2.0
    y_arr = heights.astype(np.float32)
    # Interleave as (gh*gw, 3) in C order → row-major matches vertex index = row*gw+col
    positions = np.stack([x_arr, y_arr, z_arr], axis=-1).reshape(-1, 3).astype(np.float32)
    n_verts = positions.shape[0]
    pos_bytes = positions.tobytes()

    # ---- Indices (two CCW triangles per quad) ----
    # tl=row*gw+col, tr=tl+1, bl=tl+gw, br=bl+1
    rows = np.arange(gh - 1, dtype=np.uint32)
    cols = np.arange(gw - 1, dtype=np.uint32)
    r, c = np.meshgrid(rows, cols, indexing="ij")  # (gh-1, gw-1)
    tl = (r * gw + c).ravel()
    tr = tl + 1
    bl = tl + gw
    br = bl + 1
    # Triangle 1: tl, bl, tr — Triangle 2: tr, bl, br
    tri1 = np.stack([tl, bl, tr], axis=-1)
    tri2 = np.stack([tr, bl, br], axis=-1)
    indices = np.concatenate([tri1, tri2], axis=-1).ravel().astype(np.uint32)
    n_idx = indices.size
    idx_bytes = indices.tobytes()

    # ---- Normals (central-difference, fully vectorised) ----
    h = heights.astype(np.float32)
    # Pad height field by 1 on each edge to enable simple slicing without boundary checks
    h_pad = np.pad(h, 1, mode="edge")
    # Central differences: dh/dc (column direction), dh/dr (row direction)
    dh_dc = (h_pad[1:-1, 2:] - h_pad[1:-1, :-2]) / (2.0 * dx)   # (gh, gw)
    dh_dr = (h_pad[2:, 1:-1] - h_pad[:-2, 1:-1]) / (2.0 * dz)   # (gh, gw)
    # Tangent along +X: (dx, dh_dc*dx, 0) — normalised later
    # Tangent along +Z: (0, dh_dr*dz, dz)
    # Normal = cross(Tz, Tx) → (-dh_dc, 1, -dh_dr) before normalisation
    nx = -dh_dc
    ny = np.ones_like(nx)
    nz = -dh_dr
    norms = np.stack([nx, ny, nz], axis=-1).reshape(-1, 3)  # (n_verts, 3)
    lengths = np.linalg.norm(norms, axis=-1, keepdims=True)
    lengths = np.where(lengths < 1e-9, 1.0, lengths)
    norms = (norms / lengths).astype(np.float32)
    nrm_bytes = norms.tobytes()

    # ---- UV coords ----
    u_arr = col_grid / max(gw - 1, 1)
    v_arr = 1.0 - row_grid / max(gh - 1, 1)
    uvs = np.stack([u_arr, v_arr], axis=-1).reshape(-1, 2).astype(np.float32)
    uv_bytes = uvs.tobytes()

    # ---- Vertex colors (elevation-based, RGBA float32) ----
    # Normalise heights to [0..1]
    h_flat = heights.astype(np.float32).ravel()
    h_min, h_max = h_flat.min(), h_flat.max()
    h_norm = (h_flat - h_min) / max(h_max - h_min, 1.0)

    # Elevation colour ramp: deep=water-blue, low=grass, mid=dirt, high=rock, top=snow
    ramp = np.array([
        [0.15, 0.30, 0.65, 1.0],   # water / very low
        [0.28, 0.52, 0.20, 1.0],   # grass / low
        [0.45, 0.38, 0.22, 1.0],   # dirt / mid-low
        [0.48, 0.44, 0.40, 1.0],   # rock / mid-high
        [0.78, 0.76, 0.74, 1.0],   # grey rock / high
        [0.95, 0.95, 0.97, 1.0],   # snow / peak
    ], dtype=np.float32)
    n_stops = len(ramp)
    t = h_norm * (n_stops - 1)
    lo = np.clip(t.astype(np.int32), 0, n_stops - 2)
    hi = lo + 1
    frac = (t - lo).reshape(-1, 1)
    vertex_colors = ramp[lo] * (1.0 - frac) + ramp[hi] * frac  # (n_verts, 4)
    col_bytes = vertex_colors.astype(np.float32).tobytes()

    # ---- Binary buffer layout ----
    idx_buf = _pad4(idx_bytes)
    pos_buf = _pad4(pos_bytes)
    nrm_buf = _pad4(nrm_bytes)
    uv_buf  = _pad4(uv_bytes)
    col_buf = _pad4(col_bytes)

    buf_off_idx = 0
    buf_off_pos = len(idx_buf)
    buf_off_nrm = buf_off_pos + len(pos_buf)
    buf_off_uv  = buf_off_nrm + len(nrm_buf)
    buf_off_col = buf_off_uv  + len(uv_buf)
    total_bin   = buf_off_col + len(col_buf)

    # ---- AABB ----
    pos_min = positions.min(axis=0).tolist()
    pos_max = positions.max(axis=0).tolist()

    # ---- glTF JSON ----
    gltf = {
        "asset": {
            "generator": "muLLM terrain_api",
            "version": "2.0",
            "extras": metadata or {},
        },
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{
            "name": "terrain",
            "primitives": [{
                "attributes": {
                    "POSITION": 1,
                    "NORMAL": 2,
                    "TEXCOORD_0": 3,
                    "COLOR_0": 4,
                },
                "indices": 0,
                "material": 0,
                "mode": 4,  # TRIANGLES
            }],
        }],
        "materials": [{
            "name": "terrain_elevation",
            "pbrMetallicRoughness": {
                "baseColorFactor": [1.0, 1.0, 1.0, 1.0],  # vertex colors multiply through
                "metallicFactor": 0.0,
                "roughnessFactor": 0.88,
            },
            "doubleSided": False,
        }],
        "accessors": [
            {   # 0 — indices
                "bufferView": 0,
                "componentType": 5125,  # UNSIGNED_INT
                "count": n_idx,
                "type": "SCALAR",
            },
            {   # 1 — positions
                "bufferView": 1,
                "componentType": 5126,  # FLOAT
                "count": n_verts,
                "type": "VEC3",
                "min": pos_min,
                "max": pos_max,
            },
            {   # 2 — normals
                "bufferView": 2,
                "componentType": 5126,
                "count": n_verts,
                "type": "VEC3",
            },
            {   # 3 — uvs
                "bufferView": 3,
                "componentType": 5126,
                "count": n_verts,
                "type": "VEC2",
            },
            {   # 4 — vertex colors (COLOR_0, VEC4 FLOAT)
                "bufferView": 4,
                "componentType": 5126,
                "count": n_verts,
                "type": "VEC4",
            },
        ],
        "bufferViews": [
            {"buffer": 0, "byteOffset": buf_off_idx, "byteLength": len(idx_bytes), "target": 34963},
            {"buffer": 0, "byteOffset": buf_off_pos, "byteLength": len(pos_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": buf_off_nrm, "byteLength": len(nrm_bytes), "target": 34962},
            {"buffer": 0, "byteOffset": buf_off_uv,  "byteLength": len(uv_bytes),  "target": 34962},
            {"buffer": 0, "byteOffset": buf_off_col, "byteLength": len(col_bytes),  "target": 34962},
        ],
        "buffers": [{"byteLength": total_bin}],
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    # JSON chunk must be padded to 4-byte boundary with spaces (0x20)
    json_rem = len(json_bytes) % 4
    if json_rem:
        json_bytes += b" " * (4 - json_rem)

    # ---- Assemble BIN chunk ----
    bin_data = idx_buf + pos_buf + nrm_buf + uv_buf + col_buf

    # ---- GLB chunks ----
    json_chunk = struct.pack("<II", len(json_bytes), 0x4E4F534A) + json_bytes  # JSON
    bin_chunk = struct.pack("<II", len(bin_data), 0x004E4942) + bin_data       # BIN

    total_length = 12 + len(json_chunk) + len(bin_chunk)
    header = struct.pack("<III", 0x46546C67, 2, total_length)  # magic, version, length

    return header + json_chunk + bin_chunk


# ---------------------------------------------------------------------------
# Procedural noise heightmap (for arcade preset / fallback)
# ---------------------------------------------------------------------------

def _procedural_heightmap(grid_w: int, grid_h: int, scale: float = 50.0) -> np.ndarray:
    """Simple multi-octave Perlin-like noise using numpy sin/cos."""
    x = np.linspace(0, 1, grid_w)
    z = np.linspace(0, 1, grid_h)
    xx, zz = np.meshgrid(x, z)

    h = np.zeros((grid_h, grid_w), dtype=np.float32)
    amp, freq = 1.0, 1.0
    for _ in range(6):
        h += amp * (
            np.sin(freq * 2 * np.pi * xx) * np.cos(freq * 2 * np.pi * zz)
            + 0.5 * np.sin(freq * 3.7 * np.pi * xx + 0.3)
            + 0.3 * np.cos(freq * 2.3 * np.pi * zz + 1.1)
        )
        amp *= 0.5
        freq *= 2.0

    h = (h - h.min()) / (h.max() - h.min() + 1e-9) * scale
    return h.astype(np.float32)


# ---------------------------------------------------------------------------
# Heightmap fetchers
# ---------------------------------------------------------------------------

async def _fetch_usgs(lat: float, lng: float, radius_km: float) -> np.ndarray | None:
    """USGS National Map — 1/3 arc-second DEM tiles (CONUS-focused)."""
    s, w, n, e = _bbox(lat, lng, radius_km)
    url = (
        f"https://tnmaccess.nationalmap.gov/api/v1/products"
        f"?datasets=Digital%20Elevation%20Model%20(DEM)%201%2F3%20Arc-Second"
        f"&bbox={w},{s},{e},{n}&outputFormat=JSON&max=5"
    )
    try:
        async with httpx.AsyncClient(timeout=_HTTPX_TIMEOUT) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        data = resp.json()
        items = data.get("items", [])
        if not items:
            return None
        # Pick the first available item's download URL
        dl_url = items[0].get("downloadURL", "")
        if not dl_url:
            return None
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            dem_resp = await client.get(dl_url)
        if dem_resp.status_code != 200:
            return None
        # Parse as 16-bit PNG or TIFF via PIL
        from PIL import Image
        img = Image.open(io.BytesIO(dem_resp.content))
        arr = np.array(img, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr
    except Exception:
        return None


async def _fetch_opentopography(lat: float, lng: float, radius_km: float) -> np.ndarray | None:
    """OpenTopography globaldem — needs OPENTOPOGRAPHY_API_KEY env var."""
    api_key = os.environ.get("OPENTOPOGRAPHY_API_KEY", "")
    if not api_key:
        return None
    s, w, n, e = _bbox(lat, lng, radius_km)
    url = (
        f"https://portal.opentopography.org/API/globaldem"
        f"?demtype=NASADEM&south={s}&north={n}&west={w}&east={e}"
        f"&outputFormat=GTiff&API_Key={api_key}"
    )
    try:
        async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        from PIL import Image
        img = Image.open(io.BytesIO(resp.content))
        arr = np.array(img, dtype=np.float32)
        if arr.ndim == 3:
            arr = arr[:, :, 0]
        return arr
    except Exception:
        return None


async def _fetch_mapbox(lat: float, lng: float, radius_km: float, zoom: int = 11) -> np.ndarray | None:
    """Mapbox Terrain-DEM RGB tile — needs MAPBOX_TOKEN env var.

    Elevation formula: elevation = -10000 + ((R*65536 + G*256 + B) * 0.1) metres.
    Single tile, centred on the requested point.
    """
    token = os.environ.get("MAPBOX_TOKEN", "")
    if not token:
        return None
    try:
        # Convert lat/lng to tile XYZ
        lat_r = math.radians(lat)
        n = 2 ** zoom
        tile_x = int((lng + 180.0) / 360.0 * n)
        tile_y = int((1.0 - math.log(math.tan(lat_r) + 1.0 / math.cos(lat_r)) / math.pi) / 2.0 * n)
        url = (
            f"https://api.mapbox.com/v4/mapbox.terrain-rgb"
            f"/{zoom}/{tile_x}/{tile_y}@2x.pngraw?access_token={token}"
        )
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            resp = await client.get(url)
        if resp.status_code != 200:
            return None
        from PIL import Image
        img = Image.open(io.BytesIO(resp.content)).convert("RGB")
        rgb = np.array(img, dtype=np.float32)
        r, g, b = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
        elevation = -10000.0 + (r * 65536.0 + g * 256.0 + b) * 0.1
        return elevation.astype(np.float32)
    except Exception:
        return None


async def _fetch_osm_overlay(lat: float, lng: float, radius_km: float) -> dict[str, Any]:
    """Fetch OSM features via Overpass API for map overlay."""
    s, w, n, e = _bbox(lat, lng, radius_km)
    bbox_str = f"{s},{w},{n},{e}"
    query = (
        f"[out:json][timeout:25];"
        f"("
        f"  way[building]({bbox_str});"
        f"  way[highway]({bbox_str});"
        f"  way[natural=water]({bbox_str});"
        f"  relation[natural=water]({bbox_str});"
        f");"
        f"out geom;"
    )
    try:
        async with httpx.AsyncClient(timeout=35.0) as client:
            resp = await client.post(
                "https://overpass-api.de/api/interpreter",
                data={"data": query},
            )
        if resp.status_code != 200:
            return {"buildings": [], "roads": [], "water": []}
        data = resp.json()
        buildings, roads, water = [], [], []
        for el in data.get("elements", []):
            geom = el.get("geometry", [])
            coords = [[p["lon"], p["lat"]] for p in geom if "lon" in p and "lat" in p]
            tags = el.get("tags", {})
            if "building" in tags:
                buildings.append({"coords": coords, "tags": tags})
            elif "highway" in tags:
                roads.append({"coords": coords, "highway": tags.get("highway", "unclassified")})
            elif "natural" in tags and tags["natural"] == "water":
                water.append({"coords": coords})
        return {"buildings": buildings, "roads": roads, "water": water}
    except Exception:
        return {"buildings": [], "roads": [], "water": []}


# ---------------------------------------------------------------------------
# Contour line generation (numpy marching-squares, no scipy dep)
# ---------------------------------------------------------------------------

def _generate_contours(
    heights: np.ndarray,
    x_size_m: float,
    z_size_m: float,
    n_levels: int = 10,
) -> list[list[list[float]]]:
    """Derive contour isolines from a 2-D heightmap using linear interpolation.

    Returns a list of polylines; each polyline is a list of [x, y, z] triples
    in the same coordinate space as the GLB mesh (centred at origin, Y=elevation).
    Uses a simple marching-squares edge-crossing scan rather than scipy.
    n_levels contour levels are evenly spaced between the 5th and 95th elevation percentile.
    """
    gh, gw = heights.shape
    if gh < 2 or gw < 2:
        return []

    # Downsample large grids to avoid O(n^2) chaining cost.
    # Contour visual quality at 256x256 is indistinguishable from 512+.
    MAX_CONTOUR_GRID = 256
    if gh > MAX_CONTOUR_GRID or gw > MAX_CONTOUR_GRID:
        scale = min(MAX_CONTOUR_GRID / gh, MAX_CONTOUR_GRID / gw)
        new_gh = max(2, int(gh * scale))
        new_gw = max(2, int(gw * scale))
        try:
            from PIL import Image
            img = Image.fromarray(heights.astype(np.float32))
            img = img.resize((new_gw, new_gh), Image.BILINEAR)
            heights = np.array(img, dtype=np.float32)
        except Exception:
            heights = heights[::int(gh / new_gh) or 1, ::int(gw / new_gw) or 1]
        gh, gw = heights.shape

    dx = x_size_m / (gw - 1)
    dz = z_size_m / (gh - 1)

    h_lo = float(np.percentile(heights, 5))
    h_hi = float(np.percentile(heights, 95))
    if h_hi - h_lo < 1.0:
        return []

    levels = np.linspace(h_lo, h_hi, n_levels + 2)[1:-1]  # exclude the exact endpoints

    def cell_segments(r: int, c: int, level: float) -> list[tuple[tuple[float, float, float], tuple[float, float, float]]]:
        """Return 0 or 1 line segments for the quad cell (r,c)→(r+1,c+1) at `level`."""
        # Corners: TL, TR, BL, BR
        h_tl = float(heights[r,     c])
        h_tr = float(heights[r,     c + 1])
        h_bl = float(heights[r + 1, c])
        h_br = float(heights[r + 1, c + 1])

        # World-space X/Z of each corner (centred)
        x0 = c       * dx - x_size_m / 2.0
        x1 = (c + 1) * dx - x_size_m / 2.0
        z0 = r       * dz - z_size_m / 2.0
        z1 = (r + 1) * dz - z_size_m / 2.0

        def interp_edge(ha: float, hb: float, pa: tuple, pb: tuple) -> tuple[float, float, float] | None:
            """Linear interpolation on an edge if level crosses it."""
            if (ha < level) == (hb < level):
                return None  # no crossing
            t = (level - ha) / (hb - ha + 1e-12)
            return (
                pa[0] + t * (pb[0] - pa[0]),
                level,
                pa[1] + t * (pb[1] - pa[1]),
            )

        corners = {
            "TL": (x0, z0, h_tl),
            "TR": (x1, z0, h_tr),
            "BL": (x0, z1, h_bl),
            "BR": (x1, z1, h_br),
        }

        edges = [
            ("TL", "TR"),  # top
            ("TR", "BR"),  # right
            ("BL", "BR"),  # bottom
            ("TL", "BL"),  # left
        ]

        def corner_pos(name: str) -> tuple[float, float]:
            c3 = corners[name]
            return (c3[0], c3[1])

        pts = []
        for a_name, b_name in edges:
            ha2 = corners[a_name][2]
            hb2 = corners[b_name][2]
            pa = corner_pos(a_name)
            pb = corner_pos(b_name)
            pt = interp_edge(ha2, hb2, pa, pb)
            if pt is not None:
                pts.append(pt)

        if len(pts) == 2:
            return [(pts[0], pts[1])]
        return []

    polylines: list[list[list[float]]] = []

    for level in levels:
        # Collect all segments for this level, then chain into polylines
        segs: list[tuple[tuple, tuple]] = []
        for row in range(gh - 1):
            for col in range(gw - 1):
                segs.extend(cell_segments(row, col, level))

        if not segs:
            continue

        # Hash-map based polyline chaining: O(n) lookup via quantised endpoint keys.
        # Quantise coordinates to 3 decimal places (sub-millimetre for km-scale terrains).
        def qkey(pt: tuple) -> tuple:
            return (round(pt[0], 3), round(pt[2], 3))

        # Build adjacency: endpoint_key → list of segment indices with that endpoint
        endpoint_map: dict = defaultdict(list)
        for idx, (p0, p1) in enumerate(segs):
            endpoint_map[qkey(p0)].append((idx, False))   # False = p0 side
            endpoint_map[qkey(p1)].append((idx, True))    # True  = p1 side

        used = [False] * len(segs)
        chains: list[list[list[float]]] = []

        for start_i in range(len(segs)):
            if used[start_i]:
                continue
            used[start_i] = True
            p0, p1 = segs[start_i]
            chain: list[list[float]] = [list(p0), list(p1)]

            # Walk forward from tail
            while True:
                tail_key = qkey(chain[-1])
                candidates = endpoint_map.get(tail_key, [])
                found = False
                for j, is_p1_side in candidates:
                    if used[j]:
                        continue
                    used[j] = True
                    q0, q1 = segs[j]
                    # Append the *other* end of segment j
                    chain.append(list(q1) if not is_p1_side else list(q0))
                    found = True
                    break
                if not found:
                    break

            chains.append(chain)

        polylines.extend(chains)

    return polylines


# ---------------------------------------------------------------------------
# Source availability check (fast, cached-per-request)
# ---------------------------------------------------------------------------

async def _check_url(url: str, timeout: float = 5.0) -> bool:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            r = await client.head(url)
        return r.status_code < 500
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Preset definitions
# ---------------------------------------------------------------------------

PRESETS: dict[str, dict[str, Any]] = {
    "arcade": {
        "name": "Arcade",
        "description": "Low-poly stylized terrain, procedural noise, no real DEM data needed.",
        "grid": 32,
        "use_real_dem": False,
        "normal_quality": "none",
        "texture_detail": "flat",
        "height_scale": 1.0,
    },
    "game": {
        "name": "Game",
        "description": "128x128 from real DEM source, PBR-ready geometry, suitable for game engines.",
        "grid": 128,
        "use_real_dem": True,
        "normal_quality": "medium",
        "texture_detail": "pbr",
        "height_scale": 1.0,
    },
    "realistic": {
        "name": "Realistic",
        "description": "512x512 from best available source, high-fidelity normals, multi-texture splat.",
        "grid": 512,
        "use_real_dem": True,
        "normal_quality": "high",
        "texture_detail": "splat",
        "height_scale": 1.0,
    },
    "survey": {
        "name": "Survey",
        "description": "Maximum source resolution, lossless, GIS metadata preserved in GLB extras.",
        "grid": 1024,
        "use_real_dem": True,
        "normal_quality": "high",
        "texture_detail": "lossless",
        "height_scale": 1.0,
    },
}

# ---------------------------------------------------------------------------
# Example locations
# ---------------------------------------------------------------------------

EXAMPLE_LOCATIONS = [
    {
        "name": "Iceland Highlands",
        "description": "Volcanic plateau, dramatic ridgelines, glacial valleys",
        "lat": 64.8014,
        "lng": -18.3274,
        "radius_km": 15.0,
        "recommended_preset": "realistic",
        "region": "europe",
    },
    {
        "name": "Grand Canyon South Rim",
        "description": "Deep gorge, 1600m vertical relief, iconic layered stratigraphy",
        "lat": 36.0544,
        "lng": -112.1401,
        "radius_km": 20.0,
        "recommended_preset": "realistic",
        "region": "north_america",
    },
    {
        "name": "Swiss Alps — Eiger",
        "description": "3970m peak, north face, dense contour terrain",
        "lat": 46.5763,
        "lng": 8.0054,
        "radius_km": 10.0,
        "recommended_preset": "survey",
        "region": "europe",
    },
    {
        "name": "Mojave Desert (Martian analog)",
        "description": "Flat basins, volcanic buttes, used as Mars terrain stand-in",
        "lat": 34.9592,
        "lng": -116.2227,
        "radius_km": 25.0,
        "recommended_preset": "game",
        "region": "north_america",
    },
    {
        "name": "Faroe Islands",
        "description": "Coastal cliffs, sea stacks, fog — perfect for game world art direction",
        "lat": 62.0079,
        "lng": -6.7888,
        "radius_km": 8.0,
        "recommended_preset": "realistic",
        "region": "europe",
    },
    {
        "name": "Rub al Khali Dunes",
        "description": "World's largest sand sea, smooth undulating dune ridges",
        "lat": 22.7673,
        "lng": 51.7011,
        "radius_km": 30.0,
        "recommended_preset": "arcade",
        "region": "middle_east",
    },
]

# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------

@router.get("/sources")
async def list_sources() -> dict[str, Any]:
    """List all terrain data sources with capabilities, availability, and cost."""
    opentopo_key = bool(os.environ.get("OPENTOPOGRAPHY_API_KEY", ""))
    mapbox_token = bool(os.environ.get("MAPBOX_TOKEN", ""))
    cesium_configured = bool(os.environ.get("CESIUM_TOKEN", ""))
    felt_configured = bool(os.environ.get("FELT_TOKEN", ""))

    # Quick availability ping (fire-and-forget; non-blocking)
    usgs_up = await _check_url("https://tnmaccess.nationalmap.gov/api/v1/products?max=1", timeout=4.0)
    overpass_up = await _check_url("https://overpass-api.de/api/interpreter", timeout=4.0)

    return {
        "sources": [
            {
                "id": "usgs",
                "name": "USGS National Map",
                "description": "1/3 arc-second DEM (~10m) for CONUS. Keyless, free.",
                "resolution": "1/3 arc-second (~10m)",
                "coverage": "Continental US",
                "cost": "free",
                "requires_key": False,
                "available": usgs_up,
                "status": "online" if usgs_up else "unreachable",
                "url": "https://www.usgs.gov/programs/national-geospatial-program/national-map",
                "datasets": ["3DEP 1/3 arc-second DEM"],
            },
            {
                "id": "opentopography",
                "name": "OpenTopography",
                "description": "Global DEMs: NASADEM (30m), SRTM (30/90m), Copernicus (30m). Free API key required.",
                "resolution": "30m–90m (NASADEM/SRTM/Copernicus)",
                "coverage": "Global",
                "cost": "free (API key required)",
                "requires_key": True,
                "key_env": "OPENTOPOGRAPHY_API_KEY",
                "available": opentopo_key,
                "status": "configured" if opentopo_key else "needs_key",
                "reason": None if opentopo_key else "set OPENTOPOGRAPHY_API_KEY",
                "url": "https://portal.opentopography.org/",
                "datasets": ["NASADEM", "SRTM GL3", "SRTM GL1", "Copernicus DEM"],
            },
            {
                "id": "mapbox",
                "name": "Mapbox Terrain-DEM",
                "description": "512px tiles globally, RGB-encoded elevation. Needs MAPBOX_TOKEN.",
                "resolution": "varies by zoom level (~10m–80m)",
                "coverage": "Global",
                "cost": "free tier / pay per request",
                "requires_key": True,
                "key_env": "MAPBOX_TOKEN",
                "available": mapbox_token,
                "status": "configured" if mapbox_token else "needs_key",
                "reason": None if mapbox_token else "set MAPBOX_TOKEN",
                "url": "https://docs.mapbox.com/data/tilesets/reference/mapbox-terrain-dem-v1/",
                "datasets": ["Mapbox Terrain-RGB v1"],
            },
            {
                "id": "osm",
                "name": "OpenStreetMap (Overpass)",
                "description": "Buildings, roads, water bodies for overlay. Keyless.",
                "resolution": "vector (unlimited)",
                "coverage": "Global",
                "cost": "free",
                "requires_key": False,
                "available": overpass_up,
                "status": "online" if overpass_up else "unreachable",
                "url": "https://overpass-api.de/",
                "datasets": ["OSM buildings", "OSM highways", "OSM water"],
            },
            {
                "id": "cesiumion",
                "name": "CesiumIon",
                "description": "High-resolution global terrain. Requires CesiumIon token and provider adapter.",
                "resolution": "up to 1m",
                "coverage": "Global (commercial)",
                "cost": "commercial",
                "requires_key": True,
                "key_env": "CESIUM_TOKEN",
                "available": cesium_configured,
                "status": "adapter_required" if cesium_configured else "needs_key",
                "reason": "enable CesiumIon adapter" if cesium_configured else "set CESIUM_TOKEN",
                "url": "https://cesium.com/platform/cesium-ion/",
                "datasets": [],
            },
            {
                "id": "felt",
                "name": "Felt",
                "description": "Collaborative mapping layers. Requires Felt token and provider adapter.",
                "resolution": "varies",
                "coverage": "Global (commercial)",
                "cost": "commercial",
                "requires_key": True,
                "key_env": "FELT_TOKEN",
                "available": felt_configured,
                "status": "adapter_required" if felt_configured else "needs_key",
                "reason": "enable Felt adapter" if felt_configured else "set FELT_TOKEN",
                "url": "https://felt.com/",
                "datasets": [],
            },
        ]
    }


@router.get("/presets")
async def list_presets() -> dict[str, Any]:
    """List terrain generation presets with quality/detail trade-offs."""
    return {"presets": [{"id": k, **v} for k, v in PRESETS.items()]}


@router.get("/examples")
async def list_examples() -> dict[str, Any]:
    """Return example locations useful for game development terrain reference."""
    return {"locations": EXAMPLE_LOCATIONS}


@router.post("/fetch")
async def fetch_heightmap(request: Request) -> dict[str, Any]:
    """Fetch a raw heightmap for a location from the specified source.

    Body:
        lat, lng       — centre coordinate (degrees)
        radius_km      — half-width of the area (1–100 km)
        source         — 'usgs' | 'opentopography' | 'mapbox' (default: 'usgs')
    """
    body = await request.json()
    lat = float(body.get("lat", 0))
    lng = float(body.get("lng", 0))
    radius_km = max(1.0, min(100.0, float(body.get("radius_km", 10.0))))
    source = str(body.get("source", "usgs")).lower()

    if not (-90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="lat must be in [-90, 90]")
    if not (-180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="lng must be in [-180, 180]")

    heightmap: np.ndarray | None = None

    if source == "usgs":
        heightmap = await _fetch_usgs(lat, lng, radius_km)
    elif source == "opentopography":
        heightmap = await _fetch_opentopography(lat, lng, radius_km)
    elif source == "mapbox":
        heightmap = await _fetch_mapbox(lat, lng, radius_km)
    else:
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")

    if heightmap is None:
        return {
            "ok": False,
            "source": source,
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
            "error": "source unavailable or returned no data",
            "heightmap_rows": None,
            "heightmap_cols": None,
            "min_elevation_m": None,
            "max_elevation_m": None,
            "heights": None,
        }

    h_min = float(heightmap.min())
    h_max = float(heightmap.max())

    # Downsample for JSON preview (max 64×64)
    preview = heightmap
    if preview.shape[0] > 64 or preview.shape[1] > 64:
        from PIL import Image
        img = Image.fromarray(preview)
        img = img.resize((64, 64), Image.BILINEAR)
        preview = np.array(img, dtype=np.float32)

    return {
        "ok": True,
        "source": source,
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        "heightmap_rows": heightmap.shape[0],
        "heightmap_cols": heightmap.shape[1],
        "min_elevation_m": h_min,
        "max_elevation_m": h_max,
        "preview_64x64": preview.tolist(),
    }


@router.post("/generate")
async def generate_terrain(request: Request) -> JSONResponse:
    """Generate a terrain GLB from real DEM or procedural noise.

    Body:
        lat, lng       — centre coordinate (degrees)
        radius_km      — area half-width in km (1–100)
        preset         — 'arcade' | 'game' | 'realistic' | 'survey'
        source         — 'usgs' | 'opentopography' | 'mapbox' | 'procedural'
        osm_overlay    — true/false, add OSM buildings/roads/water metadata
        osm_buildings  — true/false individual toggle
        osm_roads      — true/false individual toggle
        osm_water      — true/false individual toggle
        osm_contours   — true/false, generate elevation contour lines from DEM (no network call)
        contour_levels — number of contour levels to generate (default 10, max 30)
    """
    body = await request.json()
    lat = float(body.get("lat", 0))
    lng = float(body.get("lng", 0))
    radius_km = max(1.0, min(100.0, float(body.get("radius_km", 10.0))))
    preset_name = str(body.get("preset", "game")).lower()
    source = str(body.get("source", "usgs")).lower()
    want_osm = bool(body.get("osm_overlay", False))
    want_buildings = bool(body.get("osm_buildings", True))
    want_roads = bool(body.get("osm_roads", True))
    want_water = bool(body.get("osm_water", True))
    want_contours = bool(body.get("osm_contours", False))
    contour_levels = max(3, min(30, int(body.get("contour_levels", 10))))

    if not (-90 <= lat <= 90):
        raise HTTPException(status_code=400, detail="lat must be in [-90, 90]")
    if not (-180 <= lng <= 180):
        raise HTTPException(status_code=400, detail="lng must be in [-180, 180]")
    if preset_name not in PRESETS:
        raise HTTPException(status_code=400, detail=f"unknown preset: {preset_name}. Use: {list(PRESETS)}")

    preset = PRESETS[preset_name]
    grid = int(preset["grid"])
    use_real = bool(preset["use_real_dem"])

    # ---- Heightmap acquisition ----
    t0 = time.monotonic()
    heightmap: np.ndarray | None = None
    actual_source = source

    if use_real and source != "procedural":
        if source == "usgs":
            heightmap = await _fetch_usgs(lat, lng, radius_km)
        elif source == "opentopography":
            heightmap = await _fetch_opentopography(lat, lng, radius_km)
        elif source == "mapbox":
            heightmap = await _fetch_mapbox(lat, lng, radius_km)
        else:
            raise HTTPException(status_code=400, detail=f"unknown source: {source}")

    if heightmap is None:
        # Fallback to procedural
        actual_source = "procedural"
        # Use game-scale relief: the previous ``radius_km * 0.1`` calculation
        # produced just 0.2 m of relief across a 4 km terrain, which rendered
        # and exported as an apparently flat plane.  Ten percent of the
        # half-width gives useful hills while keeping slopes navigable.
        height_scale = float(preset.get("height_scale", 1.0)) * radius_km * 100.0
        heightmap = _procedural_heightmap(grid, grid, scale=height_scale)

    # ---- Resample to target grid ----
    if heightmap.shape != (grid, grid):
        from PIL import Image
        img = Image.fromarray(heightmap.astype(np.float32))
        img = img.resize((grid, grid), Image.BILINEAR)
        heightmap = np.array(img, dtype=np.float32)

    # ---- Normalise heights for game use (0 → max_relief) ----
    h_min = float(heightmap.min())
    h_max = float(heightmap.max())
    h_range = h_max - h_min
    # Keep absolute metres but ensure zero-floor
    heightmap = heightmap - h_min

    # ---- Real-world extent in metres ----
    x_size_m = radius_km * 2.0 * 1000.0
    z_size_m = radius_km * 2.0 * 1000.0

    # ---- GLB metadata ----
    meta = {
        "source": actual_source,
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        "preset": preset_name,
        "grid": grid,
        "min_elevation_m": h_min,
        "max_elevation_m": h_max,
        "height_range_m": h_range,
        "x_size_m": x_size_m,
        "z_size_m": z_size_m,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    glb_bytes = _build_glb(heightmap, grid, grid, x_size_m, z_size_m, meta)

    # ---- Save to assets/3d ----
    slug = _slug(lat, lng, radius_km, preset_name, actual_source)
    filename = f"terrain-{slug}"
    stored = get_asset_store().put_bytes(filename, glb_bytes, {
        "source": actual_source,
        "prompt": f"terrain {lat},{lng} r={radius_km}km {preset_name}",
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ai_generated": False,
        "pipeline": "terrain_api",
        "category": "terrain",
        "tags": ["terrain", preset_name, actual_source],
        **meta,
    })

    # Export the source height field beside local GLBs.  A 16-bit PNG preserves
    # enough precision for re-import into Three.js, Blender, and game engines.
    # Remote asset backends may not expose a writable local path, so this is a
    # best-effort companion while the GLB remains the canonical result.
    heightmap_url: str | None = None
    try:
        from PIL import Image

        normalized = heightmap / max(float(heightmap.max()), 1e-9)
        height_u16 = np.round(normalized * 65535.0).astype(np.uint16)
        heightmap_path = Path(stored.path).with_name(f"{stored.name}-heightmap.png")
        Image.fromarray(height_u16, mode="I;16").save(heightmap_path)
        heightmap_url = f"/assets/3d/{heightmap_path.name}"
    except (OSError, ValueError):
        logger.warning("Could not persist terrain heightmap companion", exc_info=True)

    elapsed = time.monotonic() - t0

    # ---- OSM overlay ----
    overlay: dict[str, Any] = {}
    if want_osm or want_contours:
        if want_osm:
            raw_overlay = await _fetch_osm_overlay(lat, lng, radius_km)
        else:
            raw_overlay = {"buildings": [], "roads": [], "water": []}
        overlay = {
            "buildings": raw_overlay["buildings"] if want_buildings else [],
            "roads": raw_overlay["roads"] if want_roads else [],
            "water": raw_overlay["water"] if want_water else [],
        }
        # Contour lines derived from the DEM heightmap — no network call
        if want_contours:
            overlay["contour_lines"] = _generate_contours(
                heightmap, x_size_m, z_size_m, n_levels=contour_levels
            )
        else:
            overlay["contour_lines"] = []
        overlay["counts"] = {
            "buildings": len(overlay["buildings"]),
            "roads": len(overlay["roads"]),
            "water": len(overlay["water"]),
            "contour_lines": len(overlay["contour_lines"]),
        }

    return JSONResponse({
        "ok": True,
        "glb_url": stored.url,
        "glb_path": stored.path,
        "glb_size_kb": round(stored.bytes / 1024, 1),
        "heightmap_url": heightmap_url,
        "heightmap_format": "16-bit grayscale PNG" if heightmap_url else None,
        "asset_name": stored.name,
        "source": actual_source,
        "source_requested": source,
        "fallback_used": actual_source != source,
        "preset": preset_name,
        "grid": grid,
        "lat": lat,
        "lng": lng,
        "radius_km": radius_km,
        "min_elevation_m": h_min,
        "max_elevation_m": h_max,
        "height_range_m": h_range,
        "x_size_m": x_size_m,
        "z_size_m": z_size_m,
        "elapsed_s": round(elapsed, 2),
        "overlay": overlay,
        "meta": meta,
    })
