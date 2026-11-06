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
        api_path: str = "/v1",
        responses_path: str | None = None,
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
        self._api_path = api_path
        self._responses_path = responses_path

    def _request(self, messages, model, stream, kwargs):
        responses = self._responses_path or (
            "/v1/responses" if self.provider_name == "openai" and model.startswith(("gpt-5", "gpt-6")) else None)
        payload = {"model": model, "stream": stream, **kwargs}
        payload.setdefault("max_tokens", 4096)
        if responses:
            payload["input"] = messages
            payload["max_output_tokens"] = payload.pop("max_completion_tokens", payload.pop("max_tokens", 4096))
            payload.pop("temperature", None)
            payload.pop("top_p", None)
            return self._base_url + responses, payload, True
        payload["messages"] = messages
        if model.startswith("glm-5.3"):
            payload.update(thinking={"type": "enabled"}, reasoning_effort="low", temperature=1.0)
        return self._base_url + self._api_path + "/chat/completions", payload, False

    def _headers(self) -> dict:
        h = {"Content-Type": "application/json"}
        if self._api_key:
            h["Authorization"] = f"Bearer {self._api_key}"
        h.update(self._extra_headers)
        return h

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        from router.policy import require_inference_allowed

        require_inference_allowed(self._base_url)
        m = model or self._default_model
        url, payload, responses = self._request(messages, m, False, kwargs)
        from router.spend_guard import reserve_backend, settle
        reservation = await reserve_backend(self.provider_name, m, self._default_model, messages,
                                            payload.get("max_output_tokens", payload.get("max_tokens", 4096)),
                                            self._input_cost, self._output_cost, self._base_url)
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                url,
                json=payload,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

        choice = ("".join(part.get("text", "") for item in data.get("output", [])
                         for part in item.get("content", []) if part.get("type") == "output_text")
                  if responses else data["choices"][0]["message"]["content"])
        usage = data.get("usage", {})
        in_tok = usage.get("input_tokens" if responses else "prompt_tokens", 0)
        out_tok = usage.get("output_tokens" if responses else "completion_tokens", 0)
        cost = (in_tok / 1000 * self._input_cost) + (out_tok / 1000 * self._output_cost)
        from router.config import CLOUD_MODEL_PRICING
        from router.frontier_models import standard_cost
        pricing = CLOUD_MODEL_PRICING.get(m)
        if pricing and pricing["provider"] == self.provider_name:
            cost = standard_cost(m, pricing, in_tok, out_tok)
        if reservation:
            import asyncio
            await asyncio.to_thread(settle, reservation, 2 * cost)
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
        from router.policy import require_inference_allowed

        require_inference_allowed(self._base_url)
        m = model or self._default_model
        url, payload, responses = self._request(messages, m, True, kwargs)
        from router.spend_guard import reserve_backend
        # Keep the full reservation: streaming text chunks are not exact billing evidence.
        await reserve_backend(self.provider_name, m, self._default_model, messages,
                              payload.get("max_output_tokens", payload.get("max_tokens", 4096)),
                              self._input_cost, self._output_cost, self._base_url)
        async with httpx.AsyncClient(timeout=120) as client:
            async with client.stream(
                "POST",
                url,
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
                            event = json.loads(chunk)
                            if responses:
                                if event.get("type") == "response.output_text.delta":
                                    yield event.get("delta", "")
                                continue
                            delta = (
                                event["choices"][0]["delta"].get(
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
                    f"{self._base_url}{self._api_path}/models", headers=self._headers()
                )
                return resp.status_code < 400
        except Exception:
            return False
