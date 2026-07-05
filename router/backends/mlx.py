"""
MLX backend for Apple Silicon (M1/M2/M3/M4).

Best local inference choice for Mac M-series — uses the GPU/Neural Engine
via Apple's MLX framework.

Install: pip install mlx-lm
Models:  mlx-community/ on HuggingFace (pre-quantized for MLX)
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .protocol import BackendResponse


class MLXBackend:
    """Apple Silicon optimized inference via MLX. Best choice for Mac M-series."""

    provider_name = "mlx"

    def __init__(
        self,
        model_path: str,
        default_model: str = "mlx-community/Qwen2.5-7B-Instruct-4bit",
    ):
        self._model_path = model_path or default_model
        self._default_model = default_model
        self._model = None
        self._tokenizer = None

    def _load(self) -> None:
        """Lazy-load the MLX model. Called on first inference request."""
        if self._model is not None:
            return
        from mlx_lm import load
        self._model, self._tokenizer = load(self._model_path)

    def _sync_generate(self, messages: list[dict], kwargs: dict) -> str:
        self._load()
        from mlx_lm import generate
        prompt = self._tokenizer.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )
        return generate(
            self._model,
            self._tokenizer,
            prompt=prompt,
            max_tokens=kwargs.get("max_tokens", 2048),
        )

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None, self._sync_generate, messages, kwargs
        )
        return BackendResponse(
            text=text, model=model or self._default_model, provider="mlx"
        )

    async def stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncIterator[str]:
        # mlx-lm has a streaming generate; wiring it through asyncio.Queue
        # is a future improvement. For now, yield the full response.
        result = await self.generate(messages, model, **kwargs)
        yield result.text

    async def health(self) -> bool:
        try:
            import mlx  # noqa: F401
            return True
        except ImportError:
            return False
