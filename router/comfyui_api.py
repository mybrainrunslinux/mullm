"""ComfyUI integration routes for optional Studio/Scene workflows."""

from __future__ import annotations

import os
import re
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from router.config import settings

router = APIRouter(tags=["comfyui"])


def comfyui_base_url() -> str:
    return os.environ.get("COMFYUI_BASE_URL", settings.comfyui_base_url).rstrip("/")


def validate_comfyui_url(raw: str) -> str:
    value = raw.strip().rstrip("/")
    if not value:
        raise HTTPException(status_code=400, detail="base_url is required")
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", value):
        raise HTTPException(status_code=400, detail="base_url must be an http(s) URL")
    return value


async def _client_get(path: str, timeout: float = 10.0, params: dict[str, Any] | None = None) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.get(f"{comfyui_base_url()}{path}", params=params)


async def _client_post(path: str, payload: dict[str, Any], timeout: float = 30.0) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(f"{comfyui_base_url()}{path}", json=payload)


async def _client_post_files(
    path: str,
    *,
    data: dict[str, Any],
    files: dict[str, Any],
    timeout: float = 30.0,
) -> httpx.Response:
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.post(f"{comfyui_base_url()}{path}", data=data, files=files)


_PREFERRED_CHECKPOINTS = [
    "flux1-krea-dev_fp8_scaled.safetensors",
    "sd_xl_base_1.0.safetensors",
    "v1-5-pruned-emaonly.safetensors",
    "dreamshaper_8.safetensors",
    "dreamshaperXL_v21TurboDPMSDE.safetensors",
    "realisticVisionV60B1_v51VAE.safetensors",
]

_PREFERRED_HUNYUAN3D_MODELS = [
    "hunyuan3d-dit-v2-mini-fp16.safetensors",
    "hunyuan3d-dit-v2-0-fp16.safetensors",
    "hunyuan3d-dit-v2_fp16.safetensors",
    "hunyuan3d-dit-v2-mini.safetensors",
]

_PREFERRED_HUNYUAN3D_VAES = [
    "hunyuan3d-vae-v2-mini.safetensors",
]


def _object_info_choices(data: dict[str, Any], node_name: str, input_name: str) -> list[str]:
    raw = (
        data.get(node_name, {})
        .get("input", {})
        .get("required", {})
        .get(input_name, [[]])
    )
    if not raw or not isinstance(raw, list):
        return []
    choices = raw[0]
    if not isinstance(choices, list):
        return []
    return [str(item) for item in choices if str(item).strip()]


async def _best_checkpoint() -> str:
    """Return the best available checkpoint or GGUF model name.

    Checks CheckpointLoaderSimple first (safetensors), then falls back to
    UnetLoaderGGUF (Flux GGUF). Returns the GGUF filename so _is_flux_gguf()
    can detect it and use the correct workflow.
    """
    # Try traditional checkpoints first
    try:
        resp = await _client_get("/object_info/CheckpointLoaderSimple", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            available: list[str] = (
                data.get("CheckpointLoaderSimple", {})
                    .get("input", {}).get("required", {})
                    .get("ckpt_name", [[]])[0]
            )
            if available:
                for preferred in _PREFERRED_CHECKPOINTS:
                    if preferred in available:
                        return preferred
                return available[0]
    except Exception:
        pass
    # Fall back to GGUF models (Flux Schnell/Dev)
    try:
        resp = await _client_get("/object_info/UnetLoaderGGUF", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            gguf_models: list[str] = (
                data.get("UnetLoaderGGUF", {})
                    .get("input", {}).get("required", {})
                    .get("unet_name", [[]])[0]
            )
            for name in gguf_models:
                if "flux" in name.lower():
                    return name  # triggers _is_flux_gguf() → Flux workflow
            if gguf_models:
                return gguf_models[0]
    except Exception:
        pass
    raise HTTPException(
        status_code=503,
        detail="No checkpoints found in ComfyUI. Run scripts/fix_model_downloads.sh to download models.",
    )


async def _best_object_choice(node_name: str, input_name: str, preferred: list[str], timeout: float = 5.0) -> str:
    info = await _object_info_for(node_name, timeout=timeout)
    choices = _object_info_choices(info, node_name, input_name)
    if not choices:
        raise HTTPException(
            status_code=503,
            detail=f"ComfyUI node {node_name} has no available choices for {input_name}. Check model installation.",
        )
    for name in preferred:
        if name in choices:
            return name
    return choices[0]


async def _object_info_for(node_name: str, timeout: float = 5.0) -> dict[str, Any]:
    resp = await _client_get(f"/object_info/{node_name}", timeout=timeout)
    if resp.status_code >= 400:
        return {}
    try:
        data = resp.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


async def _require_comfyui_nodes(node_names: list[str]) -> None:
    missing: list[str] = []
    for node_name in node_names:
        info = await _object_info_for(node_name, timeout=3.0)
        if node_name not in info:
            missing.append(node_name)
    if missing:
        raise HTTPException(
            status_code=503,
            detail=(
                "Local ComfyUI 3D pipeline is missing required nodes: "
                + ", ".join(missing)
                + ". Update ComfyUI and enable the Hunyuan3D/3D nodes before using local mesh generation."
            ),
        )


def _asset_slug(value: str, fallback: str = "model") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip().lower()).strip("-._")
    return (slug or fallback)[:80]


def _normalize_asset_type(value: str | None) -> str:
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "auto": "",
        "sword": "weapon",
        "weapon": "weapon",
        "siege": "siege",
        "siege_engine": "siege",
        "character": "creature",
        "creature": "creature",
        "building": "building",
        "environment": "building",
        "prop": "prop",
    }
    return aliases.get(raw, raw if raw in {"weapon", "siege", "creature", "building", "prop"} else "")


def _asset_type_prompt_hint(asset_type: str) -> str:
    hints = {
        "weapon": (
            "single game-ready weapon prop, clear handle or hilt, clear sharp business end, "
            "straight readable silhouette, point facing up, no hand holding it, no duplicate weapons"
        ),
        "siege": (
            "single game-ready siege engine prop, readable mechanical frame, wheels or supports visible, "
            "front firing direction clear, no crew, no battlefield clutter"
        ),
        "creature": (
            "single full-body character or creature, neutral standing pose, arms and legs unobstructed, "
            "front view, complete body visible, no background characters"
        ),
        "building": (
            "single environment or building asset, complete structure visible, clean base, "
            "front three-quarter view, no surrounding city clutter"
        ),
        "prop": "single game-ready prop, complete object visible, clean silhouette, centered product render",
    }
    return hints.get(asset_type, "single centered object, complete object visible, clean silhouette")


async def _copy_output_image_to_input(image_name: str) -> str:
    """Make a generated output image usable by LoadImage.

    ComfyUI's LoadImage node validates against the input namespace. Studio pages
    often pass a filename returned by SaveImage in the output namespace, so copy
    it through ComfyUI's upload endpoint when possible.
    """
    clean_name = image_name.strip()
    if not re.fullmatch(r"[A-Za-z0-9_. -]{1,220}", clean_name):
        raise HTTPException(status_code=400, detail="invalid image filename")
    view_resp = await _client_get("/view", timeout=30.0, params={"filename": clean_name, "type": "output"})
    if view_resp.status_code == 404:
        return clean_name
    if view_resp.status_code >= 400:
        raise HTTPException(status_code=view_resp.status_code, detail=view_resp.text[:300])
    upload_resp = await _client_post_files(
        "/upload/image",
        data={"overwrite": "true", "type": "input"},
        files={"image": (clean_name, view_resp.content, view_resp.headers.get("content-type", "image/png"))},
        timeout=30.0,
    )
    if upload_resp.status_code >= 400:
        raise HTTPException(status_code=upload_resp.status_code, detail=upload_resp.text[:300])
    try:
        uploaded = upload_resp.json()
    except ValueError:
        uploaded = {}
    uploaded_name = str(uploaded.get("name") or clean_name).strip()
    return uploaded_name or clean_name


def _queue_texture_workflow(asset_name: str, style: str, seed: int) -> dict[str, Any]:
    pos_prompt = (
        f"masterpiece, best quality, {style}, seamless tileable texture sheet, "
        "UV unwrapped, PBR material, high detail, 4K, physically based rendering, "
        "clean edges, professional game asset texture"
    )
    neg_prompt = (
        "blurry, low quality, noise, artifacts, watermark, text, signature, jpeg artifacts, "
        "distorted, amateur, oversaturated, dark, muddy, border, frame, split, collage"
    )
    return {
        "prompt": {
            "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "sd_xl_base_1.0.safetensors"}},
            "2": {"class_type": "EmptyLatentImage", "inputs": {"width": 1024, "height": 1024, "batch_size": 1}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": pos_prompt, "clip": ["1", 1]}},
            "4": {"class_type": "CLIPTextEncode", "inputs": {"text": neg_prompt, "clip": ["1", 1]}},
            "5": {
                "class_type": "KSampler",
                "inputs": {
                    "seed": seed,
                    "steps": 30,
                    "cfg": 7.5,
                    "sampler_name": "dpmpp_2m",
                    "scheduler": "karras",
                    "denoise": 1.0,
                    "model": ["1", 0],
                    "positive": ["3", 0],
                    "negative": ["4", 0],
                    "latent_image": ["2", 0],
                },
            },
            "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
            "7": {
                "class_type": "SaveImage",
                "inputs": {"filename_prefix": f"mullm_texture_{asset_name}", "images": ["6", 0]},
            },
        }
    }


def _is_flux_gguf(ckpt_name: str) -> bool:
    return ckpt_name.endswith(".gguf") and "flux" in ckpt_name.lower()


# Requested model id → preferred checkpoint filenames (first available wins).
_MODEL_CHECKPOINTS: dict[str, list[str]] = {
    "sdxl-base":  ["sd_xl_base_1.0.safetensors"],
    "sdxl-turbo": ["sd_xl_turbo_1.0_fp16.safetensors"],
}


async def _queue_image_workflow(
    prompt: str, negative_prompt: str, seed: int, width: int, height: int,
    model: str | None = None,
    lora: str | None = None,
    lora_strength: float = 0.8,
) -> dict[str, Any]:
    ckpt = ""
    if model and model in _MODEL_CHECKPOINTS:
        try:
            ckpt = await _best_object_choice(
                "CheckpointLoaderSimple", "ckpt_name", _MODEL_CHECKPOINTS[model]
            )
        except Exception:
            ckpt = ""
    if not ckpt:
        ckpt = await _best_checkpoint()
    if _is_flux_gguf(ckpt):
        # Flux GGUF workflow (uses UnetLoaderGGUF + dual CLIP + FluxGuidance)
        return {"prompt": {
            "1": {"class_type": "UnetLoaderGGUF",   "inputs": {"unet_name": ckpt}},
            "2": {"class_type": "CLIPLoader",        "inputs": {"clip_name": "clip_l.safetensors",             "type": "flux"}},
            "3": {"class_type": "CLIPLoader",        "inputs": {"clip_name": "t5xxl_fp8_e4m3fn.safetensors",   "type": "flux"}},
            "4": {"class_type": "DualCLIPLoader",    "inputs": {"clip_name1": "clip_l.safetensors", "clip_name2": "t5xxl_fp8_e4m3fn.safetensors", "type": "flux"}},
            "5": {"class_type": "VAELoader",         "inputs": {"vae_name": "ae.safetensors"}},
            "6": {"class_type": "CLIPTextEncode",    "inputs": {"text": prompt,          "clip": ["4", 0]}},
            "7": {"class_type": "EmptyLatentImage",  "inputs": {"width": width, "height": height, "batch_size": 1}},
            "8": {"class_type": "FluxGuidance",      "inputs": {"guidance": 3.5, "conditioning": ["6", 0]}},
            "9": {"class_type": "KSampler",          "inputs": {
                "seed": seed, "steps": 20, "cfg": 1.0,
                "sampler_name": "euler", "scheduler": "simple", "denoise": 1.0,
                "model": ["1", 0], "positive": ["8", 0], "negative": ["6", 0], "latent_image": ["7", 0],
            }},
            "10": {"class_type": "VAEDecode",        "inputs": {"samples": ["9", 0], "vae": ["5", 0]}},
            "11": {"class_type": "SaveImage",        "inputs": {"filename_prefix": "mullm_image", "images": ["10", 0]}},
        }}
    # SDXL / DreamShaper / SD1.5 workflow, with optional LoRA stacking.
    is_turbo = "turbo" in ckpt.lower()
    model_ref, clip_ref = ["1", 0], ["1", 1]
    nodes: dict[str, Any] = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "EmptyLatentImage",       "inputs": {"width": width, "height": height, "batch_size": 1}},
    }
    if lora:
        lora_name = lora if lora.endswith(".safetensors") else f"{lora}.safetensors"
        nodes["10"] = {"class_type": "LoraLoader", "inputs": {
            "lora_name": lora_name,
            "strength_model": lora_strength, "strength_clip": lora_strength,
            "model": ["1", 0], "clip": ["1", 1],
        }}
        model_ref, clip_ref = ["10", 0], ["10", 1]
    nodes.update({
        "3": {"class_type": "CLIPTextEncode",         "inputs": {"text": prompt,          "clip": clip_ref}},
        "4": {"class_type": "CLIPTextEncode",         "inputs": {"text": negative_prompt, "clip": clip_ref}},
        "5": {"class_type": "KSampler",               "inputs": {
            # Turbo checkpoints are distilled for few-step low-CFG sampling.
            "seed": seed,
            "steps": 6 if is_turbo else 25,
            "cfg": 1.5 if is_turbo else 7.0,
            "sampler_name": "euler_ancestral" if is_turbo else "dpmpp_2m",
            "scheduler": "simple" if is_turbo else "karras",
            "denoise": 1.0,
            "model": model_ref, "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0],
        }},
        "6": {"class_type": "VAEDecode",              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",              "inputs": {"filename_prefix": "mullm_image", "images": ["6", 0]}},
    })
    return {"prompt": nodes}


async def _queue_hunyuan3d_image_workflow(image_name: str, asset_name: str, seed: int, resolution: int = 3072) -> dict[str, Any]:
    await _require_comfyui_nodes(
        [
            "LoadImage",
            "CLIPVisionLoader",
            "CLIPVisionEncode",
            "Hunyuan3Dv2Conditioning",
            "UNETLoader",
            "EmptyLatentHunyuan3Dv2",
            "KSampler",
            "VAELoader",
            "VAEDecodeHunyuan3D",
            "VoxelToMesh",
            "SaveGLB",
        ]
    )
    model_name = await _best_object_choice("UNETLoader", "unet_name", _PREFERRED_HUNYUAN3D_MODELS)
    vae_name = await _best_object_choice("VAELoader", "vae_name", _PREFERRED_HUNYUAN3D_VAES)
    clip_name = await _best_object_choice("CLIPVisionLoader", "clip_name", ["clip_vision_g.safetensors"])
    return {"prompt": {
        "1": {"class_type": "LoadImage", "inputs": {"image": image_name}},
        "2": {"class_type": "CLIPVisionLoader", "inputs": {"clip_name": clip_name}},
        "3": {"class_type": "CLIPVisionEncode", "inputs": {"clip_vision": ["2", 0], "image": ["1", 0], "crop": "center"}},
        "4": {"class_type": "Hunyuan3Dv2Conditioning", "inputs": {"clip_vision_output": ["3", 0]}},
        "5": {"class_type": "UNETLoader", "inputs": {"unet_name": model_name, "weight_dtype": "default"}},
        "6": {"class_type": "EmptyLatentHunyuan3Dv2", "inputs": {"resolution": resolution, "batch_size": 1}},
        "7": {"class_type": "KSampler", "inputs": {
            "seed": seed,
            "steps": 30,
            "cfg": 5.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["5", 0],
            "positive": ["4", 0],
            "negative": ["4", 1],
            "latent_image": ["6", 0],
        }},
        "8": {"class_type": "VAELoader", "inputs": {"vae_name": vae_name}},
        "9": {"class_type": "VAEDecodeHunyuan3D", "inputs": {
            "samples": ["7", 0],
            "vae": ["8", 0],
            "num_chunks": 8000,
            "octree_resolution": 256,
        }},
        "10": {"class_type": "VoxelToMesh", "inputs": {"voxel": ["9", 0], "algorithm": "surface net", "threshold": 0.6}},
        "11": {"class_type": "SaveGLB", "inputs": {"mesh": ["10", 0], "filename_prefix": f"mullm_3d/{asset_name}"}},
    }}


async def _queue_video_workflow(prompt: str, seed: int, frames: int) -> dict[str, Any]:
    ckpt = await _best_checkpoint()
    return {"prompt": {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": ckpt}},
        "2": {"class_type": "EmptyLatentImage",       "inputs": {"width": 768, "height": 432, "batch_size": max(1, min(frames, 32))}},
        "3": {"class_type": "CLIPTextEncode",         "inputs": {"text": prompt, "clip": ["1", 1]}},
        "4": {"class_type": "CLIPTextEncode",         "inputs": {"text": "low quality, flicker, watermark, text", "clip": ["1", 1]}},
        "5": {"class_type": "KSampler",               "inputs": {
            "seed": seed, "steps": 18, "cfg": 6.0,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
            "model": ["1", 0], "positive": ["3", 0], "negative": ["4", 0], "latent_image": ["2", 0],
        }},
        "6": {"class_type": "VAEDecode",              "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
        "7": {"class_type": "SaveImage",              "inputs": {"filename_prefix": "mullm_video_frame", "images": ["6", 0]}},
    }}


@router.get("/api/comfyui/status")
async def comfyui_status():
    base = comfyui_base_url()
    try:
        resp = await _client_get("/system_stats", timeout=2.0)
        payload: dict[str, Any] = {}
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except ValueError:
                payload = {}
        return {
            "running": resp.status_code == 200,
            "base_url": base,
            "system_stats": payload,
            "install_hint": "Install ComfyUI, start it on port 8188 or 8189, then enable local image/3D modules.",
        }
    except Exception:
        return {
            "running": False,
            "base_url": base,
            "install_hint": "Install ComfyUI, start it on port 8188 or 8189, then enable local image/3D modules.",
        }


@router.get("/api/comfyui/models")
async def comfyui_models():
    """Return ComfyUI model inventory relevant to muLLM Studio setup."""
    base = comfyui_base_url()
    try:
        checkpoint_info = await _object_info_for("CheckpointLoaderSimple")
        lora_info = await _object_info_for("LoraLoader")
        vae_info = await _object_info_for("VAELoader")
        unet_info = await _object_info_for("UNETLoader")
        gguf_info = await _object_info_for("UnetLoaderGGUF")

        checkpoints = _object_info_choices(checkpoint_info, "CheckpointLoaderSimple", "ckpt_name")
        loras = _object_info_choices(lora_info, "LoraLoader", "lora_name")
        vaes = _object_info_choices(vae_info, "VAELoader", "vae_name")
        diffusion_models = _object_info_choices(unet_info, "UNETLoader", "unet_name")
        gguf_models = _object_info_choices(gguf_info, "UnetLoaderGGUF", "unet_name")

        preferred_checkpoint = ""
        for name in _PREFERRED_CHECKPOINTS:
            if name in checkpoints:
                preferred_checkpoint = name
                break
        if not preferred_checkpoint and checkpoints:
            preferred_checkpoint = checkpoints[0]

        return {
            "running": True,
            "base_url": base,
            "checkpoints": checkpoints,
            "loras": loras,
            "vaes": vaes,
            "diffusion_models": diffusion_models,
            "gguf_models": gguf_models,
            "preferred_checkpoint": preferred_checkpoint,
            "counts": {
                "checkpoints": len(checkpoints),
                "loras": len(loras),
                "vaes": len(vaes),
                "diffusion_models": len(diffusion_models),
                "gguf_models": len(gguf_models),
            },
        }
    except Exception as exc:
        return {
            "running": False,
            "base_url": base,
            "error": str(exc),
            "checkpoints": [],
            "loras": [],
            "vaes": [],
            "diffusion_models": [],
            "gguf_models": [],
            "preferred_checkpoint": "",
            "counts": {
                "checkpoints": 0,
                "loras": 0,
                "vaes": 0,
                "diffusion_models": 0,
                "gguf_models": 0,
            },
        }


@router.post("/api/comfyui/config")
async def comfyui_config_save(payload: dict):
    raw = validate_comfyui_url(str(payload.get("base_url", "")))
    from router.main import _write_toml_section_values

    _write_toml_section_values("studio", {"comfyui_base_url": raw})
    os.environ["COMFYUI_BASE_URL"] = raw
    return {"saved": True, "base_url": raw}


@router.get("/api/comfyui/history/{prompt_id}")
async def comfyui_history(prompt_id: str):
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", prompt_id):
        raise HTTPException(status_code=400, detail="invalid prompt_id")
    resp = await _client_get(f"/history/{prompt_id}", timeout=10.0)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    return resp.json()


@router.post("/api/comfyui/prompt")
async def comfyui_prompt(request: Request):
    payload = await request.json()
    if not isinstance(payload, dict) or "prompt" not in payload:
        raise HTTPException(status_code=400, detail="ComfyUI prompt payload required")
    resp = await _client_post("/prompt", payload, timeout=30.0)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    return resp.json()


@router.get("/api/comfyui/view")
async def comfyui_view(filename: str | None = None, subfolder: str = "", type: str = "output"):
    if not filename:
        return JSONResponse(
            {
                "status": "requires_filename",
                "detail": "Pass filename, optional subfolder, and type=output|input|temp.",
            }
        )
    if not re.fullmatch(r"[A-Za-z0-9_. -]{1,220}", filename):
        raise HTTPException(status_code=400, detail="invalid filename")
    params = {"filename": filename, "subfolder": subfolder, "type": type}
    resp = await _client_get("/view", timeout=30.0, params=params)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    return Response(
        content=resp.content,
        media_type=resp.headers.get("content-type", "application/octet-stream"),
    )


@router.post("/api/texture")
async def texture_asset(request: Request):
    import time

    body = await request.json()
    asset_name = str(body.get("asset_name", "")).strip()
    style = str(body.get("style", "realistic PBR texture, high detail")).strip()
    if not asset_name:
        raise HTTPException(status_code=400, detail="asset_name required")
    seed = int(body.get("seed") or int(time.time()) % 2**32)
    workflow = _queue_texture_workflow(asset_name, style, seed)
    resp = await _client_post("/prompt", workflow, timeout=30.0)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    data = resp.json()
    prompt_id = data.get("prompt_id", "")
    return {"job_id": prompt_id, "status": "queued", "poll_url": f"/api/comfyui/history/{prompt_id}"}


# /api/image/generate is handled by router/image_api.py (supports model routing)


@router.post("/api/video/generate")
@router.post("/api/video")
async def video_generate(request: Request):
    import time

    body = await request.json()
    prompt = str(body.get("prompt") or body.get("content") or "").strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="prompt required")
    provider = str(body.get("provider") or body.get("backend") or "comfyui").strip().lower()
    if provider not in {"", "local", "comfyui"}:
        raise HTTPException(
            status_code=412,
            detail=f"Video provider '{provider}' is not configured. Add its API/base URL in setup or use local ComfyUI.",
        )
    seed = int(body.get("seed") or int(time.time()) % 2**32)
    frames = max(1, min(int(body.get("frames") or 16), 32))
    workflow = await _queue_video_workflow(prompt, seed, frames)
    resp = await _client_post("/prompt", workflow, timeout=30.0)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    prompt_id = resp.json().get("prompt_id", "")
    return {"job_id": prompt_id, "status": "queued", "poll_url": f"/api/comfyui/history/{prompt_id}", "provider": "comfyui"}


@router.post("/api/3d/comfyui")
async def comfyui_3d_generate(request: Request):
    """Queue local ComfyUI 3D generation.

    Hunyuan3D is image-to-model. For a text-only request, queue a local
    reference-image job and return the exact next step instead of failing with a
    missing route or pretending the GLB has already been created.
    """
    import time

    body = await request.json()
    prompt = str(body.get("prompt") or body.get("content") or "").strip()
    style = str(body.get("style") or "game-ready 3D asset, clean silhouette").strip()
    name = _asset_slug(str(body.get("name") or body.get("asset_name") or prompt or "model"))
    asset_type = _normalize_asset_type(body.get("asset_type") or body.get("category"))
    image_name = str(body.get("image") or body.get("image_name") or body.get("filename") or "").strip()
    seed = int(body.get("seed") or int(time.time()) % 2**32)

    if image_name:
        input_image_name = await _copy_output_image_to_input(image_name)
        workflow = await _queue_hunyuan3d_image_workflow(input_image_name, name, seed)
        resp = await _client_post("/prompt", workflow, timeout=30.0)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
        prompt_id = resp.json().get("prompt_id", "")
        return {
            "job_id": prompt_id,
            "prompt_id": prompt_id,
            "status": "queued",
            "stage": "mesh",
            "provider": "comfyui",
            "asset_type": asset_type,
            "poll_url": f"/api/comfyui/history/{prompt_id}",
            "expected_output": f"mullm_3d/{name}_*.glb",
        }

    if not prompt:
        raise HTTPException(status_code=400, detail="prompt or image filename required")

    ref_prompt = (
        f"{prompt}, {style}, {_asset_type_prompt_hint(asset_type)}, orthographic product render, "
        "plain background, complete object visible, sharp silhouette, game asset concept"
    )
    negative = (
        "cropped, multiple objects, hands, person, watermark, text, logo, blurry, "
        "low quality, distorted geometry, cluttered background"
    )
    workflow = await _queue_image_workflow(ref_prompt, negative, seed, 1024, 1024)
    # Override the default image prefix so the user can identify the reference
    # image in ComfyUI's output/input browser before queueing Hunyuan3D.
    prompt_graph = workflow.get("prompt", {})
    if isinstance(prompt_graph, dict):
        save_node = max(prompt_graph.keys(), key=lambda key: int(key) if str(key).isdigit() else -1)
        node = prompt_graph.get(save_node, {})
        inputs = node.get("inputs", {}) if isinstance(node, dict) else {}
        if isinstance(inputs, dict) and node.get("class_type") == "SaveImage":
            inputs["filename_prefix"] = f"mullm_{name}_ref"

    resp = await _client_post("/prompt", workflow, timeout=30.0)
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    prompt_id = resp.json().get("prompt_id", "")
    return {
        "job_id": prompt_id,
        "prompt_id": prompt_id,
        "status": "queued",
        "stage": "reference_image",
        "provider": "comfyui",
        "asset_type": asset_type,
        "prompt_hint": _asset_type_prompt_hint(asset_type),
        "poll_url": f"/api/comfyui/history/{prompt_id}",
        "next_step": "After the reference image completes, submit its filename to /api/3d/comfyui as image or image_name to queue Hunyuan3D GLB generation.",
        "reference_prefix": f"mullm_{name}_ref",
    }


@router.get("/api/video")
async def video_status():
    status = await comfyui_status()
    return {
        "ok": True,
        "providers": {
            "comfyui": {
                "configured": bool(status.get("running")),
                "status": "ready" if status.get("running") else "offline",
                "base_url": status.get("base_url"),
            }
        },
        "endpoints": [
            "/api/video",
            "/api/video/generate",
            "/api/video/{job_id}",
            "/api/video/list",
            "/api/video/stitch",
            "/api/video/upscale",
        ],
    }


@router.get("/api/video/list")
async def video_list():
    """Return locally known generated videos.

    The core package can always return a stable empty gallery shape. Deployment
    adapters may extend this with actual media indexing.
    """
    return {"videos": [], "items": [], "count": 0}


@router.get("/api/video/{job_id}")
async def video_job_status(job_id: str):
    if not job_id.strip():
        raise HTTPException(status_code=400, detail="job_id required")
    resp = await _client_get(f"/history/{job_id}", timeout=5.0)
    if resp.status_code == 404:
        raise HTTPException(status_code=404, detail="video job not found")
    if resp.status_code >= 400:
        raise HTTPException(status_code=resp.status_code, detail=resp.text[:300])
    data = resp.json()
    record = data.get(job_id, {}) if isinstance(data, dict) else {}
    outputs = record.get("outputs") or {}
    done = bool(outputs)
    return {
        "job_id": job_id,
        "status": "done" if done else "running",
        "provider": "comfyui",
        "history": record,
    }


@router.post("/api/video/stitch")
async def video_stitch(request: Request):
    body = await request.json()
    clips = body.get("clips") or []
    if not isinstance(clips, list) or not clips:
        raise HTTPException(status_code=400, detail="clips are required")
    if len(clips) == 1 and isinstance(clips[0], dict) and clips[0].get("url"):
        return {"ok": True, "status": "done", "output_url": clips[0]["url"], "clips": 1}
    raise HTTPException(
        status_code=501,
        detail="Video stitching requires the ffmpeg/movie pipeline adapter. Enable the Studio video extra or export a single clip.",
    )


@router.post("/api/video/upscale")
async def video_upscale(request: Request):
    body = await request.json()
    url = str(body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url required")
    raise HTTPException(
        status_code=501,
        detail="Video upscale requires the Real-ESRGAN video adapter. Enable the Studio video extra before upscaling.",
    )
