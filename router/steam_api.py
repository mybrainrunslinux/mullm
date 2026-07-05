"""Steam asset capture pipeline for muLLM game dev assistant.

Endpoints:
  POST /api/steam/capture          — screenshot + resize to all Steam formats
  GET  /api/steam/assets/{game}    — list generated assets for a game
  GET  /api/steam/formats          — required Steam image formats + dimensions
  POST /api/steam/capsule          — AI-generated capsule with title overlay
  POST /api/steam/clip             — Playwright screen recording → webm/mp4
"""

from __future__ import annotations

import asyncio
import io
import logging
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from router.config import settings

logger = logging.getLogger("mullm.steam")

router = APIRouter(prefix="/api/steam", tags=["steam"])

# ---------------------------------------------------------------------------
# Steam format registry
# ---------------------------------------------------------------------------

STEAM_FORMATS: dict[str, tuple[int, int]] = {
    "header":            (460,  215),   # Store page header
    "capsule_sm":        (231,   87),   # Small capsule
    "capsule_md":        (616,  353),   # Medium capsule (primary)
    "capsule_lg":        (616,  353),   # Large capsule
    "hero":              (3840, 1240),  # Store page hero
    "screenshot":        (1280,  720),  # Minimum screenshot
    "screenshot_hd":     (1920, 1080),  # Full HD screenshot
    "icon":              (32,    32),   # App icon
    "icon_lg":           (256,  256),   # Large icon
    "library_600x900":   (600,  900),   # Library portrait
    "library_hero":      (3840, 1240),  # Library hero
    "trailer_thumbnail": (1280,  720),  # Video thumbnail
}

STEAM_FORMAT_NOTES: dict[str, str] = {
    "header":            "Store page header — shown in search results and browsing",
    "capsule_sm":        "Small capsule — appears in recommendation carousels",
    "capsule_md":        "Medium capsule — primary store listing image (required)",
    "capsule_lg":        "Large capsule — featured placement on store front",
    "hero":              "Store hero — full-bleed header art at 4K",
    "screenshot":        "Minimum screenshot resolution (at least 5 required)",
    "screenshot_hd":     "Full HD screenshot — preferred quality",
    "icon":              "32×32 px app icon for taskbar and small UI",
    "icon_lg":           "256×256 px icon for app list and about page",
    "library_600x900":   "Library portrait — vertical art for new library UI",
    "library_hero":      "Library hero banner — 4K widescreen background",
    "trailer_thumbnail": "Video trailer thumbnail shown on store page",
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ROUTER_DIR = Path(__file__).parent
_PROJECT_DIR = _ROUTER_DIR.parent


def _steam_dir(game: str) -> Path:
    d = _PROJECT_DIR / "assets" / "steam" / _safe_game(game)
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_game(name: str) -> str:
    """Sanitize game name for use as a directory/filename component."""
    import re
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", name)[:64]


def _game_url(game: str) -> str:
    port = getattr(settings, "port", 6856)
    return f"https://localhost:{port}/{game}"


def _asset_url(game: str, filename: str) -> str:
    return f"/api/steam/file/{_safe_game(game)}/{filename}"


# ---------------------------------------------------------------------------
# PIL resize helper
# ---------------------------------------------------------------------------

def _resize_to_format(img_bytes: bytes, fmt_name: str, width: int, height: int) -> bytes:
    """Resize image bytes to target dimensions using Lanczos, preserve aspect via crop/pad."""
    from PIL import Image

    src = Image.open(io.BytesIO(img_bytes)).convert("RGBA")
    src_w, src_h = src.size
    tgt_w, tgt_h = width, height

    # Scale to cover target (crop to fit)
    scale = max(tgt_w / src_w, tgt_h / src_h)
    new_w = int(src_w * scale)
    new_h = int(src_h * scale)
    scaled = src.resize((new_w, new_h), Image.LANCZOS)

    # Center crop
    left = (new_w - tgt_w) // 2
    top  = (new_h - tgt_h) // 2
    cropped = scaled.crop((left, top, left + tgt_w, top + tgt_h))

    # Flatten alpha to dark background for non-icon formats
    if fmt_name not in ("icon", "icon_lg"):
        bg = Image.new("RGB", (tgt_w, tgt_h), (10, 10, 26))
        bg.paste(cropped, mask=cropped.split()[3] if cropped.mode == "RGBA" else None)
        out = bg
    else:
        out = cropped.convert("RGBA")

    buf = io.BytesIO()
    fmt = "PNG" if fmt_name in ("icon", "icon_lg") else "PNG"
    out.save(buf, format=fmt, optimize=True)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Playwright availability guard
# ---------------------------------------------------------------------------

def _require_playwright():
    try:
        from playwright.async_api import async_playwright  # noqa: F401
        return True
    except ImportError:
        return False


# ---------------------------------------------------------------------------
# Request/response models
# ---------------------------------------------------------------------------

class CaptureRequest(BaseModel):
    game: str = Field(..., description="Game slug — HTML filename without extension (e.g. 'capyballista')")
    wait_ms: int = Field(3000, ge=500, le=15000, description="Milliseconds to wait after page load")
    formats: list[str] | None = Field(None, description="Subset of format keys to generate; null = all")


class CaptureResponse(BaseModel):
    game: str
    files: list[dict[str, Any]]
    duration_ms: float
    errors: list[str]


class CapsuleRequest(BaseModel):
    game: str = Field(..., description="Game slug")
    title: str = Field(..., description="Game title to overlay on the capsule")
    prompt: str = Field(..., description="Visual description for AI image generation")
    model: str = Field("dall-e-3", description="Image model: dall-e-3, gpt-image-1, imagen-4, etc.")
    format: str = Field("capsule_md", description="Which capsule format to generate")


class ClipRequest(BaseModel):
    game: str = Field(..., description="Game slug")
    duration_s: int = Field(10, ge=3, le=60, description="Recording duration in seconds")


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/formats")
async def get_formats():
    """Return all required Steam image formats with dimensions and notes."""
    return {
        "formats": {
            k: {
                "width": w,
                "height": h,
                "note": STEAM_FORMAT_NOTES.get(k, ""),
            }
            for k, (w, h) in STEAM_FORMATS.items()
        }
    }


@router.get("/assets/{game}")
async def list_assets(game: str):
    """List all generated Steam assets for a game."""
    steam_dir = _steam_dir(game)
    files = []
    for f in sorted(steam_dir.iterdir()):
        if f.is_file():
            stat = f.stat()
            files.append({
                "filename": f.name,
                "url": _asset_url(game, f.name),
                "size_bytes": stat.st_size,
                "modified": stat.st_mtime,
                "format": f.stem if "_" not in f.stem else f.stem.rsplit("_", 1)[0],
            })
    # Compute completeness: which Steam format keys have a matching file?
    generated_stems = {f["format"] for f in files}
    checklist = {
        k: {
            "complete": k in generated_stems,
            "dimensions": f"{w}x{h}",
            "note": STEAM_FORMAT_NOTES.get(k, ""),
        }
        for k, (w, h) in STEAM_FORMATS.items()
    }
    return {
        "game": game,
        "files": files,
        "count": len(files),
        "checklist": checklist,
        "complete_count": sum(1 for v in checklist.values() if v["complete"]),
        "total_formats": len(STEAM_FORMATS),
    }


@router.get("/file/{game}/{filename}")
async def serve_asset(game: str, filename: str):
    """Serve a generated Steam asset file."""
    import re
    if re.search(r"\.\.", filename) or re.search(r"\.\.", game):
        raise HTTPException(status_code=400, detail="Invalid path")
    path = _steam_dir(game) / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Asset not found")
    media = "image/png" if filename.endswith(".png") else "video/webm" if filename.endswith(".webm") else "video/mp4"
    return FileResponse(str(path), media_type=media)


@router.post("/capture", response_model=CaptureResponse)
async def capture_game(req: CaptureRequest):
    """
    Open the game in a headless browser, take a 1920x1080 screenshot,
    then resize it to every requested Steam format.
    """
    if not _require_playwright():
        raise HTTPException(
            status_code=501,
            detail=(
                "Playwright is not installed. "
                "Run: pip install playwright && playwright install chromium"
            ),
        )

    try:
        from PIL import Image as _PIL_Image  # noqa: F401
    except ImportError:
        raise HTTPException(status_code=501, detail="Pillow not installed. Run: pip install Pillow")

    t0 = time.perf_counter()
    errors: list[str] = []
    game_slug = _safe_game(req.game)
    steam_dir = _steam_dir(req.game)
    game_url = _game_url(req.game)
    target_formats = {k: v for k, v in STEAM_FORMATS.items() if not req.formats or k in req.formats}

    # ── Screenshot via Playwright ──────────────────────────────────────────
    screenshot_bytes: bytes | None = None
    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                ignore_https_errors=True,
                user_agent="muLLM-SteamCapture/1.0",
            )
            page = await ctx.new_page()
            try:
                await page.goto(game_url, wait_until="networkidle", timeout=30000)
            except Exception:
                # Fallback: some games block networkidle — just wait a fixed time
                try:
                    await page.goto(game_url, wait_until="domcontentloaded", timeout=20000)
                except Exception as exc:
                    errors.append(f"Page load failed: {exc}")
            if req.wait_ms > 0:
                await asyncio.sleep(req.wait_ms / 1000)
            if not errors:
                screenshot_bytes = await page.screenshot(full_page=False, type="png")
            await browser.close()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Playwright error: {exc}")

    if screenshot_bytes is None:
        raise HTTPException(status_code=500, detail="Screenshot capture failed: " + "; ".join(errors))

    # Save raw HD screenshot
    raw_path = steam_dir / f"{game_slug}_raw_1920x1080.png"
    raw_path.write_bytes(screenshot_bytes)

    # ── Resize to all formats ──────────────────────────────────────────────
    files: list[dict[str, Any]] = [{
        "format": "raw_1920x1080",
        "filename": raw_path.name,
        "url": _asset_url(req.game, raw_path.name),
        "width": 1920,
        "height": 1080,
        "size_bytes": len(screenshot_bytes),
    }]

    for fmt_name, (w, h) in target_formats.items():
        try:
            resized = _resize_to_format(screenshot_bytes, fmt_name, w, h)
            fname = f"{game_slug}_{fmt_name}_{w}x{h}.png"
            out_path = steam_dir / fname
            out_path.write_bytes(resized)
            files.append({
                "format": fmt_name,
                "filename": fname,
                "url": _asset_url(req.game, fname),
                "width": w,
                "height": h,
                "size_bytes": len(resized),
            })
        except Exception as exc:
            errors.append(f"{fmt_name}: {exc}")

    elapsed = (time.perf_counter() - t0) * 1000
    return CaptureResponse(
        game=req.game,
        files=files,
        duration_ms=round(elapsed, 1),
        errors=errors,
    )


@router.post("/capsule")
async def generate_capsule(req: CapsuleRequest):
    """
    Generate a capsule image using AI (ComfyUI or OpenAI), overlay the game title,
    and resize to the requested capsule format.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise HTTPException(status_code=501, detail="Pillow not installed. Run: pip install Pillow")

    if req.format not in STEAM_FORMATS:
        raise HTTPException(status_code=400, detail=f"Unknown format '{req.format}'. Valid: {list(STEAM_FORMATS)}")

    tgt_w, tgt_h = STEAM_FORMATS[req.format]
    game_slug = _safe_game(req.game)
    steam_dir = _steam_dir(req.game)

    # ── Generate base image via image_api internals ────────────────────────
    # We call the internal functions directly to avoid HTTP overhead.
    img_bytes: bytes | None = None
    provider_used = "none"

    # Try ComfyUI first (free, local)
    try:
        from router.comfyui_api import comfyui_base_url
        import httpx as _httpx
        base_url = comfyui_base_url()
        # Quick health check
        async with _httpx.AsyncClient(timeout=5.0) as client:
            probe = await client.get(f"{base_url}/system_stats")
        if probe.status_code == 200:
            from router.image_api import _generate_comfyui
            job = await _generate_comfyui(req.prompt, "", -1, tgt_w, tgt_h)
            # Poll for result (up to 60s)
            prompt_id = job["job_id"]
            for _ in range(60):
                await asyncio.sleep(1)
                async with _httpx.AsyncClient(timeout=10.0) as client:
                    hist = await client.get(f"{base_url}/history/{prompt_id}")
                if hist.status_code == 200:
                    data = hist.json().get(prompt_id, {})
                    for node_out in data.get("outputs", {}).values():
                        for img_info in node_out.get("images", []):
                            fn = img_info.get("filename", "")
                            sf = img_info.get("subfolder", "")
                            async with _httpx.AsyncClient(timeout=30.0) as client:
                                dl = await client.get(
                                    f"{base_url}/view",
                                    params={"filename": fn, "subfolder": sf, "type": "output"},
                                )
                            if dl.status_code == 200:
                                img_bytes = dl.content
                                provider_used = "comfyui"
                                break
                    if img_bytes:
                        break
    except Exception as exc:
        logger.debug("ComfyUI capsule gen failed, trying OpenAI: %s", exc)

    # Fallback to OpenAI
    if img_bytes is None:
        try:
            from router.image_api import _generate_openai, _JOBS, _image_dir
            # Adjust size for dall-e-3 constraints
            gen_size = "1024x1024"
            if req.model not in ("dall-e-3",):
                gen_size = f"{tgt_w}x{tgt_h}"
            job = await _generate_openai(req.prompt, req.model, gen_size)
            job_id = job["job_id"]
            # _generate_openai stores completed jobs synchronously
            job_data = _JOBS.get(job_id, {})
            output_url = job_data.get("output_url", "")
            if output_url:
                filename = output_url.split("/")[-1]
                img_path = _image_dir() / filename
                if img_path.exists():
                    img_bytes = img_path.read_bytes()
                    provider_used = "openai"
        except Exception as exc:
            logger.warning("OpenAI capsule gen failed: %s", exc)

    if img_bytes is None:
        raise HTTPException(
            status_code=503,
            detail="Image generation unavailable. Configure ComfyUI or an OpenAI API key.",
        )

    # ── Resize to capsule dimensions ───────────────────────────────────────
    resized_bytes = _resize_to_format(img_bytes, req.format, tgt_w, tgt_h)
    capsule_img = Image.open(io.BytesIO(resized_bytes)).convert("RGB")

    # ── Overlay title text ─────────────────────────────────────────────────
    draw = ImageDraw.Draw(capsule_img)

    # Try to load a nice font, fall back to default
    font_size = max(18, tgt_h // 8)
    font = None
    for font_path in [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
    ]:
        if Path(font_path).exists():
            try:
                from PIL import ImageFont as _IF
                font = _IF.truetype(font_path, font_size)
                break
            except Exception:
                pass
    if font is None:
        from PIL import ImageFont as _IF
        font = _IF.load_default()

    # Measure text to center it
    try:
        bbox = draw.textbbox((0, 0), req.title, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    except Exception:
        tw, th = len(req.title) * (font_size // 2), font_size

    tx = (tgt_w - tw) // 2
    ty = tgt_h - th - max(12, tgt_h // 10)

    # Shadow + text
    for dx, dy in [(-2, -2), (-2, 2), (2, -2), (2, 2), (0, 3)]:
        draw.text((tx + dx, ty + dy), req.title, font=font, fill=(0, 0, 0, 200))
    draw.text((tx, ty), req.title, font=font, fill=(255, 255, 255, 255))

    # ── Save ───────────────────────────────────────────────────────────────
    fname = f"{game_slug}_capsule_{req.format}_{tgt_w}x{tgt_h}.png"
    out_path = steam_dir / fname
    buf = io.BytesIO()
    capsule_img.save(buf, format="PNG", optimize=True)
    out_path.write_bytes(buf.getvalue())

    return {
        "game": req.game,
        "format": req.format,
        "filename": fname,
        "url": _asset_url(req.game, fname),
        "width": tgt_w,
        "height": tgt_h,
        "provider": provider_used,
        "size_bytes": out_path.stat().st_size,
    }


@router.post("/clip")
async def record_clip(req: ClipRequest):
    """
    Record a gameplay clip using Playwright's video recording feature.
    Saves as .webm; converts to .mp4 via ffmpeg if available.
    """
    if not _require_playwright():
        raise HTTPException(
            status_code=501,
            detail="Playwright is not installed. Run: pip install playwright && playwright install chromium",
        )

    game_slug = _safe_game(req.game)
    steam_dir = _steam_dir(req.game)
    game_url = _game_url(req.game)
    clip_id = uuid.uuid4().hex[:8]
    webm_name = f"{game_slug}_clip_{clip_id}.webm"
    mp4_name  = f"{game_slug}_clip_{clip_id}.mp4"

    import tempfile
    tmpdir = Path(tempfile.mkdtemp(prefix="mullm_steam_clip_"))

    try:
        from playwright.async_api import async_playwright
        async with async_playwright() as p:
            browser = await p.chromium.launch(
                args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"]
            )
            ctx = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                ignore_https_errors=True,
                record_video_dir=str(tmpdir),
                record_video_size={"width": 1280, "height": 720},
            )
            page = await ctx.new_page()
            try:
                await page.goto(game_url, wait_until="domcontentloaded", timeout=20000)
            except Exception as exc:
                logger.warning("Clip: page load partial: %s", exc)
            await asyncio.sleep(req.duration_s)
            video_path_str = await page.video.path() if page.video else None
            await ctx.close()
            await browser.close()
    except Exception as exc:
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Playwright clip error: {exc}")

    # Find the recorded webm
    recorded: Path | None = None
    if video_path_str and Path(video_path_str).exists():
        recorded = Path(video_path_str)
    else:
        webms = list(tmpdir.glob("*.webm"))
        if webms:
            recorded = webms[0]

    if not recorded or not recorded.exists():
        shutil.rmtree(tmpdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="No video file was recorded")

    dest_webm = steam_dir / webm_name
    shutil.copy2(str(recorded), str(dest_webm))
    shutil.rmtree(tmpdir, ignore_errors=True)

    result: dict[str, Any] = {
        "game": req.game,
        "duration_s": req.duration_s,
        "webm": {
            "filename": webm_name,
            "url": _asset_url(req.game, webm_name),
            "size_bytes": dest_webm.stat().st_size,
        },
        "mp4": None,
    }

    # Optional ffmpeg conversion
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        dest_mp4 = steam_dir / mp4_name
        try:
            proc = await asyncio.create_subprocess_exec(
                ffmpeg, "-y",
                "-i", str(dest_webm),
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-movflags", "+faststart",
                str(dest_mp4),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            if dest_mp4.exists():
                result["mp4"] = {
                    "filename": mp4_name,
                    "url": _asset_url(req.game, mp4_name),
                    "size_bytes": dest_mp4.stat().st_size,
                }
        except Exception as exc:
            logger.warning("ffmpeg conversion failed: %s", exc)

    return result


@router.get("/download/{game}")
async def download_all(game: str):
    """Download all Steam assets for a game as a zip archive."""
    import zipfile

    steam_dir = _steam_dir(game)
    files = [f for f in steam_dir.iterdir() if f.is_file()]
    if not files:
        raise HTTPException(status_code=404, detail=f"No assets found for game '{game}'")

    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tf:
        zip_path = Path(tf.name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files:
            zf.write(f, f.name)

    return FileResponse(
        str(zip_path),
        media_type="application/zip",
        filename=f"steam_assets_{_safe_game(game)}.zip",
        headers={"Content-Disposition": f'attachment; filename="steam_assets_{_safe_game(game)}.zip"'},
    )
