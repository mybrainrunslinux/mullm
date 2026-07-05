"""Meshy 3D generation adapter used by Scene/Studio routes."""

from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

import httpx

from router.config import settings

MESHY_BASE_URL = os.getenv("MESHY_BASE_URL", "https://api.meshy.ai").rstrip("/")

_MESHY_KEY: str = os.getenv("MESHY_API_KEY", "")


class MeshyError(RuntimeError):
    """Raised when Meshy is unavailable or rejects a request."""


def api_key() -> str:
    return _MESHY_KEY


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


async def poll_task(task_id: str, endpoint: str = "text-to-3d", dry_run: bool = False) -> dict[str, Any]:
    if not task_id.strip():
        raise MeshyError("task_id is required")
    api_version = "v1" if "image" in endpoint else "v2"
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
    return {
        "provider": "meshy",
        "task_id": task_id,
        "status": "complete" if raw_status == "SUCCEEDED" else raw_status.lower(),
        "model_urls": data.get("model_urls", {}),
        "thumbnail_url": data.get("thumbnail_url", ""),
        "texture_urls": data.get("texture_urls", {}),
        "response": data,
    }
