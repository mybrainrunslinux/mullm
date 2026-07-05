"""Scene and 3D asset APIs for optional muLLM Studio/Scene surfaces."""

from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from router import meshy
from router.asset_store import (
    AssetStoreError,
    asset_url,
    assets_3d_dir,
    compress_asset,
    compression_status,
    get_asset_store,
    packaged_assets_3d_dir,
    resolve_asset_file,
    sanitize_asset_name,
)
from router.config import settings
from router.world_providers import GenerationRequest, WorldProviderError, generate, provider_status

router = APIRouter(tags=["scene"])

WEAPON_KEYWORDS = {
    "sword",
    "swordgun",
    "blade",
    "katana",
    "saber",
    "sabre",
    "rapier",
    "epee",
    "dagger",
    "kukri",
    "cutlass",
    "broadsword",
    "longsword",
    "greatsword",
    "crossbow",
    "bow",
    "scythe",
    "halberd",
    "spear",
    "polearm",
    "mace",
    "flail",
    "axe",
    "staff",
}
SIEGE_KEYWORDS = {
    "ballista",
    "catapult",
    "trebuchet",
    "onager",
    "battering",
    "ram",
    "siege",
}
CREATURE_KEYWORDS = {
    "dog",
    "wolf",
    "cat",
    "capybara",
    "horse",
    "dragon",
    "creature",
    "humanoid",
    "knight",
    "skeleton",
}
BUILDING_KEYWORDS = {
    "building",
    "tower",
    "castle",
    "house",
    "dojo",
    "bridge",
    "gate",
    "wall",
    "fountain",
}

ASSET_TYPE_ALIASES = {
    "": "",
    "auto": "",
    "prop": "prop",
    "sword": "weapon",
    "weapon": "weapon",
    "siege": "siege",
    "siege_engine": "siege",
    "character": "creature",
    "creature": "creature",
    "building": "building",
    "environment": "building",
}


def normalize_asset_type(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return ASSET_TYPE_ALIASES.get(raw, raw if raw in {"weapon", "siege", "creature", "building", "prop"} else "")


def _read_sidecar(path: Path) -> dict[str, Any]:
    sidecar = path.with_suffix(".json")
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _slug_text(*parts: str) -> str:
    return " ".join(part.lower().replace("_", "-") for part in parts if part)


def _has_keyword(text: str, keywords: set[str]) -> bool:
    return any(re.search(rf"(?<![a-z0-9]){re.escape(word)}(?![a-z0-9])", text) for word in keywords)


def classify_asset(name: str, prompt: str = "", metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    """Classify an asset into routing/use categories for Scene, Dojo, and Siege."""
    meta = metadata or {}
    explicit_type = normalize_asset_type(
        str(meta.get("asset_type") or meta.get("kind") or meta.get("category") or "")
    )
    explicit_categories = [
        normalize_asset_type(str(item))
        for item in meta.get("categories", []) or []
        if isinstance(item, str)
    ]
    text = _slug_text(
        name,
        prompt,
        str(meta.get("asset_type", "")),
        str(meta.get("kind", "")),
        str(meta.get("category", "")),
        " ".join(meta.get("tags", []) or []),
    )

    categories: list[str] = []
    for category in [explicit_type, *explicit_categories]:
        if category and category not in categories:
            categories.append(category)
    if _has_keyword(text, WEAPON_KEYWORDS):
        if "weapon" not in categories:
            categories.append("weapon")
    if _has_keyword(text, SIEGE_KEYWORDS):
        if "siege" not in categories:
            categories.append("siege")
    if _has_keyword(text, CREATURE_KEYWORDS):
        if "creature" not in categories:
            categories.append("creature")
    if _has_keyword(text, BUILDING_KEYWORDS):
        if "building" not in categories:
            categories.append("building")
    if not categories:
        categories.append("prop")

    tags = sorted(set(categories + [tag for tag in meta.get("tags", []) or [] if isinstance(tag, str)]))
    return {
        "category": categories[0],
        "categories": categories,
        "tags": tags,
        "can_try": {
            "dojo": "weapon" in categories,
            "siege": "siege" in categories,
            "rigs": "creature" in categories or "weapon" in categories,
            "walks": "creature" in categories or "building" in categories,
            "scene": True,
        },
        "orientation": meta.get(
            "orientation",
            {
                "forward_axis": "+z",
                "up_axis": "+y",
                "handle_axis": "-y" if "weapon" in categories else "",
                "business_axis": "+y" if "weapon" in categories else "",
            },
        ),
    }


def asset_record(path: Path) -> dict[str, Any]:
    meta = _read_sidecar(path)
    prompt = str(meta.get("prompt", ""))
    classified = classify_asset(path.stem, prompt, meta)
    stat = path.stat()
    thumbnail = str(meta.get("thumbnail", ""))
    return {
        "name": path.stem,
        "file": path.name,
        "size_kb": round(stat.st_size / 1024, 1),
        "url": asset_url(path.name),
        "source": meta.get("source", "procedural"),
        "prompt": prompt,
        "thumbnail": thumbnail,
        "ai_generated": bool(meta.get("ai_generated", True)),
        "pipeline": meta.get("pipeline", "unknown"),
        "date": meta.get("date", ""),
        "updated_at": stat.st_mtime,
        "storage": {
            "backend": settings.asset_storage_backend,
            "local_path": str(path),
            "external_base_url": settings.asset_external_base_url,
            "compression": settings.asset_compression,
            "compressed": _compressed_variants(path),
        },
        **classified,
    }


def list_assets() -> list[dict[str, Any]]:
    seen: set[str] = set()
    paths: list[Path] = []
    for asset_dir in (assets_3d_dir(), packaged_assets_3d_dir()):
        if not asset_dir.exists():
            continue
        for path in sorted(asset_dir.glob("*.glb"), key=lambda item: item.stat().st_mtime, reverse=True):
            if path.name in seen:
                continue
            seen.add(path.name)
            paths.append(path)
    return [asset_record(path) for path in paths]


def _compressed_variants(path: Path) -> dict[str, str]:
    variants: dict[str, str] = {}
    for suffix, label in (
        (".glb.br", "brotli"),
        (".glb.gz", "gzip"),
        ("-draco.glb", "draco"),
        ("-meshopt.glb", "meshopt"),
    ):
        candidate = path.with_name(path.stem + suffix) if suffix.startswith("-") else Path(str(path) + suffix[4:])
        if candidate.exists():
            variants[label] = asset_url(candidate.name)
    return variants


@router.get("/api/3d-assets")
async def list_3d_assets(category: str | None = None, q: str | None = None):
    assets = list_assets()
    if category:
        normalized = category.strip().lower()
        assets = [asset for asset in assets if normalized in asset.get("categories", [])]
    if q:
        needle = q.strip().lower()
        assets = [
            asset
            for asset in assets
            if needle in asset["name"].lower() or needle in str(asset.get("prompt", "")).lower()
        ]
    counts: dict[str, int] = {}
    for asset in assets:
        for category_name in asset.get("categories", []):
            counts[category_name] = counts.get(category_name, 0) + 1
    return {
        "assets": assets,
        "total": len(assets),
        "counts": counts,
        "storage": asset_storage_status_payload(),
    }


@router.get("/assets/3d/{filename}")
async def serve_3d_asset(filename: str):
    """Serve configured local 3D assets without assuming the repo asset root."""
    try:
        path = resolve_asset_file(filename)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except AssetStoreError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    headers = {
        "Content-Length": str(path.stat().st_size),
        "Cache-Control": "public, max-age=3600",
    }
    media_type = "model/gltf-binary" if path.suffix.lower() == ".glb" else "application/octet-stream"
    return Response(path.read_bytes(), media_type=media_type, headers=headers)


def asset_storage_status_payload() -> dict[str, Any]:
    asset_dir = assets_3d_dir()
    packaged_dir = packaged_assets_3d_dir()
    total_bytes = 0
    count = 0
    seen: set[str] = set()
    for root in (asset_dir, packaged_dir):
        if not root.exists():
            continue
        for path in root.glob("*.glb"):
            if path.name in seen:
                continue
            seen.add(path.name)
            count += 1
            total_bytes += path.stat().st_size
    return {
        "backend": settings.asset_storage_backend,
        "root": str(asset_dir),
        "packaged_root": str(packaged_dir),
        "external_base_url": settings.asset_external_base_url,
        "compression": settings.asset_compression,
        "max_local_gb": settings.asset_max_local_gb,
        "local_total_gb": round(total_bytes / (1024 ** 3), 4),
        "asset_count": count,
        "compression_options": ["none", "gzip", "brotli", "draco", "meshopt", "ktx2", "auto"],
        "compression_status": compression_status(),
        "storage_options": ["local", "s3", "azure_blob", "external_api"],
        "notes": [
            "Local disk is the default and works offline.",
            "Object storage and external asset APIs are represented in metadata now and can be backed by provider adapters.",
            "glTF compression choices should be per-project because Draco, Meshopt, KTX2, gzip, and Brotli trade CPU, size, and compatibility differently.",
        ],
    }


@router.get("/api/scene/storage")
async def asset_storage_status():
    return asset_storage_status_payload()


@router.get("/api/world/providers")
async def world_provider_status():
    return provider_status()


async def _generate_world_or_asset(request: Request):
    body = await request.json()
    from router.world_providers import SanaWmProvider
    _default_provider = "comfyui" if not SanaWmProvider().configured() else "sana_wm"
    provider = str(body.get("provider") or _default_provider)
    prompt = str(body.get("prompt") or body.get("content") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    kind = str(body.get("kind") or body.get("mode") or "text_to_3d")
    if kind not in {"text_to_3d", "image_to_3d", "world"}:
        raise HTTPException(status_code=400, detail="unsupported generation kind")
    image_urls = body.get("image_urls") or ([body["image_url"]] if body.get("image_url") else [])
    if not isinstance(image_urls, list):
        raise HTTPException(status_code=400, detail="image_urls must be a list")
    options = body.get("options") or {}
    if not isinstance(options, dict):
        raise HTTPException(status_code=400, detail="options must be an object")
    try:
        return await generate(
            provider,
            GenerationRequest(
                prompt=prompt,
                kind=kind,  # type: ignore[arg-type]
                image_urls=[str(item) for item in image_urls],
                options=options,
            ),
            dry_run=bool(body.get("dry_run", False)),
        )
    except WorldProviderError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc


@router.post("/api/world/generate")
async def generate_world(request: Request):
    return await _generate_world_or_asset(request)


@router.post("/api/3d/generate")
async def generate_3d_asset(request: Request):
    return await _generate_world_or_asset(request)


@router.get("/api/3d/providers")
async def three_d_provider_status():
    status = provider_status()
    status["providers"]["meshy"] = meshy.status()
    return status


@router.post("/api/3d/text")
async def generate_3d_text(request: Request):
    body = await request.json()
    target_polycount = body.get("target_polycount")
    try:
        return await meshy.text_to_3d(
            prompt=str(body.get("prompt", "")),
            style=str(body.get("style", "realistic")),
            dry_run=bool(body.get("dry_run", False)),
            model_type=str(body.get("model_type", "standard")),
            ai_model=str(body.get("ai_model", "latest")),
            topology=str(body.get("topology", "quad")),
            target_polycount=int(target_polycount) if target_polycount else None,
            should_remesh=body.get("should_remesh"),
        )
    except meshy.MeshyError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc


@router.post("/api/3d/image")
async def generate_3d_image(request: Request):
    body = await request.json()
    try:
        return await meshy.image_to_3d(
            image_url=str(body.get("image_url", "")),
            image_path=str(body.get("image_path", "")),
            dry_run=bool(body.get("dry_run", False)),
        )
    except meshy.MeshyError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc


@router.post("/api/3d/refine")
async def refine_3d_asset(request: Request):
    body = await request.json()
    preview_task_id = str(body.get("preview_task_id", ""))
    if not preview_task_id:
        name = str(body.get("name") or body.get("asset_name") or "").strip()
        if name:
            for candidate in (name, f"meshy-{name}"):
                meta_path = assets_3d_dir() / f"{sanitize_asset_name(candidate)}.json"
                if not meta_path.exists():
                    continue
                meta = _read_sidecar(meta_path.with_suffix(".glb"))
                preview_task_id = str(
                    meta.get("meshy_task_id") or meta.get("task_id") or meta.get("preview_task_id") or ""
                )
                if preview_task_id:
                    break
    try:
        return await meshy.refine_task(preview_task_id, dry_run=bool(body.get("dry_run", False)))
    except meshy.MeshyError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc


@router.get("/api/3d/status/{task_id}")
async def check_3d_status(task_id: str, endpoint: str = "text-to-3d", dry_run: bool = False):
    try:
        return await meshy.poll_task(task_id, endpoint=endpoint, dry_run=dry_run)
    except meshy.MeshyError as exc:
        raise HTTPException(status_code=412, detail=str(exc)) from exc


@router.delete("/api/3d-assets/{name}")
async def delete_3d_asset(name: str):
    safe = re.sub(r"[^A-Za-z0-9_.-]", "", name)
    if not safe:
        raise HTTPException(status_code=400, detail="invalid asset name")
    deleted: list[str] = []
    for suffix in (".glb", ".json"):
        path = assets_3d_dir() / f"{safe}{suffix}"
        if path.exists():
            path.unlink()
            deleted.append(path.name)
    return {"deleted": deleted, "ok": bool(deleted)}


@router.post("/api/scene/assets/{name}/compress")
async def compress_3d_asset(name: str, request: Request):
    """Create local compressed variants for glTF assets.

    gzip is implemented directly because it is dependency-free and useful for
    quick validation. Draco, Meshopt, and KTX2 require external tooling and are
    reported as configured-but-missing until those adapters are installed.
    """
    body = await request.json()
    method = str(body.get("method") or settings.asset_compression or "gzip").lower()
    try:
        safe = sanitize_asset_name(name)
        source = resolve_asset_file(f"{safe}.glb")
        output = compress_asset(source, method)  # type: ignore[arg-type]
        return {
            "ok": True,
            "method": "gzip" if method == "auto" else method,
            "input": source.name,
            "output": Path(output.path).name,
            "url": output.url,
            "input_bytes": source.stat().st_size,
            "output_bytes": output.bytes,
        }
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="asset not found") from exc
    except AssetStoreError as exc:
        status = 501 if method in {"brotli", "draco", "meshopt", "ktx2", "draco_ktx2"} else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def _compression_payload(source: Path, output: Any, method: str, *, mode: str) -> dict[str, Any]:
    input_bytes = source.stat().st_size
    if isinstance(output, dict):
        output_path = Path(output["path"])
        output_url = str(output["url"])
        output_bytes = int(output.get("bytes", output_path.stat().st_size))
    else:
        output_path = Path(output.path)
        output_url = str(output.url)
        output_bytes = int(getattr(output, "bytes", output_path.stat().st_size))
    reduction_pct = round(max(0.0, 1.0 - (output_bytes / max(input_bytes, 1))) * 100, 1)
    return {
        "ok": True,
        "mode": mode,
        "method": method,
        "input": source.name,
        "output": output_path.name,
        "url": output_url,
        "input_bytes": input_bytes,
        "output_bytes": output_bytes,
        "size_before_kb": round(input_bytes / 1024, 1),
        "size_after_kb": round(output_bytes / 1024, 1),
        "reduction_pct": reduction_pct,
        "geometry_modified": False,
        "shape_preserving": True,
        "message": "Created a non-destructive optimized variant; source mesh was left unchanged.",
    }


@router.post("/api/3d/optimize")
@router.post("/api/3d/decimate")
async def optimize_3d_asset(request: Request):
    """Create a conservative optimized variant without destructive decimation.

    Older Studio UI called this operation "decimate" and sent keep_ratio=0.1,
    which was too destructive for game assets. The compatibility endpoint now
    treats that request as shape-preserving asset optimization.
    """
    body = await request.json()
    name = str(body.get("name") or body.get("asset_name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    requested_method = str(body.get("method") or body.get("compression") or "auto").lower()
    if requested_method in {"decimate", "simplify", "reduce", "lowpoly"}:
        requested_method = "auto"
    if requested_method not in {"auto", "gzip", "brotli", "draco", "meshopt", "ktx2", "none"}:
        raise HTTPException(status_code=400, detail="unsupported optimization method")

    safe = sanitize_asset_name(name)
    source = resolve_asset_file(f"{safe}.glb")
    method = "gzip" if requested_method == "auto" else requested_method
    output_name = {
        "none": source.name,
        "gzip": source.name + ".gz",
        "brotli": source.name + ".br",
        "draco": source.stem + "-draco.glb",
        "meshopt": source.stem + "-meshopt.glb",
        "ktx2": source.stem + "-ktx2.glb",
    }[method]
    existing = source.with_name(output_name)
    if existing.exists():
        return {
            **_compression_payload(
                source,
                {
                    "path": str(existing),
                    "url": asset_url(existing.name),
                    "bytes": existing.stat().st_size,
                },
                method,
                mode="optimize",
            ),
            "already_exists": True,
        }

    try:
        output = compress_asset(source, requested_method)  # type: ignore[arg-type]
        return _compression_payload(source, output, method, mode="optimize")
    except AssetStoreError as exc:
        status = 501 if method in {"brotli", "draco", "meshopt", "ktx2", "draco_ktx2"} else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc


def _number(value: str) -> float:
    parsed = float(value)
    return 0.0 if parsed == -0.0 else parsed


def _scene_action_cache_key(text: str, selected: str = "") -> str:
    payload = json.dumps(
        {
            "text": text.strip(),
            "selected": selected.strip(),
            "version": 1,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def parse_scene_action(text: str, selected: str = "") -> dict[str, Any]:
    """Parse exact Scene commands without semantic cache or LLM involvement."""
    raw = text.strip()
    lower = raw.lower()
    action: dict[str, Any] = {"action": "none", "reason": "No deterministic command matched."}

    coord = r"(-?\d+(?:\.\d+)?)"
    sep = r"(?:\s*,\s*|\s+)"
    place = re.search(
        rf"\bplace\s+(.+?)\s+(?:at|to|in)\s+{coord}{sep}{coord}{sep}{coord}\b",
        lower,
    )
    if place:
        action = {
            "action": "place",
            "asset": place.group(1).strip().strip("\"'"),
            "x": _number(place.group(2)),
            "y": _number(place.group(3)),
            "z": _number(place.group(4)),
        }
    else:
        move = re.search(
            rf"\bmove\s+(?:(?:it|selected|[\w.-]+)\s+)?(?:to\s+)?{coord}{sep}{coord}{sep}{coord}\b",
            lower,
        )
        if move:
            action = {
                "action": "move",
                "x": _number(move.group(1)),
                "y": _number(move.group(2)),
                "z": _number(move.group(3)),
            }
        else:
            scale = re.search(r"\bscale\s+(?:it\s+|selected\s+)?(?:to\s+)?(\d+(?:\.\d+)?)\b", lower)
            if scale:
                action = {"action": "scale", "value": _number(scale.group(1))}
            else:
                rotate = re.search(r"\brotate\s+(?:it\s+|selected\s+)?(?:y\s+)?(?:to\s+)?(-?\d+(?:\.\d+)?)\s*(?:deg|degree|degrees)?\b", lower)
                if rotate:
                    action = {"action": "rotate", "y": _number(rotate.group(1))}
                elif re.search(r"\b(clear|empty|reset)\s+(the\s+)?scene\b", lower):
                    action = {"action": "clear"}
                elif re.search(r"\b(remove|delete)\b", lower):
                    action = {"action": "remove"}

    return {
        "action": action,
        "cache_policy": "exact-only",
        "cache_key": _scene_action_cache_key(raw, selected),
        "cached": False,
        "parsed_at": time.time(),
    }


@router.post("/api/scene/action")
async def scene_action(request: Request):
    body = await request.json()
    text = str(body.get("text") or body.get("content") or "")
    selected = str(body.get("selected") or "")
    if not text.strip():
        raise HTTPException(status_code=400, detail="text required")
    return parse_scene_action(text, selected)


@router.post("/api/3d/upload")
async def upload_image_for_3d(request: Request):
    """Upload a base64 image for image-to-3D conversion. Saves to ComfyUI input dir."""
    import base64

    body = await request.json()
    image_data = str(body.get("image_data", ""))
    filename = re.sub(r"[^A-Za-z0-9_.-]", "_", str(body.get("filename", f"upload_{int(time.time())}.png")))
    if not image_data:
        raise HTTPException(status_code=400, detail="image_data (base64) required")
    try:
        raw = base64.b64decode(image_data.split(",")[-1])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"invalid base64: {exc}") from exc

    # Try ComfyUI input dir first, fall back to mullm cache
    comfy_input = Path("/opt/comfyui/input")
    fallback = Path.home() / ".mullm" / "uploads"
    dest_dir = comfy_input if comfy_input.exists() else fallback
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / filename
    dest.write_bytes(raw)
    return {"saved": True, "filename": filename, "path": str(dest), "size_kb": round(len(raw) / 1024, 1)}


@router.post("/api/3d/download")
async def download_3d_asset(request: Request):
    """Download a GLB from a remote URL and register metadata."""
    import httpx

    body = await request.json()
    url = str(body.get("url", ""))
    name = sanitize_asset_name(str(body.get("name", "model")))
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    async with httpx.AsyncClient(timeout=60.0, follow_redirects=True) as client:
        response = await client.get(url)
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"download failed: {response.status_code}")
    meta = {
        "source": body.get("source", "meshy"),
        "prompt": body.get("prompt", name),
        "asset_type": normalize_asset_type(body.get("asset_type") or body.get("category")),
        "category": normalize_asset_type(body.get("category") or body.get("asset_type")),
        "tags": [str(tag) for tag in body.get("tags", []) if isinstance(tag, str)] if isinstance(body.get("tags"), list) else [],
        "url": url,
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ai_generated": True,
        "pipeline": body.get("pipeline", "download"),
    }
    try:
        stored = get_asset_store().put_bytes(name, response.content, meta)
    except AssetStoreError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    path = Path(stored.path)
    return JSONResponse({"saved": stored.path, "asset": asset_record(path) if path.exists() else stored.__dict__})


@router.post("/api/3d/import-comfyui")
async def import_comfyui_3d_asset(request: Request):
    """Copy a ComfyUI output GLB into the muLLM 3D asset store."""
    import httpx

    from router.comfyui_api import comfyui_base_url

    body = await request.json()
    filename = str(body.get("filename") or "").strip()
    subfolder = str(body.get("subfolder") or "").strip()
    output_type = str(body.get("type") or "output").strip()
    name = sanitize_asset_name(str(body.get("name") or Path(filename).stem or "model"))
    if not re.fullmatch(r"[A-Za-z0-9_. -]{1,220}", filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    if subfolder and not re.fullmatch(r"[A-Za-z0-9_. /-]{1,220}", subfolder):
        raise HTTPException(status_code=400, detail="invalid subfolder")
    if output_type not in {"output", "input", "temp"}:
        raise HTTPException(status_code=400, detail="invalid ComfyUI file type")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(
            f"{comfyui_base_url()}/view",
            params={"filename": filename, "subfolder": subfolder, "type": output_type},
        )
    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"ComfyUI import failed: {response.status_code}")
    meta = {
        "source": body.get("source", "comfyui"),
        "prompt": body.get("prompt", name),
        "asset_type": normalize_asset_type(body.get("asset_type") or body.get("category")),
        "category": normalize_asset_type(body.get("category") or body.get("asset_type")),
        "tags": [str(tag) for tag in body.get("tags", []) if isinstance(tag, str)] if isinstance(body.get("tags"), list) else [],
        "date": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ai_generated": True,
        "pipeline": body.get("pipeline", "hunyuan3d-local"),
    }
    try:
        stored = get_asset_store().put_bytes(name, response.content, meta)
    except AssetStoreError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    path = Path(stored.path)
    return JSONResponse({"saved": stored.path, "asset": asset_record(path) if path.exists() else stored.__dict__})
