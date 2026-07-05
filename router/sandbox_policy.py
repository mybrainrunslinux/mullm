"""Native sandbox policy helpers.

This is not a replacement for containers or OS policy. It gives muLLM a
central contract for path-scoped writes so code paths can refuse to touch files
outside the configured workspace before we add deeper platform enforcement.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from router.config import settings


def sandbox_root() -> Path:
    configured = str(settings.sandbox_root or "").strip()
    root = Path(configured).expanduser() if configured else settings.project_root
    return root.resolve()


def is_path_allowed(path: str | Path) -> bool:
    mode = settings.sandbox_mode
    if mode == "off":
        return True
    candidate = Path(path).expanduser().resolve()
    root = sandbox_root()
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def require_path_allowed(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not is_path_allowed(candidate):
        raise PermissionError(f"Path is outside muLLM sandbox root: {candidate}")
    return candidate


def status() -> dict[str, Any]:
    root = sandbox_root()
    return {
        "mode": settings.sandbox_mode,
        "root": str(root),
        "allow_network": settings.sandbox_allow_network,
        "native_path_guard": settings.sandbox_mode in {"workspace", "container"},
        "container_recommended": settings.sandbox_mode == "container",
    }
