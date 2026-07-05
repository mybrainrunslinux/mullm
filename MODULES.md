# muLLM Modules — Product Boundary and Modular Capability Architecture

## Recommended Package Boundary

Ship the first public release as a small, boring core plus optional modules.

| Package / extra | Owns | Distribution stance |
|---|---|---|
| `mullm` / `mullm-core` | router, classifier, groundtruth LUT, privacy-preserving metadata logs, OpenAI-compatible API, setup, basic chat/dashboard | Default install. This is the enterprise-trust boundary. |
| `mullm[classifier]` | DeBERTa or multilingual classifier runtime and local model path support | Optional because Torch/Transformers change install size and GPU friction. |
| `mullm[gpu]` | GPU telemetry and hardware detection only | Optional, lightweight; no CUDA runtime promise. |
| `mullm-code` or `mullm[code]` | repo indexing, mini-DAG orchestration, patch application, IDE/agent integrations | Separate command surface; higher risk because it writes code and touches repos. |
| `mullm-studio` or `mullm[studio]` | games, 3D, ComfyUI, Meshy, image/video/audio creation surfaces | Plugin/companion app. Great demo surface, not core router scope. |
| `mullm-bench` or `mullm[bench]` | PR-Gauntlet, muPatch, HumanEval/MultiPL-E runners, benchmark dashboards | Optional; large data and external toolchains do not belong in default install. |
| `mullm-enterprise` | OIDC/SAML, Azure OpenAI, Bedrock, Postgres/Snowflake, audit exports, admin quotas | Commercial/services layer; avoid putting enterprise-only operational commitments in Apache core. |

This keeps the Apache 2.0 core clean while preserving a natural services and hosted-product path.
The current folder can still contain all pages during refactor; the release artifact should hide or
disable non-core modules unless explicitly enabled in setup/config.

## UI Release Modes

Use `MULLM_UI_MODE=regular|demo|dev` to control what appears in navigation and setup.

| Mode | Shows | Intended audience |
|---|---|---|
| `regular` | Chat, dashboard, setup, translation, privacy, security, troubleshooting | Users and enterprise evaluators. |
| `demo` | Regular pages plus demo, investors, benchmarks, research, performance, showcase/comparison pages | Fundraising, conference demos, early adopters who want the story. |
| `dev` | Demo pages plus studio/game/3D/ComfyUI/tests/MCP workbench pages | Internal development and power users who knowingly enable experimental modules. |

Direct URLs can remain available during development, but packaged builds should use this registry as
the source of truth for navigation and installer defaults.

## CUDA Policy

Do not make CUDA 13 a default promise yet. Document three GPU tracks:

| Track | Target | Recommendation |
|---|---|---|
| Portable default | Windows/macOS/Linux without CUDA assumptions | Ollama/llama.cpp/MLX paths; lowest support burden. |
| Stable NVIDIA | Most users with recent NVIDIA cards | CUDA 12.8 wheels where PyTorch/backend support is mature. |
| Experimental NVIDIA | Your highest-performance local benchmarking | CUDA 13+ / nightly backend path, clearly labeled advanced and not required for core. |

The install wizard should recommend CUDA 12.8 or backend-native installs by default, and expose CUDA
13+ as an advanced path only after hardware detection.

## Concept

muLLM starts as a pure classifier+router. Capabilities are installed as modules.
Each module adds a new media type, routing path, and optional local model.
The /setup page lets you enable/disable modules and configure local vs cloud per capability.

---

## Module Registry

### Core (always on)
- Classifier → intent detection, complexity scoring, category labeling
- Router → tier selection (local / cloud-cheap / cloud-strong)
- Local LLM → Ollama, currently OmniCoder 9B
- Cache → ChromaDB semantic cache
- **Proxy-only mode:** disable local LLM entirely — pure API routing proxy, zero GPU required
  - Value prop: smart cost-saving routing for teams already paying for Claude/GPT/Gemini
  - SaaS angle: host muLLM, charge a flat fee, save users 40-70% on API costs

### Vision (image understanding)
- Local: Qwen2-VL 7B, LLaVA-1.6 (both on 32GB VRAM)
- Cloud: GPT-4o vision, Gemini Flash vision
- Triggers on: image attachments, screenshot analysis, "what is in this image" queries
- Already partially wired in router

### Image Generation
- Local: Flux.1-schnell (8GB VRAM), SDXL (10GB), Flux.1-dev (16GB)
- Cloud: DALL-E 3 ($0.04/image), Imagen 3 (Vertex)
- Router logic: simple/fast → local Flux-schnell, photorealistic/complex → DALL-E 3

### Video Generation ← NEW
- Local options (RTX 5090 32GB) — ranked:
  1. **Wan2.2 14B** (24GB, ~7 min, 24 FPS, TI2V image-to-video) — best quality, native ComfyUI, user has tried it on Windows
  2. **HunyuanVideo v1.5 FP8** (~12GB, ~75s/clip, 24 FPS, I2V supported) — fastest high-quality option
  3. **LTX-Video Q4** (10-16GB, ~30s, 24 FPS, I2V primary use case) — previews and iteration
  - ~~CogVideoX-5B~~ — outputs 8 FPS, too choppy for game trailers, skip
  - ~~Wan2.1 14B~~ — superseded by 2.2, and needed 40-80GB anyway
- Cloud adapters: Veo, Kling, Seedance 2.0, and other async video APIs should be pluggable rather than default-on.
- Default policy: local preview/iteration first, cloud video only when the user has configured a provider and accepted cost/latency.
- Router logic: preview/iteration → LTX-Video local, hero/cinematic → Wan2.2 local
- Image-to-video: Wan2.2 TI2V for animating game screenshots and 3D renders
- Install path: ComfyUI native for all three (Wan2.2 officially integrated July 2025)

### 3D Generation
- Cloud: Meshy API (already wired, budget managed)
- Local: future — TripoSG, Zero123++ if VRAM allows
- Triggers on: "generate a 3D model of...", GLB requests

### Audio
- Local: Whisper large-v3 (STT), Kokoro TTS (TTS)
- Cloud: ElevenLabs, Google Cloud TTS
- Already partially wired (Whisper)

### Code (specialized)
- Local: OmniCoder 9B (already primary model)
- Cloud escalation: Claude Sonnet for architecture/complex problems
- Benchmark: HumanEval 100% local (see project_humaneval_results.md)

---

## /setup Page Design

Tabbed interface: Core | Vision | Image | Video | 3D | Audio

Each module card shows:
- Toggle: Enabled / Disabled
- Local model: dropdown of installed Ollama models (if applicable)
- Cloud provider: API key slot with masked display
- Cost estimate: "$0.00/query local" or "$0.04/image DALL-E"
- Quality tier: ★★★ rating

Install flow:
```
[Enable Video] →
  "Local: HunyuanVideo requires 24GB VRAM. Install via ComfyUI? [Yes / Use Cloud Only]"
  "Cloud: Choose configured Veo/Kling/Seedance provider (optional, budget-gated)"
  [Save]
```

---

## Proxy-Only Mode (lightweight deployment)

For users with no GPU who just want smart routing across their existing API keys:
- Disable all local models
- muLLM acts as a pure classifier + cost-aware routing proxy
- Routes between: GPT-4o-mini (cheap) / GPT-4o (mid) / o1 (expensive)
  or: Haiku / Sonnet / Opus
  or: Gemini Flash / Pro / Ultra
- Learns from feedback which tier each query type needs
- Deployable on a $5/mo VPS, no GPU
- This is a real SaaS product: charge $10-20/mo flat, save users $50-200/mo in API costs

---

## Cost Philosophy

- Local always wins if quality is sufficient — $0.00
- Cloud only when local genuinely can't handle it
- Video is the exception: even local is slow (5 min/clip) — batch overnight, cache results
- Keep cloud video budget-gated. Provider pricing and availability change quickly, so cloud video adapters should expose estimate-before-run and hard spend caps.

---

## Implementation Priority

1. Proxy-only mode toggle in /setup (easy, high value for external users)
2. Video tab in /setup with LTX-Video local install (fast model, low VRAM)
3. Image generation tab (Flux.1-schnell already installable via Ollama/diffusers)
4. HunyuanVideo when video quality bar is needed
5. Full module marketplace UI
