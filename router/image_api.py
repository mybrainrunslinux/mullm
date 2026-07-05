"""Image generation API: ComfyUI (local), OpenAI GPT-Image-1/2, Google Gemini Nano Banana."""

from __future__ import annotations

import base64
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse

from router.config import settings

router = APIRouter(tags=["image"])

# In-memory job store for cloud-generated images
_JOBS: dict[str, dict[str, Any]] = {}


def _image_dir() -> Path:
    d = Path.home() / ".mullm" / "generated_images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _parse_size(size_str: str | None, default_w: int = 1024, default_h: int = 1024) -> tuple[int, int]:
    if size_str and "x" in str(size_str):
        parts = str(size_str).split("x", 1)
        try:
            return int(parts[0]), int(parts[1])
        except ValueError:
            pass
    return default_w, default_h


def _api_key(provider: str) -> str:
    env_map = {"openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}
    setting_map = {"openai": "openai_api_key", "google": "google_api_key", "anthropic": "anthropic_api_key"}
    key = getattr(settings, setting_map.get(provider, ""), "") or os.getenv(env_map.get(provider, ""), "")
    return key if key and "CHANGEME" not in key else ""


# ── OpenAI image models ─────────────────────────────────────────────────────
# gpt-image-1, gpt-image-1-mini, gpt-image-1.5, gpt-image-2 → always b64_json
# dall-e-3 → b64_json requested explicitly
_OPENAI_IMAGE_MODELS = {"gpt-image-1", "gpt-image-1-mini", "gpt-image-1.5", "gpt-image-2", "dall-e-3"}

# dalle-3 only supports specific fixed sizes
_DALLE3_SIZES = {"1024x1024", "1792x1024", "1024x1792"}


async def _generate_openai(prompt: str, model: str, size: str) -> dict[str, Any]:
    key = _api_key("openai")
    if not key:
        raise HTTPException(status_code=412, detail="OpenAI API key not configured — add OPENAI_API_KEY")

    payload: dict[str, Any] = {"model": model, "prompt": prompt, "n": 1}
    if model == "dall-e-3":
        payload["size"] = size if size in _DALLE3_SIZES else "1024x1024"
        payload["response_format"] = "b64_json"
    else:
        payload["size"] = size  # gpt-image-* support arbitrary WxH

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                json=payload,
            )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OpenAI request failed: {exc}") from exc

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"OpenAI {resp.status_code}: {resp.text[:300]}")

    item = resp.json()["data"][0]
    b64 = item.get("b64_json", "")
    if not b64:
        raise HTTPException(status_code=502, detail="OpenAI returned no image data")

    job_id = str(uuid.uuid4())
    filename = f"openai_{job_id}.png"
    (_image_dir() / filename).write_bytes(base64.b64decode(b64))
    output_url = f"/api/image/file/{filename}"

    _JOBS[job_id] = {
        "job_id": job_id, "status": "done", "output_url": output_url,
        "provider": "openai", "model": model, "created_at": time.time(),
    }
    return {"job_id": job_id, "status": "queued", "provider": "openai", "poll_url": f"/api/image/{job_id}"}


# ── Google Gemini image models (Nano Banana + Imagen) ──────────────────────
_GOOGLE_IMAGE_MODELS = {
    "gemini-2.5-flash-image",  # Nano Banana
    "gemini-3-pro-image",      # Nano Banana Pro
    "gemini-3.1-flash-image",  # Nano Banana 2
    "imagen-4",
    "imagen-3",
}

# Imagen model IDs on the predict endpoint
_IMAGEN_API_IDS = {
    "imagen-4": "imagen-4.0-generate-001",
    "imagen-3": "imagen-3.0-generate-002",
}


async def _generate_google(prompt: str, model: str) -> dict[str, Any]:
    key = _api_key("google")
    if not key:
        raise HTTPException(status_code=412, detail="Google API key not configured — add GOOGLE_API_KEY")

    img_bytes: bytes | None = None

    if model in _IMAGEN_API_IDS:
        model_id = _IMAGEN_API_IDS[model]
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_id}:predict?key={key}"
        payload = {"instances": [{"prompt": prompt}], "parameters": {"sampleCount": 1}}
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Google request failed: {exc}") from exc
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Google {resp.status_code}: {resp.text[:300]}")
        preds = resp.json().get("predictions", [])
        if preds:
            b64 = preds[0].get("bytesBase64Encoded", "")
            if b64:
                img_bytes = base64.b64decode(b64)
    else:
        # Gemini native image generation via generateContent + responseModalities
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        }
        try:
            async with httpx.AsyncClient(timeout=120.0) as client:
                resp = await client.post(url, json=payload)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"Google request failed: {exc}") from exc
        if resp.status_code != 200:
            raise HTTPException(status_code=502, detail=f"Google {resp.status_code}: {resp.text[:300]}")
        for part in resp.json().get("candidates", [{}])[0].get("content", {}).get("parts", []):
            inline = part.get("inlineData", {})
            if inline.get("mimeType", "").startswith("image/"):
                img_bytes = base64.b64decode(inline["data"])
                break

    if not img_bytes:
        raise HTTPException(status_code=502, detail="Google returned no image data")

    job_id = str(uuid.uuid4())
    filename = f"google_{job_id}.png"
    (_image_dir() / filename).write_bytes(img_bytes)
    output_url = f"/api/image/file/{filename}"

    _JOBS[job_id] = {
        "job_id": job_id, "status": "done", "output_url": output_url,
        "provider": "google", "model": model, "created_at": time.time(),
    }
    return {"job_id": job_id, "status": "queued", "provider": "google", "poll_url": f"/api/image/{job_id}"}


# ── ComfyUI local generation ────────────────────────────────────────────────

async def _generate_comfyui(
    prompt: str, negative: str, seed: int, width: int, height: int,
    model: str | None = None, lora: str | None = None, lora_strength: float = 0.8,
) -> dict[str, Any]:
    from router.comfyui_api import _queue_image_workflow, comfyui_base_url
    workflow = await _queue_image_workflow(
        prompt, negative, seed, width, height,
        model=model, lora=lora, lora_strength=lora_strength,
    )
    base_url = comfyui_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(f"{base_url}/prompt", json=workflow)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"ComfyUI not reachable: {exc}") from exc
    if resp.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"ComfyUI error: {resp.text[:300]}")
    prompt_id = resp.json().get("prompt_id", "")
    return {
        "job_id": prompt_id, "status": "queued",
        "provider": "comfyui", "poll_url": f"/api/image/{prompt_id}",
    }


# ── Main generate endpoint ──────────────────────────────────────────────────
# NOTE: /api/image/list, /api/image/backends, /api/image/file/{f} are defined
# ABOVE the /{job_id} catch-all so FastAPI matches them first.

@router.post("/api/image/generate")
async def image_generate(request: Request):
    body = await request.json()
    prompt = str(body.get("prompt") or body.get("content") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")

    model = str(body.get("model") or "sdxl-turbo").strip()
    size_str = str(body.get("size") or "1024x1024")
    width, height = _parse_size(size_str)
    width  = max(256, min(int(body.get("width")  or width),  2048))
    height = max(256, min(int(body.get("height") or height), 2048))
    negative = str(body.get("negative") or body.get("negative_prompt") or "low quality, blurry, watermark, text").strip()
    seed = int(body.get("seed") or int(time.time()) % 2**32)

    if model in _OPENAI_IMAGE_MODELS:
        return await _generate_openai(prompt, model, size_str)
    if model in _GOOGLE_IMAGE_MODELS:
        return await _generate_google(prompt, model)
    # sdxl-turbo, sdxl-base, or anything unrecognised → ComfyUI
    lora = str(body.get("lora") or "").strip() or None
    try:
        lora_strength = max(0.0, min(float(body.get("lora_strength") or 0.8), 2.0))
    except (TypeError, ValueError):
        lora_strength = 0.8
    return await _generate_comfyui(
        prompt, negative, seed, width, height,
        model=model, lora=lora, lora_strength=lora_strength,
    )


# ── Gallery (must come before /{job_id}) ───────────────────────────────────

@router.get("/api/image/list")
async def image_list():
    images: list[dict] = []
    seen_urls: set[str] = set()

    for job in sorted(_JOBS.values(), key=lambda j: j.get("created_at", 0), reverse=True):
        if job.get("status") == "done" and job.get("output_url"):
            url = job["output_url"]
            if url not in seen_urls:
                seen_urls.add(url)
                images.append({
                    "url": url, "model": job.get("model", ""),
                    "provider": job.get("provider", ""), "created_at": job.get("created_at", 0),
                })

    try:
        for f in sorted(_image_dir().iterdir(), key=lambda p: p.stat().st_mtime, reverse=True)[:50]:
            if f.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
                continue
            url = f"/api/image/file/{f.name}"
            if url not in seen_urls:
                seen_urls.add(url)
                images.append({
                    "url": url, "filename": f.name,
                    "provider": "openai" if f.name.startswith("openai_") else "google" if f.name.startswith("google_") else "comfyui",
                    "created_at": f.stat().st_mtime,
                })
    except Exception:
        pass

    return {"images": images}


# ── Backends (must come before /{job_id}) ──────────────────────────────────

@router.get("/api/image/backends")
async def image_backends():
    from router.comfyui_api import comfyui_base_url
    comfyui_running = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{comfyui_base_url()}/system_stats")
            comfyui_running = r.status_code == 200
    except Exception:
        pass

    okey = bool(_api_key("openai"))
    gkey = bool(_api_key("google"))

    return {
        "backends": [
            {
                "id": "comfyui", "name": "ComfyUI (local)", "running": comfyui_running,
                "models": ["sdxl-turbo", "sdxl-base"], "free": True,
            },
            {
                "id": "openai", "name": "OpenAI", "running": okey,
                "models": ["gpt-image-2", "gpt-image-1.5", "gpt-image-1", "gpt-image-1-mini", "dall-e-3"],
                "free": False,
            },
            {
                "id": "google", "name": "Google Gemini", "running": gkey,
                "models": ["gemini-2.5-flash-image", "gemini-3-pro-image", "gemini-3.1-flash-image", "imagen-4"],
                "free": False,
            },
        ]
    }


# ── Video backends (must come before /{job_id}) ────────────────────────────

@router.get("/api/video/backends")
async def video_backends():
    from router.comfyui_api import comfyui_base_url
    comfyui_running = False
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{comfyui_base_url()}/system_stats")
            comfyui_running = r.status_code == 200
    except Exception:
        pass
    return {
        "backends": [
            {
                "id": "comfyui", "name": "ComfyUI (local)", "running": comfyui_running,
                "models": ["sdxl-frames"], "free": True,
            }
        ]
    }


# ── Provider status ─────────────────────────────────────────────────────────

@router.get("/api/providers/status")
async def providers_status():
    return {
        "openai":    bool(_api_key("openai")),
        "google":    bool(_api_key("google")),
        "anthropic": bool(_api_key("anthropic")),
        "meshy":     bool(settings.meshy_api_key or os.getenv("MESHY_API_KEY", "")),
    }


# ── Serve saved image files ─────────────────────────────────────────────────

@router.get("/api/image/file/{filename}")
async def image_file(filename: str):
    if not re.fullmatch(r"[a-zA-Z0-9_.\-]{1,160}", filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    path = _image_dir() / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="not found")
    suffix = path.suffix.lower()
    media_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp"}
    return FileResponse(str(path), media_type=media_map.get(suffix, "image/png"))


# ── Job status polling (catch-all — MUST come last) ─────────────────────────

@router.get("/api/image/{job_id}")
async def image_job_status(job_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_\-]{8,160}", job_id):
        raise HTTPException(status_code=400, detail="invalid job_id")

    # Cloud jobs stored in memory
    if job_id in _JOBS:
        return _JOBS[job_id]

    # ComfyUI jobs — proxy to history
    from router.comfyui_api import comfyui_base_url
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{comfyui_base_url()}/history/{job_id}")
            if resp.status_code == 200:
                history = resp.json()
                if job_id in history:
                    job_data = history[job_id]
                    for node_out in job_data.get("outputs", {}).values():
                        imgs = node_out.get("images", [])
                        if imgs:
                            img = imgs[0]
                            fname = img.get("filename", "")
                            sub = img.get("subfolder", "")
                            view_url = f"/api/comfyui/view?filename={fname}&subfolder={sub}&type=output"
                            return {"job_id": job_id, "status": "done", "output_url": view_url, "provider": "comfyui"}
                    return {"job_id": job_id, "status": "running", "provider": "comfyui"}
                return {"job_id": job_id, "status": "running", "provider": "comfyui"}
    except Exception:
        pass

    return {"job_id": job_id, "status": "unknown"}
