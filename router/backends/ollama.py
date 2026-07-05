"""
Ollama local inference backend.

Uses /api/chat (multi-turn) and /api/tags (health).
Free — $0 per token, runs entirely on local hardware.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .protocol import BackendResponse


class OllamaBackend:
    """Ollama local inference — primary free tier for muLLM."""

    provider_name = "ollama"

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        default_model: str = "qwen3:9b",
    ):
        self._base_url = base_url.rstrip("/")
        self._default_model = default_model

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        m = model or self._default_model
        payload = {"model": m, "messages": messages, "stream": False, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._base_url}/api/chat", json=payload)
            resp.raise_for_status()
            data = resp.json()
        text = data.get("message", {}).get("content", "")
        return BackendResponse(text=text, model=m, provider="ollama")

    async def stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncIterator[str]:
        m = model or self._default_model
        payload = {"model": m, "messages": messages, "stream": True, **kwargs}
        async with httpx.AsyncClient(timeout=300) as client:
            async with client.stream(
                "POST", f"{self._base_url}/api/chat", json=payload
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line:
                        try:
                            chunk = json.loads(line)
                            delta = chunk.get("message", {}).get("content", "")
                            if delta:
                                yield delta
                        except Exception:
                            pass

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"{self._base_url}/api/tags")
                return resp.status_code == 200
        except Exception:
            return False
