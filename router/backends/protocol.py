"""
BackendProtocol — structural Protocol for all muLLM inference backends.

Any class that implements provider_name, generate(), stream(), and health()
satisfies this protocol without needing to inherit from it.
"""
from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass
class BackendResponse:
    """Unified response returned by every backend's generate() call."""

    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    model: str = ""
    provider: str = ""


@runtime_checkable
class BackendProtocol(Protocol):
    """
    Structural protocol satisfied by any object that exposes:
      - provider_name  str
      - generate()     async, returns BackendResponse
      - stream()       async generator, yields str tokens
      - health()       async, returns bool
    """

    provider_name: str  # e.g. "anthropic", "openai", "venice"

    async def generate(
        self, messages: list[dict], model: str, **kwargs
    ) -> BackendResponse: ...

    async def stream(
        self, messages: list[dict], model: str, **kwargs
    ) -> AsyncIterator[str]: ...

    async def health(self) -> bool: ...


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_registry: dict[str, BackendProtocol] = {}


def register_backend(name: str, backend: BackendProtocol) -> None:
    """Register a backend under *name* (e.g. "ollama", "openai")."""
    _registry[name] = backend


def get_backend(name: str) -> BackendProtocol | None:
    """Return a registered backend by name, or None if not found."""
    return _registry.get(name)


def list_backends() -> list[str]:
    """Return all currently registered backend names."""
    return list(_registry.keys())
