"""
Generic OpenAI-compatible backend.

Works for any provider that exposes a /v1/chat/completions endpoint:
OpenAI, Venice, DeepSeek, GLM, Mistral, Cohere, Perplexity, OpenRouter,
IBM BAM, vLLM, LiteLLM proxy, and any custom self-hosted endpoint.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from .protocol import BackendResponse


class OpenAICompatBackend:
    """Reusable backend for any OpenAI-compatible /v1/chat/completions endpoint."""

    def __init__(
        self,
        provider_name: str,
        base_url: str,
        api_key: str | None,
        default_model: str,
        input_cost_per_1k: float = 0.0,
        output_cost_per_1k: float = 0.0,
        extra_headers: dict | None = None,
    ):
        self.provider_name = provider_name
        self._base_url = base_url.rstrip("/")
        if self._base_url.endswith("/v1"):
            self._base_url = self._base_url[:-3]
        self._api_key = api_key
        self._default_model = default_model
        self._input_cost = input_cost_per_1k
        self._output_cost = output_cost_per_1k
        self._extra_headers = extra_headers or {}

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        h.update(self._extra_headers)
        return h

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        m = model or self._default_model
        payload = {"model": m, "messages": messages, "stream": False, **kwargs}
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        choice = data["choices"][0]["message"]["content"]
        usage = data.get("usage", {})
        in_tok = usage.get("prompt_tokens", 0)
        out_tok = usage.get("completion_tokens", 0)
        cost = (in_tok / 1000 * self._input_cost) + (out_tok / 1000 * self._output_cost)
        return BackendResponse(
            text=choice,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            model=m,
            provider=self.provider_name,
        )

    async def stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncIterator[str]:
        m = model or self._default_model
        payload = {"model": m, "messages": messages, "stream": True, **kwargs}
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        chunk = line[6:]
                        if chunk == "[DONE]":
                            break
                        try:
                            delta = (
                                json.loads(chunk)["choices"][0]["delta"].get(
                                    "content", ""
                                )
                            )
                            if delta:
                                yield delta
                        except Exception:
                            pass

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(
                    f"{self._base_url}/v1/models", headers=self._headers()
                )
                return resp.status_code < 400
        except Exception:
            return False
