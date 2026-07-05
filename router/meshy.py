"""Meshy 3D generation adapter used by Scene/Studio routes."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from router.config import settings

MESHY_BASE_URL = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai").rstrip("/")

# Test-override hook: patch to force a key (""/value); None → dynamic.
_MESHY_KEY: str | None = None


class MeshyError(RuntimeError):
    """Raised when Meshy is unavailable or rejects a request."""


def api_key() -> str:
    if _MESHY_KEY is not None:
        return _MESHY_KEY
    # Resolve at call time: env first, then settings (loads .env / MULLM_ENV_FILE).
    return os.getenv("MESHY_API_KEY", "") or (getattr(settings, "meshy_api_key", None) or "")


def configured() -> bool:
    return bool(api_key())


def _headers() -> dict[str, str]:
    key = api_key()
    if not key:
        raise MeshyError("MESHY_API_KEY is required for Meshy generation")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def status() -> dict[str, Any]:
    return {
        "provider": "meshy",
        "configured": configured(),
        "base_url": MESHY_BASE_URL,
        "capabilities": ["text_to_3d", "image_to_3d", "refine", "pbr", "glb"],
    }


async def text_to_3d(
    prompt: str,
    style: str = "realistic",
    dry_run: bool = False,
    *,
    model_type: str = "standard",
    ai_model: str = "latest",
    topology: str = "quad",
    target_polycount: int | None = None,
    should_remesh: bool | None = None,
) -> dict[str, Any]:
    if not prompt.strip():
        raise MeshyError("prompt is required")
    payload: dict[str, Any] = {
        "mode": "preview",
        "prompt": prompt,
        "art_style": style,
        "model_type": model_type,
        "ai_model": ai_model,
    }
    if model_type != "lowpoly":
        payload["topology"] = topology
        if target_polycount:
            payload["target_polycount"] = target_polycount
        if should_remesh is not None:
            payload["should_remesh"] = should_remesh
    endpoint = f"{MESHY_BASE_URL}/openapi/v2/text-to-3d"
    if dry_run:
        return {"provider": "meshy", "submitted": False, "endpoint": endpoint, "json": payload}
    if not api_key():
        return {"error": "MESHY_API_KEY not configured"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=_headers(), json=payload)
    if response.status_code not in (200, 201, 202):
        return {"error": f"Meshy error ({response.status_code}): {response.text[:300]}"}
    data = response.json()
    task_id = data.get("result") or data.get("id") or data.get("task_id") or ""
    return {"provider": "meshy", "task_id": task_id, "status": "queued", "response": data}


def _image_to_data_uri(image_path: str) -> str:
    path = Path(image_path).expanduser()
    if not path.is_file():
        raise MeshyError(f"Image not found: {image_path}")
    resolved = path.resolve()
    allowed_roots = [Path(settings.cache_dir).resolve(), Path.cwd().resolve()]
    if not any(resolved == root or root in resolved.parents for root in allowed_roots):
        raise MeshyError("image_path must be under the current project or muLLM cache directory")
    ext = path.suffix.lower().lstrip(".")
    mime = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


async def image_to_3d(
    image_url: str = "",
    image_path: str = "",
    dry_run: bool = False,
    *,
    ai_model: str = "latest",
    enable_pbr: bool = True,
    should_texture: bool = True,
    should_remesh: bool = False,
    topology: str = "quad",
    target_polycount: int | None = None,
) -> dict[str, Any]:
    if image_path and not image_url:
        image_url = _image_to_data_uri(image_path)
    if not image_url:
        raise MeshyError("image_url or image_path is required")
    payload: dict[str, Any] = {
        "image_url": image_url,
        "ai_model": ai_model,
        "enable_pbr": enable_pbr,
        "should_texture": should_texture,
        "should_remesh": should_remesh,
    }
    if should_remesh:
        payload["topology"] = topology
        if target_polycount:
            payload["target_polycount"] = target_polycount
    endpoint = f"{MESHY_BASE_URL}/openapi/v1/image-to-3d"
    if dry_run:
        safe_payload = {**payload, "image_url": "<data-uri>" if image_url.startswith("data:") else image_url}
        return {"provider": "meshy", "submitted": False, "endpoint": endpoint, "json": safe_payload}
    if not api_key():
        return {"error": "MESHY_API_KEY not configured"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=_headers(), json=payload)
    if response.status_code not in (200, 201, 202):
        raise MeshyError(f"Meshy error ({response.status_code}): {response.text[:300]}")
    data = response.json()
    task_id = data.get("result") or data.get("id") or data.get("task_id") or ""
    return {"provider": "meshy", "task_id": task_id, "status": "queued", "response": data}


async def refine_task(
    preview_task_id: str,
    dry_run: bool = False,
    *,
    enable_pbr: bool = True,
    texture_prompt: str = "",
) -> dict[str, Any]:
    if not preview_task_id.strip():
        raise MeshyError("preview_task_id is required")
    payload: dict[str, Any] = {"mode": "refine", "preview_task_id": preview_task_id, "enable_pbr": enable_pbr}
    if texture_prompt.strip():
        payload["texture_prompt"] = texture_prompt.strip()
    endpoint = f"{MESHY_BASE_URL}/openapi/v2/text-to-3d"
    if dry_run:
        return {"provider": "meshy", "submitted": False, "endpoint": endpoint, "json": payload}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=_headers(), json=payload)
    if response.status_code not in (200, 201, 202):
        raise MeshyError(f"Meshy refine error ({response.status_code}): {response.text[:300]}")
    data = response.json()
    task_id = data.get("result") or data.get("id") or data.get("task_id") or ""
    return {"provider": "meshy", "task_id": task_id, "status": "queued", "step": "refine", "response": data}


async def remesh_task(
    input_task_id: str,
    target_polycount: int = 60_000,
    dry_run: bool = False,
    *,
    topology: str = "triangle",
) -> dict[str, Any]:
    """Submit a Meshy remesh task (e.g. to get under the 300k-face rigging limit)."""
    if not input_task_id.strip():
        raise MeshyError("input_task_id is required")
    payload: dict[str, Any] = {
        "input_task_id": input_task_id,
        "target_polycount": target_polycount,
        "topology": topology,
    }
    # NB: remesh lives under v1 (Meshy's own 400 hint says v2, but that 404s).
    endpoint = f"{MESHY_BASE_URL}/openapi/v1/remesh"
    if dry_run:
        return {"provider": "meshy", "submitted": False, "endpoint": endpoint, "json": payload}
    if not api_key():
        return {"error": "MESHY_API_KEY not configured"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=_headers(), json=payload)
    if response.status_code not in (200, 201, 202):
        raise MeshyError(f"Meshy remesh error ({response.status_code}): {response.text[:300]}")
    data = response.json()
    task_id = data.get("result") or data.get("id") or data.get("task_id") or ""
    return {"provider": "meshy", "task_id": task_id, "status": "queued", "response": data}


async def rig_task(
    input_task_id: str = "",
    model_url: str = "",
    dry_run: bool = False,
    *,
    height_meters: float | None = None,
) -> dict[str, Any]:
    """Submit a Meshy auto-rigging task (humanoid/biped models).

    Accepts either a completed Meshy task id or a public model URL.
    """
    if not input_task_id and not model_url:
        raise MeshyError("input_task_id or model_url is required")
    payload: dict[str, Any] = {}
    if input_task_id:
        payload["input_task_id"] = input_task_id
    if model_url:
        payload["model_url"] = model_url
    if height_meters:
        payload["height_meters"] = height_meters
    endpoint = f"{MESHY_BASE_URL}/openapi/v1/rigging"
    if dry_run:
        return {"provider": "meshy", "submitted": False, "endpoint": endpoint, "json": payload}
    if not api_key():
        return {"error": "MESHY_API_KEY not configured"}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(endpoint, headers=_headers(), json=payload)
    if response.status_code not in (200, 201, 202):
        raise MeshyError(f"Meshy rigging error ({response.status_code}): {response.text[:300]}")
    data = response.json()
    task_id = data.get("result") or data.get("id") or data.get("task_id") or ""
    return {"provider": "meshy", "task_id": task_id, "status": "queued", "response": data}


async def poll_task(task_id: str, endpoint: str = "text-to-3d", dry_run: bool = False) -> dict[str, Any]:
    if not task_id.strip():
        raise MeshyError("task_id is required")
    api_version = "v1" if ("image" in endpoint or endpoint in {"rigging", "animation", "remesh"}) else "v2"
    url = f"{MESHY_BASE_URL}/openapi/{api_version}/{endpoint}/{task_id}"
    if dry_run:
        return {"provider": "meshy", "submitted": False, "endpoint": url}
    if not api_key():
        return {"error": "MESHY_API_KEY not configured"}
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(url, headers=_headers())
    if response.status_code >= 400:
        raise MeshyError(f"Meshy status error ({response.status_code}): {response.text[:300]}")
    data = response.json()
    raw_status = data.get("status", "unknown")
    if raw_status == "FAILED":
        return {"provider": "meshy", "task_id": task_id, "error": "Task FAILED", "response": data}
    # Rigging/animation responses nest outputs under "result".
    result_obj = data.get("result") if isinstance(data.get("result"), dict) else {}
    model_urls = data.get("model_urls") or result_obj.get("model_urls") or {}
    if not model_urls:
        for k, v in {**result_obj, **data}.items():
            if isinstance(v, str) and v.startswith("http") and ".glb" in v:
                model_urls = {"glb": v}
                break
    return {
        "provider": "meshy",
        "task_id": task_id,
        "status": "complete" if raw_status == "SUCCEEDED" else raw_status.lower(),
        "model_urls": model_urls,
        "thumbnail_url": data.get("thumbnail_url", ""),
        "texture_urls": data.get("texture_urls", {}),
        "response": data,
    }
