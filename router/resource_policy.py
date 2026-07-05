"""Resource and cache policy status for multi-instance muLLM deployments."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from router.config import settings


def _dir_size_bytes(path: Path) -> int:
    total = 0
    if not path.exists():
        return 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def status() -> dict[str, Any]:
    cache_bytes = _dir_size_bytes(settings.cache_dir)
    max_bytes = int(settings.cache_max_gb * 1024**3) if settings.cache_max_gb > 0 else 0
    return {
        "vram": {
            "limit_gb": settings.vram_limit_gb,
            "reserve_gb": settings.vram_reserve_gb,
            "mode": "auto" if settings.vram_limit_gb <= 0 else "capped",
            "notes": (
                "Use separate config/env per systemd service or container. "
                "Example: production MULLM_VRAM_LIMIT_GB=24, dev MULLM_VRAM_LIMIT_GB=8."
            ),
        },
        "cache": {
            "dir": str(settings.cache_dir),
            "size_bytes": cache_bytes,
            "size_gb": round(cache_bytes / 1024**3, 3),
            "max_gb": settings.cache_max_gb,
            "usage_pct": round((cache_bytes / max_bytes) * 100, 1) if max_bytes else 0.0,
            "eviction_policy": settings.cache_eviction_policy,
            "manager_status": "status_only",
        },
    }
