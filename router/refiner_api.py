"""Refiner capability endpoints for image, video, texture, and world workflows."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter

from router.config import settings
from router.world_providers import SanaWmProvider

router = APIRouter(prefix="/api/refiner", tags=["refiner"])


@router.get("/status")
async def refiner_status() -> dict[str, Any]:
    sana = SanaWmProvider()
    return {
        "available": sana.configured() or bool(settings.comfyui_base_url),
        "default_provider": "sana_wm" if sana.configured() else "comfyui",
        "providers": {
            "sana_wm": {
                "available": sana.configured(),
                "capabilities": [
                    "long_video_consistency",
                    "camera_path_consistency",
                    "world_lighting_consistency",
                    "scene_texture_continuity",
                ],
                "note": "SANA-WM uses a two-stage long-video refiner in the published pipeline; muLLM treats it as a reusable refinement capability when a local/custom endpoint is configured.",
            },
            "comfyui": {
                "available": bool(settings.comfyui_base_url),
                "capabilities": [
                    "image_upscale",
                    "img2img_texture_refine",
                    "video_upscale_or_stitch",
                    "lighting_reference_pass",
                ],
            },
        },
        "targets": ["image", "video", "texture", "lighting", "world"],
    }


@router.post("/plan")
async def refiner_plan(payload: dict) -> dict[str, Any]:
    target = str(payload.get("target", "image")).lower()
    quality = str(payload.get("quality", "balanced")).lower()
    provider = str(payload.get("provider", "auto")).lower()
    if provider == "auto":
        provider = "sana_wm" if SanaWmProvider().configured() and target in {"video", "world"} else "comfyui"
    steps = [
        {"step": "analyze", "description": f"Inspect {target} for blur, temporal inconsistency, lighting mismatch, and texture artifacts."},
        {"step": "refine", "provider": provider, "quality": quality},
        {"step": "verify", "description": "Run visual checks and preserve original asset unless refinement improves the selected metrics."},
    ]
    if target in {"texture", "lighting"}:
        steps.insert(1, {"step": "reference-lock", "description": "Preserve material identity, orientation, and existing UV/scene relationships."})
    return {"target": target, "provider": provider, "quality": quality, "steps": steps, "estimated_cost_usd": 0.0 if provider == "comfyui" else None}
