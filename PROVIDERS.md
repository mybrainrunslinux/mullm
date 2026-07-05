# muLLM Provider and Action Support

This file separates what is active in the refactor from what is present as UI,
registered as a backend, or provider-gated in optional modules.

## Current Layers

| Layer | Meaning |
|---|---|
| Active pipeline | Used by `router.tiers.execute_pipeline()` today. |
| Registered backend | Implemented in `router/backends/*` and available after env/config, but not fully selected by the main pipeline yet. |
| Setup only | Key/toggle/status UI exists; the provider is configured before a paid call is attempted. |
| Provider-gated | Endpoint shape is present, but the provider must be installed/configured before use. |
| Custom adapter | Use the OpenAI-compatible or custom provider fields to connect a compatible endpoint. |

## Active Pipeline Providers

| Provider | Env | Capabilities |
|---|---|---|
| Ollama | `MULLM_OLLAMA_BASE_URL`, `MULLM_OLLAMA_MODEL` | local chat, local vision model, local embeddings |
| Anthropic | `ANTHROPIC_API_KEY` / `MULLM_ANTHROPIC_API_KEY` | cloud text fallback |
| OpenAI | `OPENAI_API_KEY` / `MULLM_OPENAI_API_KEY` | cloud text fallback |
| Google | `GOOGLE_API_KEY` / `MULLM_GOOGLE_API_KEY` | cloud text fallback |
| Cerebras | `CEREBRAS_API_KEY` | OpenAI-compatible cloud text |
| DeepSeek | `DEEPSEEK_API_KEY` | OpenAI-compatible cloud text |
| GLM/Zhipu | `GLM_API_KEY` / `ZHIPU_API_KEY` | OpenAI-compatible cloud text |

## Registered But Needs Main-Pipeline Integration

| Provider | Env | Notes |
|---|---|---|
| OpenRouter | `OPENROUTER_API_KEY` | Meta-router. Good for free/cheap public models and price discovery. |
| LiteLLM | `LITELLM_BASE_URL`, optional `LITELLM_API_KEY` | Team/local proxy for many providers. |
| vLLM | `VLLM_BASE_URL`, `VLLM_MODEL` | Self-hosted high-throughput inference. |
| Mistral | `MISTRAL_API_KEY` | OpenAI-compatible adapter. |
| Cohere | `COHERE_API_KEY` | OpenAI-compatible compatibility endpoint. |
| Perplexity | `PERPLEXITY_API_KEY` | Online/search-augmented model path. |
| Venice | `VENICE_API_KEY` | Privacy-focused model path. |
| xAI | `XAI_API_KEY` | Grok-compatible path. |
| IBM BAM | `IBM_BAM_API_KEY`, `IBM_BAM_BASE_URL` | Enterprise provider path. |
| Custom OpenAI-compatible | `MULLM_CUSTOM_PROVIDER_URL`, `MULLM_CUSTOM_PROVIDER_KEY`, `MULLM_CUSTOM_PROVIDER_MODEL` | Best extension point for enterprise gateways. |
| ExLlamaV2 | `EXLLAMAV2_MODEL_PATH` | Local NVIDIA high-performance backend. |
| llama.cpp | `LLAMACPP_MODEL_PATH` | CPU, AMD/ROCm, Metal, Windows-friendly backend. |
| MLX | `MLX_MODEL_PATH` | Apple Silicon local backend. |

## Studio / Media Providers

| Provider | Status | Capabilities |
|---|---|---|
| Meshy | setup only | text-to-3D, image-to-3D, refine, GLB download |
| ComfyUI | partial | local image, texture pass, Hunyuan3D workflows, LoRA/workflow graph support via ComfyUI |
| TopologyAI | custom adapter | text/image-to-3D through a compatible custom 3D provider endpoint |
| Kling | provider-gated | text-to-video, image-to-video, video edits |
| Google Veo | provider-gated | Vertex AI text/image-to-video, first/last frame, video extension |
| Seedance 2.0 | provider-gated | text-to-video, image-to-video, reference-to-video |

Media provider adapters should use one common async task contract:

```json
{
  "provider": "kling",
  "kind": "video",
  "operation": "text_to_video",
  "prompt": "...",
  "inputs": [],
  "options": {},
  "budget_limit_usd": 1.00
}
```

and return:

```json
{
  "task_id": "...",
  "status": "queued|running|succeeded|failed",
  "cost_estimate_usd": 0.0,
  "artifacts": []
}
```

## OmniRoute Comparison and Integration

OmniRoute is a strong adjacent project: it is an OpenAI-compatible AI gateway
with many providers, compression, fallback, MCP/A2A, and broad coding-tool
compatibility.

The low-risk muLLM integration is:

1. Run OmniRoute on its default `/v1` gateway.
2. Register it as `omniroute` using the same OpenAI-compatible backend shape as
   LiteLLM/vLLM.
3. Benchmark three modes:
   - muLLM router -> providers
   - OmniRoute router -> providers
   - muLLM classifier/budget/groundtruth -> OmniRoute fallback

muLLM's likely differentiators remain:

- deterministic groundtruth tier,
- local-first quality gate,
- private metadata logging with query-content opt-in,
- hard budget / runaway stop controls,
- visual cost and tier dashboards,
- local studio/game/3D orchestration.

OmniRoute's likely differentiators are:

- more provider and coding-tool coverage out of the box,
- subscription/OAuth provider routing,
- prompt/tool-output compression,
- mature multi-account/fallback dashboard.

The combined path is useful: muLLM can route cheap/free/local first, then send
only expensive or provider-broad fallback traffic to OmniRoute.

## Protocol Surfaces To Keep Polished

These should have first-class explainer pages and examples:

- OpenAI-compatible `/v1/chat/completions`
- JSON-RPC 2.0
- MCP server/tools
- A2A agent card and JSON-RPC agent methods
- Provider catalog at `/api/provider-catalog` and `/api/providers/catalog`
- URL registry for all pages/actions
- Swagger/OpenAPI docs in dev mode at `/docs`

## Packaging Split

| Package | Owns |
|---|---|
| `mullm-core` | routing, groundtruth, classifier, cache, OpenAI API, budget/privacy |
| `mullm-code` | CLI, orchestrator, repo patching, APK/iOS wrappers, agent compatibility |
| `mullm-studio` | 3D, video, sound recorder, musaic, rigs, ComfyUI/Meshy/Kling/Veo/Seedance |
| `mullm-bench` | HumanEval, MultiPL-E, PR-Gauntlet, muPatch, provider comparisons |
| `mullm-knowledge` | Joplin, Obsidian vault indexing, custom RAG connectors |
| `mullm-enterprise` | SSO, RBAC, quotas, audit exports, hosted/team deployment |
