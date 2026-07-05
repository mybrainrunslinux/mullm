"""
VRAM guard — prevents loading two large models simultaneously on Ollama.

Policy (hard invariants):
  1. Only one "large" model (≥ 10GB) may be loaded at a time.
  2. Embedding models (< 1GB) are never touched.
  3. The target model is never evicted to make room for itself.
  4. Small models (9b class) coexist freely with one large model.

Steady-state on RTX 5090 (32GB):
  qwen3-coder-65k (~21GB) + OmniCoder-9b (~6GB) + nomic-embed (~0.6GB) = 27.6GB  ✓

Eviction is done via Ollama's keep_alive=0 trick:
  POST /api/generate {"model": "name", "keep_alive": 0}
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import httpx

from router.config import settings

logger = logging.getLogger("mullm.vram_guard")

LARGE_THRESHOLD_BYTES: int = 10 * 1024**3   # 10 GB — 30b-class
EMBED_THRESHOLD_BYTES: int = 1 * 1024**3    # 1 GB  — embed models


def _total_vram_bytes() -> int:
    """Return total GPU VRAM in bytes.  Returns 0 if detection fails."""
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        return pynvml.nvmlDeviceGetMemoryInfo(handle).total
    except Exception:
        pass
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return torch.cuda.get_device_properties(0).total_memory
    except Exception:
        pass
    return 0


def _is_embed(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in ("embed", "bge", "e5-", "minilm", "nomic"))


def _is_large(size_bytes: int) -> bool:
    return size_bytes >= LARGE_THRESHOLD_BYTES


def _names_match(a: str, b: str) -> bool:
    """Fuzzy match: consider base name without tag."""
    if a == b:
        return True
    return a.split(":")[0] == b.split(":")[0]


async def _loaded_models() -> list[dict]:
    """Query Ollama /api/ps for currently loaded models."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/ps")
            resp.raise_for_status()
            return resp.json().get("models", [])
    except Exception as exc:
        logger.debug("VRAM guard: /api/ps failed: %s", exc)
        return []


async def _evict(model_name: str) -> None:
    """Evict a model from VRAM via keep_alive=0 ping.

    Uses Connection: close to bypass httpx pool — persistent connections in the
    ollama client pool prevent Ollama from unloading the runner otherwise.
    """
    try:
        async with httpx.AsyncClient(
            timeout=10.0,
            headers={"Connection": "close"},
        ) as client:
            await client.post(
                f"{settings.ollama_base_url}/api/generate",
                json={"model": model_name, "keep_alive": 0, "prompt": ""},
                headers={"Connection": "close"},
            )
        logger.info("VRAM guard: evicted %s", model_name)
    except Exception as exc:
        logger.warning("VRAM guard: eviction of %s failed: %s", model_name, exc)


async def evict_all_models(*, wait_seconds: float = 15.0) -> dict:
    """Evict ALL Ollama models and wait until VRAM is actually released.

    Closes any shared ollama-client HTTP pools first so Ollama runner
    processes are not kept alive by idle connections.  Polls nvidia-smi
    until GPU memory drops or timeout expires.

    Returns {"evicted": [...], "vram_free_gb": float, "success": bool}.
    """
    import asyncio

    # 1. Close the shared ollama-library client pool if accessible
    try:
        import ollama as _ol  # type: ignore
        if hasattr(_ol, "_client") and hasattr(_ol._client, "_client"):
            _ol._client._client.close()
    except Exception:
        pass

    # 2. Get currently loaded models
    loaded = await _loaded_models()
    evicted: list[str] = []

    # 3. Evict each model with fresh connection (Connection: close)
    for m in loaded:
        name = m["name"]
        await _evict(name)
        evicted.append(name)
        logger.info("VRAM nuke: evicted %s", name)

    # 4. Wait for VRAM to actually drop
    deadline = asyncio.get_event_loop().time() + wait_seconds
    free_gb = 0.0
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(1.5)
        remaining = await _loaded_models()
        if not remaining:
            break

    # 5. Measure final free VRAM
    try:
        import pynvml  # type: ignore
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        info = pynvml.nvmlDeviceGetMemoryInfo(handle)
        free_gb = round(info.free / 1e9, 2)
    except Exception:
        pass

    remaining_after = await _loaded_models()
    success = len(remaining_after) == 0
    if not success:
        logger.warning("VRAM nuke: still loaded after %ss: %s", wait_seconds,
                       [m["name"] for m in remaining_after])
    return {"evicted": evicted, "vram_free_gb": free_gb, "success": success}


async def _model_size_bytes(model_name: str) -> int:
    """Look up a model's actual size from Ollama /api/tags. Returns 0 on failure."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            resp.raise_for_status()
            for m in resp.json().get("models", []):
                if _names_match(m.get("name", ""), model_name):
                    return int(m.get("size", 0))
    except Exception:
        pass
    return 0


async def ensure_vram_headroom(
    target_model: str,
    required_bytes: int = 0,
    *,
    _loaded_fn: Callable | None = None,
) -> list[str]:
    """Ensure enough VRAM headroom to load *target_model*.

    Uses the actual model size from Ollama /api/tags so the check is exact,
    not a conservative fixed estimate. Evicts non-embed, non-target models
    largest-first until the target fits.

    Returns the list of model names evicted.
    """
    loaded = await (_loaded_fn() if _loaded_fn else _loaded_models())

    # Check if target is already loaded — nothing to do
    for m in loaded:
        if _names_match(m["name"], target_model):
            return []

    total_vram = _total_vram_bytes()
    if total_vram == 0:
        return []  # can't determine VRAM — don't evict blindly

    currently_used = sum(float(m.get("size_vram", 0)) for m in loaded)
    available = total_vram - currently_used

    # Use actual model size if caller didn't supply one
    if not required_bytes:
        required_bytes = await _model_size_bytes(target_model)
    if not required_bytes:
        required_bytes = LARGE_THRESHOLD_BYTES  # fallback conservative estimate

    if required_bytes <= available:
        return []  # fits without evicting anything

    # Need to free space — evict non-embed, non-target models largest first
    candidates = [
        m for m in loaded
        if not _is_embed(m["name"]) and not _names_match(m["name"], target_model)
    ]
    candidates.sort(key=lambda m: float(m.get("size_vram", 0)), reverse=True)

    evicted: list[str] = []
    for victim in candidates:
        freed = float(victim.get("size_vram", 0))
        await _evict(victim["name"])
        evicted.append(victim["name"])
        available += freed
        if required_bytes <= available:
            break

    return evicted


async def evict_all_except(target_model: str) -> list[str]:
    """Evict every loaded model except *target_model* and embed models.

    Used by bench_mode requests so that only the benchmark model occupies VRAM.
    This prevents stale vision/chat models from fragmenting VRAM during runs.
    """
    loaded = await _loaded_models()
    evicted: list[str] = []
    for m in loaded:
        name = m["name"]
        if _is_embed(name) or _names_match(name, target_model):
            continue
        await _evict(name)
        evicted.append(name)
    if evicted:
        logger.info("VRAM bench-evict: removed %s", evicted)
    return evicted
