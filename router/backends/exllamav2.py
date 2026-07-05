"""
ExLlamaV2 backend — fastest token/s for NVIDIA GPUs.

30–50% more tokens/second than Ollama on the same hardware.
Requires EXL2-quantized models from HuggingFace.

Install: pip install exllamav2
  — or build from source for CUDA 13 / RTX 5090:
    git clone https://github.com/turboderp/exllamav2 && pip install -e .
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from .protocol import BackendResponse


class ExLlamaV2Backend:
    """
    ExLlamaV2 local inference backend.

    Model format: EXL2 quantized (e.g. Qwen2.5-32B-Instruct-6.0bpw-exl2).
    Lazy-loads on first generate() call to avoid import errors when
    exllamav2 is not installed.
    """

    provider_name = "exllamav2"

    def __init__(
        self,
        model_path: str,
        default_model: str = "exllamav2",
        max_seq_len: int = 8192,
    ):
        self._model_path = model_path
        self._default_model = default_model
        self._max_seq_len = max_seq_len
        self._model = None      # lazy load
        self._tokenizer = None
        self._generator = None

    def _load(self) -> None:
        """Load model into VRAM. Called once on first inference request."""
        if self._model is not None:
            return
        from exllamav2 import (
            ExLlamaV2,
            ExLlamaV2Cache,
            ExLlamaV2Config,
            ExLlamaV2Tokenizer,
        )
        from exllamav2.generator import ExLlamaV2DynamicGenerator

        config = ExLlamaV2Config(self._model_path)
        config.max_seq_len = self._max_seq_len
        self._tokenizer = ExLlamaV2Tokenizer(config)
        self._model = ExLlamaV2(config)
        self._model.load()
        cache = ExLlamaV2Cache(self._model, lazy=True)
        self._generator = ExLlamaV2DynamicGenerator(
            model=self._model, cache=cache, tokenizer=self._tokenizer
        )

    def _sync_generate(self, messages: list[dict], kwargs: dict) -> str:
        self._load()
        from exllamav2.generator import ExLlamaV2Sampler

        prompt = self._messages_to_prompt(messages)
        settings = ExLlamaV2Sampler.Settings()
        settings.temperature = kwargs.get("temperature", 0.7)
        output = self._generator.generate(
            prompt=prompt,
            settings=settings,
            max_new_tokens=kwargs.get("max_tokens", 2048),
        )
        return output

    def _messages_to_prompt(self, messages: list[dict]) -> str:
        """Minimal chat template for models without a tokenizer chat template."""
        return (
            "\n".join(
                f"{m['role'].upper()}: {m['content']}" for m in messages
            )
            + "\nASSISTANT: "
        )

    async def generate(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> BackendResponse:
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(
            None, self._sync_generate, messages, kwargs
        )
        return BackendResponse(
            text=text, model=self._default_model, provider="exllamav2"
        )

    async def stream(
        self, messages: list[dict], model: str | None = None, **kwargs
    ) -> AsyncIterator[str]:
        # Full generate in executor — real token streaming requires
        # ExLlamaV2DynamicGenerator in a dedicated thread with a queue.
        # TODO: wire up per-token streaming via asyncio.Queue.
        result = await self.generate(messages, model, **kwargs)
        yield result.text

    async def health(self) -> bool:
        import os
        return os.path.isdir(self._model_path)
