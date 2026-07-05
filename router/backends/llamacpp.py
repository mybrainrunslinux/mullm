"""
llama.cpp backend via llama-cpp-python.

Best for: CPU inference, AMD GPU (ROCm), Windows, Mac Intel.

Install:
  pip install llama-cpp-python

CUDA (NVIDIA):
  CMAKE_ARGS="-DGGML_CUDA=on" pip install llama-cpp-python

Metal (Apple Silicon / Mac):
  CMAKE_ARGS="-DGGML_METAL=on" pip install llama-cpp-python

ROCm (AMD):
  CMAKE_ARGS="-DGGML_HIPBLAS=on" pip install llama-cpp-python

Configuration:
  Set LLAMACPP_MODEL_PATH env var to the path of your GGUF file.
  Set LLAMACPP_N_GPU_LAYERS to control GPU offload (-1 = all layers).
  Download GGUF models from HuggingFace (e.g. TheBloke repos).
"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

from .protocol import BackendResponse


class LlamaCppBackend:
    """
    llama.cpp local inference backend via llama-cpp-python.

    - Works on CPU, CUDA, ROCm (AMD), Metal (Mac)
    - Uses GGUF model format
    - Model is loaded lazily on first request
    - Streaming is handled via a thread executor + asyncio Queue
    """

    provider_name = "llamacpp"

    def __init__(
        self,
        model_path: str,
        n_gpu_layers: int = -1,
        n_ctx: int = 8192,
        default_model: str = "llamacpp",
    ) -> None:
        """
        Args:
            model_path:    Path to the GGUF model file.
            n_gpu_layers:  Number of layers to offload to GPU. -1 = all layers.
                           0 = CPU only.
            n_ctx:         Context window size in tokens.
            default_model: Model name to report in BackendResponse.
        """
        self._model_path = model_path
        self._n_gpu_layers = n_gpu_layers
        self._n_ctx = n_ctx
        self._default_model = default_model
        self._llm = None

    def _load(self) -> None:
        """Lazily load the Llama model. Thread-safe: only loads once."""
        if self._llm is not None:
            return
        from llama_cpp import Llama
        self._llm = Llama(
            model_path=self._model_path,
            n_gpu_layers=self._n_gpu_layers,
            n_ctx=self._n_ctx,
            verbose=False,
            chat_format="chatml",
        )

    async def generate(
        self,
        messages: list[dict],
        model: str | None = None,
        **kwargs,
    ) -> BackendResponse:
        """Generate a complete response (non-streaming)."""
        loop = asyncio.get_event_loop()
        text = await loop.run_in_executor(None, self._sync_generate, messages, kwargs)
        return BackendResponse(
            text=text,
            model=self._default_model,
            provider="llamacpp",
        )

    def _sync_generate(self, messages: list[dict], kwargs: dict) -> str:
        self._load()
        result = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=kwargs.get("max_tokens", 2048),
            temperature=kwargs.get("temperature", 0.7),
            stream=False,
        )
        return result["choices"][0]["message"]["content"]

    async def stream(
        self,
        messages: list[dict],
        model: str | None = None,
        **kwargs,
    ) -> AsyncIterator[str]:
        """Stream tokens using a background thread + asyncio Queue."""
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _stream_worker() -> None:
            self._load()
            for chunk in self._llm.create_chat_completion(
                messages=messages,
                max_tokens=kwargs.get("max_tokens", 2048),
                temperature=kwargs.get("temperature", 0.7),
                stream=True,
            ):
                delta = chunk["choices"][0]["delta"].get("content", "")
                if delta:
                    loop.call_soon_threadsafe(queue.put_nowait, delta)
            loop.call_soon_threadsafe(queue.put_nowait, None)  # sentinel

        loop.run_in_executor(None, _stream_worker)

        while True:
            token = await queue.get()
            if token is None:
                break
            yield token

    async def health(self) -> bool:
        """Return True if the model file exists on disk."""
        return os.path.isfile(self._model_path)
