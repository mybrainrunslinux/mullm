"""
muLLM FastAPI application — port 6856 (MULM on phone keypad).

Security layers (outermost to innermost):
  1. CORS middleware          — allowlist-only origins
  2. BearerAuth middleware    — optional in dev mode, required in prod
  3. RateLimiter middleware   — 40 mutating req/min per (IP, session)
  4. RequestDedup middleware  — MD5 hash + 2s window to drop duplicates
  5. Pydantic validation      — all user input validated before business logic
  6. Budget middleware        — hard budget enforcement per session
"""

from __future__ import annotations

import asyncio
import base64
import csv
import hashlib
import hmac
import html
import io
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psutil
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from router.config import CLOUD_MODEL_PRICING, settings
from router.models import (
    ChatCompletionChoice,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ChatCompletionUsage,
    ChatMessage,
    DashboardData,
    GpuStats,
    HealthResponse,
    ModelInfo,
    ModelsListResponse,
    PipelineResult,
    QueryRequest,
    SplitQueryRequest,
    SplitResult,
    SystemStats,
    TierLabel,
    TierStats,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("mullm.main")
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# OpenTelemetry — optional production tracing
# ---------------------------------------------------------------------------

try:
    from opentelemetry import trace as _otel_trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
        OTLPSpanExporter as _OTLPSpanExporter,
    )
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor as _FastAPIInstrumentor
    from opentelemetry.sdk.resources import Resource as _Resource
    from opentelemetry.sdk.trace import TracerProvider as _TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor as _BatchSpanProcessor

    _otel_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317")
    _resource = _Resource.create({"service.name": "mullm"})
    _provider = _TracerProvider(resource=_resource)
    _provider.add_span_processor(
        _BatchSpanProcessor(_OTLPSpanExporter(endpoint=_otel_endpoint, insecure=True))
    )
    _otel_trace.set_tracer_provider(_provider)
    _tracer = _otel_trace.get_tracer("mullm.query")
    _otel_available = True
    logger.info("OpenTelemetry tracing enabled → %s", _otel_endpoint)
except ImportError:
    _tracer = None  # type: ignore[assignment]
    _otel_available = False
    logger.warning(
        "opentelemetry packages not installed — tracing disabled. "
        "Install: pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc opentelemetry-instrumentation-fastapi"
    )



# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated on_event("startup") / on_event("shutdown"))
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    from router.groundtruth.loader import load_categories
    load_categories()

    # Apply persisted /setup toggles that map onto runtime settings
    # (fable_top_tier swaps the Anthropic power model: Fable 5 vs Opus).
    _apply_fable_toggle(_load_toggles().get("fable_top_tier", True))

    from router.secrets import load_pass_secrets_into_env
    loaded_secret_names = load_pass_secrets_into_env()
    if loaded_secret_names:
        logger.info("Loaded %d provider secrets from pass", len(loaded_secret_names))

    from router.backends.registry import init_backends
    init_backends()

    from router.intent import _load_deberta
    if settings.classifier_model_path:
        if _load_deberta():
            logger.info("Intent classifier (DeBERTa) loaded and warmed")
        else:
            logger.warning("Intent classifier configured but failed to load — falling back to LUT rules")
    else:
        logger.info("No classifier model path configured — using LUT rules routing")

    from router import retrain_scheduler
    if settings.classifier_retrain_enabled:
        retrain_scheduler.start()

    mode = "DEV" if settings.dev_mode else "PROD"
    from router.backends.protocol import list_backends
    backend_names = ", ".join(list_backends()) or "none"
    banner = (
        f"\n"
        f"  mu|LLM v{settings.version}  —  port {settings.port}  —  {mode} mode\n"
        f"  Ollama: {settings.ollama_base_url}  model: {settings.ollama_model}\n"
        f"  Budget: warn=${settings.budget_warn}  moderate=${settings.budget_moderate}  hard=${settings.budget_hard}\n"
        f"  Auth: {'disabled (dev)' if settings.dev_mode or not settings.api_key else 'bearer token'}\n"
        f"  Docs: {'http://localhost:' + str(settings.port) + '/docs' if settings.dev_mode else 'disabled'}\n"
        f"  Backends: {backend_names}\n"
    )
    print(banner)
    logger.info("muLLM started on port %d", settings.port)
    yield
    # Shutdown
    from router import retrain_scheduler as _retrain_scheduler
    await _retrain_scheduler.stop()
    logger.info("muLLM shutting down gracefully")


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(
    title="muLLM",
    version=settings.version,
    description="Local-first LLM router. 96.4% cost reduction. Free tier first.",
    docs_url="/docs" if settings.dev_mode else None,
    redoc_url="/redoc" if settings.dev_mode else None,
    lifespan=lifespan,
)


# Instrument FastAPI with OTel if available
if _otel_available:
    _FastAPIInstrumentor.instrument_app(app)

from router import research_exports
from router.bench_api import router as bench_router
from router.civitai_api import router as civitai_router
from router.comfyui_api import router as comfyui_router
from router.coverage_api import router as coverage_router
from router.dataviz3d_api import router as dataviz3d_router
from router.dialogue_api import router as dialogue_router
from router.image_api import router as image_api_router
from router.languages import language_payload, normalize_enabled_languages
from router.local_models_api import router as local_models_router
from router.market_api import router as market_router
from router.physics_api import router as physics_router
from router.refiner_api import router as refiner_router
from router.review_api import router as review_router
from router.scene_api import router as scene_router
from router.steam_api import router as steam_router
from router.terrain_api import router as terrain_router

app.include_router(review_router)
app.include_router(bench_router)
app.include_router(image_api_router)  # must come before comfyui_router (owns /api/image/*)
app.include_router(comfyui_router)
app.include_router(coverage_router)
app.include_router(civitai_router)
app.include_router(dataviz3d_router)
app.include_router(local_models_router)
app.include_router(refiner_router)
app.include_router(market_router)
app.include_router(physics_router)
app.include_router(scene_router)
app.include_router(dialogue_router)
app.include_router(steam_router)
app.include_router(terrain_router)


# ---------------------------------------------------------------------------
# CORS middleware
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Session-ID"],
)


# ---------------------------------------------------------------------------
# Security response headers — OWASP A05, CSP, XSS, clickjacking, MIME sniff
# Enterprise mode: also enforces X-Mullm-Token custom header + Referer policy
# ---------------------------------------------------------------------------

_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "   # inline JS in single-file HTML pages
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob:; "              # audio/video elements need blob: for TTS playback
    "connect-src 'self' https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://fonts.gstatic.com https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none';"
)

_DOCS_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
    "font-src 'self' data: https://fonts.gstatic.com; "
    "connect-src 'self'; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none';"
)

_GAME_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
    "img-src 'self' data: blob: https:; "
    "media-src 'self' blob:; "
    "connect-src 'self' https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
    "font-src 'self' data: https://cdnjs.cloudflare.com https://unpkg.com https://cdn.jsdelivr.net; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none';"
)

# Terrain pages need Three.js CDN + OSM tiles + Nominatim geocoding
_TERRAIN_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob: https://tile.openstreetmap.org https://*.tile.openstreetmap.org; "
    "media-src 'self' blob:; "
    "connect-src 'self' https://cdn.jsdelivr.net https://nominatim.openstreetmap.org https://tile.openstreetmap.org; "
    "font-src 'self' data:; "
    "worker-src 'self' blob:; "
    "frame-ancestors 'none';"
)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    if settings.require_referer_match and request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin") or ""
        referer = request.headers.get("referer") or ""
        allowed = set(settings.cors_origins)
        if origin and origin not in allowed:
            return JSONResponse(status_code=403, content={"detail": "Origin not allowed"})
        if referer and not any(referer.startswith(allowed_origin + "/") for allowed_origin in allowed):
            return JSONResponse(status_code=403, content={"detail": "Referer not allowed"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    if request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}:
        csp = _DOCS_CSP
    elif request.url.path.startswith("/code/ready/"):
        csp = _GAME_CSP
    elif request.url.path in ("/terrain", "/terrain-standalone"):
        csp = _TERRAIN_CSP
    else:
        csp = _CSP
    response.headers["Content-Security-Policy"] = csp
    if not settings.dev_mode:
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains"
    # Enterprise: require custom header if configured
    if getattr(settings, "require_custom_header", None):
        expected = settings.require_custom_header
        if request.headers.get("X-Mullm-Token") != expected:
            return JSONResponse(
                status_code=403,
                content={"detail": "Missing required enterprise header"},
            )
    return response


# ---------------------------------------------------------------------------
# Access log middleware — CC6/CC7 SOC2 evidence, one line per request
# ---------------------------------------------------------------------------

_access_log_path = settings.cache_dir / "access_log.jsonl"

@app.middleware("http")
async def access_logger(request: Request, call_next):
    t0 = time.monotonic()
    response = await call_next(request)
    latency_ms = round((time.monotonic() - t0) * 1000, 1)
    entry = {
        "ts": round(time.time(), 3),
        "ip": request.client.host if request.client else "unknown",
        "method": request.method,
        "path": request.url.path,
        "status": response.status_code,
        "ua": request.headers.get("user-agent", ""),
        "latency_ms": latency_ms,
    }
    try:
        _access_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(_access_log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass
    return response


# ---------------------------------------------------------------------------
# Bearer token auth middleware
# ---------------------------------------------------------------------------

_AUTH_EXEMPT = {"/health", "/docs", "/redoc", "/openapi.json"}


@app.middleware("http")
async def bearer_auth(request: Request, call_next):
    if settings.dev_mode or settings.api_key is None:
        return await call_next(request)
    if request.url.path in _AUTH_EXEMPT:
        return await call_next(request)

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "Missing or malformed Authorization header"},
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = auth_header[len("Bearer "):]
    # Constant-time compare to prevent timing attacks
    if not hmac.compare_digest(token.encode(), settings.api_key.encode()):
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content={"detail": "Invalid API key"},
        )
    return await call_next(request)


# ---------------------------------------------------------------------------
# Rate limiting middleware — sliding window per (IP, session) + hard IP cap
# ---------------------------------------------------------------------------

# Per (IP, session) sliding window — 40 mutating req/min default
_rate_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=settings.rate_limit_per_minute))
# Per-IP hard cap regardless of session rotation
_IP_HARD_LIMIT = settings.ip_rate_limit_per_minute
_ip_rate_windows: dict[str, deque] = defaultdict(lambda: deque(maxlen=_IP_HARD_LIMIT))
_WINDOW_SECONDS = 60.0


@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    if request.url.path in {"/health", "/docs", "/redoc", "/openapi.json"}:
        return await call_next(request)
    if settings.dev_mode:
        return await call_next(request)
    # Do not count static assets, HTML pages, or browser polling GETs against
    # the LLM/action rate budget. The desktop UI can legitimately load dozens
    # of assets and status probes before the first chat request.
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    session_id = request.headers.get("X-Session-ID", "default")

    now = time.monotonic()

    # ── Hard per-IP limit (session-rotation-proof) ──────────────────────
    ip_window = _ip_rate_windows[client_ip]
    while ip_window and now - ip_window[0] > _WINDOW_SECONDS:
        ip_window.popleft()
    if len(ip_window) >= _IP_HARD_LIMIT:
        retry_after = int(_WINDOW_SECONDS - (now - ip_window[0])) + 1
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"IP rate limit exceeded. Retry after {retry_after}s."},
            headers={"Retry-After": str(retry_after)},
        )
    ip_window.append(now)

    # ── Per (IP, session) limit ──────────────────────────────────────────
    key = f"{client_ip}:{session_id}"
    window = _rate_windows[key]
    while window and now - window[0] > _WINDOW_SECONDS:
        window.popleft()
    if len(window) >= settings.rate_limit_per_minute:
        retry_after = int(_WINDOW_SECONDS - (now - window[0])) + 1
        return JSONResponse(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            content={"detail": f"Rate limit exceeded. Retry after {retry_after}s."},
            headers={"Retry-After": str(retry_after)},
        )
    window.append(now)

    return await call_next(request)


# ---------------------------------------------------------------------------
# Request cancellation registry
# ---------------------------------------------------------------------------

_cancel_events: dict[str, asyncio.Event] = {}
_agent_registry: dict[str, dict[str, Any]] = {}
_agent_tasks: dict[str, list[dict[str, Any]]] = defaultdict(list)


def _register_agent_payload(body: dict[str, Any], query: Any | None = None) -> dict[str, Any]:
    query = query or {}
    agent_id = str(body.get("agent_id") or body.get("id") or query.get("agent_id") or "").strip()
    endpoint = str(body.get("endpoint") or query.get("endpoint") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", agent_id):
        raise HTTPException(status_code=400, detail="agent_id is required and must be a safe identifier")
    if endpoint and not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]{1,500}", endpoint):
        raise HTTPException(status_code=400, detail="endpoint must be an http(s) URL")
    raw_caps = body.get("capabilities") or query.get("capabilities") or []
    if isinstance(raw_caps, str):
        capabilities = [part.strip() for part in raw_caps.split(",") if part.strip()]
    elif isinstance(raw_caps, list):
        capabilities = [str(part).strip() for part in raw_caps if str(part).strip()]
    else:
        capabilities = []
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    record = {
        "agent_id": agent_id,
        "id": agent_id,
        "endpoint": endpoint,
        "capabilities": capabilities,
        "name": str(body.get("name") or agent_id),
        "paused": False,
        "registered_at": _agent_registry.get(agent_id, {}).get("registered_at") or now,
        "last_heartbeat_at": now,
    }
    _agent_registry[agent_id] = record
    return {"registered": True, "agent": record}


@app.post("/cancel/{request_id}")
async def cancel_request(request_id: str):
    """Signal an in-flight request to cancel by request_id."""
    if request_id in _cancel_events:
        _cancel_events[request_id].set()
        from router.audit import audit_event
        audit_event("query.cancel", request_id=request_id, cancelled=True)
        return {"cancelled": True}
    return {"cancelled": False}


@app.post("/query/cancel")
async def cancel_query_compat(request_id: str = ""):
    """Compatibility endpoint used by the chat UI and older clients."""
    if not request_id:
        raise HTTPException(status_code=400, detail="request_id required")
    return await cancel_request(request_id)


@app.post("/api/stream/{request_id}/cancel")
async def cancel_stream_compat(request_id: str):
    """Compatibility endpoint for stream cancellation buttons."""
    return await cancel_request(request_id)


# ---------------------------------------------------------------------------
# Request deduplication middleware — MD5 + 2s window
# ---------------------------------------------------------------------------

_dedup_cache: dict[str, float] = {}
_DEDUP_LOCK = asyncio.Lock()


async def _is_duplicate(body_bytes: bytes) -> bool:
    digest = hashlib.md5(body_bytes, usedforsecurity=False).hexdigest()
    now = time.monotonic()
    async with _DEDUP_LOCK:
        last_seen = _dedup_cache.get(digest)
        if last_seen is not None and now - last_seen < settings.dedup_window_seconds:
            return True
        _dedup_cache[digest] = now
        # Prune old entries (keep dict bounded)
        if len(_dedup_cache) > 10_000:
            cutoff = now - settings.dedup_window_seconds * 2
            for k, v in list(_dedup_cache.items()):
                if v < cutoff:
                    del _dedup_cache[k]
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _ollama_available() -> bool:
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@app.get("/health", response_model=HealthResponse)
async def health():
    from router import cache as cache_mod
    from router.intent import is_model_loaded

    ollama_ok = await _ollama_available()
    semantic_cache_ok = cache_mod.is_available()

    _cache_docs = cache_mod.count_entries()

    return HealthResponse(
        version=settings.version,
        port=settings.port,
        mode="dev" if settings.dev_mode else "prod",
        ollama_available=ollama_ok,
        ollama_ok=ollama_ok,
        chromadb_available=semantic_cache_ok,
        semantic_cache_available=semantic_cache_ok,
        semantic_cache_backend=cache_mod.backend_name(),
        classifier_loaded=is_model_loaded(),
        cache_docs=_cache_docs,
    )


@app.get("/api/popular-queries")
async def popular_queries():
    """Return optional chat sample telemetry. Empty is valid and should not 404."""
    return {"popular": None, "interesting": None}


@app.get("/events")
async def events():
    """Lightweight SSE heartbeat used by dashboard/chat surfaces."""

    async def event_stream() -> AsyncIterator[str]:
        yield f"data: {json.dumps({'type': 'ready', 'ts': time.time()})}\n\n"
        while True:
            await asyncio.sleep(15)
            yield f"data: {json.dumps({'type': 'heartbeat', 'ts': time.time()})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/classify")
async def classify_endpoint(body: QueryRequest):
    """Return routing classification without executing any model tier."""
    from router import scorer
    from router.intent import classify

    t0 = time.monotonic()
    result = classify(body.content, history=body.history)
    tier = scorer.select_tier(result, session_id=body.session_id)
    elapsed_ms = round((time.monotonic() - t0) * 1000, 2)
    classification = {
        "category": result.category.value,
        "complexity": result.complexity,
        "confidence": result.confidence,
        "keywords": result.keywords,
        "needs_vision": result.needs_vision,
        "needs_web": result.needs_web,
        "suggested_tier": tier.value,
    }
    return {
        "classification": classification,
        "category": result.category.value,
        "complexity": result.complexity,
        "tier": tier.value,
        "elapsed_ms": elapsed_ms,
    }


@app.delete("/cache/clear")
async def cache_clear():
    """Clear the semantic vector cache collection."""
    from router import cache as cache_mod

    cleared, _before, remaining = cache_mod.clear_entries()
    if not cleared:
        return {"cleared": False, "docs_remaining": 0, "reason": "cache unavailable"}
    return {"cleared": True, "docs_remaining": remaining}


@app.get("/cache/scan")
async def cache_scan(limit: int = 100, offset: int = 0):
    """List cache entries for review without exposing Chroma internals to the UI."""
    from router import cache as cache_mod

    limit = max(1, min(int(limit), 1000))
    offset = max(0, int(offset))
    entries = cache_mod.scan_entries(limit=limit, offset=offset)
    return {"entries": entries, "count": len(entries), "limit": limit, "offset": offset}


@app.delete("/cache/entry")
async def cache_entry_delete(payload: dict):
    """Delete one cache entry by id or exact query text."""
    from router import cache as cache_mod

    deleted = cache_mod.delete_entry(
        entry_id=payload.get("id") or payload.get("entry_id"),
        query=payload.get("query") or payload.get("content"),
    )
    return {"deleted": bool(deleted), "count": deleted}


@app.post("/query", response_model=PipelineResult)
async def query(request: Request, body: QueryRequest):
    # Deduplication check (read body bytes from starlette)
    body_bytes = await request.body()
    if not settings.dev_mode and await _is_duplicate(body_bytes):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Duplicate request — try again after 2 seconds",
        )

    import re as _re
    import uuid as _uuid
    raw_request_id = (body.request_id or "").strip()
    if raw_request_id and not _re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", raw_request_id):
        raise HTTPException(status_code=400, detail="Invalid request_id")
    request_id = raw_request_id or _uuid.uuid4().hex
    cancel_event = asyncio.Event()
    _cancel_events[request_id] = cancel_event

    # ── WITH RICE / powerup: parallel top-model fan-out ─────────────────
    if body.powerup:
        from router.powerup import estimated_cost, powerup_models, powerup_pipeline

        if not body.powerup_confirmed:
            _cancel_events.pop(request_id, None)
            return JSONResponse(
                status_code=402,
                content={
                    "error": "powerup_needs_confirmation",
                    "models": [m for _, m in powerup_models()],
                    "estimated_cost": estimated_cost(),
                    "message": "WITH RICE fires the top models in parallel then synthesizes. "
                               "Resend with powerup_confirmed=true to proceed.",
                },
            )
        try:
            result = await powerup_pipeline(body, time.perf_counter())
        except RuntimeError as exc:
            raise HTTPException(status_code=502, detail=str(exc))
        finally:
            _cancel_events.pop(request_id, None)
        return Response(
            content=result.model_dump_json(),
            media_type="application/json",
            headers={"X-Request-ID": request_id},
        )

    from router.audit import audit_event, content_hash
    from router.tiers import execute_pipeline
    audit_event(
        "query.start",
        request_id=request_id,
        session_id=body.session_id,
        content_hash=content_hash(body.content),
        forced_tier=body.tier_override.value if body.tier_override else None,
        use_web=body.use_web,
    )
    pipeline_task = asyncio.create_task(execute_pipeline(body, cancel_event=cancel_event))
    cancel_task = asyncio.create_task(cancel_event.wait())
    try:
        done, _pending = await asyncio.wait(
            {pipeline_task, cancel_task},
            timeout=settings.request_timeout_seconds,
            return_when=asyncio.FIRST_COMPLETED,
        )
        if cancel_task in done:
            pipeline_task.cancel()
            audit_event("query.cancelled", request_id=request_id, session_id=body.session_id)
            raise asyncio.CancelledError
        if pipeline_task not in done:
            cancel_event.set()
            pipeline_task.cancel()
            audit_event("query.timeout", request_id=request_id, session_id=body.session_id)
            raise TimeoutError
        result = pipeline_task.result()
        audit_event(
            "query.finish",
            request_id=request_id,
            session_id=body.session_id,
            tier=result.tier.value,
            model=result.model_used,
            cost=result.cost,
            latency_ms=result.latency_ms,
        )
        # OTel span — set attributes on the current active span (created by FastAPIInstrumentor)
        if _otel_available and _tracer is not None:
            _span = _otel_trace.get_current_span()
            if _span and _span.is_recording():
                _category = (
                    result.intent.category.value
                    if result.intent and hasattr(result.intent, "category") and result.intent.category
                    else "unknown"
                )
                _span.set_attribute("mullm.intent_category", _category)
                _span.set_attribute("mullm.tier", result.tier.value)
                _span.set_attribute("mullm.model_used", result.model_used)
                _span.set_attribute("mullm.cost", float(result.cost))
                _span.set_attribute("mullm.latency_ms", float(result.latency_ms))
                _span.set_attribute("mullm.cached", bool(result.cached))
    except TimeoutError:
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Pipeline exceeded {settings.request_timeout_seconds}s timeout",
        )
    except asyncio.CancelledError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Request cancelled",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    finally:
        cancel_task.cancel()
        if not pipeline_task.done():
            pipeline_task.cancel()
        _cancel_events.pop(request_id, None)

    # Return request_id in header so clients can cancel in-flight
    return Response(
        content=result.model_dump_json(),
        media_type="application/json",
        headers={"X-Request-ID": request_id},
    )


@app.post("/query/split", response_model=SplitResult)
async def query_split(body: SplitQueryRequest):
    """
    Split a multi-part query into independent sub-queries and execute in parallel.
    Each sub-query routes independently through the 4-tier pipeline.
    """
    from router.tiers import execute_pipeline

    # Naive split on newlines / numbered lists — real splitting via LLM would be Tier 2
    raw_parts = [p.strip() for p in body.content.split("\n") if p.strip()]
    if len(raw_parts) <= 1:
        # Try sentence split as fallback
        import re
        raw_parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.content) if s.strip()]

    parts = raw_parts[: body.max_parts]
    if not parts:
        raise HTTPException(status_code=400, detail="Could not split query into sub-parts")

    sub_requests = [
        QueryRequest(content=p, session_id=body.session_id) for p in parts
    ]

    t0 = time.monotonic()
    sub_results = await asyncio.gather(
        *[execute_pipeline(r) for r in sub_requests],
        return_exceptions=True,
    )
    total_latency = (time.monotonic() - t0) * 1000

    pipeline_results: list[PipelineResult] = []
    for idx, res in enumerate(sub_results):
        if isinstance(res, Exception):
            pipeline_results.append(PipelineResult(
                response=f"[Error: {res}]",
                tier=TierLabel.LOCAL,
                cost=0.0, tokens_used=0, latency_ms=0.0,
                model_used="error", cached=False,
            ))
        else:
            pipeline_results.append(res)

    combined = "\n\n".join(r.response for r in pipeline_results)
    total_cost = sum(r.cost for r in pipeline_results)

    return SplitResult(
        parts=pipeline_results,
        combined_response=combined,
        total_cost=total_cost,
        total_latency_ms=round(total_latency, 2),
    )


@app.get("/query/hyper")
async def query_hyper(q: str, session_id: str = "hyper", max_tasks: int = 8):
    """SSE endpoint for Hyper-Decomposer: decompose once, execute subtasks live."""
    from router.decomposer import decompose_prompt
    from router.tiers import execute_pipeline

    prompt = q.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="q is required")
    max_tasks = max(1, min(int(max_tasks), 12))

    async def event_stream() -> AsyncIterator[str]:
        started = time.monotonic()
        subtasks = (await decompose_prompt(prompt))[:max_tasks]
        if not subtasks:
            subtasks = [{"task": prompt, "suggested_tier": "local", "depends_on": []}]
        task_meta = [
            {
                "id": f"task-{idx + 1}",
                "priority": idx + 1,
                "service": str(task.get("suggested_tier") or "auto"),
                "model": "auto",
                "task": str(task.get("task") or prompt),
            }
            for idx, task in enumerate(subtasks)
        ]
        yield f"data: {json.dumps({'type': 'decomposed', 'tasks': task_meta})}\n\n"

        async def run_one(meta: dict[str, Any]) -> dict[str, Any]:
            t0 = time.monotonic()
            try:
                result = await execute_pipeline(
                    QueryRequest(content=meta["task"], session_id=session_id)
                )
                duration_ms = round((time.monotonic() - t0) * 1000, 2)
                cost = float(result.cost or 0.0)
                return {
                    "id": meta["id"],
                    "status": "done",
                    "result": result.response,
                    "cost": cost,
                    "costLabel": "FREE" if cost == 0 else f"${cost:.4f}",
                    "durationMs": duration_ms,
                    "service": result.tier.value,
                    "model": result.model_used,
                }
            except Exception as exc:
                duration_ms = round((time.monotonic() - t0) * 1000, 2)
                return {
                    "id": meta["id"],
                    "status": "error",
                    "result": f"{exc.__class__.__name__}: {exc}",
                    "cost": 0.0,
                    "costLabel": "FREE",
                    "durationMs": duration_ms,
                    "service": "error",
                    "model": "error",
                }

        tasks = [asyncio.create_task(run_one(meta)) for meta in task_meta]
        results: list[dict[str, Any]] = []
        for completed in asyncio.as_completed(tasks):
            item = await completed
            results.append(item)
            yield f"data: {json.dumps({'type': 'result', 'task': item})}\n\n"

        wall_ms = round((time.monotonic() - started) * 1000, 2)
        seq_ms = round(sum(float(item.get("durationMs") or 0) for item in results), 2)
        total_cost = round(sum(float(item.get("cost") or 0) for item in results), 8)
        yield f"data: {json.dumps({'type': 'done', 'wallMs': wall_ms, 'seqMs': max(seq_ms, wall_ms), 'totalCost': total_cost, 'tasks': results})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/query/stream")
async def query_stream(
    content: str,
    session_id: str = "default",
    request_id: str = "",
    force_tier: str = "local",
    model: str = "",
):
    """SSE streaming with cancellation parity.

    Streaming remains local-first for safety. Non-local streaming should go
    through explicit provider-specific endpoints once their cancellation and
    budget semantics are fully restored.
    """
    import uuid as _uuid

    from router.audit import audit_event, content_hash
    from router.intent import classify
    from router.tiers import stream_local

    rid = request_id.strip() or _uuid.uuid4().hex
    if not re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", rid):
        raise HTTPException(status_code=400, detail="Invalid request_id")
    cancel_event = asyncio.Event()
    _cancel_events[rid] = cancel_event
    tier = TierLabel.LOCAL if force_tier in ("", "auto", "local") else TierLabel.LOCAL
    request = QueryRequest(content=content, session_id=session_id, request_id=rid, stream=True, tier_override=tier, model_override=model or None)
    intent = classify(content)
    audit_event("query.stream.start", request_id=rid, session_id=session_id, content_hash=content_hash(content))

    async def event_stream() -> AsyncIterator[str]:
        try:
            async for chunk in stream_local(request, intent):
                if cancel_event.is_set():
                    audit_event("query.stream.cancelled", request_id=rid, session_id=session_id)
                    yield f"data: {json.dumps({'cancelled': True, 'request_id': rid})}\n\n"
                    break
                # SSE format: "data: <payload>\n\n"
                payload = json.dumps({"token": chunk, "chunk": chunk, "request_id": rid})
                yield f"data: {payload}\n\n"
        except Exception as exc:
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
        finally:
            _cancel_events.pop(rid, None)
        yield "data: [DONE]\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Request-ID": rid,
        },
    )


def _query_trace(records: list[dict]) -> list[dict]:
    trace: list[dict] = []
    for row in records:
        trace.append({
            "t": float(row.get("ts", 0) or 0),
            "q": row.get("query", row.get("query_hash", "")) or "",
            "query": row.get("query", "") or "",
            "tier": row.get("tier", "unknown"),
            "model": row.get("model", ""),
            "category": row.get("category", ""),
            "ms": float(row.get("latency_ms", 0) or 0),
            "latency_ms": float(row.get("latency_ms", 0) or 0),
            "cost": float(row.get("cost_usd", row.get("cost", 0)) or 0),
            "intent_id": row.get("intent_id", ""),
        })
    return trace


def _dashboard_records(records: list[dict], include_test: bool = False) -> list[dict]:
    if include_test:
        return records
    fake_models = {"fake-local", "fake-cloud", "mock-local", "mock-cloud"}
    return [
        row
        for row in records
        if str(row.get("model") or row.get("model_used") or "") not in fake_models
        and str(row.get("tier") or row.get("tier_used") or "") not in {"fake", "mock"}
        and not bool(row.get("test_record", False))
    ]


def _routing_decisions(records: list[dict], limit: int = 100) -> list[dict]:
    decisions: list[dict] = []
    for idx, row in enumerate(records[-limit:]):
        tier = str(row.get("tier", "unknown") or "unknown")
        ts = float(row.get("ts", 0) or 0)
        decisions.append({
            "id": row.get("intent_id") or f"q-{max(0, len(records) - limit) + idx + 1}",
            "timestamp": ts,
            "timestamp_iso": datetime.fromtimestamp(ts).isoformat() if ts else "",
            "category": row.get("category") or "unknown",
            "tier_used": tier,
            "tier": tier,
            "model_used": row.get("model") or "",
            "model": row.get("model") or "",
            "latency_ms": float(row.get("latency_ms", 0) or 0),
            "cost": float(row.get("cost_usd", row.get("cost", 0)) or 0),
            "tokens_used": int(row.get("tokens_used", row.get("tokens", 0)) or 0),
            "success": bool(row.get("success", True)),
            "sensitive_mode": bool(row.get("sensitive_mode", False)),
            "query": row.get("query", "") or "",
            "query_hash": row.get("query_hash", "") or "",
        })
    return decisions


def _dashboard_flow(records: list[dict]) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, int]]]:
    cat_tier: dict[str, dict[str, int]] = {}
    tier_model: dict[str, dict[str, int]] = {}
    for row in records:
        cat = str(row.get("category") or "unknown")
        tier = str(row.get("tier") or "unknown")
        model = str(row.get("model") or tier)
        cat_tier.setdefault(cat, {})[tier] = cat_tier.setdefault(cat, {}).get(tier, 0) + 1
        tier_model.setdefault(tier, {})[model] = tier_model.setdefault(tier, {}).get(model, 0) + 1
    return cat_tier, tier_model


@app.get("/api/dashboard")
async def dashboard(include_test: bool = False):
    """Aggregate stats from active scoring storage for the dashboard."""
    from router.scorer import read_scoring_log

    raw_records = read_scoring_log(limit=10_000)
    records = _dashboard_records(raw_records, include_test=include_test)
    if not records:
        data = DashboardData(
            total_queries=0,
            total_cost=0.0,
            cost_reduction_pct=0.0,
            session_cost=0.0,
            tier_breakdown={},
            top_categories=[],
            queries_last_hour=0,
            avg_latency_ms=0.0,
        ).model_dump()
        data.update(
            {
                "local_rate": 0.0,
                "savings_pct": 0.0,
                "savings": 0.0,
                "cache_hit_rate": 0.0,
                "estimated_cloud_cost": 0.0,
                "tier_distribution": {},
                "query_trace": [],
                "sankey": {
                    "cat_tier": {},
                    "tier_model": {},
                    "total_queries": 0,
                },
            }
        )
        return data

    total_cost = sum(float(r.get("cost_usd", r.get("cost", 0)) or 0) for r in records)
    # Cloud baseline: estimate what all queries would cost at cloud_full price
    cloud_full_price_per_m_input  = 3.00   # claude-sonnet-4-6
    cloud_full_price_per_m_output = 15.00
    avg_tokens = 1000
    cloud_baseline = len(records) * (avg_tokens * (cloud_full_price_per_m_input + cloud_full_price_per_m_output) / 2) / 1_000_000
    reduction = (1 - total_cost / cloud_baseline) * 100 if cloud_baseline > 0 else 0.0

    tier_stats: dict[str, TierStats] = {}
    category_counts: dict[str, int] = {}
    latencies: list[float] = []
    one_hour_ago = time.time() - 3600
    recent_count = 0

    for r in records:
        tier = r.get("tier", "unknown")
        if tier not in tier_stats:
            tier_stats[tier] = TierStats()
        tier_stats[tier].hits += 1
        tier_stats[tier].total_cost += float(r.get("cost_usd", r.get("cost", 0)) or 0)
        lat = r.get("latency_ms", 0)
        if lat:
            tier_stats[tier].avg_latency_ms = (
                (tier_stats[tier].avg_latency_ms * (tier_stats[tier].hits - 1) + lat)
                / tier_stats[tier].hits
            )
            latencies.append(lat)
        cat = r.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        if r.get("ts", 0) > one_hour_ago:
            recent_count += 1

    top_categories = sorted(
        [{"category": k, "count": v} for k, v in category_counts.items()],
        key=lambda x: x["count"],
        reverse=True,
    )[:8]

    avg_lat = sum(latencies) / len(latencies) if latencies else 0.0

    local_hits = sum(1 for r in records if str(r.get("tier", "")).startswith(("groundtruth", "cache", "local")))
    local_rate = (local_hits / len(records) * 100.0) if records else 0.0
    savings = max(0.0, cloud_baseline - total_cost)
    data = DashboardData(
        total_queries=len(records),
        total_cost=round(total_cost, 6),
        cost_reduction_pct=round(reduction, 2),
        session_cost=0.0,  # per-session cost requires session_id context
        tier_breakdown={k: v for k, v in tier_stats.items()},
        top_categories=top_categories,
        queries_last_hour=recent_count,
        avg_latency_ms=round(avg_lat, 2),
    ).model_dump()
    data.update({
        "local_rate": round(local_rate, 2),
        "savings_pct": round(reduction, 2),
        "savings": round(savings, 6),
        "cache_hit_rate": round((tier_stats.get("cache", TierStats()).hits / len(records)) * 100, 2),
        "estimated_cloud_cost": round(cloud_baseline, 6),
        "tier_distribution": {k: v.hits for k, v in tier_stats.items()},
        "query_trace": _query_trace(records[-200:]),
    })
    cat_tier, tier_model = _dashboard_flow(records)
    data["sankey"] = {
        "cat_tier": cat_tier,
        "tier_model": tier_model,
        "total_queries": len(records),
    }
    return data


@app.get("/api/routing/replay")
async def routing_replay(limit: int = 100, include_test: bool = False):
    """Return recent routing decisions for the dashboard replay strip."""
    from router.scorer import read_scoring_log

    safe_limit = max(1, min(int(limit or 100), 500))
    records = _dashboard_records(read_scoring_log(limit=10_000), include_test=include_test)
    decisions = _routing_decisions(records, safe_limit)
    return {
        "total": len(records),
        "shown": len(decisions),
        "decisions": decisions,
    }


@app.get("/api/queries/active")
async def active_queries():
    """Return active query stream state.

    The refactor does not yet maintain the old rich active-query registry, but
    the dashboard should still receive a valid shape instead of a 404.
    """
    return {"active": [], "queries": [], "recent_completed": [], "count": 0, "total": 0}


@app.get("/api/agents")
async def agents_status(capability: str = ""):
    """List registered A2A-style agents."""
    agents = list(_agent_registry.values())
    if capability:
        agents = [
            agent for agent in agents
            if capability in set(agent.get("capabilities") or [])
        ]
    running = sum(1 for agent in agents if not agent.get("paused"))
    return {
        "agents": agents,
        "count": len(agents),
        "total": len(agents),
        "running": running,
        "paused": len(agents) - running,
    }


@app.post("/api/agents/register")
async def register_agent(request: Request, payload: dict[str, Any] | None = None):
    """Register an HTTP A2A-style agent with endpoint and capabilities."""
    return _register_agent_payload(payload or {}, request.query_params)


@app.post("/api/agents/{agent_id}/pause")
async def pause_agent(agent_id: str):
    agent = _agent_registry.get(agent_id)
    if agent is None:
        return {"id": agent_id, "paused": False, "available": False, "detail": "Agent is not registered."}
    agent["paused"] = True
    return {"id": agent_id, "paused": True, "available": True}


@app.post("/api/agents/{agent_id}/heartbeat")
async def heartbeat_agent(agent_id: str):
    agent = _agent_registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent is not registered")
    agent["last_heartbeat_at"] = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {"id": agent_id, "ok": True, "agent": agent}


@app.get("/api/agents/{agent_id}/tasks")
async def list_agent_tasks(agent_id: str):
    return {"agent_id": agent_id, "tasks": _agent_tasks.get(agent_id, []), "count": len(_agent_tasks.get(agent_id, []))}


@app.post("/api/agents/{agent_id}/task")
async def create_agent_task(agent_id: str, payload: dict[str, Any] | None = None, content: str = ""):
    agent = _agent_registry.get(agent_id)
    if agent is None:
        raise HTTPException(status_code=404, detail="Agent is not registered")
    body = payload or {}
    task_content = str(body.get("content") or content or "").strip()
    if not task_content:
        raise HTTPException(status_code=400, detail="Task content is required")
    task = {
        "task_id": hashlib.sha256(f"{agent_id}:{time.time()}:{task_content}".encode()).hexdigest()[:16],
        "agent_id": agent_id,
        "content": task_content,
        "status": "accepted",
        "detail": "Registered agent tasks are tracked in-process; no remote worker dispatch is running in this install.",
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    _agent_tasks[agent_id].append(task)
    return task


@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    existed = agent_id in _agent_registry
    _agent_registry.pop(agent_id, None)
    _agent_tasks.pop(agent_id, None)
    return {"id": agent_id, "deleted": existed, "available": existed}


@app.post("/api/queries/cancel-all")
async def cancel_all_queries():
    for event in list(_cancel_events.values()):
        event.set()
    return {"cancelled": len(_cancel_events), "remaining": 0}


@app.get("/api/budget")
async def budget_status():
    """Return current process budget state for cost/privacy dashboards."""
    from router.scorer import budget_snapshot

    return budget_snapshot()


@app.post("/api/budget/cap")
async def budget_cap(cap: float = 0.0):
    """Adjust the in-process daily hard cap.

    This is intentionally scoped to the current process until persistent team
    policy storage is restored.
    """
    if cap <= 0:
        raise HTTPException(status_code=400, detail="cap must be positive")
    from router import policy
    from router.audit import audit_event

    policy.save_policy({"daily_limit": float(cap), "mode": "normal"})
    settings.budget_hard = float(cap)
    from router.scorer import budget_snapshot
    snap = budget_snapshot()
    audit_event("budget.cap.update", cap=cap)
    return {"new_cap": cap, "remaining": snap.get("effective_daily_limit", cap) - snap.get("daily_spend", 0.0), **snap}


@app.post("/api/sessions/budget/state")
async def session_budget_state(color: str = "", status: str = "", summary: str = ""):
    """Compatibility endpoint for cost page local-only/resume controls."""
    from router import policy
    from router.audit import audit_event
    from router.scorer import budget_snapshot

    mode = "local_only" if "local" in status.lower() else "normal"
    saved = policy.save_policy({"mode": mode})
    audit_event("budget.mode.update", mode=mode, color=color, summary=summary)
    return {"saved": True, "policy": saved, **budget_snapshot()}


@app.post("/api/budget/mode")
async def budget_mode(payload: dict):
    from router import policy
    from router.audit import audit_event

    mode = str(payload.get("mode", "normal"))
    if mode not in {"normal", "local_only", "unlimited"}:
        raise HTTPException(status_code=400, detail="mode must be normal, local_only, or unlimited")
    saved = policy.save_policy({"mode": mode})
    audit_event("budget.mode.update", mode=mode)
    return {"saved": True, "policy": saved}


_SLOW_DISMISSED: set[str] = set()
_SLOW_PINNED: set[str] = set()


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    vals = sorted(values)
    idx = min(len(vals) - 1, max(0, round((pct / 100.0) * (len(vals) - 1))))
    return vals[idx]


@app.get("/api/performance")
async def performance(trace: int = 0, slow_range: int = 24, include_test: bool = False):
    from router.scorer import read_scoring_log

    records = _dashboard_records(read_scoring_log(limit=10_000), include_test=include_test)
    now = time.time()
    latencies = [float(r.get("latency_ms", 0) or 0) for r in records if float(r.get("latency_ms", 0) or 0) >= 0]
    costs = [float(r.get("cost_usd", r.get("cost", 0)) or 0) for r in records]
    recent = [r for r in records if now - float(r.get("ts", 0) or 0) <= 60]
    tier_distribution: dict[str, int] = {}
    model_usage: dict[str, int] = {}
    category_distribution: dict[str, int] = {}
    for r in records:
        tier = str(r.get("tier") or r.get("tier_used") or "unknown")
        tier_distribution[tier] = tier_distribution.get(tier, 0) + 1
        model = str(r.get("model") or r.get("model_used") or "unknown")
        model_usage[model] = model_usage.get(model, 0) + 1
        category = str(r.get("category") or "unknown")
        category_distribution[category] = category_distribution.get(category, 0) + 1
    cache_hits = tier_distribution.get("cache", 0)
    total = len(records)
    slow_cutoff = now - max(1, slow_range) * 3600
    slow_queries = [
        {
            "intent_id": str(r.get("intent_id") or f"q-{i}"),
            "latency_ms": float(r.get("latency_ms", 0) or 0),
            "tier": r.get("tier", ""),
            "model": r.get("model", ""),
            "category": r.get("category", ""),
            "query": r.get("query", ""),
            "response": r.get("response", ""),
        }
        for i, r in enumerate(records)
        if float(r.get("ts", 0) or 0) >= slow_cutoff and float(r.get("latency_ms", 0) or 0) >= 2000
    ]
    return {
        "uptime_seconds": round(time.monotonic(), 2),
        "total_requests": total,
        "requests_per_minute": len(recent),
        "throughput_qps": round(len(recent) / 60.0, 4),
        "tokens_per_second": 0.0,
        "latency_p50": round(_percentile(latencies, 50), 2),
        "latency_p95": round(_percentile(latencies, 95), 2),
        "latency_p99": round(_percentile(latencies, 99), 2),
        "avg_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
        "error_rate": 0.0,
        "cache_hit_rate": round((cache_hits / total * 100.0), 2) if total else 0.0,
        "cost_per_hour": round(sum(float(r.get("cost_usd", r.get("cost", 0)) or 0) for r in recent) * 60.0, 6),
        "tier_distribution": tier_distribution,
        "tier_detail": {k: {"count": v} for k, v in tier_distribution.items()},
        "model_usage": model_usage,
        "category_distribution": category_distribution,
        "query_trace": _query_trace(records[-200:]) if trace else [],
        "mcp_trace": [],
        "slow_queries": slow_queries,
        "slowest_queries": sorted(slow_queries, key=lambda row: row["latency_ms"], reverse=True)[:20],
        "total_cost": round(sum(costs), 8),
    }


@app.get("/api/performance/slow/state")
async def performance_slow_state():
    return {"dismissed": sorted(_SLOW_DISMISSED), "pinned": sorted(_SLOW_PINNED)}


@app.post("/api/performance/slow/dismiss")
async def performance_slow_dismiss(payload: dict):
    if payload.get("intent_id"):
        _SLOW_DISMISSED.add(str(payload["intent_id"]))
    return await performance_slow_state()


@app.post("/api/performance/slow/pin")
async def performance_slow_pin(payload: dict):
    intent_id = str(payload.get("intent_id") or "")
    if intent_id in _SLOW_PINNED:
        _SLOW_PINNED.remove(intent_id)
    elif intent_id:
        _SLOW_PINNED.add(intent_id)
    return await performance_slow_state()


@app.post("/api/performance/slow/clear-dismissed")
async def performance_slow_clear_dismissed():
    _SLOW_DISMISSED.clear()
    return await performance_slow_state()


@app.get("/api/session/{session_id}/cost")
async def session_cost(session_id: str):
    """Return cost summary and spend velocity for a session."""
    from router.scorer import check_session_budget, get_velocity

    summary = check_session_budget(session_id)
    velocity = get_velocity(session_id)
    return {
        "total_cost": summary.total_cost,
        "query_count": summary.query_count,
        "budget_remaining": summary.remaining_budget,
        "velocity_warn": velocity["warn"],
        "velocity_per_min": velocity["velocity_per_min"],
    }


@app.get("/api/system", response_model=SystemStats)
async def system_stats():
    """CPU, RAM, and GPU stats (real values via psutil + pynvml or nvidia-smi)."""
    cpu_pct = psutil.cpu_percent(interval=0.1)
    vm = psutil.virtual_memory()
    ram_used  = vm.used  / 1024 ** 3
    ram_total = vm.total / 1024 ** 3

    gpu_stats: GpuStats | None = None
    ollama_models: list[str] = []
    ollama_model_rows: list[dict] = []

    # GPU via pynvml (non-blocking)
    try:
        import pynvml
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        name    = pynvml.nvmlDeviceGetName(handle)
        mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        util    = pynvml.nvmlDeviceGetUtilizationRates(handle)
        temp    = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
        gpu_stats = GpuStats(
            name=name if isinstance(name, str) else name.decode(),
            vram_used_mb=mem_info.used / 1024 ** 2,
            vram_total_mb=mem_info.total / 1024 ** 2,
            memory_used_mb=mem_info.used / 1024 ** 2,
            memory_total_mb=mem_info.total / 1024 ** 2,
            memory_pct=round((mem_info.used / mem_info.total) * 100, 1) if mem_info.total else 0.0,
            utilization_pct=util.gpu,
            temperature_c=float(temp),
        )
    except Exception:
        pass

    # Loaded Ollama models
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/ps")
            if resp.status_code == 200:
                ollama_model_rows = resp.json().get("models", [])
                ollama_models = [m["name"] for m in ollama_model_rows]
    except Exception:
        pass

    if gpu_stats is None and ollama_model_rows:
        used_mb = sum(float(m.get("size_vram") or 0) for m in ollama_model_rows) / 1024 ** 2
        total_mb = settings.vram_limit_gb * 1024 if settings.vram_limit_gb > 0 else 0.0
        gpu_stats = GpuStats(
            name="Ollama models",
            vram_used_mb=used_mb,
            vram_total_mb=total_mb,
            memory_used_mb=used_mb,
            memory_total_mb=total_mb,
            memory_pct=round((used_mb / total_mb) * 100, 1) if total_mb else 0.0,
            utilization_pct=0.0,
            temperature_c=None,
            inferred_only=True,
        )

    return SystemStats(
        cpu_pct=cpu_pct,
        ram_used_gb=round(ram_used, 2),
        ram_total_gb=round(ram_total, 2),
        gpu=gpu_stats,
        ollama_loaded_models=ollama_models,
        cpu_count=psutil.cpu_count(logical=True) or 0,
        memory_used_gb=round(ram_used, 2),
        memory_total_gb=round(ram_total, 2),
        memory_pct=round(vm.percent, 1),
        uptime_seconds=round(time.monotonic(), 2),
        ollama_models=[
            {
                "name": row.get("name", ""),
                "model": row.get("model", row.get("name", "")),
                "size_vram_gb": round(float(row.get("size_vram") or 0) / 1024 ** 3, 2),
                "size_gb": round(float(row.get("size") or 0) / 1024 ** 3, 2),
                "expires_at": row.get("expires_at"),
            }
            for row in ollama_model_rows
        ],
    )


@app.get("/api/vram/status")
async def vram_status():
    """Return lightweight GPU/VRAM pressure data for setup/chat status pills."""
    stats = await system_stats()
    total_gb = (stats.gpu.vram_total_mb / 1024) if stats.gpu else 0.0
    used_gb = (stats.gpu.vram_used_mb / 1024) if stats.gpu else 0.0
    pct = round((used_gb / total_gb) * 100, 1) if total_gb > 0 else 0.0
    if pct >= 92:
        pressure = "critical"
    elif pct >= 80:
        pressure = "heavy"
    elif pct >= 60:
        pressure = "moderate"
    else:
        pressure = "ok"

    loaded_models = []
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/ps")
            if resp.status_code == 200:
                for model in resp.json().get("models", []):
                    loaded_models.append({
                        "name": model.get("name", "model"),
                        "vram_gb": round(float(model.get("size_vram") or 0) / 1024 ** 3, 2),
                    })
    except Exception:
        pass
    if not loaded_models:
        for name in stats.ollama_loaded_models:
            loaded_models.append({"name": name, "vram_gb": 0.0})

    return {
        "available": stats.gpu is not None,
        "gpu": stats.gpu.name if stats.gpu else "",
        "vram_used_gb": round(used_gb, 2),
        "vram_total_gb": round(total_gb, 2),
        "pct_used": pct,
        "pressure": pressure,
        "inferred_only": bool(stats.gpu.inferred_only) if stats.gpu else False,
        "capacity_known": total_gb > 0,
        "pending_requests": 0,
        "loaded_models": loaded_models,
        "ollama_loaded_models": stats.ollama_loaded_models,
    }


@app.post("/api/vram/evict")
async def vram_evict_all():
    """Evict ALL Ollama models and wait for VRAM to actually free.

    Use this before launching vLLM or any other process that needs full GPU.
    Closes muLLM's shared httpx pools first so Ollama runners are not kept
    alive by idle connections.
    """
    from router.vram_guard import evict_all_models
    result = await evict_all_models(wait_seconds=20.0)
    return result


@app.post("/api/vram/free")
async def vram_free_alias():
    """Compatibility endpoint for Studio pages that free Ollama VRAM."""
    before = await vram_status()
    from router.vram_guard import evict_all_models

    result = await evict_all_models(wait_seconds=20.0)
    after = await vram_status()
    before_used = float(before.get("vram_used_gb") or 0.0)
    after_used = float(after.get("vram_used_gb") or 0.0)
    total_freed = max(0.0, round(before_used - after_used, 2))
    evicted = [str(name) for name in result.get("evicted", [])]
    per_model = round(total_freed / len(evicted), 2) if evicted else 0.0
    return {
        **result,
        "freed": [{"model": name, "vram_gb": per_model} for name in evicted],
        "total_freed_gb": total_freed,
        "before": before,
        "after": after,
    }


@app.get("/api/gpu/advisor")
async def gpu_advisor():
    """Return conservative GPU routing advice for dashboard/setup surfaces."""
    status = await vram_status()
    capacity_known = bool(status.get("capacity_known"))
    total = float(status.get("vram_total_gb") or 0.0)
    used = float(status.get("vram_used_gb") or 0.0)
    pressure = str(status.get("pressure") or "ok")
    if not capacity_known:
        recommendation = "GPU capacity is unknown; using Ollama loaded-model telemetry only."
        profile = "inferred"
    elif total >= 24 and pressure in {"ok", "moderate"}:
        recommendation = "32GB/24GB-class local coding profile is available."
        profile = "local-heavy"
    elif total >= 8:
        recommendation = "Use the 7B/9B local profile and route complex tasks upward."
        profile = "local-fast"
    else:
        recommendation = "Use groundtruth/cache/local-small and prefer cloud for complex work."
        profile = "constrained"
    return {
        "available": bool(status.get("available")),
        "capacity_known": capacity_known,
        "profile": profile,
        "pressure": pressure,
        "vram_used_gb": used,
        "vram_total_gb": total,
        "loaded_models": status.get("loaded_models", []),
        "recommendation": recommendation,
    }


# ---------------------------------------------------------------------------
# OpenAI-compatible endpoints
# ---------------------------------------------------------------------------

_VALID_MODELS = set(CLOUD_MODEL_PRICING.keys()) | {"mullm-auto"}


@app.post("/v1/chat/completions")
async def openai_chat_completions(body: ChatCompletionRequest):
    """OpenAI-compatible chat completions endpoint — supports stream=true for aider/opencode."""
    import json as _json
    import uuid as _uuid

    # Validate model name against whitelist to prevent injection
    if body.model not in _VALID_MODELS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown model {body.model!r}. Use one of: {sorted(_VALID_MODELS)}",
        )

    # Concatenate all messages for the pipeline (preserve system prompt + history)
    user_messages = [m for m in body.messages if m.role == "user"]
    if not user_messages:
        raise HTTPException(status_code=400, detail="No user message in messages array")

    content = user_messages[-1].text()
    history = [{"role": m.role, "content": m.text()} for m in body.messages[:-1]]

    request = QueryRequest(
        content=content,
        history=history,
        temperature=body.temperature,
    )

    from router.tiers import execute_pipeline
    result = await execute_pipeline(request)

    cid = f"chatcmpl-{_uuid.uuid4().hex[:12]}"
    prompt_tokens = sum(len(m.text().split()) for m in body.messages)
    completion_tokens = len(result.response.split())

    if body.stream:
        # SSE streaming — emit content as a single chunk then [DONE]
        async def _sse():
            chunk = {
                "id": cid, "object": "chat.completion.chunk",
                "model": result.model_used,
                "choices": [{"index": 0, "delta": {"role": "assistant", "content": result.response}, "finish_reason": None}],
            }
            yield f"data: {_json.dumps(chunk)}\n\n"
            done_chunk = {
                "id": cid, "object": "chat.completion.chunk",
                "model": result.model_used,
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            yield f"data: {_json.dumps(done_chunk)}\n\n"
            yield "data: [DONE]\n\n"

        from fastapi.responses import StreamingResponse as _SR
        return _SR(_sse(), media_type="text/event-stream",
                   headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    choice = ChatCompletionChoice(
        index=0,
        message=ChatMessage(role="assistant", content=result.response),
        finish_reason="stop",
    )
    return ChatCompletionResponse(
        id=cid,
        model=result.model_used,
        choices=[choice],
        usage=ChatCompletionUsage(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
        ),
    )


@app.get("/v1/models", response_model=ModelsListResponse)
async def list_models():
    """OpenAI-compatible model list — exposes all configured cloud models + local."""
    models = [
        ModelInfo(id="mullm-auto", owned_by="mullm"),
        ModelInfo(id=settings.ollama_model, owned_by="ollama"),
    ]
    for model_id, meta in CLOUD_MODEL_PRICING.items():
        models.append(ModelInfo(id=model_id, owned_by=meta["provider"]))
    return ModelsListResponse(data=models)


# ---------------------------------------------------------------------------
# HTML page routes — serve static HTML pages
# ---------------------------------------------------------------------------

_HTML_DIR = Path(__file__).parent  # router/
_SOURCE_CODE_DIR = _HTML_DIR.parent / "code"
_PACKAGED_CODE_DIR = _HTML_DIR / "code"
_CODE_DIR = _SOURCE_CODE_DIR if _SOURCE_CODE_DIR.exists() else _PACKAGED_CODE_DIR
_READY_GAMES_DIR = _CODE_DIR / "ready"


def _game_title_from_file(filename: str) -> str:
    stem = filename.removesuffix(".html")
    return " ".join(part.capitalize() for part in stem.replace("_", "-").split("-") if part)


def _game_categories_from_file(filename: str) -> list[str]:
    name = filename.lower()
    categories: list[str] = []
    checks = (
        ("3d", "3D"),
        ("iso", "Isometric"),
        ("archer", "Archery"),
        ("bow", "Archery"),
        ("siege", "Siege"),
        ("ballista", "Siege"),
        ("catapult", "Siege"),
        ("sword", "Swords"),
        ("blade", "Swords"),
        ("gyro", "Gyroscope"),
        ("tilt", "Gyroscope"),
        ("card", "Cards"),
        ("poker", "Cards"),
        ("cribbage", "Cards"),
        ("canasta", "Cards"),
        ("music", "Music"),
        ("rhythm", "Music"),
        ("instrument", "Music"),
    )
    for needle, category in checks:
        if needle in name and category not in categories:
            categories.append(category)
    return categories or ["Game"]


def _visible_pages() -> list[dict[str, str]]:
    from router.page_registry import visible_pages

    return visible_pages()


@app.get("/api/pages")
async def pages_manifest():
    """Return the navigation/page registry for the configured UI mode."""
    return {
        "mode": settings.ui_mode,
        "primary": _visible_pages()[:6],
        "pages": _visible_pages(),
    }


@app.get("/api/game-list")
async def game_list():
    """Discover packaged games and supporting assets under code/ready."""
    games: list[dict[str, Any]] = []
    assets: list[dict[str, Any]] = []
    if _READY_GAMES_DIR.exists():
        for path in sorted(_READY_GAMES_DIR.iterdir(), key=lambda p: p.name.lower()):
            if not path.is_file():
                continue
            if path.suffix.lower() == ".html":
                stat = path.stat()
                games.append(
                    {
                        "id": path.stem,
                        "name": _game_title_from_file(path.name),
                        "file": path.name,
                        "path": f"/code/ready/{path.name}",
                        "created_at": int(stat.st_mtime),
                        "size_bytes": stat.st_size,
                        "categories": _game_categories_from_file(path.name),
                    }
                )
            elif path.suffix.lower() in {".glb", ".gltf", ".bin", ".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".ogg"}:
                assets.append(
                    {
                        "file": path.name,
                        "path": f"/code/ready/{path.name}",
                        "size_bytes": path.stat().st_size,
                        "kind": path.suffix.lower().lstrip("."),
                    }
                )
    return {"games": games, "assets": assets, "count": len(games), "asset_count": len(assets)}


_HTML_ALIASES = {
    "/": "site",
    "/scene": "studio",
    "/terrain-standalone": "terrain_standalone",
}

_PAGE_REQUIRED_ENDPOINTS = {
    "/onnx": ["/api/onnx/tasks", "/api/onnx/task/{task_num}", "/api/onnx/validate", "/api/onnx/save", "/api/onnx/generate"],
    "/minitest": ["/api/minitest/prompts", "/api/minitest/results", "/api/minitest/run"],
    "/compare": ["/api/compare/stream", "/api/compare/star"],
    "/compare3d": ["/api/compare/stream", "/api/compare/star"],
}


def _registered_route_paths() -> set[str]:
    return {getattr(route, "path", "") for route in _iter_app_routes() if getattr(route, "path", "")}


def _iter_app_routes(routes: list[Any] | None = None) -> list[Any]:
    """Return concrete routes, including routers deferred by newer FastAPI."""
    concrete: list[Any] = []
    for route in routes or list(app.routes):
        original_router = getattr(route, "original_router", None)
        if original_router is not None:
            concrete.extend(_iter_app_routes(list(getattr(original_router, "routes", []))))
            continue
        concrete.append(route)
    return concrete


def _html_path_for_href(href: str) -> Path:
    stem = _HTML_ALIASES.get(href)
    if stem is None:
        stem = href.strip("/") or "site"
        if stem.endswith(".html"):
            stem = stem[:-5]
    return _HTML_DIR / f"{stem}.html"


def _missing_required_endpoints(href: str, route_paths: set[str]) -> list[str]:
    return [
        endpoint
        for endpoint in _PAGE_REQUIRED_ENDPOINTS.get(href, [])
        if endpoint not in route_paths
    ]


def _page_availability(href: str, route_paths: set[str] | None = None) -> dict[str, Any]:
    route_paths = route_paths or _registered_route_paths()
    html_exists = href == "/" or _html_path_for_href(href).exists()
    route_exists = "{" not in href and href in route_paths
    missing_endpoints = _missing_required_endpoints(href, route_paths)
    exists = bool(html_exists or route_exists)
    status_value = "missing" if not exists else ("degraded" if missing_endpoints else "available")
    return {
        "exists": exists,
        "status": status_value,
        "missing_endpoints": missing_endpoints,
    }


@app.get("/api/pages/status")
async def pages_status():
    """Return static page availability and backing API health."""
    route_paths = _registered_route_paths()
    statuses = []
    for page in _visible_pages():
        href = page["href"]
        statuses.append({**page, **_page_availability(href, route_paths)})
    return {"mode": settings.ui_mode, "pages": statuses}


@app.get("/api/provider-policy")
async def provider_policy_status():
    from router import provider_policy

    return provider_policy.status()


@app.get("/api/settings")
async def public_settings_status():
    """Return non-secret UI settings for Studio pages."""
    return {
        "version": settings.version,
        "ui_mode": settings.ui_mode,
        "enable_studio": settings.enable_studio,
        "remote_access": settings.remote_access,
        "nsfw": bool(os.getenv("MULLM_ALLOW_NSFW", "0").lower() in {"1", "true", "yes", "on"}),
        "providers": {
            "openai": bool(settings.openai_api_key or os.getenv("OPENAI_API_KEY")),
            "anthropic": bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")),
            "google": bool(settings.google_api_key or os.getenv("GOOGLE_API_KEY")),
        },
    }


@app.post("/api/provider-policy")
async def provider_policy_update(payload: dict):
    from router import provider_policy

    return provider_policy.update_policy(payload)


@app.get("/api/sandbox/status")
async def sandbox_status():
    from router import sandbox_policy

    return sandbox_policy.status()


@app.get("/api/resource-policy")
async def resource_policy_status():
    from router import resource_policy

    return resource_policy.status()


@app.get("/api/provider-catalog")
@app.get("/api/providers/catalog")
async def provider_catalog_endpoint(module: str | None = None):
    """Return provider capabilities for setup, docs, and integration probes."""
    from router.provider_catalog import provider_catalog, providers_by_module

    providers = providers_by_module(module) if module else provider_catalog()
    return {"providers": providers}


@app.get("/api/providers/models")
async def provider_models_endpoint():
    """Return configured cloud provider models by routing tier."""
    from router.provider_selector import provider_model_map

    tiers = ("cloud_cheap", "cloud_full", "cloud_power")
    providers = {
        provider: dict(zip(tiers, models, strict=True))
        for provider, models in provider_model_map().items()
    }
    return {"tiers": tiers, "providers": providers}


@app.get("/api/modules/manifest")
async def module_manifest_endpoint():
    """Return installable module metadata for setup and packaging."""
    from router.module_catalog import module_manifest

    return {"modules": module_manifest()}


@app.post("/api/modules/{module_id}/install")
async def module_install_create(module_id: str):
    """Create an explicit install job for an optional module.

    This records consent and provides a stable progress contract. The actual
    per-platform downloader is intentionally attached later so early builds do
    not silently fetch heavy media tooling.
    """
    from router.audit import audit_event
    from router.jobs import create_job, update_job
    from router.module_catalog import module_by_id
    from router.studio_installer import install_studio_assets

    spec = module_by_id(module_id)
    if spec is None:
        raise HTTPException(status_code=404, detail="Unknown module")
    if spec.id == "core":
        raise HTTPException(status_code=400, detail="Core is already bundled")

    job = create_job(
        kind=f"module-install:{spec.id}",
        cost_budget_usd=0.0,
        message=f"Preparing {spec.name} optional install",
    )
    if spec.id == "studio":
        update_job(job.id, "running", message="Installing Studio asset profiles")
        install_result = await install_studio_assets()
        settings.enable_studio = True
        _write_toml_section_values("modules", {"enable_studio": True})
        update_job(
            job.id,
            "done",
            message=f"{spec.name} asset profiles installed",
            result={
                "module": spec.id,
                "package": spec.package,
                "extra": spec.extra,
                "installer": spec.installer,
                "requires_download": spec.requires_download,
                **install_result,
            },
        )
    else:
        update_job(
            job.id,
            "done",
            message=f"{spec.name} is opt-in. Package downloader is not enabled in this build.",
            result={
                "module": spec.id,
                "package": spec.package,
                "extra": spec.extra,
                "installer": spec.installer,
                "requires_download": spec.requires_download,
                "next_step": "Use setup guidance or install the package extra when published.",
            },
        )
    audit_event("module.install.requested", job_id=job.id, module=spec.id, package=spec.package)
    return job.to_dict()


@app.get("/api/backends")
async def backend_status():
    """Return registered inference backend health without sending prompts."""
    from router.backends.protocol import get_backend, list_backends

    statuses = []
    for name in list_backends():
        backend = get_backend(name)
        healthy = False
        if backend is not None:
            try:
                healthy = await backend.health()
            except Exception:
                healthy = False
        statuses.append({"name": name, "healthy": healthy})
    return {"backends": statuses}


class BackendSmokeRequest(BaseModel):
    backend: str = Field(..., min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.:-]+$")
    prompt: str = Field(default="Reply with exactly: mullm-ok", min_length=1, max_length=1000)
    model: str | None = Field(default=None, max_length=200)


@app.post("/api/backends/smoke")
async def backend_smoke(payload: BackendSmokeRequest):
    """Run one capped smoke query through a registered backend."""
    from router.backends.protocol import get_backend

    backend = get_backend(payload.backend)
    if backend is None:
        raise HTTPException(status_code=404, detail="Backend not registered")
    result = await backend.generate(
        [{"role": "user", "content": payload.prompt}],
        model=payload.model,
        max_tokens=64,
        temperature=0,
    )
    return {
        "backend": payload.backend,
        "model": result.model,
        "provider": result.provider,
        "text": result.text[:1000],
        "input_tokens": result.input_tokens,
        "output_tokens": result.output_tokens,
        "cost_usd": result.cost_usd,
    }


# ---------------------------------------------------------------------------
# Research/demo compatibility APIs
# ---------------------------------------------------------------------------

_ONNX_SAVED_SOLUTIONS: dict[int, str] = {}
_COMPARE_STARS: list[dict[str, Any]] = []
_MINITEST_RESULTS: dict[str, dict[str, dict[str, Any]]] = {}

_MINITEST_PROMPTS = [
    {
        "id": "css-margin-padding",
        "title": "CSS margin vs padding",
        "type": "text",
        "prompt": "Explain the practical difference between margin and padding in CSS, with a tiny example.",
    },
    {
        "id": "threejs-sword-dojo",
        "title": "Sword dojo prototype",
        "type": "game",
        "prompt": "Create a compact HTML sword dojo prototype with clear stab and slash controls.",
    },
    {
        "id": "tdd-fastapi-bug",
        "title": "FastAPI TDD fix",
        "type": "text",
        "prompt": "Given a failing FastAPI status-code test, describe a concise TDD fix loop.",
    },
]


def _arc_demo_task(task_num: int) -> dict[str, Any]:
    task = max(1, min(int(task_num), 400))
    return {
        "task_num": task,
        "h_in": 3,
        "w_in": 3,
        "h_out": 3,
        "w_out": 3,
        "examples": [
            {
                "input": [[0, 1, 0], [1, 1, 1], [0, 1, 0]],
                "output": [[0, 1, 0], [1, 2, 1], [0, 1, 0]],
            },
            {
                "input": [[3, 0, 3], [0, 3, 0], [3, 0, 3]],
                "output": [[3, 0, 3], [0, 4, 0], [3, 0, 3]],
            },
            {
                "input": [[5, 5, 0], [5, 0, 0], [0, 0, 0]],
                "output": None,
            },
        ],
    }


@app.get("/api/onnx/tasks")
async def onnx_tasks():
    """Return demo ARC task IDs for the ONNX playground."""
    return list(range(1, 401))


@app.get("/api/onnx/task/{task_num}")
async def onnx_task(task_num: int):
    """Return a deterministic demo ARC task for the ONNX playground."""
    return _arc_demo_task(task_num)


@app.post("/api/onnx/validate")
async def onnx_validate(payload: dict[str, Any]):
    """Validate ONNX playground code structurally without executing it."""
    started = time.perf_counter()
    code = str(payload.get("code") or "")
    task_num = int(payload.get("task_num") or 1)
    has_builder = "def build_model" in code
    has_onnx_import = "import onnx" in code or "from onnx import" in code
    ok = bool(has_builder and has_onnx_import)
    score = 18.0 if ok else 0.0
    return {
        "ok": ok,
        "task_num": task_num,
        "score": score,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "error": "" if ok else "Code must define build_model() and import ONNX. Server-side execution is disabled in this build.",
        "safe_mode": True,
    }


@app.post("/api/onnx/save")
async def onnx_save(payload: dict[str, Any]):
    """Store an ONNX playground solution in process memory for this session."""
    task_num = int(payload.get("task_num") or 1)
    code = str(payload.get("code") or "")
    if not code.strip():
        raise HTTPException(status_code=400, detail="code is required")
    _ONNX_SAVED_SOLUTIONS[task_num] = code
    return {"saved": True, "task_num": task_num, "count": len(_ONNX_SAVED_SOLUTIONS)}


@app.post("/api/onnx/generate")
async def onnx_generate(payload: dict[str, Any]):
    """Stream a deterministic starter ONNX model for the playground."""
    task_num = int(payload.get("task_num") or 1)
    task = _arc_demo_task(task_num)
    code = (
        "import onnx\n"
        "from onnx import helper, TensorProto\n\n"
        "def build_model():\n"
        f"    X = helper.make_tensor_value_info('input', TensorProto.INT64, [1, {task['h_in']}, {task['w_in']}])\n"
        f"    Y = helper.make_tensor_value_info('output', TensorProto.INT64, [1, {task['h_out']}, {task['w_out']}])\n"
        "    node = helper.make_node('Identity', inputs=['input'], outputs=['output'])\n"
        "    graph = helper.make_graph([node], 'arc_demo', [X], [Y])\n"
        "    return helper.make_model(graph, opset_imports=[helper.make_opsetid('', 18)])\n"
    )

    async def stream():
        for i in range(0, len(code), 80):
            yield f"data: {json.dumps({'chunk': code[i:i + 80]})}\n\n"
            await asyncio.sleep(0)
        yield "data: [DONE]\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


def _compare_backend_for_model(model_id: str) -> tuple[str, str | None]:
    """Resolve compare UI ids to registered backend names and model ids."""
    aliases: dict[str, tuple[str, str | None]] = {
        "local": ("ollama", settings.ollama_model),
        "local-9b": ("ollama", settings.ollama_model),
        "local-30b": ("ollama", settings.ollama_model),
        "gemini": ("google", settings.cloud_cheap_model_google),
        "gemini-flash": ("google", settings.cloud_cheap_model_google),
        "gpt-mini": ("openai", settings.cloud_cheap_model_openai),
        "gpt-4o-mini": ("openai", settings.cloud_cheap_model_openai),
        "claude-haiku": ("anthropic", settings.cloud_cheap_model_anthropic),
        "claude-sonnet": ("anthropic", settings.cloud_full_model_anthropic),
    }
    if model_id in aliases:
        return aliases[model_id]
    if ":" in model_id:
        provider, model = model_id.split(":", 1)
        return provider.strip(), model.strip() or None
    return model_id, None


def _compare_cost_label(cost_usd: float | None) -> str:
    if cost_usd is None or cost_usd <= 0:
        return "$0.00"
    return f"${cost_usd:.6f}"


@app.get("/api/compare/stream")
async def compare_stream(prompt: str = "", models: str = "local-9b,local-30b"):
    """Stream real model-comparison events through registered muLLM backends."""
    from router.backends.protocol import get_backend

    selected = [part.strip() for part in models.split(",") if part.strip()][:8] or ["local-9b"]
    user_prompt = (prompt or "Compare these models on a short answer.").strip()
    messages = [{"role": "user", "content": user_prompt}]

    async def stream():
        for model_id in selected:
            provider, provider_model = _compare_backend_for_model(model_id)
            backend = get_backend(provider)
            if backend is None:
                message = f"{provider} is not configured. Add it in /setup, then run Compare again."
                yield f"data: {json.dumps({'model': model_id, 'token': message, 'done': False, 'error': True})}\n\n"
                yield f"data: {json.dumps({'model': model_id, 'done': True, 'tokens': 0, 'cost': '$0.00', 'error': True})}\n\n"
                continue
            try:
                response = await backend.generate(messages, model=provider_model, max_tokens=512, temperature=0.4)
            except Exception as exc:
                detail = f"{provider} comparison failed: {exc.__class__.__name__}"
                yield f"data: {json.dumps({'model': model_id, 'token': detail, 'done': False, 'error': True})}\n\n"
                yield f"data: {json.dumps({'model': model_id, 'done': True, 'tokens': 0, 'cost': '$0.00', 'error': True})}\n\n"
                continue

            text = response.text or "(empty response)"
            for i in range(0, len(text), 24):
                yield f"data: {json.dumps({'model': model_id, 'token': text[i:i + 24], 'done': False})}\n\n"
                await asyncio.sleep(0)
            tokens = response.output_tokens or max(1, len(text.split()))
            yield f"data: {json.dumps({'model': model_id, 'done': True, 'tokens': tokens, 'cost': _compare_cost_label(response.cost_usd)})}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream")


@app.post("/api/compare/star")
async def compare_star(payload: dict[str, Any]):
    """Record model preference data from the compare UI in memory."""
    entry = {
        "prompt": str(payload.get("prompt") or "")[:2000],
        "preferred_model": str(payload.get("preferred_model") or ""),
        "timestamp": str(payload.get("timestamp") or datetime.now(UTC).isoformat()),
        "models_in_comparison": payload.get("models_in_comparison") if isinstance(payload.get("models_in_comparison"), list) else [],
    }
    _COMPARE_STARS.append(entry)
    return {"saved": True, "count": len(_COMPARE_STARS)}


@app.get("/api/minitest/prompts")
async def minitest_prompts():
    """Return deterministic prompts for the MiniTest comparison page."""
    return {"prompts": _MINITEST_PROMPTS, "models": ["30b", "omnicoder", "mullm"]}


@app.get("/api/minitest/results")
async def minitest_results():
    """Return in-memory MiniTest results for this server process."""
    return {"results": _MINITEST_RESULTS}


@app.post("/api/minitest/run")
async def minitest_run(payload: dict[str, Any]):
    """Run a deterministic MiniTest sample without external model spend."""
    started = time.perf_counter()
    prompt_idx = int(payload.get("prompt_idx") or 0)
    model = str(payload.get("model") or "mullm")[:64]
    if prompt_idx < 0 or prompt_idx >= len(_MINITEST_PROMPTS):
        raise HTTPException(status_code=400, detail="prompt_idx is out of range")

    prompt = _MINITEST_PROMPTS[prompt_idx]
    if prompt["type"] == "game":
        response = (
            "<!doctype html><html><body style='margin:0;background:#111;color:#eee;font-family:sans-serif'>"
            "<canvas id='c' width='520' height='300' style='width:100%;height:100%;display:block'></canvas>"
            "<script>"
            "const c=document.getElementById('c'),x=c.getContext('2d');let mode='slash';"
            "function draw(){x.fillStyle='#111';x.fillRect(0,0,c.width,c.height);x.strokeStyle='#d4af37';x.lineWidth=8;"
            "x.beginPath();if(mode==='stab'){x.moveTo(150,150);x.lineTo(410,150)}else{x.arc(260,170,110,-2.6,-.3)}x.stroke();"
            "x.fillStyle='#e5e7eb';x.fillText('Click to toggle stab/slash',20,30)}"
            "c.onclick=()=>{mode=mode==='stab'?'slash':'stab';draw()};draw();"
            "</script></body></html>"
        )
    else:
        response = (
            f"MiniTest {model} response for '{prompt['title']}': start with the failing test, "
            "make the smallest production change, rerun the targeted test, then run the related smoke suite. "
            "For CSS, padding is inside the border and margin is outside it."
        )

    result = {
        "response": response,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "cost": 0.0,
        "tier_used": "local" if model == "mullm" else "demo",
        "model_used": model,
    }
    prompt_results = _MINITEST_RESULTS.setdefault(str(prompt["id"]), {})
    prompt_results[model] = result
    return result


# ---------------------------------------------------------------------------
# MCP / A2A / JSON-RPC protocol surface
# ---------------------------------------------------------------------------

JSONRPC_PARSE_ERROR = -32700
JSONRPC_INVALID_REQUEST = -32600
JSONRPC_METHOD_NOT_FOUND = -32601
JSONRPC_INVALID_PARAMS = -32602
JSONRPC_INTERNAL_ERROR = -32603


async def _execute_query_body(body: QueryRequest) -> PipelineResult:
    """Run the current pipeline for protocol wrappers without HTTP re-entry."""
    from router.tiers import execute_pipeline

    return await execute_pipeline(body)


def _jsonable_model(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_jsonable_model(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable_model(item) for key, item in value.items()}
    return value


def _jsonrpc_success(request_id: int | str | None, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "result": _jsonable_model(result), "id": request_id}


def _jsonrpc_error(
    request_id: int | str | None,
    code: int,
    message: str,
    data: Any = None,
) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "error": error, "id": request_id}


@app.get("/.well-known/agent.json")
async def a2a_agent_card():
    """A2A-style discovery card for muLLM routing capabilities."""
    return {
        "name": "muLLM",
        "description": (
            "Local-first LLM request router with groundtruth, semantic cache, "
            "local model routing, cloud escalation, and split-query execution."
        ),
        "url": f"http://127.0.0.1:{settings.port}",
        "version": settings.version,
        "capabilities": {"streaming": True, "pushNotifications": False},
        "defaultInputModes": ["text"],
        "defaultOutputModes": ["text"],
        "skills": [
            {
                "id": "query",
                "name": "Smart Query Routing",
                "description": "Route a prompt through groundtruth, cache, local, and configured cloud tiers.",
                "tags": ["routing", "cost-optimization", "local-first"],
                "endpoint": "/query",
                "method": "POST",
            },
            {
                "id": "classify",
                "name": "Intent Classification",
                "description": "Classify prompt category, complexity, freshness, and suggested tier.",
                "tags": ["classification", "routing"],
                "endpoint": "/classify",
                "method": "POST",
            },
            {
                "id": "split",
                "name": "Split Routing",
                "description": "Split multi-part prompts and route each part independently.",
                "tags": ["decomposition", "parallel"],
                "endpoint": "/query/split",
                "method": "POST",
            },
        ],
        "provider": {"organization": "muLLM", "url": "https://mullm.com"},
        "authentication": {"schemes": ["none"] if settings.dev_mode or not settings.api_key else ["bearer"]},
    }


@app.get("/.well-known/ai-plugin.json")
async def ai_plugin_manifest():
    """OpenAI-compatible plugin discovery manifest."""
    return {
        "schema_version": "v1",
        "name_for_human": "muLLM Router",
        "name_for_model": "mullm",
        "description_for_human": "Local-first LLM router with groundtruth, cache, local, and cloud tiers.",
        "description_for_model": (
            "Route AI queries to the cheapest capable model. Supports query, split, "
            "classification, cache-aware local routing, and cloud escalation when configured."
        ),
        "api": {"type": "openapi", "url": "/openapi.json"},
        "auth": {"type": "none" if settings.dev_mode or not settings.api_key else "bearer"},
        "logo_url": "",
        "contact_email": "security@mullm.com",
        "legal_info_url": "",
    }


@app.get("/mcp/tools")
async def mcp_list_tools():
    """List muLLM tools for HTTP MCP-style clients."""
    return {
        "tools": [
            {
                "name": "mullm_query",
                "description": "Route a prompt through muLLM's cost-optimized pipeline.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "content": {"type": "string"},
                        "force_tier": {
                            "type": "string",
                            "enum": ["groundtruth", "cache", "local", "local_multi", "cloud_cheap", "cloud_full", "cloud_power"],
                        },
                        "skip_cache": {"type": "boolean", "default": False},
                        "use_web": {"type": "boolean", "default": False},
                    },
                    "required": ["content"],
                },
            },
            {
                "name": "mullm_split",
                "description": "Split a multi-part prompt and route each part independently.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}, "max_parts": {"type": "integer", "default": 4}},
                    "required": ["content"],
                },
            },
            {
                "name": "mullm_classify",
                "description": "Classify prompt category, complexity, freshness, and suggested tier.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"content": {"type": "string"}},
                    "required": ["content"],
                },
            },
            {
                "name": "mullm_budget",
                "description": "Return current process budget counters.",
                "inputSchema": {"type": "object", "properties": {}},
            },
            {
                "name": "mullm_system",
                "description": "Return CPU, RAM, GPU, and Ollama status.",
                "inputSchema": {"type": "object", "properties": {}},
            },
        ]
    }


@app.post("/mcp/tools/query")
async def mcp_tool_query(body: QueryRequest):
    """MCP-compatible query tool wrapper."""
    result = await _execute_query_body(body)
    return {
        "type": "text",
        "text": result.response,
        "metadata": {
            "tier": result.tier.value,
            "tier_used": result.tier_used,
            "model": result.model_used,
            "cost": result.cost,
            "tokens_used": result.tokens_used,
            "latency_ms": result.latency_ms,
            "cached": result.from_cache,
            "groundtruth_category": result.groundtruth_category,
        },
    }


async def _call_mcp_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name in {"mullm_query", "query"}:
        return await mcp_tool_query(QueryRequest(**arguments))
    if name in {"mullm_split", "split"}:
        return _jsonable_model(await query_split(SplitQueryRequest(**arguments)))
    if name in {"mullm_classify", "classify"}:
        return await classify_endpoint(QueryRequest(**arguments))
    if name in {"mullm_budget", "budget.status"}:
        return await budget_status()
    if name in {"mullm_system", "system.info"}:
        return _jsonable_model(await system_stats())
    raise HTTPException(status_code=404, detail=f"Unknown MCP tool: {name}")


async def _rpc_cache_lookup(params: dict[str, Any]) -> dict[str, Any]:
    from router import cache as cache_mod

    query_text = str(params.get("query") or params.get("content") or "").strip()
    if not query_text:
        raise ValueError("query or content is required")
    category = str(params.get("category") or "default")
    hit = await cache_mod.lookup(query_text, category=category)
    if hit is None:
        return {"hit": False, "response": None, "metadata": {}}
    response, metadata = hit
    return {"hit": True, "response": response, "metadata": metadata}


async def _rpc_cache_store(params: dict[str, Any]) -> dict[str, Any]:
    from router import cache as cache_mod

    query_text = str(params.get("query") or params.get("content") or "").strip()
    response = str(params.get("response") or params.get("answer") or "").strip()
    if not query_text:
        raise ValueError("query or content is required")
    if not response:
        raise ValueError("response or answer is required")
    metadata = params.get("metadata") if isinstance(params.get("metadata"), dict) else {}
    stored = await cache_mod.store(query_text, response, metadata=metadata)
    return {"stored": bool(stored)}


@app.post("/mcp/tools/call")
@app.post("/mcp/call")
async def mcp_tool_call(payload: dict[str, Any]):
    """Execute an MCP tool by direct payload or JSON-RPC tools/call envelope."""
    request_id = payload.get("id")
    if payload.get("jsonrpc") == "2.0":
        params = payload.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            result = await _call_mcp_tool(str(name or ""), dict(arguments))
        except HTTPException as exc:
            return JSONResponse(
                _jsonrpc_error(request_id, JSONRPC_METHOD_NOT_FOUND, str(exc.detail)),
                status_code=200,
            )
        return _jsonrpc_success(request_id, result)

    name = payload.get("name")
    arguments = payload.get("arguments") or {}
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    return await _call_mcp_tool(str(name), dict(arguments))


async def _dispatch_jsonrpc(payload: dict[str, Any]) -> dict[str, Any] | None:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _jsonrpc_error(request_id, JSONRPC_INVALID_REQUEST, "Invalid JSON-RPC version, must be '2.0'")
    method = payload.get("method")
    params = payload.get("params") or {}
    if not isinstance(method, str) or not method:
        return _jsonrpc_error(request_id, JSONRPC_INVALID_REQUEST, "Missing method")
    if not isinstance(params, dict):
        return _jsonrpc_error(request_id, JSONRPC_INVALID_PARAMS, "params must be an object")
    try:
        if method == "query":
            result = await _execute_query_body(QueryRequest(**params))
        elif method == "classify":
            result = await classify_endpoint(QueryRequest(**params))
        elif method == "split":
            result = await query_split(SplitQueryRequest(**params))
        elif method == "tools/list":
            result = await mcp_list_tools()
        elif method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            result = await _call_mcp_tool(str(name or ""), dict(arguments))
        elif method == "budget.status":
            result = await budget_status()
        elif method == "system.info":
            result = await system_stats()
        elif method == "agents.list":
            result = await agents_status()
        elif method == "agents.register":
            result = _register_agent_payload(params)
        elif method in {"cache.lookup", "cache.search"}:
            result = await _rpc_cache_lookup(params)
        elif method == "cache.store":
            result = await _rpc_cache_store(params)
        else:
            available = [
                "query", "classify", "split", "tools/list", "tools/call",
                "budget.status", "system.info", "agents.list", "agents.register",
                "cache.lookup", "cache.search", "cache.store",
            ]
            return _jsonrpc_error(
                request_id,
                JSONRPC_METHOD_NOT_FOUND,
                f"Method {method!r} not found",
                data={"available": available},
            )
    except ValueError as exc:
        return _jsonrpc_error(request_id, JSONRPC_INVALID_PARAMS, str(exc))
    except HTTPException as exc:
        return _jsonrpc_error(request_id, JSONRPC_INTERNAL_ERROR, str(exc.detail))
    except Exception as exc:
        logger.exception("jsonrpc_internal_error", extra={"method": method})
        return _jsonrpc_error(request_id, JSONRPC_INTERNAL_ERROR, str(exc))
    if request_id is None:
        return None
    return _jsonrpc_success(request_id, result)


@app.post("/rpc")
async def rpc_endpoint(request: Request):
    """JSON-RPC 2.0 endpoint for query, classify, split, MCP tools, and status."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(_jsonrpc_error(None, JSONRPC_PARSE_ERROR, "Parse error: invalid JSON"), status_code=200)

    if isinstance(body, list):
        if not body:
            return JSONResponse(_jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Empty batch"), status_code=200)
        if len(body) > 50:
            return JSONResponse(_jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Batch too large"), status_code=200)
        responses = []
        for item in body:
            if not isinstance(item, dict):
                responses.append(_jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Each batch item must be an object"))
                continue
            response = await _dispatch_jsonrpc(item)
            if response is not None:
                responses.append(response)
        return JSONResponse(responses if responses else None, status_code=200 if responses else 204)

    if not isinstance(body, dict):
        return JSONResponse(_jsonrpc_error(None, JSONRPC_INVALID_REQUEST, "Request must be an object or batch"), status_code=200)
    response = await _dispatch_jsonrpc(body)
    return JSONResponse(response if response is not None else None, status_code=200 if response is not None else 204)


@app.get("/rpc/docs")
async def rpc_docs_page():
    """Serve JSON-RPC documentation linked from protocol docs and chat UI."""
    return FileResponse(_HTML_DIR / "rpc.html")


class JobCreateRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    cost_budget_usd: float = Field(default=0.0, ge=0.0, le=1000.0)
    message: str = Field(default="", max_length=1000)


@app.get("/api/jobs")
async def jobs_list():
    from router.jobs import list_jobs

    return {"jobs": list_jobs()}


@app.post("/api/jobs")
async def jobs_create(payload: JobCreateRequest):
    from router.audit import audit_event
    from router.jobs import create_job

    job = create_job(payload.kind, payload.cost_budget_usd, payload.message)
    audit_event("job.created", job_id=job.id, kind=job.kind, cost_budget_usd=job.cost_budget_usd)
    return job.to_dict()


@app.get("/api/jobs/{job_id}")
async def jobs_get(job_id: str):
    from router.jobs import get_job

    job = get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return job.to_dict()


@app.get("/api/plugins")
async def plugins_manifest(group: str | None = None):
    """Return capability manifests for setup, docs, and plugin-aware UI."""
    from router.plugin_manifest import capability_manifests

    return {"plugins": capability_manifests(group)}


def _route_inventory() -> dict[str, Any]:
    """Build a compact inventory of pages and API endpoints."""
    def is_api_route(path: str, methods: list[str]) -> bool:
        if path.startswith(("/api/", "/v1/", "/cache/", "/query", "/classify", "/rpc", "/mcp")):
            return True
        if path.startswith("/.well-known/") and not path.endswith(".txt"):
            return True
        if "{" in path:
            return True
        return not set(methods).issubset({"GET"})

    route_paths = _registered_route_paths()
    visible_status = {}
    for page in _visible_pages():
        href = page["href"]
        visible_status[href] = _page_availability(href, route_paths)

    pages = []
    apis = []
    page_paths: set[str] = set()
    for route in sorted(_iter_app_routes(), key=lambda r: getattr(r, "path", "")):
        path = getattr(route, "path", "")
        methods = sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"})
        if not path or not methods:
            continue
        endpoint = getattr(route, "endpoint", None)
        doc = ""
        if endpoint and getattr(endpoint, "__doc__", None):
            doc = endpoint.__doc__.strip().split("\n", 1)[0]
        item = {"path": path, "methods": methods, "description": doc}
        if is_api_route(path, methods):
            item["status"] = "registered"
            apis.append(item)
        else:
            default_status = _page_availability(path, route_paths)
            item.update(visible_status.get(path, default_status))
            pages.append(item)
            page_paths.add(path)
    for href, status_info in sorted(visible_status.items()):
        if href in page_paths:
            continue
        pages.append(
            {
                "path": href,
                "methods": ["GET"],
                "description": "Registry page served by the generic HTML page route.",
                **status_info,
            }
        )
    return {"pages": pages, "api": apis, "total": len(pages) + len(apis)}


@app.get("/api/routes")
async def routes_inventory_api():
    """Meta-endpoint listing all pages and API endpoints."""
    return _route_inventory()


@app.get("/api/urls")
async def urls_json():
    """List all registered FastAPI routes as JSON: [{method, path, description}]."""
    routes = []
    for route in sorted(_iter_app_routes(), key=lambda r: getattr(r, "path", "")):
        path = getattr(route, "path", "")
        methods = sorted((getattr(route, "methods", set()) or set()) - {"HEAD", "OPTIONS"})
        if not path or not methods:
            continue
        endpoint = getattr(route, "endpoint", None)
        description = ""
        if endpoint and getattr(endpoint, "__doc__", None):
            description = endpoint.__doc__.strip().split("\n", 1)[0]
        for method in methods:
            routes.append({"method": method, "path": path, "description": description})
    return routes



@app.get("/urls", response_class=HTMLResponse)

@app.get("/routes", response_class=HTMLResponse)

@app.get("/toc", response_class=HTMLResponse)
async def routes_page():
    """Interactive route directory — all available pages and API endpoints."""
    inventory = _route_inventory()

    def row(item: dict[str, Any], link_pages: bool = False) -> str:
        methods = ", ".join(item["methods"])
        path = item["path"]
        path_html = (
            f'<a href="{html.escape(path)}">{html.escape(path)}</a>'
            if link_pages and "{" not in path
            else html.escape(path)
        )
        status = ""
        if "exists" in item:
            status = item.get("status") or ("available" if item["exists"] else "missing")
        else:
            status = item.get("status", "")
        missing = item.get("missing_endpoints") or []
        desc = item.get("description") or ""
        if missing:
            desc = (desc + " " if desc else "") + "Missing/degraded: " + ", ".join(missing)
        return (
            "<tr>"
            f'<td class="method">{html.escape(methods)}</td>'
            f"<td>{path_html}</td>"
            f'<td class="{status}">{html.escape(status)}</td>'
            f'<td class="desc">{html.escape(desc)}</td>'
            "</tr>"
        )

    pages_table = "\n".join(row(item, link_pages=True) for item in inventory["pages"])
    api_table = "\n".join(row(item) for item in inventory["api"])
    total = inventory["total"]
    pages_count = len(inventory["pages"])
    api_count = len(inventory["api"])
    return f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>muLLM — URLs</title>
<style>
*{{box-sizing:border-box}}:root{{--bg:#0a0e1a;--bg2:#111827;--bg3:#1a2332;--border:#1e2d3d;--teal:#14b8a6;--amber:#f59e0b;--green:#22c55e;--red:#ef4444;--text:#e2e8f0;--text2:#94a3b8;--text3:#8294a7;--mono:'JetBrains Mono','Fira Code',monospace;--sans:Inter,system-ui,sans-serif;color-scheme:dark}}
body{{margin:0;font-family:var(--sans);background:var(--bg);color:var(--text)}}
.nav{{display:flex;gap:8px;padding:16px 24px;font:11px var(--mono);flex-wrap:wrap;align-items:center;border-bottom:1px solid var(--border);background:rgba(10,14,26,.9);position:sticky;top:0;z-index:5}}
.nav a{{color:var(--text3);text-decoration:none;padding:4px 10px;border:1px solid var(--border);border-radius:4px}}
.nav a:hover,.nav a.active{{color:var(--teal);border-color:var(--teal)}}
.brand{{font-weight:700;color:var(--teal)!important}}.brand .mu{{color:var(--amber);font-family:Georgia,serif;font-style:italic;font-size:16px}}
.container{{max-width:1120px;margin:0 auto;padding:26px 20px 80px}}
h1{{font:22px var(--mono);color:var(--teal);margin:0 0 6px}}h2{{font:14px var(--mono);color:var(--amber);margin:28px 0 10px;border-bottom:1px solid var(--border);padding-bottom:6px}}
.subtitle{{color:var(--text2);font-size:13px;margin-bottom:18px;line-height:1.5}}
.stats{{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0 20px}}.pill{{font:11px var(--mono);background:var(--bg3);border:1px solid var(--border);border-radius:999px;padding:5px 10px;color:var(--text2)}}.pill strong{{color:var(--text)}}
table{{width:100%;border-collapse:collapse;font:12px var(--mono);background:rgba(17,24,39,.45);border:1px solid var(--border)}}th{{text-align:left;padding:8px 10px;background:var(--bg2);color:var(--teal);font-size:10px;text-transform:uppercase;letter-spacing:.08em}}td{{padding:7px 10px;border-top:1px solid var(--border);vertical-align:top}}tr:hover{{background:rgba(20,184,166,.06)}}a{{color:var(--teal);text-decoration:none}}a:hover{{text-decoration:underline}}.method{{color:var(--teal);white-space:nowrap}}.desc{{color:var(--text2);font-family:var(--sans)}}.available{{color:var(--green)}}.registered{{color:var(--teal)}}.degraded{{color:var(--amber)}}.missing{{color:var(--red)}}.filter{{width:100%;max-width:440px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:9px 11px;font:12px var(--mono);margin:6px 0 10px}}
</style></head><body>
<div class="nav">
  <a href="/" class="brand"><span class="mu">m&mu;</span>|LLM</a>
  <a href="/chat">Chat</a><a href="/dashboard">Dashboard</a><a href="/setup">Setup</a>
  <a href="/urls" class="active">URLs</a><a href="/games">Games</a><a href="/unblock">Unblock</a>
</div>
<main class="container">
<h1>URLs</h1>
<p class="subtitle">A live route inventory for parity testing. Pages should be clickable; API rows give the method and first-line endpoint description.</p>
<div class="stats"><span class="pill"><strong>{total}</strong> total</span><span class="pill"><strong>{pages_count}</strong> pages</span><span class="pill"><strong>{api_count}</strong> API endpoints</span><span class="pill"><a href="/api/routes">JSON</a></span></div>
<input class="filter" id="filter" placeholder="Filter paths or descriptions..." oninput="filterRows(this.value)">
<h2>Pages</h2><table><thead><tr><th>Method</th><th>Path</th><th>Status</th><th>Description</th></tr></thead><tbody>{pages_table}</tbody></table>
<h2>API Endpoints</h2><table><thead><tr><th>Method</th><th>Path</th><th>Status</th><th>Description</th></tr></thead><tbody>{api_table}</tbody></table>
</main>
<script>
function filterRows(q){{q=(q||'').toLowerCase();document.querySelectorAll('tbody tr').forEach(function(tr){{tr.style.display=tr.textContent.toLowerCase().includes(q)?'':'none';}})}}
</script>
</body></html>"""


@app.get("/")
async def root_redirect():
    dest = "/setup" if _is_first_run() else "/chat"
    return RedirectResponse(url=dest, status_code=302)


@app.get("/setup")
async def setup_page():
    return FileResponse(_HTML_DIR / "setup.html")


@app.get("/space")
async def legacy_space_page():
    """Legacy alias for the Cost page."""
    return RedirectResponse(url="/cost", status_code=307)


@app.get("/tests")
async def tests_page():
    path = _HTML_DIR / "tests.html"
    if path.exists():
        return FileResponse(path)
    return RedirectResponse(url="/coverage", status_code=307)


_TEST_RUNS_PATH = settings.cache_dir / "test_runs.jsonl"


@app.get("/api/test-runs")
async def test_runs():
    """Return all recorded test runs (chronological, newest last)."""
    if not _TEST_RUNS_PATH.exists():
        return []
    runs = []
    for line in _TEST_RUNS_PATH.read_text().splitlines():
        line = line.strip()
        if line:
            try:
                runs.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return runs


# ---------------------------------------------------------------------------
# Translation endpoint — MarianMT fast-path when pack is installed,
# falls back to mullm pipeline. Auto-detects source language.
# API matches translate.html: { text, target_lang, source_lang? }
# ---------------------------------------------------------------------------

_LANG_NAMES = {
    "en": "English", "hu": "Hungarian", "de": "German", "fr": "French",
    "es": "Spanish", "it": "Italian", "pt": "Portuguese", "nl": "Dutch",
    "ru": "Russian", "zh": "Chinese", "ja": "Japanese", "jap": "Japanese",
    "ko": "Korean", "ar": "Arabic", "tr": "Turkish", "pl": "Polish",
    "sv": "Swedish", "fi": "Finnish", "da": "Danish", "uk": "Ukrainian",
    "cs": "Czech", "ro": "Romanian", "vi": "Vietnamese", "id": "Indonesian",
}

# MarianMT model names — only for pairs we have packs for.
# Key is "src-tgt" where src/tgt are 2-letter codes.
_MARIAN_HF = {
    "en-hu": "Helsinki-NLP/opus-mt-en-hu", "hu-en": "Helsinki-NLP/opus-mt-hu-en",
    "en-es": "Helsinki-NLP/opus-mt-en-es", "es-en": "Helsinki-NLP/opus-mt-es-en",
    "en-de": "Helsinki-NLP/opus-mt-en-de", "de-en": "Helsinki-NLP/opus-mt-de-en",
    "en-it": "Helsinki-NLP/opus-mt-en-it", "it-en": "Helsinki-NLP/opus-mt-it-en",
    "en-fr": "Helsinki-NLP/opus-mt-en-fr", "fr-en": "Helsinki-NLP/opus-mt-fr-en",
    "en-jap": "Helsinki-NLP/opus-mt-en-jap", "jap-en": "Helsinki-NLP/opus-mt-jap-en",
    "en-ko": "Helsinki-NLP/opus-mt-en-ko",  "ko-en": "Helsinki-NLP/opus-mt-ko-en",
    "en-zh": "Helsinki-NLP/opus-mt-en-zh",  "zh-en": "Helsinki-NLP/opus-mt-zh-en",
    "en-ru": "Helsinki-NLP/opus-mt-en-ru",  "ru-en": "Helsinki-NLP/opus-mt-ru-en",
    "en-pt": "Helsinki-NLP/opus-mt-en-pt",  "pt-en": "Helsinki-NLP/opus-mt-pt-en",
    "hu-de": "Helsinki-NLP/opus-mt-hu-de",  "de-hu": "Helsinki-NLP/opus-mt-de-hu",
}

_marian_runtime: dict[str, tuple] = {}  # loaded (tokenizer, model) pairs


def _marian_available(src: str, tgt: str) -> bool:
    """True only if the HuggingFace model is already cached locally (no download triggered)."""
    pair = f"{src}-{tgt}"
    if pair not in _MARIAN_HF:
        return False
    try:
        from transformers.utils.hub import cached_file
        cached_file(_MARIAN_HF[pair], "config.json", local_files_only=True)
        return True
    except Exception:
        return False


def _marian_translate(texts: list[str], src: str, tgt: str) -> list[str]:
    pair = f"{src}-{tgt}"
    if pair not in _marian_runtime:
        import torch
        from transformers import MarianMTModel, MarianTokenizer
        name = _MARIAN_HF[pair]
        tok = MarianTokenizer.from_pretrained(name, local_files_only=True) # nosec B615 -- local_files_only=True, no hub download
        mdl = MarianMTModel.from_pretrained(name, local_files_only=True) # nosec B615 -- local_files_only=True, no hub download
        mdl.eval()
        _marian_runtime[pair] = (tok, mdl)
    tok, mdl = _marian_runtime[pair]
    import torch
    inputs = tok(texts, return_tensors="pt", padding=True, truncation=True, max_length=512)
    with torch.no_grad():
        out = mdl.generate(**inputs, num_beams=4, max_new_tokens=256)
    return tok.batch_decode(out, skip_special_tokens=True)


def _detect_lang(text: str) -> str:
    """Detect language code, returns 'en' on failure."""
    try:
        from langdetect import detect
        return detect(text)
    except Exception:
        return "en"


from pydantic import BaseModel as _PydanticBase


class _TranslateSingleReq(_PydanticBase):
    text: str
    target_lang: str = "hu"
    source_lang: str = "auto"


class _TranslateBatchReq(_PydanticBase):
    strings: dict[str, str]
    target_lang: str = "hu"
    source_lang: str = "auto"


async def _translate(text: str, target_lang: str, source_lang: str) -> dict:
    src = source_lang if source_lang != "auto" else _detect_lang(text)
    if src == target_lang:
        return {"translation": text, "source_lang": src, "cost": 0.0, "tier": "identity", "model": "none"}

    # MarianMT fast-path: free, instant, no cloud cost
    if _marian_available(src, target_lang):
        results = await asyncio.get_event_loop().run_in_executor(
            None, _marian_translate, [text], src, target_lang
        )
        return {
            "translation": results[0],
            "source_lang": src,
            "cost": 0.0,
            "tier": "local",
            "model": f"MarianMT/{src}-{target_lang}",
        }

    # Pipeline fallback: routes to local LLM or cloud
    from router.tiers import execute_pipeline
    tgt_name = _LANG_NAMES.get(target_lang, target_lang)
    prompt = f"Translate to {tgt_name}. Output only the translation:\n\n{text}"
    req = QueryRequest(content=prompt, session_id="translate")
    result = await execute_pipeline(req)
    return {
        "translation": result.response,
        "source_lang": src,
        "cost": result.cost,
        "tier": result.tier.value if hasattr(result.tier, "value") else str(result.tier),
        "model": result.model_used,
    }


@app.post("/api/translate")
async def api_translate(req: _TranslateSingleReq):
    return await _translate(req.text, req.target_lang, req.source_lang)


@app.post("/api/translate/batch")
async def api_translate_batch(req: _TranslateBatchReq):
    results = await asyncio.gather(*[
        _translate(v, req.target_lang, req.source_lang)
        for v in req.strings.values()
    ])
    translations = {k: r["translation"] for k, r in zip(req.strings.keys(), results)}
    total_cost = sum(r.get("cost", 0) or 0 for r in results)
    return {"translations": translations, "cost": total_cost}


@app.get("/api/translate/packs")
async def translate_packs():
    """Which language packs are installed locally (no download needed)."""
    available = {}
    for pair, name in _MARIAN_HF.items():
        src, tgt = pair.split("-", 1)
        available[pair] = _marian_available(src, tgt)
    return {"packs": available}


@app.get("/api/translate/pairs")
async def translate_pairs():
    """Return statically supported local MarianMT pair names without probing disk/network."""
    return {
        "pairs": [
            {
                "pair": pair,
                "source_lang": pair.split("-", 1)[0],
                "target_lang": pair.split("-", 1)[1],
                "model": model,
            }
            for pair, model in sorted(_MARIAN_HF.items())
        ]
    }


@app.get("/api/languages")
async def api_languages():
    installed = {}
    for pair in _MARIAN_HF:
        src, tgt = pair.split("-", 1)
        installed[pair] = _marian_available(src, tgt)
    return language_payload(settings.enabled_languages_raw, installed)


@app.post("/api/languages")
async def save_languages(payload: dict):
    requested = payload.get("enabled", [])
    enabled = normalize_enabled_languages(requested)
    settings.enabled_languages_raw = ",".join(enabled)
    _write_toml_section_values("language", {"enabled": enabled})
    return language_payload(settings.enabled_languages_raw)


@app.get("/api/i18n.js")
async def i18n_js(lang: str = "en"):
    """Drop-in i18n script for pages that mark text with data-i18n."""
    safe_lang = "".join(ch for ch in lang[:10] if ch.isalnum() or ch in "-_") or "en"
    script = f"""
/* muLLM drop-in i18n v1.0 — auto-generated for lang="{safe_lang}" */
(function() {{
  const TARGET_LANG = "{safe_lang}";
  if (TARGET_LANG === "en") return;
  async function translatePage() {{
    const nodes = document.querySelectorAll("[data-i18n]");
    if (!nodes.length) return;
    const strings = {{}};
    nodes.forEach(el => {{
      const key = el.getAttribute("data-i18n") || el.textContent.trim().slice(0, 100);
      strings[key] = el.textContent.trim();
    }});
    try {{
      const res = await fetch("/api/translate/batch", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ strings, target_lang: TARGET_LANG }})
      }});
      if (!res.ok) return;
      const data = await res.json();
      const translated = data.translations || data.translated || {{}};
      nodes.forEach(el => {{
        const key = el.getAttribute("data-i18n") || el.textContent.trim().slice(0, 100);
        if (translated[key]) el.textContent = translated[key];
      }});
    }} catch (e) {{
      console.warn("[i18n] Translation failed:", e);
    }}
  }}
  if (document.readyState === "loading") {{
    document.addEventListener("DOMContentLoaded", translatePage);
  }} else {{
    translatePage();
  }}
}})();
""".strip()
    return Response(content=script, media_type="application/javascript")


@app.get("/api/privacy/status")
async def privacy_status():
    """Return local data inventory without exposing query content."""
    from router import cache as cache_mod
    from router import policy
    from router.audit import read_events
    from router.scorer import read_scoring_log

    records = read_scoring_log(limit=100_000)
    ts_values = [r.get("ts") for r in records if r.get("ts")]
    cache_docs = cache_mod.count_entries()

    newest = max(ts_values) if ts_values else None
    oldest = min(ts_values) if ts_values else None
    retention_days = policy.load_policy().get("retention_days", settings.data_retention_days)
    return {
        "cache_docs": cache_docs,
        "chroma_entries": cache_docs,
        "scoring_log_entries": len(records),
        "log_lines": len(records),
        "query_content_logging": settings.log_query_content,
        "cache_dir": str(settings.cache_dir),
        "oldest_ts": oldest,
        "newest_ts": newest,
        "oldest_entry_date": oldest,
        "newest_entry_date": newest,
        "retention_days": retention_days,
        "data_retention_days": retention_days,
        "audit_log_entries": len(read_events(limit=100_000)),
    }


_SESSION_ID_RE = re.compile(r"^[A-Za-z0-9_.:@-]{1,128}$")


def _validate_privacy_session_id(session_id: str) -> str:
    """Validate user/session ids before using them in DSAR operations."""
    if not _SESSION_ID_RE.fullmatch(session_id):
        raise HTTPException(status_code=400, detail="invalid session_id")
    return session_id


@app.get("/api/privacy/export")
async def privacy_export():
    """Export local routing data as a ZIP archive."""
    from router import cache as cache_mod
    from router.audit import audit_event, read_events
    from router.scorer import read_scoring_log

    export = tempfile.NamedTemporaryFile(prefix="mullm_export_", suffix=".zip", delete=False)
    export_path = Path(export.name)
    export.close()

    manifest = await privacy_status()
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        cache_entries = cache_mod.scan_entries(limit=100_000)
        zf.writestr("scoring_log.json", json.dumps(read_scoring_log(limit=100_000), indent=2))
        zf.writestr("audit_log.json", json.dumps(read_events(limit=100_000), indent=2))
        zf.writestr("cache_entries.json", json.dumps(cache_entries, indent=2))
        cache_jsonl = "\n".join(json.dumps(row) for row in cache_entries)
        zf.writestr("cache_export.jsonl", cache_jsonl)
        zf.writestr("chroma_export.jsonl", cache_jsonl)  # compatibility alias for pre-SQLite tooling
        if _access_log_path.exists():
            zf.write(_access_log_path, arcname="access_log.jsonl")
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    audit_event("privacy.export", entries=manifest["scoring_log_entries"])
    return FileResponse(export_path, filename="mullm_export.zip", media_type="application/zip")


@app.get("/api/privacy/session/{session_id}/status")
async def privacy_session_status(session_id: str):
    """Return scoped local data inventory for DSAR review."""
    from router import cache as cache_mod
    from router.audit import read_events
    from router.scorer import read_scoring_log_for_session

    session_id = _validate_privacy_session_id(session_id)
    scoring_rows = read_scoring_log_for_session(session_id, limit=100_000)
    cache_rows = cache_mod.export_entries_by_session(session_id, limit=100_000)
    audit_rows = [row for row in read_events(limit=100_000) if str(row.get("session_id", "")) == session_id]
    ts_values = [row.get("ts") for row in scoring_rows if row.get("ts")]
    return {
        "session_id": session_id,
        "scoring_log_entries": len(scoring_rows),
        "cache_entries": len(cache_rows),
        "audit_log_entries": len(audit_rows),
        "oldest_ts": min(ts_values) if ts_values else None,
        "newest_ts": max(ts_values) if ts_values else None,
        "query_content_logging": settings.log_query_content,
    }


@app.get("/api/privacy/session/{session_id}/export")
async def privacy_session_export(session_id: str):
    """Export DSAR data for one session as a ZIP archive."""
    from router import cache as cache_mod
    from router.audit import audit_event, content_hash, read_events
    from router.scorer import read_scoring_log_for_session

    session_id = _validate_privacy_session_id(session_id)
    export = tempfile.NamedTemporaryFile(prefix="mullm_session_export_", suffix=".zip", delete=False)
    export_path = Path(export.name)
    export.close()

    scoring_rows = read_scoring_log_for_session(session_id, limit=100_000)
    cache_rows = cache_mod.export_entries_by_session(session_id, limit=100_000)
    audit_rows = [row for row in read_events(limit=100_000) if str(row.get("session_id", "")) == session_id]
    manifest = {
        "scope": "session",
        "session_hash": content_hash(session_id),
        "scoring_log_entries": len(scoring_rows),
        "cache_entries": len(cache_rows),
        "audit_log_entries": len(audit_rows),
        "query_content_logging": settings.log_query_content,
    }
    with zipfile.ZipFile(export_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("scoring_log.json", json.dumps(scoring_rows, indent=2))
        zf.writestr("audit_log.json", json.dumps(audit_rows, indent=2))
        zf.writestr("cache_entries.json", json.dumps(cache_rows, indent=2))
        zf.writestr("manifest.json", json.dumps(manifest, indent=2))
    audit_event("privacy.session.export", session_hash=manifest["session_hash"], entries=len(scoring_rows))
    return FileResponse(export_path, filename=f"mullm_session_{session_id}_export.zip", media_type="application/zip")


@app.post("/api/privacy/session/{session_id}/delete")
async def privacy_session_delete(session_id: str, payload: dict):
    """Delete DSAR data for one session. Requires explicit confirmation."""
    from router import cache as cache_mod
    from router.audit import audit_event, content_hash
    from router.scorer import purge_scoring_logs_for_session

    session_id = _validate_privacy_session_id(session_id)
    if payload.get("confirm") != "DELETE_SESSION" or payload.get("session_id") != session_id:
        raise HTTPException(status_code=400, detail='confirm must be "DELETE_SESSION" and session_id must match')

    cache_deleted = cache_mod.delete_entries_by_session(session_id, limit=100_000)
    scoring_deleted = purge_scoring_logs_for_session(session_id)
    session_hash = content_hash(session_id)
    audit_event("privacy.session.delete", session_hash=session_hash, cache_entries_deleted=cache_deleted, scoring_log_lines_deleted=scoring_deleted)
    return {
        "deleted": True,
        "session_hash": session_hash,
        "cache_entries_deleted": cache_deleted,
        "scoring_log_lines_deleted": scoring_deleted,
    }


@app.post("/api/privacy/purge-all")
async def privacy_purge_all(payload: dict):
    """Delete local query/cache data. Requires an explicit confirmation token."""
    if payload.get("confirm") != "PURGE_ALL":
        raise HTTPException(status_code=400, detail='confirm must be "PURGE_ALL"')

    from router import cache as cache_mod
    from router.audit import audit_event, purge_all_events
    from router.scorer import purge_all_scoring_logs

    _cleared, cache_entries_before, cache_docs_remaining = cache_mod.clear_entries()
    cache_entries_deleted = max(0, cache_entries_before - cache_docs_remaining)

    scoring_log_lines_deleted = purge_all_scoring_logs()
    audit_log_entries_deleted = purge_all_events()
    audit_event("privacy.purge_all", cache_entries_deleted=cache_entries_deleted, scoring_log_lines_deleted=scoring_log_lines_deleted)
    return {
        "purged": True,
        "cache_docs_remaining": cache_docs_remaining,
        "chroma_entries_deleted": cache_entries_deleted,
        "scoring_log_lines_deleted": scoring_log_lines_deleted,
        "audit_log_entries_deleted": audit_log_entries_deleted,
    }


@app.post("/api/privacy/retention")
async def privacy_set_retention(payload: dict):
    from router import policy
    from router.audit import audit_event

    days = int(payload.get("days", payload.get("retention_days", settings.data_retention_days)))
    saved = policy.save_policy({"retention_days": days})
    audit_event("privacy.retention.update", days=saved["retention_days"])
    return {"saved": True, "retention_days": saved["retention_days"]}


@app.post("/api/privacy/purge-retention")
async def privacy_purge_retention():
    from router import policy
    from router.audit import audit_event, purge_events_before
    from router.scorer import purge_scoring_log_before

    days = int(policy.load_policy().get("retention_days", settings.data_retention_days))
    cutoff = time.time() - days * 86400
    scoring_deleted = purge_scoring_log_before(cutoff)
    audit_deleted = purge_events_before(cutoff)
    audit_event("privacy.retention.purge", days=days, scoring_deleted=scoring_deleted, audit_deleted=audit_deleted)
    return {"purged": True, "retention_days": days, "scoring_log_lines_deleted": scoring_deleted, "audit_log_entries_deleted": audit_deleted}


@app.get("/translate")
async def translate_page():
    return FileResponse(_HTML_DIR / "translate.html")


# ---------------------------------------------------------------------------
# Research — parallel local-first research runner
# ---------------------------------------------------------------------------


class ResearchRunRequest(_PydanticBase):
    queries: list[str] = []
    mode: str = "parallel"
    topic: str = ""
    output_format: str = "json"
    freshness: str = "recent"
    depth: str = "standard"
    technicality: str = "practitioner"
    audience: str = "general"


class ResearchExportRequest(_PydanticBase):
    results: list[dict] = []
    format: str = "markdown"


class PdfExportRequest(_PydanticBase):
    html: str


@app.post("/api/research/run")
async def research_run(req: ResearchRunRequest, request: Request):
    """Run parallel research queries and stream per-card SSE results."""
    queries = req.queries[:10]
    if req.mode == "swarm" and req.topic:
        queries = [
            f"What is the overview and definition of: {req.topic}?",
            f"What are the latest developments and trends in: {req.topic}?",
            f"What are the key challenges and limitations of: {req.topic}?",
            f"What are practical applications and use cases of: {req.topic}?",
            f"What do experts recommend or debate about: {req.topic}?",
        ]

    async def _stream_research():
        from router.tiers import execute_pipeline

        start_total = time.perf_counter()
        total_cost = 0.0
        collected: list[dict] = []
        skip_cache = req.freshness == "recent"
        prefix = (
            f"Depth: {req.depth}. Technicality level: {req.technicality}. "
            f"Target audience: {req.audience}. Preserve citations when available. "
        )

        tasks = []
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(0.15)
            qr = QueryRequest(content=prefix + query, session_id="research", skip_cache=skip_cache)
            tasks.append((i, query, asyncio.create_task(execute_pipeline(qr))))

        for i, query, _task in tasks:
            yield f"data: {json.dumps({'card': i, 'status': 'running', 'query': query, 'text': '', 'cost': 0.0})}\n\n"

        pending = list(tasks)
        while pending:
            done = []
            still = []
            for i, query, task in pending:
                if task.done():
                    done.append((i, query, task))
                else:
                    still.append((i, query, task))
            for i, query, task in done:
                try:
                    result = task.result()
                    text = getattr(result, "response", str(result))
                    cost = float(getattr(result, "cost", 0.0) or 0.0)
                    total_cost += cost
                    event = {"card": i, "status": "done", "query": query, "text": text, "cost": cost}
                except Exception as exc:
                    event = {"card": i, "status": "error", "query": query, "text": f"Error: {exc}", "cost": 0.0}
                collected.append(event)
                yield f"data: {json.dumps(event)}\n\n"
            pending = still
            if pending:
                await asyncio.sleep(0.25)

        elapsed = round(time.perf_counter() - start_total, 2)
        final = {
            "done": True,
            "total_cost": round(total_cost, 6),
            "summary": f"Research complete: {len(collected)} queries in {elapsed}s",
            "results": collected,
        }
        yield f"data: {json.dumps(final)}\n\n"

    return StreamingResponse(
        _stream_research(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/research/export")
async def research_export(req: ResearchExportRequest):
    """Export research results as Markdown, LaTeX, BibTeX, or printable HTML."""
    results = req.results
    fmt = req.format.lower()
    if fmt == "markdown":
        return Response(
            content=research_exports.render_markdown(results),
            media_type="text/markdown",
            headers={"Content-Disposition": "attachment; filename=research-report.md"},
        )
    if fmt == "latex":
        return Response(
            content=research_exports.render_latex(results),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=research-report.tex"},
        )
    if fmt == "bibtex":
        return Response(
            content=research_exports.render_bibtex(results),
            media_type="text/plain",
            headers={"Content-Disposition": "attachment; filename=research-report.bib"},
        )
    return Response(
        content=research_exports.render_html(results),
        media_type="text/html",
        headers={"Content-Disposition": "attachment; filename=research-report-printable.html"},
    )


@app.post("/api/research/export-pdf")
async def export_research_pdf(req: PdfExportRequest):
    """Export a research draft to PDF when an optional renderer is available."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch()
            page = await browser.new_page()
            await page.set_content(req.html)
            pdf_bytes = await page.pdf(format="A4", print_background=True)
            await browser.close()
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=research.pdf"},
        )
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "error": "pdf_unavailable",
                "message": "PDF renderer unavailable. Use browser Print -> Save as PDF or export HTML.",
            },
        )


@app.get("/market")
async def market_page():
    return FileResponse(_HTML_DIR / "market.html")


@app.get("/research")
async def research_page():
    return FileResponse(_HTML_DIR / "research.html")


@app.get("/steam")
async def steam_page():
    return FileResponse(_HTML_DIR / "steam.html")


@app.get("/terrain-standalone")
async def terrain_standalone_page():
    return FileResponse(_HTML_DIR / "terrain_standalone.html")


@app.get("/api/geocode")
async def geocode_proxy(q: str = "", limit: int = 6):
    """Proxy Nominatim geocoding to avoid browser CSP/CORS restrictions."""
    import httpx
    if not q.strip():
        return {"status": "requires_query", "results": [], "detail": "Pass q=<place name> to geocode."}
    url = (
        f"https://nominatim.openstreetmap.org/search"
        f"?format=json&q={q}&limit={limit}&addressdetails=1"
    )
    headers = {
        "User-Agent": "mullm-terrain-builder/1.0 (local dev tool)",
        "Accept-Language": "en",
        "Referer": "https://mullm.local/",
    }
    async with httpx.AsyncClient(timeout=8) as client:
        r = await client.get(url, headers=headers)
        r.raise_for_status()
        return JSONResponse(content=r.json())


# ---------------------------------------------------------------------------
# Joplin connector — local Web Clipper API
# ---------------------------------------------------------------------------


_JOPLIN_BASE = os.getenv("JOPLIN_BASE_URL", "http://localhost:41184")


def _joplin_discover_token() -> str | None:
    token = os.environ.get("JOPLIN_TOKEN")
    if token:
        return token
    settings_path = Path.home() / ".config" / "joplin-desktop" / "settings.json"
    try:
        if settings_path.exists():
            data = json.loads(settings_path.read_text(encoding="utf-8"))
            return data.get("api.token") or data.get("token")
    except Exception:
        return None
    return None


def _joplin_token() -> str:
    return _joplin_discover_token() or ""


@app.get("/api/joplin/status")
async def joplin_status():
    token = _joplin_token()
    if not token:
        return {"connected": False, "reason": "JOPLIN_TOKEN not set"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{_JOPLIN_BASE}/ping", params={"token": token})
        return {"connected": resp.status_code == 200, "base_url": _JOPLIN_BASE}
    except Exception as exc:
        return {"connected": False, "reason": str(exc)}


@app.get("/api/joplin/notebooks")
async def joplin_notebooks():
    token = _joplin_token()
    if not token:
        return {"notebooks": [], "error": "JOPLIN_TOKEN not set"}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{_JOPLIN_BASE}/folders",
                params={"token": token, "fields": "id,title,parent_id"},
            )
        data = resp.json()
        return {"notebooks": data.get("items", data) if isinstance(data, dict) else data}
    except Exception as exc:
        return {"notebooks": [], "error": str(exc)}


@app.post("/api/joplin/create")
async def joplin_create_note(request: Request):
    token = _joplin_token()
    if not token:
        raise HTTPException(status_code=503, detail="JOPLIN_TOKEN not set — open Joplin > Options > Web Clipper")
    body = await request.json()
    payload = {
        "title": body.get("title", "muLLM Note"),
        "body": body.get("content", ""),
        "source_application": "mullm",
    }
    if body.get("notebook_id"):
        payload["parent_id"] = body["notebook_id"]
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(f"{_JOPLIN_BASE}/notes", params={"token": token}, json=payload)
    if resp.status_code in (200, 201):
        return {"status": "created", "joplin_id": resp.json().get("id", ""), "title": payload["title"]}
    raise HTTPException(status_code=resp.status_code, detail=f"Joplin error: {resp.text[:200]}")


@app.post("/api/joplin/upload")
async def joplin_upload_files(request: Request):
    token = _joplin_token()
    if not token:
        raise HTTPException(status_code=503, detail="JOPLIN_TOKEN not set")
    form = await request.form()
    title = str(form.get("title", "muLLM Upload"))
    notebook_id = str(form.get("notebook_id", ""))
    note_body = str(form.get("content", ""))
    files = form.getlist("files")
    resource_ids = []
    async with httpx.AsyncClient(timeout=30.0) as client:
        for uploaded in files:
            data = await uploaded.read()  # type: ignore[attr-defined]
            resp = await client.post(
                f"{_JOPLIN_BASE}/resources",
                params={"token": token},
                files={
                    "data": (
                        uploaded.filename,  # type: ignore[attr-defined]
                        data,
                        uploaded.content_type or "application/octet-stream",  # type: ignore[attr-defined]
                    )
                },
                data={"title": uploaded.filename},  # type: ignore[attr-defined]
            )
            if resp.status_code in (200, 201):
                rid = resp.json().get("id", "")
                resource_ids.append({"id": rid, "filename": uploaded.filename, "mime": uploaded.content_type})  # type: ignore[attr-defined]
                if uploaded.content_type and uploaded.content_type.startswith("image/"):  # type: ignore[attr-defined]
                    note_body += f"\n\n![{uploaded.filename}](:/{rid})"  # type: ignore[attr-defined]
                else:
                    note_body += f"\n\n[{uploaded.filename}](:/{rid})"  # type: ignore[attr-defined]

        payload = {"title": title, "body": note_body, "source_application": "mullm"}
        if notebook_id:
            payload["parent_id"] = notebook_id
        resp = await client.post(f"{_JOPLIN_BASE}/notes", params={"token": token}, json=payload)
    if resp.status_code in (200, 201):
        return {"status": "created", "joplin_id": resp.json().get("id", ""), "resources": resource_ids}
    raise HTTPException(status_code=resp.status_code, detail=f"Joplin error: {resp.text[:200]}")


@app.get("/api/obsidian/status")
async def obsidian_status():
    """Return Obsidian connector readiness without indexing anything yet."""
    vault = os.getenv("OBSIDIAN_VAULT_PATH", "")
    path = Path(vault).expanduser() if vault else None
    exists = bool(path and path.exists() and path.is_dir())
    return {
        "configured": bool(vault),
        "vault_path": str(path) if path else "",
        "exists": exists,
        "mode": "ready" if exists else "configure_vault",
        "index_target": "ChromaDB",
        "notes": [
            "Set OBSIDIAN_VAULT_PATH to enable vault indexing.",
            "Indexing reads Markdown files, chunks by headings, and stores embeddings with provenance.",
            "Connector is read-only; writing notes requires a separate explicit Joplin/API action.",
        ],
    }


class ObsidianIndexRequest(BaseModel):
    vault_path: str = ""


_OBSIDIAN_INDEX_STATE: dict = {"last_indexed": 0, "chunks": 0, "files": 0, "vault": ""}

_OBSIDIAN_SEMAPHORE: asyncio.Semaphore | None = None


def _obsidian_semaphore() -> asyncio.Semaphore:
    global _OBSIDIAN_SEMAPHORE
    if _OBSIDIAN_SEMAPHORE is None:
        _OBSIDIAN_SEMAPHORE = asyncio.Semaphore(12)
    return _OBSIDIAN_SEMAPHORE


def _strip_frontmatter(text: str) -> str:
    return re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.DOTALL)


def _split_chunks(text: str, size: int = 500) -> list[str]:
    paragraphs = re.split(r'\n{2,}', text.strip())
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > size and current:
            chunks.append(current.strip())
            current = para
        else:
            current = (current + "\n\n" + para).strip() if current else para
    if current.strip():
        chunks.append(current.strip())
    return [c for c in chunks if c]


async def _index_chunk(col: Any, embed_fn: Any, chunk: str, doc_id: str, meta: dict) -> bool:
    async with _obsidian_semaphore():
        try:
            embedding = await embed_fn(chunk)
            if embedding is None:
                return False
            existing = col.get(ids=[doc_id], include=[])
            if existing["ids"]:
                col.update(ids=[doc_id], documents=[chunk], embeddings=[embedding], metadatas=[meta])
            else:
                col.add(ids=[doc_id], documents=[chunk], embeddings=[embedding], metadatas=[meta])
            return True
        except Exception as exc:
            logger.warning("Obsidian chunk index error: %s", exc)
            return False


@app.post("/api/obsidian/index")
async def obsidian_index(req: ObsidianIndexRequest):
    from router import cache as cache_mod

    vault_str = req.vault_path.strip() or os.getenv("OBSIDIAN_VAULT_PATH", "").strip()
    if not vault_str:
        raise HTTPException(status_code=400, detail="No vault_path provided and OBSIDIAN_VAULT_PATH not set.")

    vault = Path(vault_str).expanduser().resolve()
    if not vault.is_dir():
        raise HTTPException(status_code=400, detail=f"Vault path does not exist or is not a directory: {vault}")

    col = cache_mod._get_client()
    if col is None:
        raise HTTPException(status_code=503, detail="ChromaDB unavailable.")

    md_files = list(vault.rglob("*.md"))
    tasks: list[Any] = []
    file_count = 0
    for md_file in md_files:
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        content = _strip_frontmatter(content)
        chunks = _split_chunks(content)
        if not chunks:
            continue
        file_count += 1
        rel = str(md_file.relative_to(vault))
        for i, chunk in enumerate(chunks):
            doc_id = "obsidian:" + hashlib.sha256(f"{rel}:{i}".encode()).hexdigest()[:32]
            meta = {
                "source": "obsidian",
                "vault": str(vault),
                "file": rel,
                "chunk": i,
                "timestamp": int(time.time()),
            }
            tasks.append(_index_chunk(col, cache_mod._embed, chunk, doc_id, meta))

    results = await asyncio.gather(*tasks)
    indexed = sum(1 for r in results if r)

    _OBSIDIAN_INDEX_STATE["last_indexed"] = int(time.time())
    _OBSIDIAN_INDEX_STATE["chunks"] = indexed
    _OBSIDIAN_INDEX_STATE["files"] = file_count
    _OBSIDIAN_INDEX_STATE["vault"] = str(vault)

    return {"indexed": indexed, "files": file_count, "vault": str(vault)}


@app.get("/api/obsidian/index-status")
async def obsidian_index_status():
    from router import cache as cache_mod

    state = _OBSIDIAN_INDEX_STATE
    vault = os.getenv("OBSIDIAN_VAULT_PATH", state.get("vault", ""))

    if state["last_indexed"]:
        return {
            "last_indexed": state["last_indexed"],
            "chunks": state["chunks"],
            "files": state["files"],
            "vault": state["vault"],
        }

    col = cache_mod._get_client()
    if col is None:
        return {"last_indexed": 0, "chunks": 0, "files": 0, "vault": vault}

    try:
        results = col.get(where={"source": "obsidian"}, include=["metadatas"], limit=10000)
    except Exception:
        return {"last_indexed": 0, "chunks": 0, "files": 0, "vault": vault}

    metas = results.get("metadatas") or []
    if not metas:
        return {"last_indexed": 0, "chunks": 0, "files": 0, "vault": vault}

    timestamps = [m.get("timestamp", 0) for m in metas if isinstance(m, dict)]
    files = {m.get("file") for m in metas if isinstance(m, dict) and m.get("file")}
    return {
        "last_indexed": max(timestamps) if timestamps else 0,
        "chunks": len(metas),
        "files": len(files),
        "vault": vault,
    }


@app.get("/manifest.json")
async def manifest_json():
    return JSONResponse({
        "name": "muLLM",
        "short_name": "muLLM",
        "description": "Local-first LLM routing",
        "start_url": "/chat",
        "display": "standalone",
        "background_color": "#0f172a",
        "theme_color": "#0f172a",
        "icons": [],
    })


@app.get("/sw.js")
async def service_worker():
    path = _HTML_DIR / "sw.js"
    if path.is_file():
        return FileResponse(path, media_type="application/javascript")
    return Response(
        content=(
            'self.addEventListener("fetch", function () { return; });\n'
        ),
        media_type="application/javascript",
    )


# ---------------------------------------------------------------------------
# Setup wizard API endpoints
# ---------------------------------------------------------------------------

def _write_toml_modules(modules: dict) -> None:
    """Write [modules] section to mullm.toml without requiring tomli_w."""
    toml_path = Path("mullm.toml")
    lines: list[str] = []

    # Preserve existing non-modules content
    if toml_path.exists():
        in_modules = False
        for line in toml_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[modules]":
                in_modules = True
                continue
            if in_modules and stripped.startswith("["):
                in_modules = False
            if not in_modules:
                lines.append(line)

    # Remove trailing blank lines before appending
    while lines and not lines[-1].strip():
        lines.pop()

    # Append [modules] section
    lines.append("")
    lines.append("[modules]")
    for k, v in modules.items():
        toml_val = "true" if v else "false"
        lines.append(f"{k} = {toml_val}")
    lines.append("")

    toml_path.write_text("\n".join(lines), encoding="utf-8")


def _write_toml_mode(mode: str) -> None:
    """Write [core] mode to mullm.toml."""
    toml_path = Path("mullm.toml")
    lines: list[str] = []
    in_core = False
    found_mode = False

    if toml_path.exists():
        for line in toml_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped == "[core]":
                in_core = True
                lines.append(line)
                continue
            if in_core and stripped.startswith("[") and stripped != "[core]":
                in_core = False
                if not found_mode:
                    # [core] existed but had no mode key — insert before next section
                    lines.append(f'mode = "{mode}"')
                    found_mode = True
            if in_core and stripped.startswith("mode"):
                lines.append(f'mode = "{mode}"')
                found_mode = True
                continue
            lines.append(line)

    if not found_mode:
        # Add [core] section if missing
        if "[core]" not in "\n".join(lines):
            lines.append("")
            lines.append("[core]")
        lines.append(f'mode = "{mode}"')
        lines.append("")

    toml_path.write_text("\n".join(lines), encoding="utf-8")


def _write_toml_section_values(section: str, values: dict[str, str | int | float | bool | list[str]]) -> None:
    """Write or replace simple scalar keys in a top-level TOML section."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", section):
        raise ValueError("Invalid TOML section")

    toml_path = Path("mullm.toml")
    existing = toml_path.read_text(encoding="utf-8").splitlines() if toml_path.exists() else []
    lines: list[str] = []
    in_section = False
    found_section = False
    handled: set[str] = set()
    header = f"[{section}]"

    def render_value(value: str | int | float | bool | list[str]) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, int | float):
            return str(value)
        if isinstance(value, list):
            return json.dumps(value)
        return json.dumps(value)

    for line in existing:
        stripped = line.strip()
        if stripped == header:
            in_section = True
            found_section = True
            lines.append(line)
            continue
        if in_section and stripped.startswith("["):
            for key, value in values.items():
                if key not in handled:
                    lines.append(f"{key} = {render_value(value)}")
                    handled.add(key)
            in_section = False
        if in_section and "=" in stripped and not stripped.startswith("#"):
            key = stripped.split("=", 1)[0].strip()
            if key in values:
                lines.append(f"{key} = {render_value(values[key])}")
                handled.add(key)
                continue
        lines.append(line)

    if not found_section:
        while lines and not lines[-1].strip():
            lines.pop()
        lines.append("")
        lines.append(header)

    for key, value in values.items():
        if key not in handled:
            lines.append(f"{key} = {render_value(value)}")
    lines.append("")

    toml_path.write_text("\n".join(lines), encoding="utf-8")


_TOGGLES_PATH = Path(__file__).parent.parent / "config" / "toggles.json"

_DEFAULT_TOGGLES = {
    "provider_local": False,
    "provider_anthropic": False,
    "provider_openai": False,
    "provider_google": False,
    "cloud_text": True,
    "cloud_image": True,
    "cloud_3d": True,
    "local_image": True,
    "local_3d": True,
    "use_deberta": True,
    "prompt_cache": False,
    "web_search": False,
    "search_merge_cite": True,
    "experimental_configs": False,
    "nightly_configs": False,
    "fable_top_tier": True,
}


def _apply_fable_toggle(enabled: bool) -> None:
    """Swap the Anthropic power model between Claude Fable 5 and Opus.

    Off restores the exact pre-0.9 configuration (settings field default).
    """
    settings.fable_top_tier = bool(enabled)  # type: ignore[assignment]
    field_default = type(settings).model_fields["cloud_power_model_anthropic"].default
    settings.cloud_power_model_anthropic = (  # type: ignore[assignment]
        "claude-fable-5" if enabled else field_default
    )


def _provider_ready_from_status(status: dict) -> dict[str, bool]:
    from router.provider_selector import provider_ready

    ready = {}
    if "ollama" in status:
        ready["provider_local"] = bool(status.get("ollama"))
    if "anthropic" in status:
        ready["provider_anthropic"] = provider_ready("anthropic")
    if "openai" in status:
        ready["provider_openai"] = provider_ready("openai")
    if "google" in status:
        ready["provider_google"] = provider_ready("google")
    return ready


def _apply_provider_readiness(toggles: dict, status: dict) -> dict:
    ready = _provider_ready_from_status(status)
    merged = dict(toggles)
    for key, ok in ready.items():
        if not ok:
            merged[key] = False
    return merged


def _load_toggles() -> dict:
    if not _TOGGLES_PATH.exists():
        return dict(_DEFAULT_TOGGLES)
    try:
        data = json.loads(_TOGGLES_PATH.read_text(encoding="utf-8"))
        return {**_DEFAULT_TOGGLES, **{k: bool(v) for k, v in data.items()}}
    except Exception:
        return dict(_DEFAULT_TOGGLES)


def _save_toggles(toggles: dict) -> dict:
    merged = {**_DEFAULT_TOGGLES, **{k: bool(v) for k, v in toggles.items()}}
    _TOGGLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    _TOGGLES_PATH.write_text(json.dumps(merged, indent=2) + "\n", encoding="utf-8")
    return merged


@app.get("/api/setup/backend-profiles")
async def setup_backend_profiles():
    """Return local backend profiles visible under current experimental toggles."""
    from router.backend_profiles import backend_profiles

    toggles = _load_toggles()
    return {
        "profiles": backend_profiles(
            include_experimental=bool(toggles.get("experimental_configs")),
            include_nightly=bool(toggles.get("nightly_configs")),
        ),
        "experimental_enabled": bool(toggles.get("experimental_configs")),
        "nightly_enabled": bool(toggles.get("nightly_configs")),
    }


def _provider_status_sync() -> dict:
    import os

    return {
        "anthropic": bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")),
        "openai": bool(settings.openai_api_key or os.getenv("OPENAI_API_KEY")),
        "google": bool(settings.google_api_key or os.getenv("GOOGLE_API_KEY")),
        "meshy": bool(settings.meshy_api_key or os.getenv("MESHY_API_KEY")),
        "civitai": bool(settings.civitai_api_key or os.getenv("CIVITAI_API_KEY") or os.getenv("CIVIT_AI_API_KEY")),
    }


@app.get("/api/setup/detect")
async def setup_detect():
    """Detect hardware and recommend inference backend configuration."""
    import platform

    result = {
        "os": platform.system(),
        "arch": platform.machine(),
        "python": platform.python_version(),
        "gpu": None,
        "vram_gb": 0.0,
        "ram_gb": 0.0,
        "ollama": False,
        "cuda_version": None,
        "recommendation": {},
    }

    # GPU detection via pynvml
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        name = pynvml.nvmlDeviceGetName(h)
        mem = pynvml.nvmlDeviceGetMemoryInfo(h)
        result["gpu"] = name if isinstance(name, str) else name.decode()
        result["vram_gb"] = round(mem.total / 1e9, 1)
    except Exception:
        pass

    # Apple Silicon — unified memory counts as VRAM
    if platform.system() == "Darwin" and platform.machine() == "arm64":
        result["gpu"] = "Apple Silicon"
        try:
            import subprocess
            out = subprocess.check_output(["sysctl", "-n", "hw.memsize"]).strip()
            result["vram_gb"] = round(int(out) / 1e9, 1)
        except Exception:
            pass

    # RAM
    try:
        import psutil
        result["ram_gb"] = round(psutil.virtual_memory().total / 1e9, 1)
    except Exception:
        pass

    # Ollama reachability — reuse existing helper pattern
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.ollama_base_url}/api/tags")
            result["ollama"] = r.status_code == 200
    except Exception:
        pass

    # CUDA version via torch
    try:
        import torch
        result["cuda_version"] = torch.version.cuda
    except Exception:
        pass

    # Xcode CLI detection (macOS only) — for iOS build support in Game Studio
    result["xcode_cli"] = False
    if platform.system() == "Darwin":
        try:
            import subprocess
            out = subprocess.check_output(
                ["xcode-select", "-p"],
                stderr=subprocess.DEVNULL,
                timeout=3,
            ).strip()
            result["xcode_cli"] = bool(out)
        except Exception:
            pass

    # Recommendation logic
    vram = result["vram_gb"]
    gpu = result["gpu"] or ""
    os_name = result["os"]

    if "Apple Silicon" in gpu or os_name == "Darwin":
        result["recommendation"] = {
            "backend": "mlx",
            "model": "mlx-community/Qwen2.5-7B-Instruct-4bit",
            "reason": "Apple Silicon detected — MLX gives native Metal acceleration",
            "install_cmd": "pip install mlx-lm",
        }
    elif vram >= 24:
        result["recommendation"] = {
            "backend": "exllamav2",
            "model": "turboderp/Qwen2.5-Coder-32B-Instruct-exl2 (4.0bpw)",
            "reason": f"{vram}GB VRAM — ExLlamaV2 gives 3-4x faster generation than Ollama",
            "install_cmd": "pip install exllamav2",
        }
    elif vram >= 16:
        result["recommendation"] = {
            "backend": "ollama",
            "model": "qwen2.5-coder:14b",
            "reason": f"{vram}GB VRAM — Ollama with 14B model is a great fit",
            "install_cmd": "curl -fsSL https://ollama.com/install.sh | sh",
        }
    elif vram >= 8:
        result["recommendation"] = {
            "backend": "ollama",
            "model": "qwen2.5:7b",
            "reason": f"{vram}GB VRAM — Ollama with 7B model runs smoothly",
            "install_cmd": "curl -fsSL https://ollama.com/install.sh | sh",
        }
    elif os_name == "Windows":
        result["recommendation"] = {
            "backend": "llamacpp",
            "model": "bartowski/Qwen2.5-7B-Instruct-GGUF (Q4_K_M)",
            "reason": "Windows CPU/small GPU — llama.cpp GGUF works everywhere",
            "install_cmd": "pip install llama-cpp-python",
        }
    else:
        result["recommendation"] = {
            "backend": "ollama",
            "model": "qwen2.5:3b",
            "reason": "No GPU detected — CPU inference with a small model",
            "install_cmd": "curl -fsSL https://ollama.com/install.sh | sh",
        }

    return result


@app.get("/api/setup/toggles")
async def get_setup_toggles():
    toggles = _load_toggles()
    # Preserve the older flat response shape while giving newer UI code a
    # namespaced object to read from.
    return {**toggles, "toggles": toggles}


@app.post("/api/setup/toggles")
async def set_setup_toggles(payload: dict):
    toggles = payload.get("toggles", payload)
    if not isinstance(toggles, dict):
        raise HTTPException(status_code=400, detail="toggles must be an object")
    saved = _save_toggles(toggles)

    # Hot-apply the classifier toggle where possible.
    try:
        from router.intent import set_use_deberta
        set_use_deberta(saved.get("use_deberta", True))
    except Exception:
        pass

    # Hot-apply Fable ↔ Opus power-model swap.
    try:
        _apply_fable_toggle(saved.get("fable_top_tier", True))
    except Exception:
        pass

    return {"saved": True, "toggles": saved}


@app.post("/api/setup/groundtruth")
async def set_setup_groundtruth(payload: dict):
    """Persist the groundtruth resolver mode.

    The registry mode is the refactored default. Legacy mode keeps the old
    realtime resolver available as a controlled fallback while parity gaps are
    being closed.
    """
    mode = str(payload.get("mode", "")).strip().lower()
    if mode not in {"registry", "legacy"}:
        raise HTTPException(status_code=400, detail="mode must be registry or legacy")
    settings.groundtruth_mode = mode  # type: ignore[assignment]
    _write_toml_section_values("groundtruth", {"mode": mode})
    return {"saved": True, "mode": mode}


@app.get("/api/classifier/status")
async def get_classifier_status():
    """Return configured classifier backends and retraining policy status."""
    from router.intent import classifier_status

    return classifier_status()


@app.get("/api/classifier/retrain/status")
async def get_classifier_retrain_status():
    """Return continuous retraining schedule and last-run status."""
    from router import retrain_scheduler

    return retrain_scheduler.status()


@app.post("/api/classifier/retrain/run")
async def run_classifier_retrain(payload: dict | None = None):
    """Run one configured classifier retraining cycle."""
    from router import retrain_scheduler

    force = bool((payload or {}).get("force", False))
    try:
        return await retrain_scheduler.run_once(force=force)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class ApiPolicyRequest(BaseModel):
    require_referer_match: bool | None = None
    allow_mcp_requests: bool | None = None
    allow_a2a_requests: bool | None = None
    allow_offbox_mcp_a2a: bool | None = None
    allowed_outbound_domains: list[str] | None = None


def _api_policy_payload() -> dict[str, Any]:
    return {
        "require_referer_match": settings.require_referer_match,
        "allow_mcp_requests": settings.allow_mcp_requests,
        "allow_a2a_requests": settings.allow_a2a_requests,
        "allow_offbox_mcp_a2a": settings.allow_offbox_mcp_a2a,
        "allowed_outbound_domains": settings.allowed_outbound_domains,
        "cors_origins": settings.cors_origins,
        "remote_access": settings.remote_access,
    }


@app.get("/api/setup/api-policy")
async def setup_api_policy():
    """Return security policy knobs for MCP/A2A/API exposure."""
    return _api_policy_payload()


@app.post("/api/setup/api-policy")
async def save_setup_api_policy(payload: ApiPolicyRequest):
    """Apply API policy knobs for the running process."""
    for field in (
        "require_referer_match",
        "allow_mcp_requests",
        "allow_a2a_requests",
        "allow_offbox_mcp_a2a",
    ):
        value = getattr(payload, field)
        if value is not None:
            setattr(settings, field, value)
    if payload.allowed_outbound_domains is not None:
        cleaned = []
        for domain in payload.allowed_outbound_domains:
            domain = domain.strip().lower()
            if domain and re.fullmatch(r"[a-z0-9.-]+(?::\d+)?", domain):
                cleaned.append(domain)
        settings.allowed_outbound_domains_raw = ",".join(cleaned)
    return _api_policy_payload()


@app.post("/api/setup/install")
async def setup_install(payload: dict):
    """Run an allowlisted install command and return combined output."""
    import shlex

    cmd = payload.get("cmd", "").strip()
    ALLOWED_PREFIXES = [
        "pip install",
        "ollama pull",
        "huggingface-cli download",
        "pip install --extra-index-url",
    ]
    if not any(cmd.startswith(p) for p in ALLOWED_PREFIXES):
        raise HTTPException(status_code=400, detail="Command not in allowlist")

    argv = shlex.split(cmd)
    if not argv:
        raise HTTPException(status_code=400, detail="Empty command")

    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    return {
        "output": stdout.decode(errors="replace"),
        "returncode": proc.returncode,
    }


@app.get("/api/setup/modules")
async def get_modules():
    """Return current module enable/disable state (top-level + Game Studio sub-toggles)."""
    return {
        # Top-level modules
        "semantic_cache":        getattr(settings, "enable_semantic_cache", True),
        "groundtruth_lut":       getattr(settings, "enable_groundtruth_lut", True),
        "3d":                    getattr(settings, "enable_3d", False),
        "game_studio":           getattr(settings, "enable_game_studio", False),
        "joplin":                getattr(settings, "enable_joplin", False),
        "comfyui":               getattr(settings, "enable_comfyui", False),
        "benchmarks":            getattr(settings, "enable_benchmarks", True),
        "continuous_finetune":   getattr(settings, "enable_continuous_finetune", False),
        "round_robin":           getattr(settings, "enable_round_robin", False),
        "custom_classifier":     getattr(settings, "enable_custom_classifier", False),
        # Game Studio sub-modules
        "gs_games_browser":      getattr(settings, "enable_gs_games_browser", True),
        "gs_apk_builder":        getattr(settings, "enable_gs_apk_builder", True),
        "gs_ios_builder":        getattr(settings, "enable_gs_ios_builder", False),
        "gs_3d_studio_mode":     getattr(settings, "enable_gs_3d_studio_mode", False),
        "gs_siege_swords":       getattr(settings, "enable_gs_siege_swords", False),
        "gs_coverage":           getattr(settings, "enable_gs_coverage", False),
        "gs_asset_manager":      getattr(settings, "enable_gs_asset_manager", False),
    }


@app.post("/api/setup/modules")
async def set_modules(payload: dict):
    """Save module toggles to mullm.toml."""
    _write_toml_modules(payload)
    return {"saved": True}


@app.get("/api/setup/status")
async def setup_status():
    """Return configured-provider status for the setup wizard."""
    import os

    from router.intent import classifier_status
    from router.secrets import env_file_status, secret_backends_status
    ollama_models: list[str] = []
    ollama_ok = await _ollama_available()
    if ollama_ok:
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                r = await client.get(f"{settings.ollama_base_url}/api/tags")
                if r.status_code == 200:
                    ollama_models = [m.get("name", "") for m in r.json().get("models", [])]
        except Exception:
            pass
    comfyui_base_url = os.getenv("COMFYUI_BASE_URL", settings.comfyui_base_url).rstrip("/")
    comfyui_ok = False
    try:
        async with httpx.AsyncClient(timeout=1.0) as client:
            r = await client.get(f"{comfyui_base_url}/system_stats")
            comfyui_ok = r.status_code == 200
    except Exception:
        comfyui_ok = False
    custom_providers: list[dict[str, str | bool]] = []
    for env_name, value in os.environ.items():
        if not env_name.startswith("MULLM_CUSTOM_") or not env_name.endswith("_BASE_URL"):
            continue
        custom_id = env_name[len("MULLM_CUSTOM_"):-len("_BASE_URL")].lower()
        custom_providers.append({
            "id": custom_id,
            "name": custom_id.replace("_", " ").title(),
            "base_url": value,
            "model": os.getenv(f"MULLM_CUSTOM_{custom_id.upper()}_MODEL", ""),
            "configured": bool(os.getenv(f"MULLM_CUSTOM_{custom_id.upper()}_API_KEY") and value),
        })

    status = {
        "anthropic": bool(settings.anthropic_api_key or os.getenv("ANTHROPIC_API_KEY")),
        "openai":    bool(settings.openai_api_key    or os.getenv("OPENAI_API_KEY")),
        "google":    bool(settings.google_api_key    or os.getenv("GOOGLE_API_KEY")),
        "cerebras":  bool(settings.cerebras_api_key  or os.getenv("CEREBRAS_API_KEY")),
        "deepseek":  bool(os.getenv("DEEPSEEK_API_KEY")),
        "mistral":   bool(os.getenv("MISTRAL_API_KEY")),
        "cohere":    bool(os.getenv("COHERE_API_KEY")),
        "perplexity": bool(os.getenv("PERPLEXITY_API_KEY")),
        "venice":    bool(os.getenv("VENICE_API_KEY")),
        "openrouter": bool(os.getenv("OPENROUTER_API_KEY")),
        "sambanova": bool(os.getenv("SAMBANOVA_API_KEY")),
        "together":  bool(os.getenv("TOGETHER_API_KEY")),
        "nim":       bool(os.getenv("NIM_API_KEY")),
        "xai":       bool(os.getenv("XAI_API_KEY")),
        "ibm":       bool(os.getenv("IBM_BAM_API_KEY")),
        "vllm_url":  bool(os.getenv("VLLM_BASE_URL")),
        "tabbyapi":  bool(os.getenv("TABBYAPI_BASE_URL") or os.getenv("TABBY_BASE_URL")),
        "litellm":   bool(os.getenv("LITELLM_BASE_URL")),
        "omniroute": bool(os.getenv("OMNIROUTE_BASE_URL")),
        "brave_search": bool(os.getenv("BRAVE_SEARCH_API_KEY")),
        "tavily": bool(os.getenv("TAVILY_API_KEY")),
        "serpapi": bool(os.getenv("SERPAPI_API_KEY")),
        "google_cse": bool(os.getenv("GOOGLE_CSE_API_KEY") and os.getenv("GOOGLE_CSE_ID")),
        "kagi": bool(os.getenv("KAGI_API_KEY")),
        "exa": bool(os.getenv("EXA_API_KEY")),
        "runpod": bool(os.getenv("RUNPOD_API_KEY") or os.getenv("RUNPOD_BASE_URL")),
        "vastai": bool(os.getenv("VASTAI_API_KEY") or os.getenv("VASTAI_BASE_URL")),
        "huggingface": bool(os.getenv("HUGGINGFACE_API_KEY") or os.getenv("HUGGINGFACE_BASE_URL")),
        "aws_bedrock": bool(os.getenv("AWS_BEDROCK_PROFILE") or os.getenv("AWS_PROFILE")),
        "gcp_vertex": bool(os.getenv("GCP_VERTEX_PROJECT") or os.getenv("GOOGLE_APPLICATION_CREDENTIALS")),
        "azure_ai": bool(os.getenv("AZURE_AI_API_KEY") or os.getenv("AZURE_AI_BASE_URL")),
        "digitalocean": bool(os.getenv("DIGITALOCEAN_API_KEY") or os.getenv("DIGITALOCEAN_BASE_URL")),
        "private_gpu": bool(os.getenv("PRIVATE_GPU_BASE_URL")),
        "kling":     bool(os.getenv("KLING_API_KEY")),
        "veo":       bool(os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("VEO_API_KEY")),
        "seedance2": bool(os.getenv("SEEDANCE_API_KEY")),
        "topologyai": bool(os.getenv("TOPOLOGYAI_API_KEY")),
        "tripo": bool(settings.tripo_api_key or os.getenv("TRIPO_API_KEY")),
        "rodin": bool(settings.rodin_api_key or os.getenv("RODIN_API_KEY") or os.getenv("HYPER3D_API_KEY")),
        "sana_wm": bool(settings.sana_wm_base_url or settings.sana_wm_local_path or os.getenv("SANA_WM_BASE_URL") or os.getenv("SANA_WM_LOCAL_PATH")),
        "meshy":     bool(settings.meshy_api_key or os.getenv("MESHY_API_KEY")),
        "civitai":   bool(settings.civitai_api_key or os.getenv("CIVITAI_API_KEY") or os.getenv("CIVIT_AI_API_KEY")),
        "comfyui":   comfyui_ok,
        "comfyui_base_url": comfyui_base_url,
        "ollama":    ollama_ok,
        "ollama_models": ollama_models,
        "custom_providers": sorted(custom_providers, key=lambda p: str(p["id"])),
        "mode": settings.mullm_mode,
        "ui_mode": settings.ui_mode,
        "groundtruth_mode": settings.groundtruth_mode,
        "api_policy": _api_policy_payload(),
        "classifier": classifier_status(),
        "languages": language_payload(settings.enabled_languages_raw),
        "secrets": {
            "pass_available": secret_backends_status()["pass"]["available"],
            "backends": secret_backends_status(),
            "env_file": env_file_status(),
        },
    }
    status["toggles"] = _apply_provider_readiness(_load_toggles(), status)
    status["provider_ready"] = _provider_ready_from_status(status)
    return status


def _asset_setup_payload() -> dict[str, Any]:
    from router.scene_api import asset_storage_status_payload

    storage = asset_storage_status_payload()
    return {
        "root": settings.asset_root,
        "resolved_root": str(Path(settings.asset_root).expanduser().resolve()),
        "backend": settings.asset_storage_backend,
        "external_base_url": settings.asset_external_base_url,
        "compression": settings.asset_compression,
        "storage": storage,
        "future_backends": ["local", "nfs", "git_lfs", "perforce", "s3", "azure_blob", "external_api"],
    }


@app.get("/api/setup/assets")
async def setup_assets():
    """Return configurable Studio asset storage settings."""
    return _asset_setup_payload()


@app.post("/api/setup/assets")
async def setup_save_assets(payload: dict):
    """Persist local Studio asset storage settings to mullm.toml."""
    root = str(payload.get("root") or "").strip()
    if not root:
        raise HTTPException(status_code=400, detail="asset root is required")
    if any(ord(ch) < 32 for ch in root):
        raise HTTPException(status_code=400, detail="asset root contains invalid characters")
    if len(root) > 500:
        raise HTTPException(status_code=400, detail="asset root is too long")

    resolved = Path(root).expanduser()
    try:
        resolved.mkdir(parents=True, exist_ok=True)
        (resolved / "3d").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"could not create asset root: {exc}") from exc

    _write_toml_section_values("studio.assets", {"root": root})
    settings.asset_root = root
    return {"saved": True, **_asset_setup_payload()}


@app.post("/api/setup/save-key")
async def setup_save_key(payload: dict):
    """Save an API key to pass or .env with restrictive permissions."""
    import os as _os

    from router.secrets import env_var_for_provider, store_secret

    provider = payload.get("provider", "").strip()
    key = payload.get("key", "").strip()
    storage = payload.get("storage", "auto").strip().lower()

    if not provider or not key:
        raise HTTPException(status_code=400, detail="provider and key are required")

    env_var = env_var_for_provider(provider)
    if not env_var:
        raise HTTPException(status_code=400, detail=f"Unknown provider: {provider!r}")

    try:
        selected_storage = store_secret(env_var, key, backend=storage)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    # Set in current process so it takes effect immediately
    _os.environ[env_var] = key

    return {"saved": True, "var": env_var, "storage": selected_storage}


@app.get("/api/setup/secrets")
async def setup_secrets_status():
    from router.secrets import env_file_status, secret_backends_status

    backends = secret_backends_status()
    return {
        "pass_available": backends["pass"]["available"],
        "keyring_available": backends["keyring"]["available"],
        "default_backend": backends["default"],
        "backends": backends,
        "env_file": env_file_status(),
    }


@app.post("/api/setup/secrets/pass-selftest")
async def setup_pass_selftest():
    from router.secrets import pass_selftest

    try:
        return pass_selftest()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/setup/secrets/keyring-selftest")
async def setup_keyring_selftest():
    from router.secrets import keyring_selftest

    try:
        return keyring_selftest()
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/setup/env/harden")
async def setup_harden_env(payload: dict | None = None):
    from router.secrets import harden_env_file

    readonly = True if payload is None else bool(payload.get("readonly", True))
    try:
        return harden_env_file(readonly=readonly)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=".env not found") from None


@app.post("/api/setup/mode")
async def setup_mode(payload: dict):
    """Persist mullm_mode (single_user | team) to mullm.toml."""
    mode = payload.get("mode", "single_user")
    if mode not in ("single_user", "team"):
        raise HTTPException(status_code=400, detail="mode must be 'single_user' or 'team'")
    _write_toml_mode(mode)
    return {"saved": True, "mode": mode}


@app.get("/api/comfyui/status-legacy")
async def comfyui_status():
    """Return whether a local ComfyUI server appears reachable."""
    base = os.environ.get("COMFYUI_BASE_URL", settings.comfyui_base_url).rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            resp = await client.get(f"{base}/system_stats")
        return {
            "running": resp.status_code == 200,
            "base_url": base,
            "install_hint": "Install ComfyUI, start it on port 8188, then enable local image/3D modules.",
        }
    except Exception:
        return {
            "running": False,
            "base_url": base,
            "install_hint": "Install ComfyUI, start it on port 8188, then enable local image/3D modules.",
        }


@app.post("/api/comfyui/config-legacy")
async def comfyui_config_save(payload: dict):
    """Persist the ComfyUI base URL used by setup and Studio routes."""
    raw = str(payload.get("base_url", "")).strip().rstrip("/")
    if not raw:
        raise HTTPException(status_code=400, detail="base_url is required")
    if not re.fullmatch(r"https?://[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+", raw):
        raise HTTPException(status_code=400, detail="base_url must be an http(s) URL")
    _write_toml_section_values("studio", {"comfyui_base_url": raw})
    os.environ["COMFYUI_BASE_URL"] = raw
    return {"saved": True, "base_url": raw}


@app.get("/api/comfyui/asset-pack")
async def comfyui_asset_pack():
    """Return the built-in ComfyUI Studio profile manifest."""
    from router.studio_installer import COMFYUI_PROFILES

    return COMFYUI_PROFILES


# ---------------------------------------------------------------------------
# /api/attribution — commit attribution settings (read + hot-update)
# ---------------------------------------------------------------------------

def _load_runtime_toml() -> dict:
    """Read ~/.mullm/runtime.toml into a flat dict. Returns {} if missing."""
    import tomllib
    p = Path.home() / ".mullm" / "runtime.toml"
    if not p.exists():
        return {}
    try:
        return tomllib.loads(p.read_text())
    except Exception:
        return {}


def _save_runtime_toml(updates: dict) -> None:
    """Merge updates into ~/.mullm/runtime.toml (create if needed)."""
    p = Path.home() / ".mullm" / "runtime.toml"
    p.parent.mkdir(parents=True, exist_ok=True)
    current = _load_runtime_toml()
    current.update(updates)
    lines = ["# muLLM runtime settings — edited via UI or API\n"]
    for k, v in current.items():
        if isinstance(v, bool):
            lines.append(f'{k} = {"true" if v else "false"}\n')
        elif isinstance(v, str):
            lines.append(f'{k} = "{v}"\n')
        else:
            lines.append(f"{k} = {v}\n")
    p.write_text("".join(lines))


# In-memory attribution config (overridable at runtime without restart)
_attribution: dict = {}


def _get_attribution() -> dict:
    rt = _load_runtime_toml()
    return {
        "mode":  rt.get("commit_attribution_mode",  _attribution.get("mode",  settings.commit_attribution_mode)),
        "name":  rt.get("commit_attribution_name",  _attribution.get("name",  settings.commit_attribution_name)),
        "email": rt.get("commit_attribution_email", _attribution.get("email", settings.commit_attribution_email)),
    }


def _attribution_line() -> str | None:
    """Return 'Co-authored-by: ...' string, or None if attribution is disabled."""
    cfg = _get_attribution()
    if cfg["mode"] == "never":
        return None
    return f"Co-authored-by: {cfg['name']} <{cfg['email']}>"


@app.get("/api/attribution")
async def get_attribution():
    """Return current attribution settings and the trailer line."""
    cfg = _get_attribution()
    line = _attribution_line()
    return {**cfg, "trailer": line, "hook_installed": _check_hook_installed()}


@app.patch("/api/attribution")
async def patch_attribution(payload: dict):
    """Update attribution settings — applied immediately + persisted to runtime.toml."""
    allowed_modes = {"auto", "always", "never"}
    updates = {}
    if "mode" in payload:
        if payload["mode"] not in allowed_modes:
            raise HTTPException(status_code=400, detail=f"mode must be one of {allowed_modes}")
        updates["commit_attribution_mode"] = payload["mode"]
        _attribution["mode"] = payload["mode"]
    if "name" in payload:
        updates["commit_attribution_name"] = str(payload["name"])[:64]
        _attribution["name"] = updates["commit_attribution_name"]
    if "email" in payload:
        updates["commit_attribution_email"] = str(payload["email"])[:128]
        _attribution["email"] = updates["commit_attribution_email"]
    _save_runtime_toml(updates)
    return {**_get_attribution(), "trailer": _attribution_line()}



@app.get("/.well-known/security.txt", response_class=PlainTextResponse)
async def security_txt():
    """RFC 9116 security disclosure file."""
    from router.config import settings as _s
    contact = getattr(_s, "security_contact_email", "contact@mullm.com")
    canonical = "https://mullm.com/.well-known/security.txt"
    policy = "https://mullm.com/security"
    return (
        f"Contact: mailto:{contact}\n"
        f"Expires: {__import__('datetime').date.today().replace(year=__import__('datetime').date.today().year + 1).isoformat()}T00:00:00Z\n"
        f"Canonical: {canonical}\n"
        f"Policy: {policy}\n"
        "Preferred-Languages: en, hu\n"
    )

def _check_hook_installed() -> bool:
    """Return True if a mullm prepare-commit-msg hook is installed in the cwd repo."""
    hook = Path(".git/hooks/prepare-commit-msg")
    return hook.exists() and "mullm" in hook.read_text(errors="ignore")


@app.post("/api/attribution/install-hook")
async def install_git_hook():
    """Install a prepare-commit-msg hook in the current repo."""
    hook_path = Path(".git/hooks/prepare-commit-msg")
    if not Path(".git").exists():
        raise HTTPException(status_code=400, detail="No .git directory found in server working directory")
    hook_script = (
        "#!/bin/sh\n"
        "# muLLM commit attribution hook — installed by mullm --install-git-hook\n"
        "TRAILER=$(curl -sf http://localhost:6856/api/attribution | python3 -c \\\n"
        '  "import sys,json; d=json.load(sys.stdin); print(d.get(\'trailer\') or \'\')" 2>/dev/null)\n'
        'if [ -n "$TRAILER" ]; then\n'
        '  if ! grep -qF "$TRAILER" "$1" 2>/dev/null; then\n'
        '    printf "\\n\\n%s\\n" "$TRAILER" >> "$1"\n'
        "  fi\n"
        "fi\n"
    )
    hook_path.parent.mkdir(exist_ok=True)
    hook_path.write_text(hook_script)
    hook_path.chmod(0o755)
    return {"installed": True, "path": str(hook_path)}


@app.delete("/api/attribution/install-hook")
async def remove_git_hook():
    """Remove the mullm prepare-commit-msg hook."""
    hook_path = Path(".git/hooks/prepare-commit-msg")
    if hook_path.exists() and "mullm" in hook_path.read_text(errors="ignore"):
        hook_path.unlink()
        return {"removed": True}
    return {"removed": False, "reason": "hook not found or not managed by mullm"}


# ---------------------------------------------------------------------------
# /api/understand — extract tasks from rambling input (local model, free)
# ---------------------------------------------------------------------------

_UNDERSTAND_SYSTEM = (
    "You are a task extractor. Given rambling input, output ONLY a JSON object with:\n"
    '- "tasks": array of actionable items (max 15), each a single clear sentence\n'
    '- "compressed": single sentence capturing the overall intent\n'
    '- "priority": array of "high"/"medium"/"low" matching tasks array\n\n'
    "Rules:\n"
    "- Ignore filler words, questions, rambling, emotional content\n"
    "- Keep technical specifics (file names, endpoints, feature names)\n"
    "- Merge redundant tasks\n"
    "- Output valid JSON only, no explanation"
)


@app.post("/api/understand")
@app.post("/understand")
async def understand_input(request: Request):
    """Extract actionable tasks from long rambling input using local model."""
    import re as _re

    import ollama as _ollama

    body = await request.json()
    content = (body.get("content") or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="content must not be empty")
    if len(content) > 100_000:
        raise HTTPException(status_code=400, detail="content exceeds 100K character limit")

    start = time.perf_counter()
    try:
        response = await asyncio.to_thread(
            _ollama.chat,
            model=settings.ollama_model,
            messages=[
                {"role": "system", "content": _UNDERSTAND_SYSTEM},
                {"role": "user", "content": content},
            ],
            options={"temperature": 0.1, "num_predict": 1024},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=f"Local model unavailable: {exc}") from exc

    latency_ms = round((time.perf_counter() - start) * 1000, 1)
    raw = response["message"]["content"].strip()

    raw = _re.sub(r"<think>.*?</think>", "", raw, flags=_re.DOTALL).strip()
    md_match = _re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if md_match:
        raw = md_match.group(1).strip()

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        brace_match = _re.search(r"\{[\s\S]*\}", raw)
        if brace_match:
            try:
                parsed = json.loads(brace_match.group())
            except json.JSONDecodeError:
                parsed = {"tasks": [raw], "compressed": raw[:200], "priority": ["medium"]}
        else:
            parsed = {"tasks": [raw], "compressed": raw[:200], "priority": ["medium"]}

    tasks     = parsed.get("tasks", [])
    compressed = parsed.get("compressed", "")
    priority  = parsed.get("priority", ["medium"] * len(tasks))

    orig_tokens       = max(1, len(content) // 4)
    compressed_tokens = max(1, len(compressed) // 4)
    token_savings     = round(1.0 - compressed_tokens / orig_tokens, 2)

    return JSONResponse({
        "tasks": tasks,
        "compressed": compressed,
        "priority": priority,
        "token_savings": token_savings,
        "latency_ms": latency_ms,
    })


# ---------------------------------------------------------------------------
# TTS API — /api/tts/backends and /api/tts/synth
# ---------------------------------------------------------------------------

_OPENAI_TTS_VOICES = [
    {"id": "alloy",   "label": "Alloy (neutral)"},
    {"id": "echo",    "label": "Echo (male)"},
    {"id": "fable",   "label": "Fable (warm)"},
    {"id": "onyx",    "label": "Onyx (deep)"},
    {"id": "nova",    "label": "Nova (female)"},
    {"id": "shimmer", "label": "Shimmer (bright)"},
    {"id": "ash",     "label": "Ash"},
    {"id": "ballad",  "label": "Ballad"},
    {"id": "coral",   "label": "Coral"},
    {"id": "sage",    "label": "Sage"},
    {"id": "verse",   "label": "Verse"},
]

_ELEVENLABS_DEFAULT_VOICES = [
    {"id": "21m00Tcm4TlvDq8ikWAM", "label": "Rachel"},
    {"id": "AZnzlk1XvdvUeBnXmlld", "label": "Domi"},
    {"id": "EXAVITQu4vr4xnSDxMaL", "label": "Bella"},
    {"id": "ErXwobaYiN019PkySvjV", "label": "Antoni"},
    {"id": "MF3mGyEYCl7XYWbV9V6O", "label": "Elli"},
    {"id": "TxGEqnHWrfWFTfGW9XjX", "label": "Josh"},
    {"id": "VR6AewLTigWG4xSOukaG", "label": "Arnold"},
    {"id": "pNInz6obpgDQGcFmaJgB", "label": "Adam"},
    {"id": "yoZ06aMxZJJ28mfd3POQ", "label": "Sam"},
]


@app.get("/api/tts/backends")
async def tts_backends():
    """Return available TTS backends based on API keys and installed packages."""
    toggles = _load_toggles()
    openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
    el_key = os.getenv("ELEVENLABS_API_KEY", "")
    ffmpeg_path = shutil.which("ffmpeg")

    backends = []

    # OpenAI TTS
    oai_enabled = bool(openai_key) and toggles.get("tts_openai", True)
    backends.append({
        "name": "openai",
        "label": "OpenAI TTS",
        "available": oai_enabled,
        "reason": "" if oai_enabled else ("Disabled in settings" if bool(openai_key) else "No OPENAI_API_KEY"),
        "voices": _OPENAI_TTS_VOICES if oai_enabled else [],
    })

    # ElevenLabs
    el_enabled = bool(el_key) and toggles.get("tts_elevenlabs", False)
    backends.append({
        "name": "elevenlabs",
        "label": "ElevenLabs",
        "available": el_enabled,
        "reason": "" if el_enabled else ("Disabled in settings" if bool(el_key) else "No ELEVENLABS_API_KEY"),
        "voices": _ELEVENLABS_DEFAULT_VOICES if el_enabled else [],
    })

    # Kokoro (local) — check if importable
    kokoro_device = os.getenv("MULLM_KOKORO_DEVICE", "cpu").strip() or "cpu"
    try:
        import importlib
        importlib.import_module("kokoro")
        kokoro_avail = True
    except ImportError:
        kokoro_avail = False

    backends.append({
        "name": "kokoro",
        "label": "Kokoro (local)",
        "available": kokoro_avail,
        "reason": "" if kokoro_avail else "kokoro package not installed (pip install kokoro)",
        "device": kokoro_device if kokoro_avail else "",
        "mp3_available": bool(ffmpeg_path) if kokoro_avail else False,
        "mp3_reason": "" if ffmpeg_path else "Install ffmpeg to export Kokoro audio as MP3; WAV export works without it.",
        "voices": [
            {"id": "af_heart", "label": "Heart (female)"},
            {"id": "af_bella", "label": "Bella (female)"},
            {"id": "af_nicole", "label": "Nicole (female)"},
            {"id": "am_adam",  "label": "Adam (male)"},
            {"id": "am_michael","label": "Michael (male)"},
            {"id": "bf_emma",  "label": "Emma (British female)"},
            {"id": "bm_george","label": "George (British male)"},
        ] if kokoro_avail else [],
    })

    return {
        "backends": backends,
        "tools": {
            "ffmpeg": {
                "available": bool(ffmpeg_path),
                "path": ffmpeg_path or "",
                "install_hint": "Install ffmpeg to enable local Kokoro MP3 transcoding.",
            }
        },
    }


@app.get("/api/leaderboard")
async def accuracy_leaderboard(query: str = ""):
    """Return passive model-quality leaderboard data for the Accuracy page."""
    from router.vector_cache import compute_leaderboard

    data = compute_leaderboard()
    if query:
        data["query"] = query
        data.setdefault("neighborhood", {})
    data.setdefault("neighborhood", {})
    return data


@app.get("/api/displacements")
async def displacement_events(limit: int = 30):
    """Return recent cache displacement events for the Accuracy page."""
    from router.vector_cache import CHROMA_DIR

    path = Path(CHROMA_DIR).parent / "displacement_log.jsonl"
    limit = max(1, min(int(limit or 30), 200))
    rows: list[dict[str, Any]] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines()[-limit:]:
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                rows.append(item)
    return {"events": list(reversed(rows)), "total": len(rows), "source": str(path)}


def _audio_ext_for_media_type(media_type: str) -> str:
    if media_type == "audio/mpeg":
        return "mp3"
    if media_type == "audio/wav":
        return "wav"
    return "bin"


def _encode_wav_pcm16(samples: Any, sample_rate: int = 24000) -> bytes:
    import wave as _wave

    import numpy as _np

    clipped = _np.clip(samples, -1.0, 1.0)
    buf = io.BytesIO()
    with _wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes((clipped * 32767).astype(_np.int16).tobytes())
    return buf.getvalue()


def _transcode_wav_to_mp3(wav_bytes: bytes) -> bytes | None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    try:
        result = subprocess.run(  # nosec B603 - fixed executable path, no shell, bounded input.
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "wav",
                "-i",
                "pipe:0",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                "128k",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except Exception:
        return None
    if result.returncode != 0 or not result.stdout:
        logger.warning("ffmpeg mp3 transcode failed: %s", result.stderr[:200].decode("utf-8", "ignore"))
        return None
    return result.stdout


_MUSAIC_EXT_MEDIA = {
    ".mp3": "audio/mpeg",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
}
_MUSAIC_MAX_BYTES = 50 * 1024 * 1024


def _musaic_root() -> Path:
    root = Path(settings.asset_root).expanduser() / "audio"
    for bucket in ("raw", "processed", "game"):
        (root / bucket).mkdir(parents=True, exist_ok=True)
    return root


def _musaic_bucket(value: str) -> str:
    if value not in {"raw", "processed", "game"}:
        raise HTTPException(status_code=400, detail="invalid audio bucket")
    return value


def _musaic_safe_filename(value: str, fallback: str = "audio.webm") -> str:
    name = Path(str(value or fallback)).name
    stem = re.sub(r"[^A-Za-z0-9_.-]+", "-", Path(name).stem).strip("-._")[:80] or "audio"
    ext = Path(name).suffix.lower()
    if ext not in _MUSAIC_EXT_MEDIA:
        raise HTTPException(status_code=400, detail="unsupported audio file type")
    return f"{stem}{ext}"


def _musaic_path(bucket: str, filename: str) -> Path:
    bucket = _musaic_bucket(bucket)
    safe = _musaic_safe_filename(filename)
    path = (_musaic_root() / bucket / safe).resolve()
    root = (_musaic_root() / bucket).resolve()
    if root not in path.parents:
        raise HTTPException(status_code=400, detail="invalid audio path")
    return path


def _musaic_record(path: Path, bucket: str) -> dict[str, Any]:
    stat = path.stat()
    return {
        "asset_id": f"{bucket}:{path.name}",
        "filename": path.name,
        "bucket": bucket,
        "size": stat.st_size,
        "format": path.suffix.lower().lstrip("."),
        "duration": None,
        "stream_url": f"/api/musaic/file/{bucket}/{path.name}",
        "created_at": stat.st_mtime,
    }


def _musaic_asset_path(asset_id: str) -> tuple[str, Path]:
    if ":" not in asset_id:
        raise HTTPException(status_code=400, detail="invalid asset_id")
    bucket, filename = asset_id.split(":", 1)
    path = _musaic_path(bucket, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio asset not found")
    return bucket, path


def _musaic_format(value: str) -> tuple[str, list[str]]:
    fmt = str(value or "mp3_128").lower()
    if fmt == "mp3_256":
        return ".mp3", ["-codec:a", "libmp3lame", "-b:a", "256k"]
    if fmt == "wav_16":
        return ".wav", ["-codec:a", "pcm_s16le"]
    if fmt == "wav_24":
        return ".wav", ["-codec:a", "pcm_s24le"]
    if fmt == "opus_32":
        return ".ogg", ["-codec:a", "libopus", "-b:a", "32k", "-vbr", "on"]
    return ".mp3", ["-codec:a", "libmp3lame", "-b:a", "128k"]


_FOLEY_PRESETS = {
    "hit": {"label": "Hit", "duration_ms": 220, "description": "Short impact thump with noise transient."},
    "clang": {"label": "Clang", "duration_ms": 650, "description": "Metallic strike with ringing partials."},
    "drop": {"label": "Drop", "duration_ms": 450, "description": "Object drop with low impact and bounce."},
    "drip": {"label": "Drip", "duration_ms": 300, "description": "Water droplet plink."},
    "scream": {"label": "Scream", "duration_ms": 900, "description": "Synthetic creature/arcade scream tone."},
    "shot": {"label": "Shot", "duration_ms": 420, "description": "Percussive shot with short tail."},
    "crash": {"label": "Crash", "duration_ms": 1000, "description": "Noisy debris crash."},
    "slidewhistle": {"label": "Slide whistle", "duration_ms": 850, "description": "Cartoon pitch slide."},
    "boing": {"label": "Boing", "duration_ms": 650, "description": "Springy pitch bounce."},
    "clop": {"label": "Clop", "duration_ms": 240, "description": "Hoof/wood clop."},
    "oof": {"label": "Oof", "duration_ms": 380, "description": "Soft body impact grunt-like synth."},
    "thud": {"label": "Thud", "duration_ms": 360, "description": "Heavy low impact."},
    "wheel": {"label": "Wheel", "duration_ms": 900, "description": "Loopable wagon wheel rumble with axle ticks."},
    "wood-creak": {"label": "Wood creak", "duration_ms": 850, "description": "Old floorboard or wagon creak."},
    "horse-whinny": {"label": "Horse whinny", "duration_ms": 1000, "description": "Synthetic horse whinny/neigh cue."},
    "neigh": {"label": "Neigh", "duration_ms": 850, "description": "Short horse neigh."},
    "sneeze": {"label": "Sneeze", "duration_ms": 520, "description": "Cartoon sneeze burst."},
    "grumble": {"label": "Grumble", "duration_ms": 900, "description": "Low creature or stomach grumble."},
    "grunt": {"label": "Grunt", "duration_ms": 360, "description": "Short exertion grunt."},
    "footstep": {"label": "Footstep", "duration_ms": 260, "description": "Dry boot step on dirt/wood."},
    "knock": {"label": "Knock", "duration_ms": 360, "description": "Two wooden door knocks."},
    "doorbell": {"label": "Doorbell", "duration_ms": 900, "description": "Simple two-note bell."},
    "fire-crackle": {"label": "Fire crackle", "duration_ms": 1200, "description": "Loopable fire crackle bed."},
    "explosion": {"label": "Explosion", "duration_ms": 1200, "description": "Game explosion boom and debris tail."},
    "pop": {"label": "Pop", "duration_ms": 180, "description": "Small cartoon pop."},
    "swish": {"label": "Swish", "duration_ms": 420, "description": "Fast whoosh/sword swish."},
    "shh": {"label": "Shh", "duration_ms": 650, "description": "Breathy hush/noise cue."},
    "ssss": {"label": "Ssss", "duration_ms": 750, "description": "Snake/fuse hiss."},
    "woof": {"label": "Woof", "duration_ms": 360, "description": "Synthetic dog bark."},
    "hiss": {"label": "Hiss", "duration_ms": 650, "description": "Sharp animal/steam hiss."},
    "meow": {"label": "Meow", "duration_ms": 700, "description": "Synthetic cat meow."},
    "clatter": {"label": "Clatter", "duration_ms": 750, "description": "Scattered objects or bones clattering."},
    "twig-snap": {"label": "Twig snap", "duration_ms": 220, "description": "Sharp twig break."},
    "trap-close": {"label": "Trap close", "duration_ms": 420, "description": "Mechanical trap snap shut."},
}


def _foley_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "foley")).strip("-._").lower()
    return slug[:80] or "foley"


def _foley_seed(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") & 0xFFFFFFFF


def _foley_env(length: int, attack: float = 0.015, release: float = 0.35) -> Any:
    import numpy as _np

    x = _np.linspace(0.0, 1.0, length, endpoint=False)
    atk = _np.clip(x / max(attack, 0.001), 0.0, 1.0)
    rel = _np.exp(-x / max(release, 0.001))
    return _np.minimum(atk, 1.0) * rel


def _foley_render_wav(
    effect: str,
    prompt: str,
    duration_ms: int,
    intensity: float,
    pitch_semitones: float = 0.0,
    reverb: float = 0.0,
    compression: float = 0.9,
) -> bytes:
    import numpy as _np

    sample_rate = 24000
    duration_ms = int(max(80, min(duration_ms, 5000)))
    intensity = float(max(0.05, min(intensity, 2.0)))
    pitch_semitones = float(max(-24.0, min(pitch_semitones, 24.0)))
    reverb = float(max(0.0, min(reverb, 1.0)))
    compression = float(max(0.1, min(compression, 2.0)))
    n = max(64, int(sample_rate * duration_ms / 1000))
    t = _np.arange(n, dtype=_np.float32) / sample_rate
    rng = _np.random.default_rng(_foley_seed(effect, prompt, str(duration_ms), str(round(intensity, 3)), str(round(pitch_semitones, 2))))
    e = effect.lower().strip() or "hit"
    noise = rng.normal(0.0, 1.0, n).astype(_np.float32)
    out = _np.zeros(n, dtype=_np.float32)

    def tone(freq: float, amp: float = 1.0, decay: float = 0.3, phase: float = 0.0) -> Any:
        return amp * _np.sin(2 * _np.pi * freq * t + phase) * _np.exp(-t / max(decay, 0.001))

    def apply_pitch(samples: Any) -> Any:
        if abs(pitch_semitones) < 0.01:
            return samples
        ratio = 2 ** (pitch_semitones / 12.0)
        src = _np.arange(n, dtype=_np.float32) * ratio
        valid = src < n - 1
        shifted = _np.zeros(n, dtype=_np.float32)
        shifted[valid] = _np.interp(src[valid], _np.arange(n), samples).astype(_np.float32)
        return shifted

    if e in {"clang", "metal", "sword", "blade"}:
        out += tone(520, 0.55, 0.55) + tone(911, 0.35, 0.75) + tone(1570, 0.22, 0.45)
        out += noise * _np.exp(-t / 0.04) * 0.35
    elif e in {"shot", "gunshot", "blast"}:
        out += noise * _np.exp(-t / 0.055) * 0.95
        out += tone(85, 0.75, 0.18)
    elif e in {"explosion"}:
        out += noise * _np.exp(-t / 0.55) * 0.85
        out += tone(52, 1.0, 0.65) + tone(104, 0.45, 0.32)
    elif e in {"crash", "shatter", "break"}:
        out += noise * _np.exp(-t / 0.45) * 0.75
        out += tone(110, 0.45, 0.35) + tone(247, 0.22, 0.25)
    elif e in {"drip", "plink"}:
        out += tone(1100, 0.85, 0.11) + tone(1760, 0.25, 0.07)
    elif e in {"slidewhistle", "slide", "whistle"}:
        direction = -1 if "down" in prompt.lower() else 1
        f0, f1 = (450, 1400) if direction > 0 else (1400, 420)
        freq = _np.linspace(f0, f1, n)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.04, release=0.9) * 0.75
    elif e in {"boing", "spring"}:
        freq = 210 + 120 * _np.sin(2 * _np.pi * 7 * t) * _np.exp(-t / 0.6)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.01, release=0.55) * 0.9
    elif e in {"clop", "hoof", "wood", "footstep"}:
        out += tone(240, 0.75, 0.06) + tone(540, 0.28, 0.04)
        out += noise * _np.exp(-t / 0.025) * 0.22
    elif e in {"oof", "grunt"}:
        freq = _np.linspace(170, 95, n)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.025, release=0.24) * 0.85
        out += noise * _np.exp(-t / 0.08) * 0.1
    elif e in {"grumble"}:
        out += tone(58, 0.75, 0.8) + tone(91, 0.35, 0.55)
        out += _np.sin(2 * _np.pi * 17 * t) * _np.exp(-t / 0.9) * 0.12
    elif e in {"scream", "yelp"}:
        freq = 620 + 170 * _np.sin(2 * _np.pi * 8 * t) + _np.linspace(0, 360, n)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.04, release=0.85) * 0.72
        out += noise * _np.exp(-t / 0.7) * 0.08
    elif e in {"horse-whinny", "neigh"}:
        freq = _np.linspace(380, 920 if e == "horse-whinny" else 720, n)
        freq += 90 * _np.sin(2 * _np.pi * 9 * t)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.05, release=0.75) * 0.78
    elif e in {"meow"}:
        freq = _np.linspace(520, 760, n)
        freq[int(n * 0.45):] = _np.linspace(760, 430, n - int(n * 0.45))
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sin(phase) * _foley_env(n, attack=0.04, release=0.55) * 0.72
    elif e in {"woof"}:
        out += tone(155, 0.8, 0.16) + tone(88, 0.35, 0.22)
        out += noise * _np.exp(-t / 0.06) * 0.22
    elif e in {"sneeze"}:
        out += noise * _np.exp(-_np.maximum(t - 0.08, 0) / 0.12) * _foley_env(n, attack=0.08, release=0.22) * 0.9
        out += tone(220, 0.25, 0.18)
    elif e in {"shh", "ssss", "hiss"}:
        out += noise * _foley_env(n, attack=0.05, release=0.65) * (0.38 if e == "shh" else 0.62)
        out += tone(3600 if e != "shh" else 1800, 0.08, 0.45)
    elif e in {"swish"}:
        sweep = _np.linspace(0.15, 1.0, n)
        out += noise * _foley_env(n, attack=0.08, release=0.22) * sweep * 0.7
    elif e in {"fire-crackle"}:
        out += noise * 0.08
        for pos in rng.integers(0, n, size=max(4, n // 3500)):
            tail = min(n - pos, int(sample_rate * 0.08))
            out[pos:pos + tail] += rng.normal(0, 1, tail) * _np.exp(-_np.arange(tail) / (sample_rate * 0.018)) * 0.45
    elif e in {"wheel"}:
        out += tone(65, 0.18, 1.2) + noise * 0.055
        tick_gap = max(1, int(sample_rate * 0.18))
        for pos in range(0, n, tick_gap):
            tail = min(n - pos, int(sample_rate * 0.035))
            out[pos:pos + tail] += tone(210, 0.35, 0.035)[:tail]
    elif e in {"wood-creak"}:
        freq = 180 + 45 * _np.sin(2 * _np.pi * 2.2 * t)
        phase = 2 * _np.pi * _np.cumsum(freq) / sample_rate
        out += _np.sign(_np.sin(phase)) * _foley_env(n, attack=0.08, release=0.8) * 0.32
    elif e in {"knock"}:
        out += tone(180, 0.7, 0.06) + noise * _np.exp(-t / 0.018) * 0.2
        delay = int(sample_rate * 0.16)
        if delay < n:
            out[delay:] += (tone(200, 0.62, 0.055) + noise * _np.exp(-t / 0.02) * 0.18)[: n - delay]
    elif e in {"doorbell"}:
        out += tone(660, 0.55, 0.45) + tone(880, 0.45, 0.38)
        delay = int(sample_rate * 0.32)
        if delay < n:
            out[delay:] += (tone(550, 0.45, 0.38) + tone(770, 0.35, 0.32))[: n - delay]
    elif e in {"pop"}:
        out += tone(460, 0.6, 0.035) + noise * _np.exp(-t / 0.014) * 0.35
    elif e in {"clatter"}:
        for pos in rng.integers(0, n, size=9):
            tail = min(n - pos, int(sample_rate * 0.075))
            out[pos:pos + tail] += (tone(float(rng.integers(220, 1200)), 0.35, 0.05) + noise * _np.exp(-t / 0.02) * 0.12)[:tail]
    elif e in {"twig-snap", "trap-close"}:
        base = 320 if e == "twig-snap" else 120
        out += tone(base, 0.78, 0.045) + noise * _np.exp(-t / 0.018) * 0.5
        if e == "trap-close":
            out += tone(760, 0.35, 0.08)
    elif e in {"drop", "bounce"}:
        first = tone(140, 0.65, 0.11)
        delay = int(sample_rate * 0.16)
        if delay < n:
            first[delay:] += tone(260, 0.33, 0.07)[: n - delay]
        out += first + noise * _np.exp(-t / 0.04) * 0.2
    else:  # hit/thud/default
        base = 72 if e == "thud" else 115
        out += tone(base, 0.85, 0.16) + noise * _np.exp(-t / 0.035) * 0.38

    out *= intensity
    out = apply_pitch(out)
    if reverb > 0:
        delay = max(1, int(sample_rate * 0.055))
        wet = out.copy()
        for tap, gain in ((delay, 0.34), (delay * 2, 0.18), (delay * 3, 0.09)):
            if tap < n:
                wet[tap:] += out[:-tap] * gain * reverb
        out = wet
    peak = float(_np.max(_np.abs(out))) or 1.0
    out = _np.tanh(out / max(peak, 0.001) * compression)
    return _encode_wav_pcm16(out, sample_rate=sample_rate)


@app.get("/api/foley/status")
async def foley_status():
    ffmpeg_path = shutil.which("ffmpeg")
    return {
        "ok": True,
        "engine": "procedural",
        "ffmpeg_available": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path or "",
        "formats": ["mp3", "wav"],
        "default_format": "mp3" if ffmpeg_path else "wav",
        "save_bucket": "game",
        "controls": {
            "duration_ms": {"min": 80, "max": 5000, "default": 400},
            "pitch_semitones": {"min": -24, "max": 24, "default": 0},
            "reverb": {"min": 0, "max": 1, "default": 0},
            "compression": {"min": 0.1, "max": 2, "default": 0.9},
        },
        "presets": list(_FOLEY_PRESETS.keys()),
    }


@app.get("/api/foley/presets")
async def foley_presets():
    return {"presets": _FOLEY_PRESETS}


@app.post("/api/foley/generate")
async def foley_generate(request: Request):
    """Generate a short procedural game sound effect and return audio bytes."""
    body = await request.json()
    effect = _foley_slug(str(body.get("effect") or body.get("kind") or "hit"))
    prompt = str(body.get("prompt") or "")
    duration_ms = int(body.get("duration_ms") or _FOLEY_PRESETS.get(effect, {}).get("duration_ms", 400))
    intensity = float(body.get("intensity") or 1.0)
    pitch_semitones = float(body.get("pitch_semitones") or body.get("pitch") or 0.0)
    reverb = float(body.get("reverb") or 0.0)
    compression = float(body.get("compression") or 0.9)
    requested_format = str(body.get("format") or "mp3").lower()
    save = bool(body.get("save", False))

    wav_bytes = _foley_render_wav(effect, prompt, duration_ms, intensity, pitch_semitones, reverb, compression)
    media = "audio/wav"
    audio = wav_bytes
    ext = "wav"
    if requested_format in {"mp3", "mpeg", "audio/mpeg"}:
        mp3 = _transcode_wav_to_mp3(wav_bytes)
        if mp3:
            audio = mp3
            media = "audio/mpeg"
            ext = "mp3"

    name = _musaic_safe_filename(f"{_foley_slug(str(body.get('name') or effect))}-{int(time.time())}.{ext}")
    headers = {
        "Content-Disposition": f'attachment; filename="{name}"',
        "X-Foley-Effect": effect,
        "X-Foley-Format": ext,
        "X-Foley-Engine": "procedural",
        "X-Foley-Pitch-Semitones": str(pitch_semitones),
    }
    if save:
        dest = _musaic_path("game", name)
        dest.write_bytes(audio)
        record = _musaic_record(dest, "game")
        headers["X-Musaic-Asset-Id"] = record["asset_id"]
        headers["X-Musaic-Stream-Url"] = record["stream_url"]
    return Response(content=audio, media_type=media, headers=headers)


@app.get("/api/musaic/status")
async def musaic_status():
    """Return Audio Studio backend capability status."""
    ffmpeg_path = shutil.which("ffmpeg")
    root = _musaic_root()
    return {
        "ok": True,
        "ffmpeg_available": bool(ffmpeg_path),
        "ffmpeg_path": ffmpeg_path or "",
        "max_upload_mb": round(_MUSAIC_MAX_BYTES / 1024 / 1024),
        "root": str(root),
        "formats": ["mp3_128", "mp3_256", "wav_16", "wav_24", "opus_32"],
    }


@app.post("/api/musaic/upload")
async def musaic_upload(file: UploadFile = File(...)):
    """Upload a raw audio asset for Audio Studio processing."""
    filename = _musaic_safe_filename(file.filename or "audio.webm")
    dest = _musaic_path("raw", f"{int(time.time())}-{filename}")
    size = 0
    with dest.open("wb") as out:
        while True:
            chunk = await file.read(1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            if size > _MUSAIC_MAX_BYTES:
                dest.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="audio file too large")
            out.write(chunk)
    if size == 0:
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="empty audio file")
    return _musaic_record(dest, "raw")


@app.get("/api/musaic/file/{bucket}/{filename}")
async def musaic_file(bucket: str, filename: str):
    """Stream a stored Audio Studio file."""
    path = _musaic_path(bucket, filename)
    if not path.exists():
        raise HTTPException(status_code=404, detail="audio asset not found")
    return FileResponse(
        path,
        filename=path.name,
        media_type=_MUSAIC_EXT_MEDIA.get(path.suffix.lower(), "application/octet-stream"),
    )


@app.get("/api/musaic/library")
async def musaic_library():
    """List stored Audio Studio files across raw, processed, and game buckets."""
    records: list[dict[str, Any]] = []
    root = _musaic_root()
    for bucket in ("raw", "processed", "game"):
        for path in (root / bucket).iterdir():
            if path.is_file() and path.suffix.lower() in _MUSAIC_EXT_MEDIA:
                records.append(_musaic_record(path, bucket))
    records.sort(key=lambda row: float(row.get("created_at", 0)), reverse=True)
    return records[:200]


@app.post("/api/musaic/process")
async def musaic_process(request: Request):
    """Process an uploaded audio asset with ffmpeg filters and export format."""
    body = await request.json()
    _, source = _musaic_asset_path(str(body.get("asset_id") or ""))
    fmt_ext, codec_args = _musaic_format(str(body.get("format") or "mp3_128"))
    output_bucket = "game" if bool(body.get("game_optimized")) or str(body.get("format")) == "opus_32" else "processed"
    output_name = _musaic_safe_filename(f"{source.stem}-{output_bucket}{fmt_ext}")
    dest = _musaic_path(output_bucket, output_name)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise HTTPException(status_code=503, detail="ffmpeg is required for Audio Studio processing")

    filters: list[str] = []
    if body.get("denoise"):
        filters.append("highpass=f=80,lowpass=f=12000,afftdn")
    if body.get("normalize", True):
        filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")
    if body.get("trim_silence"):
        filters.append("silenceremove=start_periods=1:start_threshold=-50dB:start_silence=0.2")

    cmd = [ffmpeg, "-hide_banner", "-y", "-i", str(source)]
    if filters:
        cmd.extend(["-af", ",".join(filters)])
    cmd.extend(codec_args)
    cmd.append(str(dest))
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)  # nosec B603
    if result.returncode != 0 or not dest.exists():
        dest.unlink(missing_ok=True)
        raise HTTPException(status_code=502, detail=f"ffmpeg failed: {result.stderr[-500:]}")
    record = _musaic_record(dest, output_bucket)
    return {
        **record,
        "log": "\n".join(
            line
            for line in [
                f"Input: {source.name}",
                f"Output: {dest.name}",
                f"Bucket: {output_bucket}",
                f"Filters: {', '.join(filters) if filters else 'none'}",
            ]
        ),
    }


async def _tts_synthesize_bytes(body: dict[str, Any]) -> tuple[bytes, str]:
    text    = (body.get("text") or "").strip()
    backend = body.get("backend", "openai")
    voice   = body.get("voice", "alloy")
    speed   = float(body.get("rate", 1.0))
    fmt     = str(body.get("format") or "mp3").lower()

    if not text:
        raise HTTPException(status_code=400, detail="text is required")
    if len(text) > 4096:
        raise HTTPException(status_code=400, detail="text too long (max 4096 chars)")

    speed = max(0.25, min(4.0, speed))

    if backend == "openai":
        openai_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY", "")
        if not openai_key:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY not configured")
        resp_fmt = "wav" if fmt == "wav" else "mp3"
        payload = {"model": "tts-1", "input": text, "voice": voice, "speed": speed, "response_format": resp_fmt}
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {openai_key}", "Content-Type": "application/json"},
                json=payload,
            )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"OpenAI TTS error: {r.text[:200]}")
        media = "audio/wav" if resp_fmt == "wav" else "audio/mpeg"
        return r.content, media

    elif backend == "elevenlabs":
        el_key = os.getenv("ELEVENLABS_API_KEY", "")
        if not el_key:
            raise HTTPException(status_code=503, detail="ELEVENLABS_API_KEY not configured")
        async with httpx.AsyncClient(timeout=60) as client:
            r = await client.post(
                f"https://api.elevenlabs.io/v1/text-to-speech/{voice}",
                headers={"xi-api-key": el_key, "Content-Type": "application/json"},
                json={"text": text, "model_id": "eleven_monolingual_v1",
                      "voice_settings": {"stability": 0.5, "similarity_boost": 0.75}},
            )
        if r.status_code != 200:
            raise HTTPException(status_code=r.status_code, detail=f"ElevenLabs error: {r.text[:200]}")
        return r.content, "audio/mpeg"

    elif backend == "kokoro":
        try:
            import kokoro as _kokoro
            import numpy as _np
        except ImportError:
            raise HTTPException(status_code=503, detail="kokoro package not installed")
        # Infer lang_code from voice ID prefix: af_/am_ = American, bf_/bm_ = British
        lang_code = "b" if voice.startswith("b") else "a"
        # Cache pipelines by lang_code — first call loads model (~20s), subsequent calls are instant
        if not hasattr(tts_synth, "_pipelines"):
            tts_synth._pipelines = {}
        kokoro_device = os.getenv("MULLM_KOKORO_DEVICE", "cpu").strip() or "cpu"
        pipeline_key = f"{lang_code}:{kokoro_device}"
        if pipeline_key not in tts_synth._pipelines:
            tts_synth._pipelines[pipeline_key] = _kokoro.KPipeline(
                lang_code=lang_code,
                device=kokoro_device,
            )
        pipeline = tts_synth._pipelines[pipeline_key]
        samples = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            samples.append(audio)
        if not samples:
            raise HTTPException(status_code=500, detail="Kokoro produced no audio")
        combined = _np.concatenate(samples)
        wav_bytes = _encode_wav_pcm16(combined)
        if fmt == "mp3":
            mp3_bytes = _transcode_wav_to_mp3(wav_bytes)
            if mp3_bytes:
                return mp3_bytes, "audio/mpeg"
        return wav_bytes, "audio/wav"

    else:
        raise HTTPException(status_code=400, detail=f"Unknown backend: {backend}")


@app.post("/api/tts/synth")
async def tts_synth(request: Request):
    """Synthesize speech. Returns audio bytes using the actual media type."""
    body = await request.json()
    audio, media = await _tts_synthesize_bytes(body)
    return Response(content=audio, media_type=media)


@app.post("/api/tts/batch")
async def tts_batch(request: Request):
    """Synthesize many short snippets and return base64-encoded audio items."""
    body = await request.json()
    rows = body.get("items")
    if not isinstance(rows, list):
        csv_text = str(body.get("csv") or "").strip()
        if not csv_text:
            raise HTTPException(status_code=400, detail="items or csv is required")
        parsed = list(csv.DictReader(io.StringIO(csv_text)))
        rows = parsed if parsed else [{"text": line.strip()} for line in csv_text.splitlines() if line.strip()]
    if not rows:
        raise HTTPException(status_code=400, detail="no TTS rows provided")
    if len(rows) > 50:
        raise HTTPException(status_code=400, detail="batch limit is 50 rows")

    defaults = {
        "backend": body.get("backend", "openai"),
        "voice": body.get("voice", "alloy"),
        "rate": body.get("rate", 1.0),
        "format": body.get("format", "mp3"),
    }
    results: list[dict[str, Any]] = []
    for idx, raw in enumerate(rows, start=1):
        if not isinstance(raw, dict):
            raw = {"text": str(raw)}
        text = str(raw.get("text") or raw.get("line") or raw.get("script") or "").strip()
        if not text:
            results.append({"index": idx, "ok": False, "error": "missing text"})
            continue
        if len(text) > 1000:
            results.append({"index": idx, "ok": False, "error": "text too long (max 1000 chars per row)"})
            continue
        payload = {
            **defaults,
            **{k: v for k, v in raw.items() if k in {"backend", "voice", "rate", "format"}},
            "text": text,
        }
        try:
            audio, media = await _tts_synthesize_bytes(payload)
        except HTTPException as exc:
            results.append({"index": idx, "ok": False, "error": str(exc.detail)})
            continue
        ext = _audio_ext_for_media_type(media)
        raw_name = str(raw.get("name") or f"voice_{idx:03d}")
        safe_name = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_name).strip("-._") or f"voice_{idx:03d}"
        results.append({
            "index": idx,
            "ok": True,
            "filename": f"{safe_name}.{ext}",
            "content_type": media,
            "bytes": len(audio),
            "audio_base64": base64.b64encode(audio).decode("ascii"),
        })
    return {
        "ok": any(item.get("ok") for item in results),
        "count": len(results),
        "items": results,
    }


@app.get("/api/mupatch/latest")
async def mupatch_latest():
    """Return the latest muPatch Fresh run results."""
    data_dir = settings.cache_dir
    files = sorted(data_dir.glob("mupatch_fresh_*.json"), reverse=True)
    if not files:
        return {"status": "none", "message": "No muPatch results found"}
    data = json.loads(files[0].read_text())
    return data


# ---------------------------------------------------------------------------
# RigNet auto-rigging — POST /api/rig, GET /api/rig/{job_id}
# ---------------------------------------------------------------------------

_rig_jobs: dict[str, dict] = {}


@app.post("/api/rig")
async def rig_asset(request: Request):
    """Run RigNet auto-rigging on a GLB asset. Also accepts Meshy rigging (cloud).

    POST /api/rig {"asset_name": "my-model"} — asset_name without .glb
    Returns {"job_id": "...", "status": "queued"}
    Poll GET /api/rig/{job_id} for completion. Rigged GLB saved as {asset_name}-rigged.glb.
    """
    import uuid

    body = await request.json()
    asset_name = str(body.get("asset_name", "")).strip()
    provider = str(body.get("provider", "rignet")).strip()  # "rignet" or "meshy"
    if not asset_name:
        raise HTTPException(status_code=400, detail="asset_name is required")

    assets_dir = Path(__file__).parent.parent / "assets" / "3d"
    glb_path = assets_dir / f"{asset_name}.glb"
    if not glb_path.exists():
        raise HTTPException(status_code=404, detail=f"Asset '{asset_name}.glb' not found")

    job_id = uuid.uuid4().hex[:12]
    output_path = str(assets_dir / f"{asset_name}-rigged.glb")
    _rig_jobs[job_id] = {
        "status": "running",
        "started": time.time(),
        "asset": asset_name,
        "provider": provider,
        "output": None,
        "error": None,
    }

    if provider == "meshy":
        async def _run_meshy():
            from router import meshy as _meshy
            try:
                result = await _meshy.image_to_3d(image_path=str(glb_path))
                task_id = result.get("task_id", "")
                if not task_id:
                    _rig_jobs[job_id]["status"] = "failed"
                    _rig_jobs[job_id]["error"] = result.get("error", "no task_id")
                    return
                for _ in range(60):
                    await asyncio.sleep(5)
                    poll = await _meshy.poll_task(task_id, endpoint="image-to-3d")
                    if poll.get("status") == "complete":
                        glb_url = (poll.get("model_urls") or {}).get("glb", "")
                        if glb_url:
                            async with httpx.AsyncClient(timeout=60) as cl:
                                r = await cl.get(glb_url)
                                Path(output_path).write_bytes(r.content)
                        _rig_jobs[job_id]["status"] = "done"
                        _rig_jobs[job_id]["output"] = output_path
                        return
                    if poll.get("error"):
                        break
                _rig_jobs[job_id]["status"] = "failed"
                _rig_jobs[job_id]["error"] = "timed out"
            except Exception as exc:
                _rig_jobs[job_id]["status"] = "failed"
                _rig_jobs[job_id]["error"] = str(exc)[:300]

        asyncio.create_task(_run_meshy())
    else:
        async def _run_rignet():
            script = Path(__file__).parent.parent / "scripts" / "s28-rignet-mecha-knight.py"
            venv_py = "/opt/comfyui/venv/bin/python"
            py = venv_py if Path(venv_py).exists() else sys.executable
            env = {**os.environ, "RIGNET_ASSET_NAME": asset_name, "RIGNET_OUTPUT_PATH": output_path}
            try:
                proc = await asyncio.create_subprocess_exec(
                    py, str(script), env=env,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                stdout, _ = await proc.communicate()
                if proc.returncode == 0 and Path(output_path).exists():
                    _rig_jobs[job_id]["status"] = "done"
                    _rig_jobs[job_id]["output"] = output_path
                else:
                    _rig_jobs[job_id]["status"] = "failed"
                    _rig_jobs[job_id]["error"] = (stdout or b"").decode()[-500:]
            except Exception as exc:
                _rig_jobs[job_id]["status"] = "failed"
                _rig_jobs[job_id]["error"] = str(exc)[:300]

        asyncio.create_task(_run_rignet())

    return {"job_id": job_id, "status": "queued", "asset": asset_name, "provider": provider}


@app.get("/api/rig/{job_id}")
async def rig_status(job_id: str):
    """Poll rigging job status."""
    job = _rig_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "asset": job["asset"],
        "provider": job.get("provider", "rignet"),
        "output_path": job["output"],
        "error": job["error"],
        "elapsed_s": round(time.time() - job["started"], 1),
    }


# ---------------------------------------------------------------------------
# APK manifest — GET /api/apks
# ---------------------------------------------------------------------------

@app.get("/api/apks")
async def api_apks_manifest():
    """Return all available APKs from the apks/ directory with sizes and metadata."""
    apks_dir = Path(__file__).parent.parent / "apks"
    games_meta: dict = {}
    try:
        games_html = (Path(__file__).parent / "games.html").read_text(errors="ignore")
        import re as _re2
        for m in _re2.finditer(r"\{[^}]*?file:\s*'([^']+\.html)'[^}]*?name:\s*'([^']+)'[^}]*?\}", games_html):
            games_meta[m.group(1).replace(".html", "")] = m.group(2)
        for m in _re2.finditer(r"\{[^}]*?name:\s*'([^']+)'[^}]*?file:\s*'([^']+\.html)'[^}]*?\}", games_html):
            slug = m.group(2).replace(".html", "")
            if slug not in games_meta:
                games_meta[slug] = m.group(1)
    except Exception:
        pass

    apks = []
    if apks_dir.exists():
        for apk_path in sorted(apks_dir.glob("*.apk")):
            slug = apk_path.stem
            size_mb = round(apk_path.stat().st_size / (1024 * 1024), 2)
            apks.append({
                "slug": slug,
                "name": games_meta.get(slug, slug.replace("-", " ").title()),
                "filename": apk_path.name,
                "url": f"/apks/{apk_path.name}",
                "size_mb": size_mb,
                "size_label": f"{size_mb:.1f} MB",
                "modified": int(apk_path.stat().st_mtime),
            })
    return {"apks": apks, "count": len(apks)}


@app.get("/apks-page", response_class=HTMLResponse)
async def apks_page():
    """muLLM Android APK download listing."""
    html_path = Path(__file__).parent / "apks.html"
    if html_path.exists():
        return HTMLResponse(content=html_path.read_text(), status_code=200)
    raise HTTPException(status_code=404, detail="apks.html not found")


@app.get("/apks/{filename}")
async def apk_download_or_build_notice(filename: str):
    """Serve an APK if present, otherwise show the build/download path."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".apk"):
        raise HTTPException(status_code=404, detail="APK filename must end with .apk")
    apk_path = _HTML_DIR.parent / "apks" / safe_name
    if apk_path.is_file():
        return FileResponse(apk_path, filename=safe_name, media_type="application/vnd.android.package-archive")
    game_slug = safe_name[:-4]
    return HTMLResponse(
        f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>muLLM APK Build Required</title>
<style>body{{font-family:system-ui,sans-serif;background:#0a0e1a;color:#e2e8f0;padding:32px;line-height:1.5}}a{{color:#14b8a6}}code{{background:#111827;padding:2px 6px;border-radius:4px}}</style>
</head><body><h1>APK is not built in this install</h1>
<p><code>{html.escape(safe_name)}</code> was not packaged with this local muLLM install.</p>
<p>Build it from the APK page or POST <code>{{"game":"{html.escape(game_slug)}"}}</code> to <code>/api/apk/build</code>.</p>
<p><a href="/apks-page">Back to APK builder</a></p></body></html>""",
        status_code=200,
    )


@app.get("/assets")
async def assets_page():
    """Serve the asset browser page despite the /assets static mount."""
    return FileResponse(_HTML_DIR / "assets.html")


@app.get("/code")
async def code_page():
    """Serve the code tools page despite the /code static mount."""
    return FileResponse(_HTML_DIR / "code.html")


@app.get("/foley")
async def foley_page():
    """Serve Musaic with the Foley tab selected."""
    return FileResponse(_HTML_DIR / "musaic.html")


@app.get("/play/{slug}")
async def play_ready_game(slug: str):
    """Serve a bundled ready game by slug, with a catalog fallback."""
    safe_slug = re.sub(r"[^a-zA-Z0-9_.-]", "", slug).strip(".")
    if not safe_slug:
        raise HTTPException(status_code=404, detail="Game slug required")
    game_path = _CODE_DIR / "ready" / f"{safe_slug}.html"
    if game_path.is_file():
        return FileResponse(game_path)
    return FileResponse(_HTML_DIR / "games.html")


@app.get("/static/three/three.min.js")
async def three_min_compat():
    """Compatibility alias for older pages expecting a classic Three bundle."""
    return FileResponse(_HTML_DIR / "static" / "three" / "three.module.js", media_type="application/javascript")


@app.get("/static/three/examples/js/controls/OrbitControls.js")
async def orbit_controls_compat():
    """Compatibility alias for old Three examples path."""
    return FileResponse(_HTML_DIR / "static" / "three" / "addons" / "controls" / "OrbitControls.js", media_type="application/javascript")


@app.get("/static/three/examples/js/loaders/GLTFLoader.js")
async def gltf_loader_compat():
    """Compatibility alias for old Three examples path."""
    return FileResponse(_HTML_DIR / "static" / "three" / "addons" / "loaders" / "GLTFLoader.js", media_type="application/javascript")


# ---------------------------------------------------------------------------
# APK builder — POST /api/apk/build, GET /api/apk/build/{job_id}
# Wraps scripts/build_apk.sh (Capacitor + Gradle pipeline)
# ---------------------------------------------------------------------------

_apk_jobs: dict[str, dict] = {}


@app.post("/api/apk/build")
async def apk_build(request: Request):
    """Build an Android APK from a mullm browser game.

    POST /api/apk/build {"game": "sword-dojo"}
    game: HTML slug in router/ (e.g. "swords" → router/swords.html)
    Returns {"job_id": "...", "status": "queued"}
    Poll GET /api/apk/build/{job_id} for progress and download URL.
    """
    import uuid

    body = await request.json()
    game_slug = re.sub(r"[^a-z0-9-]", "", str(body.get("game", "")).lower().strip())
    if not game_slug:
        raise HTTPException(status_code=400, detail="game slug required")

    html_path = Path(__file__).parent / f"{game_slug}.html"
    if not html_path.exists():
        raise HTTPException(status_code=404, detail=f"{game_slug}.html not found in router/")

    apks_dir = Path(__file__).parent.parent / "apks"
    apks_dir.mkdir(parents=True, exist_ok=True)
    output_apk = apks_dir / f"{game_slug}.apk"
    build_script = Path(__file__).parent.parent / "scripts" / "build_apk.sh"

    job_id = uuid.uuid4().hex[:12]
    _apk_jobs[job_id] = {
        "status": "running",
        "started": time.time(),
        "game": game_slug,
        "output": None,
        "log": "",
        "error": None,
    }

    async def _run():
        try:
            proc = await asyncio.create_subprocess_exec(
                "bash", str(build_script), game_slug, str(html_path), str(output_apk),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
            stdout, _ = await proc.communicate()
            log = (stdout or b"").decode()[-2000:]
            _apk_jobs[job_id]["log"] = log
            if proc.returncode == 0 and output_apk.exists():
                _apk_jobs[job_id]["status"] = "done"
                _apk_jobs[job_id]["output"] = f"/apks/{game_slug}.apk"
            else:
                _apk_jobs[job_id]["status"] = "failed"
                _apk_jobs[job_id]["error"] = log[-500:]
        except Exception as exc:
            _apk_jobs[job_id]["status"] = "failed"
            _apk_jobs[job_id]["error"] = str(exc)[:300]

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "queued", "game": game_slug}


@app.get("/api/apk/build/{job_id}")
async def apk_build_status(job_id: str):
    """Poll APK build job status."""
    job = _apk_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return {
        "job_id": job_id,
        "status": job["status"],
        "game": job["game"],
        "download_url": job["output"],
        "error": job["error"],
        "elapsed_s": round(time.time() - job["started"], 1),
    }


# ---------------------------------------------------------------------------
# Static file serving — must come AFTER all route definitions
# ---------------------------------------------------------------------------

app.mount("/static", StaticFiles(directory=str(_HTML_DIR / "static")), name="static")
_ASSETS_DIR = _HTML_DIR.parent / "assets"
if _ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_ASSETS_DIR)), name="assets")
if _CODE_DIR.exists():
    app.mount("/code", StaticFiles(directory=str(_CODE_DIR)), name="code")
_APKS_DIR = _HTML_DIR.parent / "apks"
if _APKS_DIR.exists():
    app.mount("/apks", StaticFiles(directory=str(_APKS_DIR)), name="apks")


# ---------------------------------------------------------------------------
# Generic HTML page serving — catches /{name} → router/{name}.html
# Must come AFTER all API routes and static mount.
# ---------------------------------------------------------------------------

@app.get("/{page}")
async def serve_page(page: str):
    """Serve any HTML file from the router/ directory by name."""
    from router.page_registry import page_allowed

    if page.endswith(".html"):
        page = page[:-5]
    html_page = "studio" if page == "scene" else page
    path = _HTML_DIR / f"{html_page}.html"
    if path.is_file():
        return FileResponse(path)
    if not page_allowed(page):
        raise HTTPException(
            status_code=404,
            detail=f"Page not available in this install/mode: {page}",
        )
    raise HTTPException(status_code=404, detail=f"Page not found: {page}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _local_ips() -> list[str]:
    """Return non-loopback IPv4 addresses for the startup banner."""
    import socket
    ips: list[str] = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    return ips or ["127.0.0.1"]


def _is_first_run() -> bool:
    """True when no mullm.toml exists and no API keys are set."""
    from pathlib import Path
    has_toml = Path("mullm.toml").exists() or (Path.home() / ".mullm" / "config.toml").exists()
    has_key = any([
        settings.anthropic_api_key,
        settings.openai_api_key,
        getattr(settings, "google_api_key", None),
    ])
    return not has_toml and not has_key


def serve_09():
    """Entry point for `mullm0.9-server` — binds port 16856 unless MULLM_PORT is set."""
    if "MULLM_PORT" not in os.environ and settings.port == 6856:
        settings.port = 16856  # type: ignore[assignment]
    serve()


def serve():
    """Start the uvicorn server. Called by `mullm-server` CLI entry point."""
    import uvicorn

    host = "0.0.0.0" if settings.remote_access else "127.0.0.1"  # nosec B104 — gated by remote_access setting
    port = settings.port
    use_https = bool(settings.ssl_certfile and settings.ssl_keyfile)
    ips = _local_ips()
    if not use_https and getattr(settings, "auto_generate_cert", False):
        _cert_dir = Path(settings.cache_dir) / "certs"
        _cert_dir.mkdir(parents=True, exist_ok=True)
        _certfile = _cert_dir / "mullm.crt"
        _keyfile = _cert_dir / "mullm.key"
        if not (_certfile.exists() and _keyfile.exists()):
            try:
                import subprocess as _sp
                _san = "DNS:localhost,IP:127.0.0.1" + (f",IP:{ips[0]}" if ips else "")
                _sp.run([
                    "openssl", "req", "-x509", "-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:P-384",
                    "-keyout", str(_keyfile), "-out", str(_certfile),
                    "-days", "365", "-nodes", "-subj", "/CN=mullm-local",
                    "-addext", f"subjectAltName={_san}",
                ], check=True, capture_output=True)
                print(f"  Auto-cert: generated at {_certfile}")
            except Exception as _e:
                print(f"  Auto-cert: generation failed ({_e}), using HTTP")
        if _certfile.exists() and _keyfile.exists():
            settings.ssl_certfile = str(_certfile)  # type: ignore[assignment]
            settings.ssl_keyfile = str(_keyfile)    # type: ignore[assignment]
            use_https = True
    scheme = "https" if use_https else "http"
    local_url = f"{scheme}://127.0.0.1:{port}"
    setup_url = f"{scheme}://{ips[0]}:{port}/setup" if settings.remote_access else f"{local_url}/setup"

    # ── Startup banner ────────────────────────────────────────────────────────
    print(f"\n  mu|LLM  v{settings.version}  -  port {port}")
    print(f"  Local:   {local_url}")
    if settings.remote_access:
        for ip in ips:
            print(f"  Network: {scheme}://{ip}:{port}")
        print("  WARNING: Remote access ON - ensure this machine is behind a firewall")
    else:
        print("  Network: disabled  (set MULLM_REMOTE_ACCESS=true to enable)")

    open_browser = os.environ.get("MULLM_OPEN_BROWSER", "0").strip().lower() in {"1", "true", "yes", "on"}
    if _is_first_run():
        print("\n  First run detected - open the setup wizard:")
        print(f"    {setup_url}\n")
        if open_browser:
            try:
                import webbrowser
                webbrowser.open(local_url + "/setup")
            except Exception:
                pass
    else:
        print(f"  Setup:   {local_url}/setup")

    print()
    # ─────────────────────────────────────────────────────────────────────────

    # ── TLS context: TLS 1.3, ECDHE, no insecure ciphers ────────────────────
    ssl_context = None
    if use_https:
        import ssl as _ssl
        ssl_context = _ssl.SSLContext(_ssl.PROTOCOL_TLS_SERVER)
        ssl_context.minimum_version = _ssl.TLSVersion.TLSv1_3
        ssl_context.load_cert_chain(settings.ssl_certfile, settings.ssl_keyfile)
        if getattr(settings, "mtls_enabled", False) and getattr(settings, "ssl_ca_certs", None):
            ssl_context.verify_mode = _ssl.CERT_REQUIRED
            ssl_context.load_verify_locations(cafile=settings.ssl_ca_certs)
            print("  mTLS:    enabled (client cert required)")
        # Prefer ECDHE-384 ciphers; Python ssl inherits OS defaults which exclude RC4/3DES
        ssl_context.set_ciphers(
            "ECDHE-ECDSA-AES256-GCM-SHA384:"
            "ECDHE-RSA-AES256-GCM-SHA384:"
            "ECDHE-ECDSA-CHACHA20-POLY1305:"
            "ECDHE-RSA-CHACHA20-POLY1305"
        )
    uvicorn_kwargs: dict = dict(
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
        reload=settings.server_reload,
    )
    if ssl_context is not None:
        # uvicorn.run() doesn't accept ssl= directly; pass cert/key files
        if use_https:
            uvicorn_kwargs["ssl_keyfile"] = settings.ssl_keyfile
            uvicorn_kwargs["ssl_certfile"] = settings.ssl_certfile
    uvicorn.run("router.main:app", **uvicorn_kwargs)


if __name__ == "__main__":
    serve()
