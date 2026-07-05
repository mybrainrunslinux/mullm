"""
muLLM tier execution engine.

Pipeline flow per request:
  Tier 0  groundtruth.resolve()    → PipelineResult(tier=GROUNDTRUTH)
  Tier 1  cache.lookup()           → PipelineResult(tier=CACHE)
  Tier 2  _run_local()             → PipelineResult(tier=LOCAL)
  Tier 3a cloud.complete(cheap)    → PipelineResult(tier=CLOUD_CHEAP)
  Tier 3b cloud.complete(full)     → PipelineResult(tier=CLOUD_FULL)

Quality gate: if local response is very short (< 40 chars) or confidence is
below threshold, automatically escalate to CLOUD_CHEAP and mark
quality_escalated=True.

All tiers obey the 10-minute hard timeout from settings.request_timeout_seconds.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import AsyncIterator

import httpx

from router import cache, cloud, scorer
from router.backends.protocol import get_backend
from router.config import settings
from router.groundtruth import lookup as groundtruth_lookup
from router.models import IntentObject, PipelineResult, QueryRequest, TierLabel

logger = logging.getLogger("mullm.tiers")

# ---------------------------------------------------------------------------
# Response quality patterns
# ---------------------------------------------------------------------------

# Strip Qwen3 <think>…</think> reasoning blocks before quality assessment
_THINK_RE = re.compile(r"<think>.*?</think>\s*", re.DOTALL)

# Hard refusal detector — only when short (< 200 chars) to avoid false positives
# on responses that mention inability briefly before answering.
_REFUSAL_RE = re.compile(
    r"(?:"
    r"I (?:cannot|can't|will not|won't) (?:help|assist|do|provide|generate|create)"
    r"|I'm (?:unable|not able) to (?:help|assist|do|provide|generate|create)"
    r"|(?:sorry|apologies),?\s+(?:but )?I (?:cannot|can't)"
    r"|this (?:request )?(?:violates|goes against)"
    r"|I (?:must|need to )(?:decline|refuse)"
    r")",
    re.IGNORECASE,
)

# Minimum response length before quality gate triggers escalation
_QUALITY_MIN_CHARS = 40
_LOCAL_BACKEND_NAMES = {"ollama", "tabbyapi", "vllm", "sglang", "llamacpp", "mlx", "exllamav2"}


# ---------------------------------------------------------------------------
# Tier 0 — Groundtruth LUT
# ---------------------------------------------------------------------------

async def run_groundtruth(request: QueryRequest) -> PipelineResult | None:
    """Attempt deterministic resolution. Returns None to fall through."""
    t0 = time.monotonic()
    if settings.groundtruth_mode == "legacy":
        from router.realtime import try_resolve_identity, try_resolve_locally

        answer = try_resolve_identity(request.content) or try_resolve_locally(request.content)
        if answer is None:
            return None
        category = "legacy-realtime"
    else:
        result = groundtruth_lookup(request.content)
        if result is None:
            return None
        answer, category = result
    latency = (time.monotonic() - t0) * 1000
    return PipelineResult(
        response=answer,
        tier=TierLabel.GROUNDTRUTH,
        cost=0.0,
        tokens_used=0,
        latency_ms=round(latency, 2),
        model_used="groundtruth-lut",
        cached=False,
        session_id=request.session_id,
        groundtruth_category=category,
    )


# ---------------------------------------------------------------------------
# Tier 1 — Semantic cache
# ---------------------------------------------------------------------------

def _freshness_requires_cache_bypass(request: QueryRequest, intent: IntentObject) -> bool:
    """Return True when cache hits could plausibly be stale for this request."""
    if request.tier_override == TierLabel.CACHE:
        return False
    return bool(request.use_web or intent.needs_web)


def _should_store_in_cache(request: QueryRequest, intent: IntentObject, result: PipelineResult) -> bool:
    if result.cached or result.tier == TierLabel.GROUNDTRUTH:
        return False
    return not _freshness_requires_cache_bypass(request, intent)


async def run_cache(
    request: QueryRequest,
    intent: IntentObject,
) -> PipelineResult | None:
    """Semantic vector cache lookup. Returns None on miss."""
    if request.skip_cache:
        return None
    if _freshness_requires_cache_bypass(request, intent):
        logger.debug("Cache lookup skipped for freshness-sensitive query")
        return None
    t0 = time.monotonic()
    hit = await cache.lookup(request.content, category=intent.category.value)
    if hit is None:
        return None
    response_text, meta = hit
    latency = (time.monotonic() - t0) * 1000
    return PipelineResult(
        response=response_text,
        tier=TierLabel.CACHE,
        cost=0.0,
        tokens_used=0,
        latency_ms=round(latency, 2),
        model_used="vector-cache",
        cached=True,
        session_id=request.session_id,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# Tier 2 — Local Ollama inference
# ---------------------------------------------------------------------------

_OLLAMA_MODEL_CACHE: tuple[float, list[str]] = (0.0, [])
_OLLAMA_MODEL_CACHE_TTL = 15.0


def _is_embedding_model(name: str) -> bool:
    n = name.lower()
    return any(marker in n for marker in ("embed", "embedding", "nomic", "bge", "minilm", "e5-"))


def _model_matches(installed: str, requested: str) -> bool:
    if installed == requested:
        return True
    inst_base = installed.split(":", 1)[0]
    req_base = requested.split(":", 1)[0]
    return inst_base == req_base


async def _ollama_installed_models() -> list[str]:
    """Return installed Ollama model names, cached briefly."""
    global _OLLAMA_MODEL_CACHE
    now = time.monotonic()
    cached_at, cached = _OLLAMA_MODEL_CACHE
    if cached and now - cached_at < _OLLAMA_MODEL_CACHE_TTL:
        return cached
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            models = [
                m.get("name", "")
                for m in resp.json().get("models", [])
                if m.get("name")
            ]
            _OLLAMA_MODEL_CACHE = (now, models)
            return models
    except Exception:
        return []


def _local_multi_model() -> str:
    return (
        os.getenv("MULLM_OLLAMA_MULTI_MODEL")
        or os.getenv("LOCAL_MULTI_MODEL")
        or os.getenv("MULLM_LOCAL_POWER_MODEL")
        or settings.ollama_model
    )


async def _select_ollama_model(request: QueryRequest, intent: IntentObject) -> str:
    """Choose an installed Ollama model instead of blindly 404ing."""
    if request.model_override:
        preferred = request.model_override
    elif request.tier_override == TierLabel.LOCAL_MULTI:
        preferred = _local_multi_model()
    else:
        preferred = settings.ollama_vision_model if intent.needs_vision else settings.ollama_model
    installed = await _ollama_installed_models()
    if not installed:
        return preferred

    for candidate in (preferred, _local_multi_model(), settings.ollama_model):
        if not candidate:
            continue
        for model in installed:
            if _model_matches(model, candidate):
                if model != preferred:
                    logger.info("Ollama model %s not installed; using installed model %s", preferred, model)
                return model

    text_models = [m for m in installed if not _is_embedding_model(m)]
    if intent.needs_vision:
        visionish = [m for m in text_models if any(x in m.lower() for x in ("vl", "vision", "llava", "minicpm"))]
        if visionish:
            logger.info("Ollama vision model %s not installed; using installed vision model %s", preferred, visionish[0])
            return visionish[0]
        return preferred

    if not text_models:
        return preferred

    category = getattr(intent.category, "value", str(intent.category)).lower()
    if category == "code":
        coder = [m for m in text_models if "code" in m.lower() or "coder" in m.lower()]
        if coder:
            logger.info("Ollama model %s not installed; using installed coding model %s", preferred, coder[0])
            return coder[0]

    logger.info("Ollama model %s not installed; using installed model %s", preferred, text_models[0])
    return text_models[0]


async def _select_ollama_model_safe(request: QueryRequest, intent: IntentObject) -> str:
    """Select Ollama model and evict conflicting large models if needed."""
    from router.vram_guard import ensure_vram_headroom, evict_all_except

    model = await _select_ollama_model(request, intent)

    ctx = request.context if hasattr(request, "context") and request.context else {}
    if ctx.get("bench_mode"):
        evicted = await evict_all_except(model)
        if evicted:
            logger.info("bench_mode VRAM evict: removed %s", evicted)
    else:
        # Pass no required_bytes — guard looks up actual model size from Ollama tags
        evicted = await ensure_vram_headroom(model)
        if evicted:
            logger.info("VRAM guard: evicted %s before loading %s", evicted, model)

    return model


def _build_ollama_payload(request: QueryRequest, intent: IntentObject, model_name: str) -> dict:
    """Construct the Ollama /api/generate payload."""
    temperature = request.temperature if request.temperature is not None \
        else scorer.default_temperature(intent)

    messages = []
    for turn in (request.history or [])[-6:]:  # last 6 turns for context
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": request.content})

    # Respect think flag from request context (bench can pass think=True per-language)
    ctx = request.context if hasattr(request, "context") and request.context else {}
    think = bool(ctx.get("think", False))
    num_predict = int(ctx.get("num_predict", -1))

    options: dict = {
        "temperature": temperature,
        "num_ctx": settings.ollama_num_ctx,
        "think": think,
    }
    if num_predict > 0:
        options["num_predict"] = num_predict

    # Vision: attach images if present
    payload: dict = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "options": options,
        "keep_alive": settings.ollama_keep_alive,
    }
    if intent.needs_vision and request.images:
        # Ollama vision: images attached to the last user message
        payload["messages"][-1]["images"] = request.images

    return payload


def _messages_from_request(request: QueryRequest) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    for turn in (request.history or [])[-6:]:
        messages.append({"role": str(turn["role"]), "content": str(turn["content"])})
    messages.append({"role": "user", "content": request.content})
    return messages


def _local_backend_priority() -> list[str]:
    raw = settings.local_backend_priority
    env = os.getenv("MULLM_LOCAL_BACKEND_PRIORITY")
    if env:
        raw = env
    names = [item.strip().lower() for item in raw.split(",") if item.strip()]
    clean = [name for name in names if name in _LOCAL_BACKEND_NAMES]
    return clean or ["ollama"]


def _select_registered_local_backend() -> str:
    for name in _local_backend_priority():
        if name == "ollama":
            return name
        if get_backend(name) is not None:
            return name
    return "ollama"


async def _run_registered_local_backend(
    backend_name: str,
    request: QueryRequest,
    intent: IntentObject,
) -> PipelineResult:
    backend = get_backend(backend_name)
    if backend is None:
        raise RuntimeError(f"Local backend '{backend_name}' is not registered")
    temperature = request.temperature if request.temperature is not None else scorer.default_temperature(intent)
    result = await backend.generate(
        _messages_from_request(request),
        model=request.model_override,
        temperature=temperature,
        max_tokens=4096,
    )
    response_text = _strip_think_tags(result.text)
    tokens = result.input_tokens + result.output_tokens
    return PipelineResult(
        response=response_text,
        tier=TierLabel.LOCAL,
        cost=result.cost_usd,
        tokens_used=tokens,
        latency_ms=0.0,
        model_used=result.model or request.model_override or backend_name,
        cached=False,
        session_id=request.session_id,
        intent=intent,
    )


async def run_local(
    request: QueryRequest,
    intent: IntentObject,
) -> PipelineResult:
    """Execute local Ollama inference (non-streaming)."""
    t0 = time.monotonic()
    backend_name = _select_registered_local_backend()
    if backend_name != "ollama":
        result = await _run_registered_local_backend(backend_name, request, intent)
        result.latency_ms = round((time.monotonic() - t0) * 1000, 2)
        return result

    model_name = await _select_ollama_model_safe(request, intent)
    payload = _build_ollama_payload(request, intent, model_name)
    model_name = payload["model"]

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
            resp = await client.post(
                f"{settings.ollama_base_url}/api/chat",
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
    except httpx.TimeoutException:
        raise RuntimeError(f"Ollama timed out after {settings.request_timeout_seconds}s")
    except httpx.HTTPStatusError as exc:
        detail = ""
        try:
            detail = exc.response.text[:500]
        except Exception:
            pass
        if exc.response.status_code == 404:
            installed = await _ollama_installed_models()
            installed_text = ", ".join(installed) if installed else "none detected"
            raise RuntimeError(
                f"Ollama model '{model_name}' is not installed. Installed models: {installed_text}. "
                "Pull a model in Setup or set MULLM_OLLAMA_MODEL to an installed model."
            ) from exc
        raise RuntimeError(f"Ollama HTTP error: {exc.response.status_code} {detail}".strip()) from exc

    latency = (time.monotonic() - t0) * 1000
    message = data.get("message", {})
    raw_content = message.get("content", "")

    # Strip Qwen3 think tags before storing/checking quality
    response_text = _strip_think_tags(raw_content)

    # Token usage (Ollama may return eval_count / prompt_eval_count)
    tokens = data.get("eval_count", 0) + data.get("prompt_eval_count", 0)

    return PipelineResult(
        response=response_text,
        tier=TierLabel.LOCAL,
        cost=0.0,
        tokens_used=tokens,
        latency_ms=round(latency, 2),
        model_used=model_name,
        cached=False,
        session_id=request.session_id,
        intent=intent,
    )


async def stream_local(
    request: QueryRequest,
    intent: IntentObject,
) -> AsyncIterator[str]:
    """Stream local Ollama inference as SSE chunks."""
    import json

    backend_name = _select_registered_local_backend()
    if backend_name != "ollama":
        backend = get_backend(backend_name)
        if backend is None:
            raise RuntimeError(f"Local backend '{backend_name}' is not registered")
        temperature = request.temperature if request.temperature is not None else scorer.default_temperature(intent)
        async for chunk in backend.stream(
            _messages_from_request(request),
            model=request.model_override,
            temperature=temperature,
            max_tokens=4096,
        ):
            yield chunk
        return

    model_name = await _select_ollama_model_safe(request, intent)
    payload = _build_ollama_payload(request, intent, model_name)
    payload["stream"] = True

    async with httpx.AsyncClient(timeout=settings.request_timeout_seconds) as client:
        async with client.stream(
            "POST",
            f"{settings.ollama_base_url}/api/chat",
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk = json.loads(line)
                except json.JSONDecodeError:
                    continue
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content
                if chunk.get("done"):
                    break


# ---------------------------------------------------------------------------
# Tier 3 — Cloud
# ---------------------------------------------------------------------------

def _provider_from_model(model: str) -> str:
    """Derive provider name from model string for ELO feedback."""
    m = model.lower()
    if m.startswith("claude"):           return "anthropic"
    if m.startswith("gpt") or m.startswith("o1") or m.startswith("o3"): return "openai"
    if m.startswith("gemini"):           return "google"
    if m.startswith("cerebras"):         return "cerebras"
    if m.startswith("deepseek"):         return "deepseek"
    if m.startswith("glm"):              return "glm"
    return ""


def _canonical_cloud_tier_for_model(tier: TierLabel, model: str) -> TierLabel:
    """Collapse cloud tier labels when configured tiers use the same model."""
    if tier not in {TierLabel.CLOUD_CHEAP, TierLabel.CLOUD_FULL, TierLabel.CLOUD_POWER}:
        return tier
    provider = _provider_from_model(model)
    if not provider:
        return tier
    try:
        from router.provider_selector import provider_model_map

        models = provider_model_map().get(provider)
    except Exception:
        models = None
    if not models:
        return tier
    cheap_model, full_model, power_model = models
    if model == cheap_model:
        return TierLabel.CLOUD_CHEAP
    if model == full_model:
        return TierLabel.CLOUD_FULL
    if model == power_model:
        return TierLabel.CLOUD_POWER
    return tier


async def run_cloud(
    request: QueryRequest,
    intent: IntentObject,
    cheap: bool = True,
    tier: TierLabel | None = None,
) -> PipelineResult:
    """Execute cloud API call via the unified cloud.complete() interface."""
    t0 = time.monotonic()
    tier = tier or (TierLabel.CLOUD_CHEAP if cheap else TierLabel.CLOUD_FULL)
    model = request.model_override or cloud.model_for_tier(
        cheap=cheap,
        tier=tier.value,
        cost_strategy=request.cost_strategy,
    )
    reported_tier = tier if request.model_override else _canonical_cloud_tier_for_model(tier, model)
    if model not in cloud.CLOUD_MODEL_PRICING:
        raise ValueError(f"Unknown cloud model: {model!r}. Refusing provider call.")
    temperature = request.temperature if request.temperature is not None \
        else scorer.default_temperature(intent)

    provider = _provider_from_model(model)
    try:
        result = await cloud.complete(
            prompt=request.content,
            model=model,
            max_tokens=4096,
            temperature=temperature,
        )
    except Exception:
        from router import provider_policy
        provider_policy.record_failure(provider)
        raise

    latency = (time.monotonic() - t0) * 1000

    # ELO feedback: record success with quality signals
    if provider:
        from router import provider_policy
        provider_policy.record_success(provider)
        try:
            data = provider_policy._load()
            entry = data.setdefault("providers", {}).setdefault(provider, {})
            # Rolling average latency (ELO quality proxy)
            prev_latency = float(entry.get("avg_latency_ms") or latency)
            entry["avg_latency_ms"] = round(prev_latency * 0.8 + latency * 0.2, 1)
            entry["total_requests"] = int(entry.get("total_requests") or 0) + 1
            provider_policy._save(data)
        except Exception:
            pass

    return PipelineResult(
        response=result.text,
        tier=reported_tier,
        cost=result.cost,
        tokens_used=result.input_tokens + result.output_tokens,
        latency_ms=round(latency, 2),
        model_used=model,
        cached=False,
        session_id=request.session_id,
        intent=intent,
    )


# ---------------------------------------------------------------------------
# Quality gate
# ---------------------------------------------------------------------------

def _should_escalate(
    text: str,
    category: IntentObject | None = None,
    complexity: int = 2,
) -> tuple[bool, str]:
    """
    Return (should_escalate, reason) for a local model response.

    Escalates only on genuine failures:
      - Empty response
      - Hard refusal (when short)
      - Too short for request complexity
      - Degenerate (single-line, very short, non-trivial request)
      - Repetitive trigram loops
      - Low vocabulary ratio (< 25% unique words)
    Never escalates on hedging language ("I think", "probably", etc.).
    """
    # Strip think tags before assessing quality
    stripped = _THINK_RE.sub("", text).strip()

    if not stripped:
        return True, "empty_response"

    if _REFUSAL_RE.search(stripped[:300]) and len(stripped) < 200:
        return True, "model_refused"

    if complexity >= 4 and len(stripped) < 80:
        return True, "too_short_for_complexity"

    # Short single-line answers are fine for lookup/math (complexity 1-2)
    if len(stripped) < 30 and "\n" not in stripped and complexity >= 3:
        return True, "degenerate_response"

    # Quality probe for complexity 3+: detect repetitive/incoherent output
    if complexity >= 3 and len(stripped) > 80:
        words = stripped.split()

        # Check for repetitive 3-gram loops (3-gram repeated 4+ times)
        if len(words) >= 12:
            trigrams: dict[tuple, int] = {}
            for i in range(len(words) - 2):
                tg = (words[i].lower(), words[i + 1].lower(), words[i + 2].lower())
                trigrams[tg] = trigrams.get(tg, 0) + 1
            if any(v >= 4 for v in trigrams.values()):
                return True, "repetitive_output"

        # Low vocabulary ratio → repetitive content
        if len(words) >= 40:
            unique_ratio = len({w.lower() for w in words}) / len(words)
            if unique_ratio < 0.25:
                return True, "low_vocabulary_repetition"

    return False, ""


def _strip_think_tags(text: str) -> str:
    """Strip Qwen3 <think>…</think> blocks from a response."""
    result = _THINK_RE.sub("", text).strip()
    # Handle unclosed <think> tags — discard partial reasoning
    if "<think>" in result:
        result = re.sub(r"<think>.*", "", result, flags=re.DOTALL).strip()
    return result


def _passes_quality_gate(result: PipelineResult) -> bool:
    """Return True if the local response is acceptable quality."""
    escalate, _ = _should_escalate(
        result.response,
        complexity=result.intent.complexity if result.intent else 2,
    )
    return not escalate


# ---------------------------------------------------------------------------
# Full pipeline executor
# ---------------------------------------------------------------------------

async def execute_pipeline(
    request: QueryRequest,
    cancel_event: asyncio.Event | None = None,
) -> PipelineResult:
    """
    Run the full 4-tier pipeline for a query.

    Tier override (request.tier_override) bypasses routing and executes the
    specified tier directly.  Budget exhaustion forces LOCAL tier.
    cancel_event: if set and triggered, raises asyncio.CancelledError between tiers.
    """

    def _check_cancel():
        if cancel_event is not None and cancel_event.is_set():
            raise asyncio.CancelledError("Request cancelled by client")

    zero_tier_only = request.tier_override == TierLabel.GROUNDTRUTH
    allow_zero_tier = request.tier_override is None or zero_tier_only

    if allow_zero_tier:
        # ── Tier 0: Groundtruth ──────────────────────────────────────────
        _check_cancel()
        gt_result = await run_groundtruth(request)
        if gt_result is not None:
            scorer.log_request(
                session_id=request.session_id,
                query=request.content,
                response=gt_result.response,
                tier=gt_result.tier,
                model=gt_result.model_used,
                cost=0.0,
                tokens=0,
                latency_ms=gt_result.latency_ms,
            )
            return gt_result

        # ── Tier 0.5: Live weather (Open-Meteo, free, no key) ────────────
        _check_cancel()
        try:
            from router.realtime import try_resolve_weather_async
            t0w = time.monotonic()
            weather_answer = await try_resolve_weather_async(request.content)
            if weather_answer is not None:
                w_ms = round((time.monotonic() - t0w) * 1000, 2)
                scorer.log_request(
                    session_id=request.session_id,
                    query=request.content,
                    response=weather_answer,
                    tier=TierLabel.GROUNDTRUTH,
                    model="open-meteo-live",
                    cost=0.0,
                    tokens=0,
                    latency_ms=w_ms,
                )
                return PipelineResult(
                    response=weather_answer,
                    tier=TierLabel.GROUNDTRUTH,
                    cost=0.0,
                    tokens_used=0,
                    latency_ms=w_ms,
                    model_used="open-meteo-live",
                    cached=False,
                    session_id=request.session_id,
                    groundtruth_category="weather-live",
                )
        except Exception as _we:
            logger.debug("Weather live lookup skipped: %s", _we)

    if zero_tier_only:
        return PipelineResult(
            response="Groundtruth miss — no deterministic result available.",
            tier=TierLabel.GROUNDTRUTH,
            cost=0.0,
            tokens_used=0,
            latency_ms=0.0,
            model_used="groundtruth-lut",
            cached=False,
            session_id=request.session_id,
        )

    # ── Classify intent ──────────────────────────────────────────────────
    _check_cancel()
    from router.intent import classify
    intent = classify(request.content, history=request.history)

    # ── Budget check ─────────────────────────────────────────────────────
    budget_exhausted = scorer.is_budget_exhausted(request.session_id)
    if budget_exhausted:
        logger.warning("Budget exhausted for session %s — forcing LOCAL tier", request.session_id)

    # ── Handle tier override ─────────────────────────────────────────────
    if request.tier_override is not None:
        _check_cancel()
        override = request.tier_override
        if budget_exhausted and override in (TierLabel.CLOUD_CHEAP, TierLabel.CLOUD_FULL, TierLabel.CLOUD_POWER):
            override = TierLabel.LOCAL
        if override == TierLabel.CACHE:
            result = await run_cache(request, intent)
            if result is None:
                result = PipelineResult(
                    response="Cache miss — no cached result available.",
                    tier=TierLabel.CACHE,
                    cost=0.0, tokens_used=0, latency_ms=0.0,
                    model_used="vector-cache", cached=False,
                    session_id=request.session_id, intent=intent,
                )
        elif override == TierLabel.LOCAL:
            result = await run_local(request, intent)
        elif override == TierLabel.LOCAL_MULTI:
            result = await run_local(request, intent)
            result.tier = TierLabel.LOCAL_MULTI
            result.tier_used = TierLabel.LOCAL_MULTI.value
        elif override == TierLabel.CLOUD_CHEAP:
            result = await run_cloud(request, intent, cheap=True)
        elif override == TierLabel.CLOUD_FULL:
            result = await run_cloud(request, intent, cheap=False)
        elif override == TierLabel.CLOUD_POWER:
            result = await run_cloud(request, intent, cheap=False, tier=TierLabel.CLOUD_POWER)
        else:
            result = await run_local(request, intent)

        _post_process(request, result, intent)
        return result

    if budget_exhausted:
        result = await run_local(request, intent)
        _post_process(request, result, intent)
        return result

    # ── Tier 1: Cache ────────────────────────────────────────────────────
    _check_cancel()
    cache_result = await run_cache(request, intent)
    if cache_result is not None:
        scorer.log_request(
            session_id=request.session_id,
            query=request.content,
            response=cache_result.response,
            tier=cache_result.tier,
            model=cache_result.model_used,
            cost=0.0, tokens=0,
            latency_ms=cache_result.latency_ms,
            intent=intent, cached=True,
        )
        return cache_result

    # ── Select tier by intent ────────────────────────────────────────────
    _check_cancel()
    selected_tier = scorer.select_tier(intent, session_id=request.session_id)

    quality_escalated = False

    if selected_tier == TierLabel.LOCAL:
        result = await run_local(request, intent)
        # Quality gate: escalate to cheap cloud if local is poor
        _check_cancel()
        if request.allow_cloud_escalation and not _passes_quality_gate(result):
            logger.info("Quality gate triggered — escalating to CLOUD_CHEAP")
            try:
                result = await run_cloud(request, intent, cheap=True)
                result.quality_escalated = True
                quality_escalated = True
            except Exception as exc:
                logger.warning("Cloud escalation failed: %s — keeping local result", exc)
        elif not request.allow_cloud_escalation and not _passes_quality_gate(result):
            logger.info("Quality gate would escalate, but automatic cloud escalation is disabled")

    elif selected_tier == TierLabel.CLOUD_CHEAP:
        try:
            result = await run_cloud(request, intent, cheap=True)
        except Exception as exc:
            logger.warning("Cloud cheap unavailable (%s) — falling back to local", exc)
            result = await run_local(request, intent)

    elif selected_tier == TierLabel.CLOUD_FULL:
        try:
            result = await run_cloud(request, intent, cheap=False)
        except Exception as exc:
            logger.warning("Cloud full unavailable (%s) — falling back to local", exc)
            result = await run_local(request, intent)

    elif selected_tier == TierLabel.CLOUD_POWER:
        try:
            result = await run_cloud(request, intent, cheap=False, tier=TierLabel.CLOUD_POWER)
        except Exception as exc:
            logger.warning("Cloud power unavailable (%s) — falling back to cloud full", exc)
            try:
                result = await run_cloud(request, intent, cheap=False)
            except Exception:
                result = await run_local(request, intent)

    else:
        result = await run_local(request, intent)

    _post_process(request, result, intent, quality_escalated=quality_escalated)
    return result


def _post_process(
    request: QueryRequest,
    result: PipelineResult,
    intent: IntentObject,
    quality_escalated: bool = False,
) -> None:
    """Log result and store in cache (async fire-and-forget)."""
    scorer.log_request(
        session_id=request.session_id,
        query=request.content,
        response=result.response,
        tier=result.tier,
        model=result.model_used,
        cost=result.cost,
        tokens=result.tokens_used,
        latency_ms=result.latency_ms,
        intent=intent,
        cached=result.cached,
        quality_escalated=quality_escalated,
    )

    # Store non-cached results in vector cache (best-effort, don't await)
    if _should_store_in_cache(request, intent, result):
        meta = {
            "session_id": request.session_id,
            "tier": result.tier.value,
            "model": result.model_used,
            "category": intent.category.value,
            "complexity": intent.complexity,
        }
        asyncio.create_task(
            cache.store(request.content, result.response, metadata=meta)
        )


# ---------------------------------------------------------------------------
# Compatibility layer — old tier-execution API  
# ---------------------------------------------------------------------------

try:
    import ollama as ollama_client  # type: ignore
except ImportError:
    ollama_client = None  # type: ignore

from router.models import (
    ClassificationResult,
    IntentCategory,
    ModelSelection,
    Tier,
    TierResult,
)

SYSTEM_PROMPTS: dict[IntentCategory, str] = {
    IntentCategory.CODE: (
        "You are an expert software engineer. Provide clear, working code with "
        "minimal prose. For diagrams use mermaid syntax. Include type hints for "
        "Python. Do not add unnecessary comments."
    ),
    IntentCategory.RESEARCH: (
        "You are a research assistant. Provide accurate, well-sourced information "
        "with structured analysis. Cite sources when possible."
    ),
    IntentCategory.CREATIVE: (
        "You are a creative writing assistant. Be imaginative, engaging, and "
        "original. Match the tone requested by the user."
    ),
    IntentCategory.CONVERSATION: (
        "You are a helpful, friendly assistant. Be concise and conversational. "
        "Answer directly without unnecessary preamble."
    ),
    IntentCategory.DEPLOY: (
        "You are a DevOps and deployment expert. Provide specific, actionable "
        "commands and configuration. Prefer idempotent solutions."
    ),
    IntentCategory.NOTE: (
        "You are a note-taking assistant. Summarize and organize information "
        "clearly. Use bullet points and headers where appropriate."
    ),
    IntentCategory.LOOKUP: (
        "You are a precise lookup assistant. Give direct, factual answers. "
        "Be brief — one or two sentences unless more is needed."
    ),
    IntentCategory.VISION: (
        "You are a vision assistant. Describe images accurately and in detail. "
        "Answer questions about visual content precisely."
    ),
}

CATEGORY_MODELS: dict[IntentCategory, str] = {
    IntentCategory.CODE:         settings.ollama_model,
    IntentCategory.RESEARCH:     settings.ollama_model,
    IntentCategory.CREATIVE:     settings.ollama_model,
    IntentCategory.CONVERSATION: settings.ollama_model,
    IntentCategory.DEPLOY:       settings.ollama_model,
    IntentCategory.NOTE:         settings.ollama_model,
    IntentCategory.LOOKUP:       settings.ollama_model,
    IntentCategory.VISION:       settings.ollama_vision_model or settings.ollama_model,
}


def _get_token_count(response: dict, text: str) -> int:
    """Extract token count from Ollama chat response, fallback to char estimate."""
    count = response.get("eval_count", 0) + response.get("prompt_eval_count", 0)
    if count > 0:
        return count
    return max(len(text) // 4, 10)


def _truncate_loop(text: str, max_repeats: int = 5) -> str:
    """Detect and remove excessively repeated lines from model output."""
    lines = text.split("\n")
    if len(lines) < 10:
        return text
    counts: dict[str, int] = {}
    result = []
    for line in lines:
        key = line.strip()
        if key:
            counts[key] = counts.get(key, 0) + 1
            if counts[key] > max_repeats:
                continue
        result.append(line)
    return "\n".join(result)


async def execute_tier_local(
    intent: IntentObject,
    classification: ClassificationResult,
) -> TierResult:
    """Execute local Ollama tier via ollama_client.chat()."""
    import time as _time
    t0 = _time.monotonic()
    has_images = bool(getattr(intent, "images", None))

    _vision_model = settings.ollama_vision_model or settings.ollama_model

    model = _vision_model if has_images else CATEGORY_MODELS.get(classification.category, settings.ollama_model)
    system_prompt = SYSTEM_PROMPTS.get(classification.category, "You are a helpful assistant.")

    try:
        messages: list[dict] = [{"role": "system", "content": system_prompt}]
        for turn in (getattr(intent, "history", None) or []):
            messages.append({"role": turn["role"], "content": turn["content"]})
        user_msg: dict = {"role": "user", "content": intent.content}
        if has_images:
            user_msg["images"] = intent.images  # type: ignore
        messages.append(user_msg)

        if ollama_client is None:
            return TierResult(
                intent_id=intent.id,
                tier=Tier.LOCAL,
                success=False,
                response="ollama Python client not installed",
                model_used=model,
                escalate=True,
                escalate_reason="ollama_error: client not installed",
            )

        resp = ollama_client.chat(model=model, messages=messages)
        text = resp.get("message", {}).get("content", "")
        text = _strip_think_tags(text)
        text = _truncate_loop(text)
        tokens = _get_token_count(resp, text)
        latency = (_time.monotonic() - t0) * 1000

        escalate, esc_reason = _should_escalate(text, classification.category, classification.complexity)
        return TierResult(
            intent_id=intent.id,
            tier=Tier.LOCAL,
            success=not escalate,
            response=text,
            model_used=model,
            tokens_used=tokens,
            cost=0.0,
            latency_ms=round(latency, 2),
            escalate=escalate,
            escalate_reason=esc_reason,
        )
    except Exception as exc:
        latency = (_time.monotonic() - t0) * 1000
        return TierResult(
            intent_id=intent.id,
            tier=Tier.LOCAL,
            success=False,
            response=f"Local model error: {exc}",
            model_used=model,
            latency_ms=round(latency, 2),
            escalate=True,
            escalate_reason=f"ollama_error: {exc}",
        )


async def execute_tier_local_multi(
    intent: IntentObject,
    classification: ClassificationResult,
) -> TierResult:
    """Execute local multi-model (higher quality local) tier."""
    import time as _time
    t0 = _time.monotonic()
    model = _local_multi_model()
    system_prompt = SYSTEM_PROMPTS.get(classification.category, "You are a helpful assistant.")
    if ollama_client is None:
        return TierResult(
            intent_id=intent.id,
            tier=Tier.LOCAL_MULTI,
            success=False,
            response="ollama Python client not installed",
            model_used=model,
            escalate=True,
            escalate_reason="ollama_error: client not installed",
        )
    try:
        # Step 1: planning pass
        plan_resp = ollama_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Create a brief plan for: {intent.content}"},
            ],
        )
        plan_text = _strip_think_tags(plan_resp.get("message", {}).get("content", ""))
    except Exception:
        return await execute_tier_local(intent, classification)
    try:
        # Step 2: execution pass using the plan as context
        resp = ollama_client.chat(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": intent.content},
                {"role": "assistant", "content": plan_text},
                {"role": "user", "content": "Now implement this completely."},
            ],
        )
        text = resp.get("message", {}).get("content", "")
        text = _strip_think_tags(text)
        text = _truncate_loop(text)
        tokens = _get_token_count(plan_resp, plan_text) + _get_token_count(resp, text)
        latency = (_time.monotonic() - t0) * 1000
        return TierResult(
            intent_id=intent.id,
            tier=Tier.LOCAL_MULTI,
            success=True,
            response=text,
            model_used=model,
            tokens_used=tokens,
            cost=0.0,
            latency_ms=round(latency, 2),
        )
    except Exception as exc:
        latency = (_time.monotonic() - t0) * 1000
        return TierResult(
            intent_id=intent.id,
            tier=Tier.LOCAL_MULTI,
            success=False,
            response=f"Multi model error: {exc}",
            model_used=model,
            latency_ms=round(latency, 2),
            escalate=True,
            escalate_reason=f"ollama_error: {exc}",
        )


async def execute_tier_cloud(
    intent: IntentObject,
    classification: ClassificationResult,
    selection: ModelSelection,
) -> TierResult:
    """Execute cloud tier using the raw-httpx execute_cloud dispatch."""
    import time as _time
    if not cloud.is_configured(selection.provider):
        return TierResult(
            intent_id=intent.id,
            tier=Tier.CLOUD_FULL,
            success=False,
            response=f"CLOUD ERROR: Provider {selection.provider!r} is not configured",
            model_used=selection.model_name,
            latency_ms=0.0,
            escalate=False,
            escalate_reason="provider_not_configured",
            cache_back=False,
        )
    t0 = _time.monotonic()
    try:
        prompt = intent.content
        history = getattr(intent, "history", None)
        if history:
            hist_str = "\n".join(
                f"{t['role'].capitalize()}: {t['content']}" for t in history
            )
            prompt = f"Previous conversation:\n{hist_str}\n\nUser: {prompt}"
        result = await cloud.execute_cloud(
            prompt=prompt,
            system=SYSTEM_PROMPTS.get(classification.category, "You are a helpful assistant."),
            model_name=selection.model_name,
            provider=selection.provider,
        )
        latency = (_time.monotonic() - t0) * 1000
        # Map tier label string to Tier enum
        tier_map = {
            "cloud_cheap": Tier.CLOUD_CHEAP,
            "cloud_full": Tier.CLOUD_FULL,
            "cloud_power": Tier.CLOUD_POWER,
        }
        tier = tier_map.get(getattr(selection, "tier", Tier.CLOUD_FULL), Tier.CLOUD_FULL)
        return TierResult(
            intent_id=intent.id,
            tier=tier,
            success=True,
            response=result["text"],
            model_used=selection.model_name,
            tokens_used=result.get("tokens_in", 0) + result.get("tokens_out", 0),
            cost=result.get("cost", 0.0),
            latency_ms=round(latency, 2),
            cache_back=True,
        )
    except (ValueError, RuntimeError) as exc:
        latency = (_time.monotonic() - t0) * 1000
        return TierResult(
            intent_id=intent.id,
            tier=Tier.CLOUD_FULL,
            success=False,
            response=f"CLOUD ERROR: {exc}",
            model_used=selection.model_name,
            latency_ms=round(latency, 2),
            escalate=False,
        )
    except Exception as exc:
        latency = (_time.monotonic() - t0) * 1000
        return TierResult(
            intent_id=intent.id,
            tier=Tier.CLOUD_FULL,
            success=False,
            response=f"CLOUD ERROR: {exc}",
            model_used=selection.model_name,
            latency_ms=round(latency, 2),
            escalate=False,
        )


async def execute_tier_note(
    intent: IntentObject,
    classification: ClassificationResult,
) -> TierResult:
    """Acknowledge a note in-memory without calling any model."""
    keywords = classification.keywords or []
    if keywords:
        kw_str = ", ".join(keywords)
        response = f"Noted: {kw_str}."
    else:
        response = "Noted: general note."
    return TierResult(
        intent_id=intent.id,
        tier=Tier.CACHE,
        success=True,
        response=response,
        model_used="local",
        cost=0.0,
        latency_ms=0.0,
        cache_back=False,
    )
