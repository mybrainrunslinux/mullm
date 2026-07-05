"""
muLLM cloud API clients.

Unified async interface:
    async def complete(prompt, model, max_tokens, temperature) -> CloudResult

Supported providers:
    - Anthropic  (claude-haiku-4-5, claude-sonnet-4-6, claude-opus-4-7, …)
    - OpenAI     (gpt-4o-mini, gpt-4o, gpt-5.5, gpt-5.5-pro, gpt-5.4-pro)
    - Google     (gemini-1.5-flash, gemini-2.5-flash, gemini-3.1-pro-preview, …)
    - Cerebras   (gpt-oss-120b) — OpenAI-compatible, ~3000 tok/s on WSE
    - DeepSeek   (deepseek-v4-pro, deepseek-v4-flash) — OpenAI-compatible
    - GLM/Zhipu  (glm-5.1) — OpenAI-compatible

All calls:
    - Retry with exponential backoff (3 attempts, 1s/2s/4s)
    - Token counting for cost calculation
    - 120-second per-call timeout
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import httpx

from router import provider_policy
from router.config import CLOUD_MODEL_PRICING, settings

logger = logging.getLogger("mullm.cloud")

# Module-level API keys (readable by tests via patch)
def _provider_key(provider: str) -> str:
    """Resolve a provider API key at call time.

    Checks the process environment first, then settings — which is what
    actually loads .env / MULLM_ENV_FILE. Import-time env snapshots miss
    keys that arrive via env files or `pass` after module import.
    """
    env_names = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY", "google": "GOOGLE_API_KEY"}
    attrs = {"anthropic": "anthropic_api_key", "openai": "openai_api_key", "google": "google_api_key"}
    key = os.environ.get(env_names.get(provider, ""), "")
    if not key:
        key = getattr(settings, attrs.get(provider, ""), None) or ""
    return key

_RETRY_DELAYS = [1.0, 2.0, 4.0]   # seconds between retries

# HTTP status codes that warrant a retry (rate limit, server overload, transient errors)
_RETRYABLE_CODES = {429, 529, 500, 502, 503, 504}


def _safe_log_kwargs(kwargs: dict) -> dict:
    """Return a copy of kwargs safe for logging — redact keys/secrets, drop messages."""
    return {k: ("***" if "key" in k.lower() or "secret" in k.lower() or "token" in k.lower() else v)
            for k, v in kwargs.items() if k != "messages"}  # never log messages content


@dataclass
class CloudResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str
    provider: str

    @property
    def cost(self) -> float:
        """Compute cost in USD from the pricing catalogue."""
        pricing = CLOUD_MODEL_PRICING.get(self.model)
        if pricing is None:
            return 0.0
        return (
            self.input_tokens  * pricing["cost_per_m_input"]  / 1_000_000
            + self.output_tokens * pricing["cost_per_m_output"] / 1_000_000
        )


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

async def _with_retry(coro_fn, *args, provider_name: str | None = None, **kwargs) -> CloudResult:
    last_exc: Exception = RuntimeError("Unknown error")
    for attempt, delay in enumerate(_RETRY_DELAYS + [None], start=1):
        try:
            result = await asyncio.wait_for(coro_fn(*args, **kwargs), timeout=120.0)
            if provider_name:
                provider_policy.record_success(provider_name)
            return result
        except TimeoutError as exc:
            last_exc = exc
            if provider_name:
                provider_policy.record_failure(provider_name)
            logger.warning("Cloud call timeout on attempt %d", attempt)
        except Exception as exc:
            last_exc = exc
            status = getattr(exc, "status_code", None)
            if provider_name and status in _RETRYABLE_CODES:
                provider_policy.record_failure(provider_name, status_code=status)
            # Don't retry on auth errors or other non-retryable client errors
            if status is not None and status not in _RETRYABLE_CODES:
                raise
            logger.warning("Cloud call error on attempt %d (status=%s): %s", attempt, status, exc)
        if delay is not None:
            await asyncio.sleep(delay)
    raise last_exc


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

# Models that reject sampling params (temperature/top_p/top_k → HTTP 400).
_ANTHROPIC_NO_SAMPLING_PREFIXES = (
    "claude-fable", "claude-mythos", "claude-opus-4-7", "claude-opus-4-8", "claude-sonnet-5",
)
# Fable-class models: thinking always on, refusal stop reason possible.
_ANTHROPIC_FABLE_PREFIXES = ("claude-fable", "claude-mythos")
_FABLE_FALLBACK_MODEL = "claude-opus-4-8"
_FABLE_FALLBACK_BETA = "server-side-fallback-2026-06-01"


def _anthropic_accepts_sampling(model: str) -> bool:
    return not model.startswith(_ANTHROPIC_NO_SAMPLING_PREFIXES)


def _is_fable_model(model: str) -> bool:
    return model.startswith(_ANTHROPIC_FABLE_PREFIXES)


def _anthropic_text(content: list) -> str:
    """First text block — Fable-class responses lead with thinking blocks."""
    for block in content or []:
        btype = block.get("type") if isinstance(block, dict) else getattr(block, "type", None)
        if btype == "text":
            return block.get("text", "") if isinstance(block, dict) else getattr(block, "text", "")
    return ""


async def _anthropic_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.anthropic_api_key:
        raise RuntimeError("MULLM_ANTHROPIC_API_KEY not set")
    import anthropic  # deferred — not installed in all envs

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    kwargs = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _anthropic_accepts_sampling(model):
        kwargs["temperature"] = temperature
    if system:
        kwargs["system"] = system
    if _is_fable_model(model):
        kwargs["extra_headers"] = {"anthropic-beta": _FABLE_FALLBACK_BETA}
        kwargs["extra_body"] = {"fallbacks": [{"model": _FABLE_FALLBACK_MODEL}]}

    logger.debug("Anthropic call kwargs: %s", _safe_log_kwargs(kwargs))
    message = await client.messages.create(**kwargs)
    if getattr(message, "stop_reason", None) == "refusal":
        raise RuntimeError(f"anthropic_refusal: {model} declined the request")
    text    = _anthropic_text(message.content)
    return CloudResult(
        text=text,
        input_tokens=message.usage.input_tokens,
        output_tokens=message.usage.output_tokens,
        model=model,
        provider="anthropic",
    )


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

async def _openai_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.openai_api_key:
        raise RuntimeError("MULLM_OPENAI_API_KEY not set")
    import openai  # deferred

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    call_kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    logger.debug("OpenAI call kwargs: %s", _safe_log_kwargs(call_kwargs))
    resp = await client.chat.completions.create(**call_kwargs)
    choice = resp.choices[0]
    usage  = resp.usage
    return CloudResult(
        text=choice.message.content or "",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
        provider="openai",
    )


# ---------------------------------------------------------------------------
# Google (Gemini via google-genai)
# ---------------------------------------------------------------------------

async def _google_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.google_api_key:
        raise RuntimeError("MULLM_GOOGLE_API_KEY not set")
    from google import genai  # deferred
    from google.genai import types as genai_types

    client = genai.Client(api_key=settings.google_api_key)
    config = genai_types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=temperature,
        system_instruction=system,
    )
    contents = prompt
    loop = asyncio.get_event_loop()
    response = await loop.run_in_executor(
        None,
        lambda: client.models.generate_content(model=model, contents=contents, config=config),
    )
    text = response.text or ""
    try:
        usage = response.usage_metadata
        in_tok  = usage.prompt_token_count
        out_tok = usage.candidates_token_count
    except AttributeError:
        in_tok  = len(prompt) // 4
        out_tok = len(text) // 4

    return CloudResult(
        text=text,
        input_tokens=in_tok,
        output_tokens=out_tok,
        model=model,
        provider="google",
    )


# ---------------------------------------------------------------------------
# Cerebras  (OpenAI-compatible, base_url override)
# ---------------------------------------------------------------------------

async def _cerebras_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.cerebras_api_key:
        raise RuntimeError("CEREBRAS_API_KEY not set")
    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.cerebras_api_key,
        base_url="https://api.cerebras.ai/v1",
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    call_kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    logger.debug("Cerebras call kwargs: %s", _safe_log_kwargs(call_kwargs))
    resp = await client.chat.completions.create(**call_kwargs)
    choice = resp.choices[0]
    usage  = resp.usage
    return CloudResult(
        text=choice.message.content or "",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
        provider="cerebras",
    )


# ---------------------------------------------------------------------------
# DeepSeek  (OpenAI-compatible, base_url override)
# ---------------------------------------------------------------------------

async def _deepseek_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY not set")
    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.deepseek_api_key,
        base_url="https://api.deepseek.com/v1",
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    call_kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    logger.debug("DeepSeek call kwargs: %s", _safe_log_kwargs(call_kwargs))
    resp = await client.chat.completions.create(**call_kwargs)
    choice = resp.choices[0]
    usage  = resp.usage
    return CloudResult(
        text=choice.message.content or "",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
        provider="deepseek",
    )


# ---------------------------------------------------------------------------
# GLM / Zhipu AI  (OpenAI-compatible, base_url override)
# ---------------------------------------------------------------------------

async def _glm_complete(
    prompt: str,
    model: str,
    max_tokens: int,
    temperature: float,
    system: str | None = None,
) -> CloudResult:
    if not settings.glm_api_key:
        raise RuntimeError("GLM_API_KEY / ZHIPU_API_KEY not set")
    import openai

    client = openai.AsyncOpenAI(
        api_key=settings.glm_api_key,
        base_url="https://open.bigmodel.cn/api/paas/v4/",
    )
    messages: list[dict] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    call_kwargs = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    logger.debug("GLM call kwargs: %s", _safe_log_kwargs(call_kwargs))
    resp = await client.chat.completions.create(**call_kwargs)
    choice = resp.choices[0]
    usage  = resp.usage
    return CloudResult(
        text=choice.message.content or "",
        input_tokens=usage.prompt_tokens,
        output_tokens=usage.completion_tokens,
        model=model,
        provider="glm",
    )


# ---------------------------------------------------------------------------
# Unified public interface
# ---------------------------------------------------------------------------

_PROVIDER_FNS = {
    "anthropic": _anthropic_complete,
    "openai":    _openai_complete,
    "google":    _google_complete,
    "cerebras":  _cerebras_complete,
    "deepseek":  _deepseek_complete,
    "glm":       _glm_complete,
}


async def complete(
    prompt: str,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    system: str | None = None,
) -> CloudResult:
    """
    Send *prompt* to *model* and return a CloudResult.

    The provider is inferred from the CLOUD_MODEL_PRICING catalogue.
    Retries up to 3 times with exponential backoff.

    Raises RuntimeError if the provider API key is missing.
    Raises ValueError if *model* is not in the pricing catalogue.
    """
    pricing = CLOUD_MODEL_PRICING.get(model)
    if pricing is None:
        raise ValueError(f"Unknown cloud model: {model!r}. Add it to CLOUD_MODEL_PRICING.")

    provider = pricing["provider"]
    fn = _PROVIDER_FNS.get(provider)
    if fn is None:
        raise ValueError(f"No client implemented for provider: {provider!r}")
    if not provider_ready(provider):
        raise RuntimeError(f"Provider {provider!r} is not ready in this runtime")

    logger.debug("Cloud call: model=%s provider=%s max_tokens=%d temp=%.2f", model, provider, max_tokens, temperature)
    return await _with_retry(fn, prompt, model, max_tokens, temperature, system, provider_name=provider)


def _configured_provider(provider: str) -> bool:
    keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "google": settings.google_api_key,
        "cerebras": settings.cerebras_api_key,
        "deepseek": settings.deepseek_api_key,
        "glm": settings.glm_api_key,
    }
    key = keys.get(provider)
    return bool(key and "CHANGEME" not in str(key))


def provider_ready(provider: str) -> bool:
    """Return True when a cloud provider can be called by this installed runtime."""
    from router.provider_selector import provider_ready as selector_provider_ready

    return selector_provider_ready(provider)


def model_for_tier(
    cheap: bool | None = True,
    tier: str | None = None,
    cost_strategy: str | None = None,
) -> str:
    """Return a cloud model for a cheap/full/power tier.

    quality/default: use preferred_cloud_provider.
    cost_optimize: among configured providers, choose the lowest listed
    input+output price for the requested tier. If no keys are configured, fall
    back to preferred provider so the caller gets the normal missing-key error.
    """
    if tier is None:
        tier = "cloud_cheap" if cheap else "cloud_full"
    from router.provider_selector import select_provider_model

    selection = select_provider_model(tier=tier, mode=cost_strategy)
    logger.info("Cloud model selected: model=%s provider=%s reason=%s", selection.model, selection.provider, selection.reason)
    return selection.model


# ---------------------------------------------------------------------------
# Compatibility aliases for original pipeline API
# ---------------------------------------------------------------------------

def is_configured(provider: str) -> bool:
    """Return True if the given cloud provider has a valid API key configured."""
    key = _provider_key(provider)
    return bool(key and "CHANGEME" not in key)


async def call_anthropic(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str = "claude-haiku-4-5",
    max_tokens: int = 4096,
    **kwargs,
) -> dict:
    return await _raw_anthropic(prompt, model, max_tokens, 0.4, system)


async def call_openai(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str = "gpt-4o-mini",
    max_tokens: int = 4096,
    **kwargs,
) -> dict:
    return await _raw_openai(prompt, model, max_tokens, 0.4, system)


async def call_google(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: str = "gemini-2.5-flash",
    max_tokens: int = 4096,
    **kwargs,
) -> dict:
    return await _raw_google(prompt, model, max_tokens, 0.4, system)


# ---------------------------------------------------------------------------
# Module-level HTTP client singleton (used by raw-httpx compat layer)
# ---------------------------------------------------------------------------

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=120.0)
    return _client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


# ---------------------------------------------------------------------------
# Model alias registry
# ---------------------------------------------------------------------------

MODEL_IDS: dict[str, str] = {
    # Short aliases → current canonical IDs
    "claude-haiku":  "claude-haiku-4-5",
    "claude-sonnet": "claude-sonnet-5",
    "claude-sonnet-46": "claude-sonnet-4-6",
    "claude-opus":   "claude-opus-4-7",
    "claude-fable":  "claude-fable-5",
    "gemini-flash":  "gemini-2.5-flash",
    "gemini-pro":    "gemini-3.1-pro-preview",
    # All canonical IDs map to themselves
    **{k: k for k in CLOUD_MODEL_PRICING},
}

PROVIDER_DISPATCH: dict = {k: v for k, v in _PROVIDER_FNS.items()}


def _get_pricing(model: str) -> dict:
    """Pricing lookup with short-name alias support. Falls back to gemini-2.5-flash."""
    if model in CLOUD_MODEL_PRICING:
        return CLOUD_MODEL_PRICING[model]
    canonical = MODEL_IDS.get(model)
    if canonical and canonical in CLOUD_MODEL_PRICING:
        return CLOUD_MODEL_PRICING[canonical]
    return CLOUD_MODEL_PRICING.get("gemini-2.5-flash", next(iter(CLOUD_MODEL_PRICING.values())))


# ---------------------------------------------------------------------------
# Raw-httpx provider functions (used by execute_cloud and streaming)
# ---------------------------------------------------------------------------

def _pricing_cost(model: str, in_tok: int, out_tok: int) -> float:
    p = CLOUD_MODEL_PRICING.get(model) or _get_pricing(model)
    return (in_tok * p.get("cost_per_m_input", 0) + out_tok * p.get("cost_per_m_output", 0)) / 1_000_000


async def _raw_anthropic(
    prompt: str,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    system: str | None = None,
) -> dict:
    headers = {
        "x-api-key": _provider_key("anthropic"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload: dict = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [{"role": "user", "content": prompt}],
    }
    if _anthropic_accepts_sampling(model):
        payload["temperature"] = temperature
    if system:
        payload["system"] = system
    if _is_fable_model(model):
        headers["anthropic-beta"] = _FABLE_FALLBACK_BETA
        payload["fallbacks"] = [{"model": _FABLE_FALLBACK_MODEL}]
    client = _get_client()
    resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    if data.get("stop_reason") == "refusal":
        raise RuntimeError(f"anthropic_refusal: {model} declined the request")
    text = _anthropic_text(data.get("content"))
    usage = data.get("usage", {})
    in_tok = usage.get("input_tokens", len(prompt) // 4)
    out_tok = usage.get("output_tokens", len(text) // 4)
    return {
        "text": text,
        "response": text,
        "tokens_in": in_tok,
        "tokens_out": out_tok,
        "cost": _pricing_cost(model, in_tok, out_tok),
        "model": model,
    }


async def _raw_openai(
    prompt: str,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    system: str | None = None,
) -> dict:
    headers = {
        "Authorization": f"Bearer {_provider_key('openai')}",
        "Content-Type": "application/json",
    }
    messages: list = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    payload = {"model": model, "messages": messages}
    if model.startswith(("gpt-5", "o1", "o3", "o4")):
        # Reasoning-era models: max_tokens is rejected (use max_completion_tokens)
        # and only the default temperature is accepted.
        payload["max_completion_tokens"] = max_tokens
    else:
        payload["max_tokens"] = max_tokens
        payload["temperature"] = temperature
    client = _get_client()
    resp = await client.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    text = data["choices"][0]["message"]["content"] if data.get("choices") else ""
    usage = data.get("usage", {})
    in_tok = usage.get("prompt_tokens", len(prompt) // 4)
    out_tok = usage.get("completion_tokens", len(text) // 4)
    return {
        "text": text,
        "response": text,
        "tokens_in": in_tok,
        "tokens_out": out_tok,
        "cost": _pricing_cost(model, in_tok, out_tok),
        "model": model,
    }


async def _raw_google(
    prompt: str,
    model: str,
    max_tokens: int = 4096,
    temperature: float = 0.4,
    system: str | None = None,
) -> dict:
    key = _provider_key("google")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    contents: list = [{"parts": [{"text": prompt}]}]
    if system:
        contents.insert(0, {"role": "user", "parts": [{"text": system}]})
    payload = {
        "contents": contents,
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    client = _get_client()
    resp = await client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()
    text = ""
    if data.get("candidates"):
        parts = data["candidates"][0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts)
    meta = data.get("usageMetadata", {})
    in_tok = meta.get("promptTokenCount", len(prompt) // 4)
    out_tok = meta.get("candidatesTokenCount", len(text) // 4)
    return {
        "text": text,
        "response": text,
        "tokens_in": in_tok,
        "tokens_out": out_tok,
        "cost": _pricing_cost(model, in_tok, out_tok),
        "model": model,
    }


_RAW_DISPATCH: dict = {
    "anthropic": _raw_anthropic,
    "openai":    _raw_openai,
    "google":    _raw_google,
}


async def execute_cloud(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model_name: str = "claude-sonnet-4-6",
    provider: str = "anthropic",
) -> dict:
    if not is_configured(provider):
        raise ValueError(f"Provider {provider!r} is not configured")
    fn = _RAW_DISPATCH.get(provider)
    if fn is None:
        raise ValueError(f"Unknown provider: {provider!r}")
    canonical = MODEL_IDS.get(model_name, model_name)
    return await fn(prompt, canonical, system=system)


# ---------------------------------------------------------------------------
# Image generation
# ---------------------------------------------------------------------------

_DALLE_COSTS: dict[str, dict[str, float]] = {
    "standard": {"1024x1024": 0.040},
    "hd":       {"1024x1024": 0.080},
}


async def generate_image(
    prompt: str,
    quality: str = "standard",
    size: str = "1024x1024",
) -> dict:
    if not _provider_key("openai"):
        return {"error": "OpenAI API key not configured"}
    cost = _DALLE_COSTS.get(quality, {}).get(size, 0.040)
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {_provider_key('openai')}", "Content-Type": "application/json"},
                json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": size, "quality": quality},
            )
            if resp.status_code != 200:
                return {"error": f"DALL-E error {resp.status_code}: {resp.text}"}
            data = resp.json()
            item = data["data"][0]
            return {"url": item["url"], "revised_prompt": item.get("revised_prompt", prompt), "cost": cost}
    except Exception as exc:
        return {"error": str(exc)}


async def generate_image_local(prompt: str) -> dict:
    """Try ComfyUI for local image generation; return error+fallback dict on failure."""
    from router.config import settings as _s
    from router.image_api import _generate_comfyui
    comfyui_url = getattr(_s, "comfyui_base_url", "http://127.0.0.1:8188")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{comfyui_url}/system_stats")
            if resp.status_code != 200:
                return {"error": "ComfyUI not responding", "fallback": True}
        seed = int(time.time()) % 2**32
        return await _generate_comfyui(
            prompt=prompt,
            negative="low quality, blurry, watermark, text",
            seed=seed,
            width=1024,
            height=1024,
        )
    except Exception as exc:
        return {"error": f"ComfyUI not running: {exc}", "fallback": True}


# ---------------------------------------------------------------------------
# Streaming generators
# ---------------------------------------------------------------------------

async def stream_anthropic(
    prompt: str,
    model: str | None = None,
    system: str = "You are a helpful assistant.",
) -> AsyncGenerator[dict, None]:
    from router.config import settings as _s
    _model = model or getattr(_s, "cloud_cheap_model_anthropic", "claude-haiku-4-5")
    headers = {
        "x-api-key": _provider_key("anthropic"),
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": _model,
        "max_tokens": 4096,
        "stream": True,
        "messages": [{"role": "user", "content": prompt}],
        "system": system,
    }
    client = _get_client()
    in_tok = 0
    out_tok = 0
    async with client.stream("POST", "https://api.anthropic.com/v1/messages", headers=headers, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            t = evt.get("type", "")
            if t == "message_start":
                in_tok = evt.get("message", {}).get("usage", {}).get("input_tokens", 0)
            elif t == "content_block_delta":
                token = evt.get("delta", {}).get("text", "")
                if token:
                    yield {"token": token}
            elif t == "message_delta":
                out_tok = evt.get("usage", {}).get("output_tokens", 0)
    yield {
        "done": True,
        "tokens_in": in_tok,
        "tokens_out": out_tok,
        "cost": _pricing_cost(_model, in_tok, out_tok),
    }


async def stream_openai(
    prompt: str,
    model: str | None = None,
    system: str = "You are a helpful assistant.",
) -> AsyncGenerator[dict, None]:
    from router.config import settings as _s
    _model = model or getattr(_s, "cloud_cheap_model_openai", "gpt-4o-mini")
    headers = {
        "Authorization": f"Bearer {_provider_key('openai')}",
        "Content-Type": "application/json",
    }
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    payload = {"model": _model, "messages": messages, "stream": True}
    client = _get_client()
    out_tok = 0
    async with client.stream("POST", "https://api.openai.com/v1/chat/completions", headers=headers, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            delta = (evt.get("choices") or [{}])[0].get("delta", {})
            token = delta.get("content", "")
            if token:
                out_tok += 1
                yield {"token": token}
    in_tok = len(prompt) // 4
    yield {"done": True, "tokens_in": in_tok, "tokens_out": out_tok, "cost": _pricing_cost(_model, in_tok, out_tok)}


async def stream_google(
    prompt: str,
    model: str | None = None,
    system: str = "You are a helpful assistant.",
) -> AsyncGenerator[dict, None]:
    from router.config import settings as _s
    _model = model or getattr(_s, "cloud_cheap_model_google", "gemini-2.5-flash")
    key = _provider_key("google")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{_model}:streamGenerateContent?alt=sse&key={key}"
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": 4096},
    }
    client = _get_client()
    in_tok = 0
    out_tok = 0
    async with client.stream("POST", url, json=payload) as resp:
        resp.raise_for_status()
        async for line in resp.aiter_lines():
            if not line.startswith("data: "):
                continue
            raw = line[6:]
            if raw == "[DONE]":
                break
            try:
                evt = json.loads(raw)
            except json.JSONDecodeError:
                continue
            candidates = evt.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                token = "".join(p.get("text", "") for p in parts)
                if token:
                    yield {"token": token}
            meta = evt.get("usageMetadata", {})
            if meta:
                in_tok = meta.get("promptTokenCount", in_tok) or in_tok
                out_tok = meta.get("candidatesTokenCount", out_tok) or out_tok
    in_tok = in_tok or (len(prompt) // 4)
    yield {"done": True, "tokens_in": in_tok, "tokens_out": out_tok, "cost": _pricing_cost(_model, in_tok, out_tok)}


STREAM_DISPATCH: dict = {
    "anthropic": stream_anthropic,
    "openai":    stream_openai,
    "google":    stream_google,
}
