"""
Backend registry — auto-register all configured backends at server startup.

Called once from the FastAPI lifespan. Each backend is registered only if
its required environment variable(s) are set. Local backends (Ollama) are
always registered with sane defaults.
"""
from __future__ import annotations

import os

from router.config import settings

from .ollama import OllamaBackend
from .openai_compat import OpenAICompatBackend
from .protocol import register_backend


def init_backends() -> None:
    """Register all configured backends. Called during FastAPI lifespan startup."""

    # ── Local backends ────────────────────────────────────────────────────

    # Ollama — always registered (local, free)
    ollama_url = os.getenv("OLLAMA_BASE_URL", settings.ollama_base_url)
    register_backend(
        "ollama",
        OllamaBackend(base_url=ollama_url, default_model=settings.ollama_model),
    )

    # ExLlamaV2 — optional, NVIDIA GPU, fastest tok/s
    exl2_path = settings.exllamav2_model_path
    if exl2_path:
        from .exllamav2 import ExLlamaV2Backend
        register_backend("exllamav2", ExLlamaV2Backend(model_path=exl2_path))

    # llama.cpp — optional, CPU/AMD/Metal (no NVIDIA Ollama required)
    llamacpp_path = settings.llamacpp_model_path
    if llamacpp_path:
        try:
            from .llamacpp import LlamaCppBackend
            register_backend(
                "llamacpp",
                LlamaCppBackend(
                    model_path=llamacpp_path,
                    n_gpu_layers=settings.llamacpp_n_gpu_layers,
                    n_ctx=settings.llamacpp_n_ctx,
                ),
            )
        except ImportError:
            pass  # llama-cpp-python not installed — skip silently

    # MLX — optional, Apple Silicon only
    mlx_model = settings.mlx_model_path
    if mlx_model:
        try:
            from .mlx import MLXBackend
            register_backend("mlx", MLXBackend(model_path=mlx_model))
        except ImportError:
            pass  # mlx-lm not installed — skip silently

    # vLLM — self-hosted OpenAI-compatible server
    vllm_url = settings.vllm_base_url
    if vllm_url:
        register_backend(
            "vllm",
            OpenAICompatBackend(
                "vllm", vllm_url, None, settings.vllm_model
            ),
        )

    # TabbyAPI — official ExLlamaV2/V3 OpenAI-compatible server

    # SGLang — self-hosted OpenAI-compatible server (supports MTP speculative decoding)
    sglang_url = settings.sglang_base_url
    if sglang_url:
        register_backend(
            "sglang",
            OpenAICompatBackend(
                "sglang", sglang_url, None, settings.sglang_model
            ),
        )
    tabby_url = settings.tabbyapi_base_url
    if tabby_url:
        register_backend(
            "tabbyapi",
            OpenAICompatBackend(
                "tabbyapi",
                tabby_url,
                settings.tabbyapi_api_key,
                settings.tabbyapi_model,
            ),
        )

    # LiteLLM proxy — routes to any provider via unified API
    litellm_url = settings.litellm_base_url
    if litellm_url:
        register_backend(
            "litellm",
            OpenAICompatBackend(
                "litellm",
                litellm_url,
                settings.litellm_api_key,
                settings.litellm_model,
            ),
        )

    # OmniRoute — OpenAI-compatible router, useful as a peer/fallback router
    omniroute_url = os.getenv("OMNIROUTE_BASE_URL", "")
    if omniroute_url:
        register_backend(
            "omniroute",
            OpenAICompatBackend(
                "omniroute",
                omniroute_url,
                os.getenv("OMNIROUTE_API_KEY") or None,
                os.getenv("OMNIROUTE_MODEL", "auto"),
            ),
        )

    # ── Cloud providers ───────────────────────────────────────────────────

    # Anthropic — native SDK (not OpenAI-compat) for streaming + cache support
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
    if anthropic_key:
        from .anthropic import AnthropicBackend
        register_backend("anthropic", AnthropicBackend(api_key=anthropic_key))

    # OpenAI
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if openai_key:
        register_backend(
            "openai",
            OpenAICompatBackend(
                "openai",
                "https://api.openai.com",
                openai_key,
                "gpt-4o-mini",
                input_cost_per_1k=0.00015,
                output_cost_per_1k=0.0006,
            ),
        )

    # Google Gemini — via OpenAI-compatible endpoint
    google_key = os.getenv("GOOGLE_API_KEY", "")
    if google_key:
        register_backend(
            "google",
            OpenAICompatBackend(
                "google",
                "https://generativelanguage.googleapis.com/v1beta/openai",
                google_key,
                "gemini-1.5-flash",
                input_cost_per_1k=0.000075,
                output_cost_per_1k=0.0003,
            ),
        )

    # DeepSeek — very cheap, OpenAI-compat
    deepseek_key = os.getenv("DEEPSEEK_API_KEY", "")
    if deepseek_key:
        register_backend(
            "deepseek",
            OpenAICompatBackend(
                "deepseek",
                "https://api.deepseek.com",
                deepseek_key,
                "deepseek-chat",
                input_cost_per_1k=0.00014,
                output_cost_per_1k=0.00028,
            ),
        )

    # Mistral AI
    mistral_key = os.getenv("MISTRAL_API_KEY", "")
    if mistral_key:
        register_backend(
            "mistral",
            OpenAICompatBackend(
                "mistral",
                "https://api.mistral.ai",
                mistral_key,
                "mistral-small-latest",
                input_cost_per_1k=0.0002,
                output_cost_per_1k=0.0006,
            ),
        )

    # Cohere — OpenAI-compat compatibility endpoint
    cohere_key = os.getenv("COHERE_API_KEY", "")
    if cohere_key:
        register_backend(
            "cohere",
            OpenAICompatBackend(
                "cohere",
                "https://api.cohere.com/compatibility",
                cohere_key,
                "command-r",
                input_cost_per_1k=0.00015,
                output_cost_per_1k=0.0006,
            ),
        )

    # Perplexity — online search-augmented models
    perplexity_key = os.getenv("PERPLEXITY_API_KEY", "")
    if perplexity_key:
        register_backend(
            "perplexity",
            OpenAICompatBackend(
                "perplexity",
                "https://api.perplexity.ai",
                perplexity_key,
                "llama-3.1-sonar-small-128k-online",
                input_cost_per_1k=0.0002,
                output_cost_per_1k=0.0002,
            ),
        )

    # OpenRouter — routes to any public model, free tier available
    openrouter_key = os.getenv("OPENROUTER_API_KEY", "")
    if openrouter_key:
        register_backend(
            "openrouter",
            OpenAICompatBackend(
                "openrouter",
                os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api"),
                openrouter_key,
                "meta-llama/llama-3.1-8b-instruct:free",
                extra_headers={
                    "HTTP-Referer": "https://github.com/mybrainrunslinux/mullm",
                    "X-Title": "muLLM",
                },
            ),
        )

    # Cerebras — ultra-fast OpenAI-compatible inference, useful as cloud_fast/burst
    cerebras_key = os.getenv("CEREBRAS_API_KEY", "")
    if cerebras_key:
        register_backend(
            "cerebras",
            OpenAICompatBackend(
                "cerebras",
                os.getenv("CEREBRAS_BASE_URL", "https://api.cerebras.ai/v1"),
                cerebras_key,
                os.getenv("CEREBRAS_MODEL", settings.cloud_cheap_model_cerebras),
                input_cost_per_1k=0.00035,
                output_cost_per_1k=0.00075,
            ),
        )

    # Venice AI — privacy-preserving, no logging
    venice_key = os.getenv("VENICE_API_KEY", "")
    if venice_key:
        register_backend(
            "venice",
            OpenAICompatBackend(
                "venice",
                "https://api.venice.ai/api",
                venice_key,
                "llama-3.3-70b",
                input_cost_per_1k=0.0005,
                output_cost_per_1k=0.0015,
            ),
        )

    # GLM / Zhipu AI
    glm_key = os.getenv("GLM_API_KEY", "")
    if glm_key:
        register_backend(
            "glm",
            OpenAICompatBackend(
                "glm",
                "https://open.bigmodel.cn/api/paas/v4",
                glm_key,
                "glm-4-flash",
                input_cost_per_1k=0.0001,
                output_cost_per_1k=0.0001,
            ),
        )

    # xAI (Grok)
    xai_key = os.getenv("XAI_API_KEY", "")
    if xai_key:
        register_backend(
            "xai",
            OpenAICompatBackend(
                "xai",
                "https://api.x.ai",
                xai_key,
                "grok-3-mini",
                input_cost_per_1k=0.0003,
                output_cost_per_1k=0.0005,
            ),
        )

    # IBM BAM (Build on AI Models)
    ibm_key = os.getenv("IBM_BAM_API_KEY", "")
    ibm_url = os.getenv("IBM_BAM_BASE_URL", "https://bam-api.res.ibm.com/v2")
    if ibm_key:
        register_backend(
            "ibm",
            OpenAICompatBackend(
                "ibm",
                ibm_url,
                ibm_key,
                "ibm/granite-13b-instruct-v2",
                extra_headers={"IBM-API-Version": "2024-01-10"},
            ),
        )

    # Custom provider — user-defined OpenAI-compatible endpoint
    custom_url = os.getenv("MULLM_CUSTOM_PROVIDER_URL", "")
    custom_key = os.getenv("MULLM_CUSTOM_PROVIDER_KEY", "")
    custom_model = os.getenv("MULLM_CUSTOM_PROVIDER_MODEL", "custom")
    if custom_url:
        register_backend(
            "custom",
            OpenAICompatBackend(
                "custom", custom_url, custom_key or None, custom_model
            ),
        )
