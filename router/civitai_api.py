"""CivitAI LoRA discovery helpers.

Downloads stay explicit; this module only verifies credentials and discovers
candidate model metadata for Studio setup.
"""

from __future__ import annotations

import os
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query

from router.config import settings

router = APIRouter(prefix="/api/civitai", tags=["civitai"])

CIVITAI_BASE_URL = "https://civitai.com/api/v1"


def civitai_key() -> str | None:
    return settings.civitai_api_key or os.getenv("CIVITAI_API_KEY") or os.getenv("CIVIT_AI_API_KEY")


def civitai_headers() -> dict[str, str]:
    key = civitai_key()
    return {"Authorization": f"Bearer {key}"} if key else {}


@router.get("/status")
async def civitai_status() -> dict[str, Any]:
    return {
        "configured": bool(civitai_key()),
        "base_url": CIVITAI_BASE_URL,
        "downloads_explicit": True,
        "supported": ["LoRA metadata search", "profile recommendations"],
    }


@router.get("/loras/search")
async def search_loras(
    q: str = Query("SDXL realism texture", min_length=2, max_length=120),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, Any]:
    params = {
        "types": "LORA",
        "query": q,
        "limit": str(limit),
        "sort": "Highest Rated",
    }
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=True) as client:
        try:
            resp = await client.get(f"{CIVITAI_BASE_URL}/models", params=params, headers=civitai_headers())
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise HTTPException(status_code=502, detail=f"CivitAI request failed: {exc}") from exc
    data = resp.json()
    items = data.get("items", []) if isinstance(data, dict) else []
    results = []
    for item in items[:limit]:
        versions = item.get("modelVersions") or []
        latest = versions[0] if versions else {}
        results.append(
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "type": item.get("type"),
                "nsfw": item.get("nsfw"),
                "creator": (item.get("creator") or {}).get("username"),
                "version": latest.get("name"),
                "base_model": latest.get("baseModel"),
                "download_url_present": bool(latest.get("downloadUrl")),
            }
        )
    return {"query": q, "count": len(results), "items": results}

