"""
Native Anthropic backend — uses the anthropic SDK for proper streaming
and prompt-cache-aware cost accounting.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from .protocol import BackendResponse


class AnthropicBackend:
    """Anthropic backend using the official anthropic SDK (not OpenAI-compat wire)."""

    provider_name = "anthropic"

    # (input_cost_per_1k, output_cost_per_1k) in USD
    MODELS: dict[str, tuple[float, float]] = {
        "claude-haiku-4-5":  (0.00025, 0.00125),
        "claude-sonnet-4-6": (0.003,   0.015),
        "claude-opus-4-7":   (0.015,   0.075),
    }

    def __init__(
        self,
        api_key: str,
        default_model: str = "claude-haiku-5-5",
    ):
        self._api_key = api_key
        self._default_model = default_model
        self._client = None  # lazy init — anthropic may not be installed

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._client

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        from router.policy import require_inference_allowed
        require_inference_allowed()
        m = model or self._default_model
        client = self._get_client()
        system = next(
            (msg["content"] for msg in messages if msg["role"] == "system"), None
        )
        user_msgs = [msg for msg in messages if msg["role"] != "system"]

        from router.spend_guard import reserve_backend, settle
        reservation = await reserve_backend("anthropic", m, self._default_model, messages, kwargs.get("max_tokens", 4096))
        resp = await client.messages.create(
            model=m,
            messages=user_msgs,
            system=system or "",
            max_tokens=kwargs.get("max_tokens", 4096),
        )
        from router.cloud import _anthropic_text, _pricing_cost
        text = _anthropic_text(resp.content)
        in_tok = resp.usage.input_tokens
        out_tok = resp.usage.output_tokens
        cost = _pricing_cost(m, in_tok, out_tok)
        if reservation:
            import asyncio
            await asyncio.to_thread(settle, reservation, 2 * cost)
        return BackendResponse(
            text=text,
            input_tokens=in_tok,
            output_tokens=out_tok,
            cost_usd=cost,
            model=m,
            provider="anthropic",
        )

    async def stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncIterator[str]:
        from router.policy import require_inference_allowed
        require_inference_allowed()
        m = model or self._default_model
        client = self._get_client()
        system = next(
            (msg["content"] for msg in messages if msg["role"] == "system"), None
        )
        user_msgs = [msg for msg in messages if msg["role"] != "system"]

        from router.spend_guard import reserve_backend
        await reserve_backend("anthropic", m, self._default_model, messages, kwargs.get("max_tokens", 4096))
        async with client.messages.stream(
            model=m,
            messages=user_msgs,
            system=system or "",
            max_tokens=kwargs.get("max_tokens", 4096),
        ) as stream:
            async for text in stream.text_stream:
                yield text

    async def health(self) -> bool:
        try:
            client = self._get_client()
            await client.models.list()
            return True
        except Exception:
            return False
