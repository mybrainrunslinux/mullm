"""Studio asset-pack installer and ComfyUI profile manifest."""

from __future__ import annotations

import importlib.util
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import httpx

STUDIO_ROOT = Path.home() / ".mullm" / "studio"

COMFYUI_PROFILES: dict[str, Any] = {
    "version": "1.0.0",
    "updated_at": "2026-05-16",
    "profiles": [
        {
            "id": "sdxl_realism_texture",
            "name": "SDXL Realism Texture",
            "kind": "image",
            "model_family": "sdxl",
            "checkpoint": "Juggernaut XL or equivalent SDXL realism checkpoint",
            "loras": [
                {"name": "Touch of Realism", "strength": 0.35, "required": False},
                {"name": "detail/texture refinement LoRA", "strength": 0.2, "required": False},
                {"name": "lighting/cinematic LoRA", "strength": 0.15, "required": False},
            ],
            "notes": "Conservative default for generated texture passes. LoRAs are optional because exact filenames vary by source.",
        },
        {
            "id": "wan22_video_fast_realism",
            "name": "WAN 2.2 Fast Realism",
            "kind": "video",
            "model_family": "wan2.2",
            "loras": [
                {"name": "PUCA V1", "strength": 0.5, "required": False},
                {"name": "CausVid or speed/quality LoRA", "strength": 0.35, "required": False},
            ],
            "notes": "Low-VRAM/faster preview profile. Use as an optional profile, not a forced default.",
        },
        {
            "id": "wan22_video_cinematic",
            "name": "WAN 2.2 Cinematic",
            "kind": "video",
            "model_family": "wan2.2",
            "loras": [
                {"name": "cinematic realism LoRA", "strength": 0.35, "required": False},
                {"name": "camera-motion LoRA", "strength": 0.25, "required": False},
            ],
            "notes": "Higher-quality local or cloud-assisted profile for game trailers and hero clips.",
        },
    ],
}


def install_builtin_asset_pack(root: Path | None = None) -> dict[str, Any]:
    root = root or STUDIO_ROOT
    root.mkdir(parents=True, exist_ok=True)
    comfy_dir = root / "comfyui"
    workflows_dir = comfy_dir / "workflows"
    lora_dir = comfy_dir / "loras"
    workflows_dir.mkdir(parents=True, exist_ok=True)
    lora_dir.mkdir(parents=True, exist_ok=True)

    profiles_path = comfy_dir / "profiles.json"
    profiles_path.write_text(json.dumps(COMFYUI_PROFILES, indent=2) + "\n", encoding="utf-8")

    readme_path = root / "README.md"
    readme_path.write_text(
        "# muLLM Studio Asset Pack\n\n"
        "This directory is managed by muLLM Studio setup. The first pack installs workflow/profile "
        "metadata only; model and LoRA downloads remain explicit because filenames, licenses, and "
        "VRAM targets vary by user.\n\n"
        "- ComfyUI profiles: `comfyui/profiles.json`\n"
        "- Put local workflow JSON files under `comfyui/workflows/`.\n"
        "- Put LoRA files or symlinks under `comfyui/loras/`.\n",
        encoding="utf-8",
    )
    return {
        "root": str(root),
        "profiles": str(profiles_path),
        "workflows": str(workflows_dir),
        "loras": str(lora_dir),
        "profile_count": len(COMFYUI_PROFILES["profiles"]),
    }


async def install_from_manifest_url(url: str, root: Path | None = None) -> dict[str, Any]:
    root = root or STUDIO_ROOT
    if not url.startswith(("https://", "http://127.0.0.1:", "http://localhost:")):
        raise ValueError("Studio manifest URL must be HTTPS or localhost")
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    root.mkdir(parents=True, exist_ok=True)
    manifest_path = root / "remote-manifest.json"
    manifest_path.write_text(resp.text, encoding="utf-8")
    return {"root": str(root), "manifest": str(manifest_path), "bytes": len(resp.content)}


def _espeak_available() -> bool:
    return shutil.which("espeak-ng") is not None


def _install_espeak_system() -> str:
    """Best-effort espeak-ng install via the system package manager."""
    if _espeak_available():
        return "already_installed"
    system = platform.system()
    if system == "Linux":
        if shutil.which("dnf"):
            subprocess.run(["sudo", "dnf", "install", "-y", "espeak-ng", "espeak-ng-devel"], check=False)
        elif shutil.which("apt-get"):
            subprocess.run(["sudo", "apt-get", "install", "-y", "espeak-ng", "libespeak-ng-dev"], check=False)
        elif shutil.which("pacman"):
            subprocess.run(["sudo", "pacman", "-S", "--noconfirm", "espeak-ng"], check=False)
    elif system == "Darwin":
        if shutil.which("brew"):
            subprocess.run(["brew", "install", "espeak"], check=False)
    return "installed" if _espeak_available() else "unavailable"


def install_tts_deps() -> dict[str, Any]:
    """Install Kokoro TTS and its system dependency espeak-ng."""
    result: dict[str, Any] = {}

    result["espeak_ng"] = _install_espeak_system()

    kokoro_present = importlib.util.find_spec("kokoro") is not None
    soundfile_present = importlib.util.find_spec("soundfile") is not None

    if not kokoro_present or not soundfile_present:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", "kokoro>=0.9,<1.0", "soundfile>=0.12,<1.0"],
            capture_output=True,
            text=True,
        )
        result["pip_returncode"] = proc.returncode
        result["pip_stderr"] = proc.stderr.strip()[-300:] if proc.stderr else ""
    else:
        result["pip_returncode"] = 0

    result["kokoro_available"] = importlib.util.find_spec("kokoro") is not None
    result["soundfile_available"] = importlib.util.find_spec("soundfile") is not None
    return result


async def install_studio_assets(manifest_url: str | None = None) -> dict[str, Any]:
    started = time.time()
    source = manifest_url or os.getenv("MULLM_STUDIO_MANIFEST_URL", "").strip()
    result = await install_from_manifest_url(source) if source else install_builtin_asset_pack()
    result["tts"] = install_tts_deps()
    result["elapsed_ms"] = round((time.time() - started) * 1000)
    result["source"] = source or "builtin"
    return result
