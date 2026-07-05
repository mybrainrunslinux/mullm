# muLLM — Agent Reference

> Derived from the research paper: *"muLLM: Cost-Optimal LLM Routing via Lightweight Intent Classification"*  
> ACL/EMNLP 2026 submission · arXiv cs.CL+cs.AI

muLLM is a four-tier LLM routing system that achieves **96.4% cost reduction** over a blended cloud baseline by resolving the majority of real-world queries at zero marginal cost before invoking any neural model.

---

## Core Principle

Production query complexity is not uniformly distributed. Most queries are repetitive, pattern-matchable, or structurally simple. A four-tier hierarchy exploits this:

```
User Query
    │
    ▼
[Tier 0: Groundtruth LUT]  ─── <1ms · $0.00 · 11.8% of queries
    │ no match
    ▼
[Tier 1: Semantic Cache]   ─── ~14ms · $0.00 · 27.1% of queries
    │ cosine < 0.98
    ▼
[DeBERTa Classifier]       ─── 44MB CPU-only · 82.4% tier accuracy
    │
    ├── complexity 1–2 → [Tier 2a: Local 30B ~5s · $0.00]
    └── complexity 3–5 → [Tier 2b: Local 30B ~8s · $0.00]
                                   │
                         [Quality Gate] ─── pass → respond
                                   │ fail
                                   ▼
                         [Tier 3: Cloud API · 2–3s · $0.001–$0.15]
                                   │
                                   ▼
                         [Update Cache + Score Log]
```

**Key emergent property: costs fall as usage grows.** Each resolved query contributes to cache density; each cache hit reduces future marginal cost.

---

## Tier Details

### Tier 0 — Groundtruth LUT (<1ms, $0.00)
1,313+ deterministic patterns across 13 categories: arithmetic, capitals, HTTP status codes, git commands, Big-O complexity, date/time, unit conversion, periodic table, ASCII, regex.  
A Python `Counter` answers "How many r's in strawberry?" in 4ms with zero hallucination risk.

### Tier 1 — Semantic Cache (~14ms, $0.00)
ChromaDB vector store, cosine similarity threshold 0.98.  
**ELO-cache semantics**: entries are only displaced by demonstrably better answers from escalation events — the cache converges toward best-ever answers over time.  
Organic cache hit rate: 55–70%.

### Tier 2 — Local Inference (~5s, $0.00)
Ollama backend with **qwen3-coder:30b** (MoE, ~3B active parameters, ~20GB VRAM at Q4_K_M).  
DeBERTa-v3-small classifies intent (CODE, RESEARCH, CREATIVE, CONVERSATION, DEPLOY, NOTE, LOOKUP, VISION) and complexity (1–5). CPU-only, 14ms, 44MB.  
Hardware requirement: ≥24GB VRAM GPU. Degrades gracefully to Tier 3 on CPU-only.

### Tier 3 — Cloud API (~2–3s, $0.001–$0.15/query)
Anthropic (claude-haiku-4-5, claude-sonnet-4-6), OpenAI (gpt-4o-mini, gpt-4o), Google (gemini-1.5-flash, gemini-1.5-pro).  
Hard spend limits at $7/$10/$50 session thresholds.  
OpenAI-compatible `/v1/chat/completions` endpoint for drop-in compatibility.

**Routing overhead:** 23µs median — below perceptible latency.

---

## Key API Endpoints

### Core Query Pipeline

| Endpoint | Method | Description |
|---|---|---|
| `/query` | POST | Main pipeline: classify → route → execute → cache |
| `/query/split` | POST | Split routing: decompose multi-part prompts, parallel execution |
| `/query/stream` | GET | SSE streaming for local Ollama |
| `/classify` | POST | Intent + complexity classification only (no inference) |
| `/cancel/{request_id}` | POST | Cancel an in-flight query |

### OpenAI-Compatible

| Endpoint | Method | Description |
|---|---|---|
| `/v1/chat/completions` | POST | Drop-in OpenAI chat endpoint — works with any OpenAI SDK |
| `/v1/models` | GET | List available models |
| `/rpc` | POST | JSON-RPC 2.0 — methods: `query`, `classify`, `split`, `tools/list`, `tools/call`, `cache.lookup`, `cache.search`, `cache.store`, `budget.status`, `system.info`, `agents.list`, `agents.register` |

### Orchestrator CLI (TDD-to-spec)

The orchestrator reads task files (`BUGS.md`, `REQUESTS.md`, `TODO.md`) and plans + executes changes across the repo using the muLLM pipeline as its inference backbone.

```bash
mullm --orchestrate BUGS.md          # plan + execute from a task file
mullm --orchestrate "fix the cache"  # inline task string
mullm --orchestrate BUGS.md --code   # generate code patches
mullm --orchestrate BUGS.md --apply  # auto-apply patches
mullm --orchestrate BUGS.md --verify "pytest tests/"  # TDD gate
mullm --orchestrate BUGS.md --no-tdd # skip spec-first mode
mullm --orchestrate BUGS.md --self-update   # allow repo self-modification with --apply
```

Programmatic use:
```python
from router.orchestrator import Orchestrator
orch = Orchestrator(api_url="https://127.0.0.1:8100")
plan = await orch.plan_from_file("BUGS.md")
results = await orch.execute(plan)
```

### MCP (Model Context Protocol)

HTTP-based MCP — works with any agent that can make HTTP requests. For Claude Desktop/Cursor, a stdio wrapper is planned.

| Endpoint | Method | Description |
|---|---|---|
| `/mcp/tools` | GET | List available tools |
| `/mcp/tools/call` | POST | Execute a tool by name |
| `/mcp/tools/query` | POST | MCP-wrapped `/query` |

Shipped tools: `mullm_query`, `mullm_split`, `mullm_classify`, `mullm_budget`, `mullm_system`.
Full docs at `/mcp`.

### A2A (Agent-to-Agent Protocol)

Inspired by Google's A2A spec. HTTP-based (not full streaming A2A). Agents register in-memory and are discoverable by other agents on the network.

| Endpoint | Method | Description |
|---|---|---|
| `/api/agents/register` | POST | Register an agent with ID, endpoint, capabilities |
| `/api/agents` | GET | Discover agents by capability |
| `/api/agents/{id}/task` | POST | Add a task to a registered agent's in-process queue |
| `/api/agents/{id}/heartbeat` | POST | Keep-alive signal |
| `/api/agents/{id}/pause` | POST | Pause an agent |
| `DELETE /api/agents/{id}` | DELETE | Remove an agent |
| `/.well-known/ai-plugin.json` | GET | Discovery manifest |

The shipped HTTP A2A surface is an in-process registry and task queue. It does not dispatch work to remote worker processes yet. Off-machine A2A should be paired with HTTPS and normal network access controls.
Full docs at `/a2a`.

### Dashboard & Monitoring

| Endpoint | Method | Description |
|---|---|---|
| `/api/dashboard` | GET | Real stats from scoring log |
| `/api/system` | GET | CPU/GPU/VRAM/RAM stats |
| `/api/performance` | GET | Slow-query tracking, P50/P95 latencies |
| `/api/budget` | GET | Session spend, tier breakdown |
| `/api/budget/cap` | POST | Set per-session hard spend cap |
| `/api/vram/status` | GET | VRAM usage per backend |
| `/api/vram/evict` | POST | Evict a model from VRAM |
| `/api/gpu/advisor` | GET | GPU utilization recommendations |

### ComfyUI / Image Generation

ComfyUI runs on `localhost:8188` with SDXL Turbo (2.2s/image, $0.00). Images are proxied through muLLM at `/api/comfyui/image` for LAN/mobile access.

| Endpoint | Method | Description |
|---|---|---|
| `/api/comfyui/status-legacy` | GET | ComfyUI health check |
| `/api/comfyui/config-legacy` | POST | Update ComfyUI config |
| `/api/comfyui/asset-pack` | GET | List available asset packs |
| `/comfyui` | GET | ComfyUI UI page |
| `/image` | GET | Image generation UI |

### TTS (Text-to-Speech)

Local TTS via Kokoro. No cloud call.

| Endpoint | Method | Description |
|---|---|---|
| `/api/tts/backends` | GET | List available TTS voices/backends |
| `/api/tts/synth` | POST | Synthesize speech from text |
| `/tts` | GET | TTS UI page |

### 3D / Game Studio

| Endpoint | Method | Description |
|---|---|---|
| `/3d` | GET | 3D scene editor (Three.js) |
| `/api/game-list` | GET | Auto-discover games in `code/ready/` |
| `/api/understand` | POST | Semantic 3D scene understanding (parses "put sword in hand" → object transforms) |
| `/understand` | POST | Alias for semantic scene ops |
| `/gamesystems` | GET | Reusable game systems catalog |
| `/games` | GET | Games browser (57+ games) |
| `/studio` | GET | Full creative studio launcher |
| `/asset-manager` | GET | 3D asset manager |
| `/assets` | GET | Asset browser |

### Misc Useful

| Endpoint | Method | Description |
|---|---|---|
| `/api/pages` | GET | Navigation registry for current UI mode |
| `/api/toggles` | GET | Feature toggle state (`config/toggles.json`) |
| `/api/backends` | GET | List registered inference backends |
| `/api/backends/smoke` | POST | Smoke-test a backend |
| `/api/routes` | GET | All registered routes (machine-readable) |
| `/api/urls` | GET | All pages + routes for discoverability |
| `/api/mupatch/latest` | GET | Latest muPatch results |
| `/health` | GET | Server health check |

Default ports: **6856** (mullm service), **8100** (dev server).

---

## Agent Usage Rules

**Use mullm before anything else:**
```bash
curl -sk -X POST http://127.0.0.1:6856/query \
  -H "Content-Type: application/json" \
  -d '{"content": "YOUR QUESTION HERE"}'
```
Local 30B model. $0.00. 1–30 seconds. Cloud escalation only if quality gate fails.

**Never spend cloud money for questions the local model can answer.** The classifier routes CODE, LOOKUP, and CONVERSATION queries to the free tier 94%+ of the time.

**Bash-as-Truth / Bash-as-Judge:** Evaluation is done by running code, not by asking an LLM. Avoid LLM self-evaluation for correctness checks.

---

## Benchmark Baseline (what to maintain)

| Benchmark | Target | Cost |
|---|---|---|
| HumanEval pass@1 | **100%** (164/164) | $0.00 |
| MultiPL-E 6-lang system-level | **≥98%** | $0.00 |
| MultiPL-E 17-lang model-only | **≥92%** | $0.00 |
| PR-Gauntlet | **110/110** | $0.33 |
| muPatch | **30/30** | $0.00 |
| RouterBench AIQ | **0.6673** | $0.00 |

Throughput target: **≥300 tok/s** on port 6856 with 35b-a3b MoE model (vLLM, ExLlamaV3/TabbyAPI, or llama.cpp).

---

## Architecture Files

| File | Purpose |
|---|---|
| `router/main.py` | FastAPI app, all HTTP routes, startup |
| `router/cli.py` | `mullm` CLI entry point |
| `router/config.py` | Pydantic settings, env var schema |
| `config/toggles.json` | Feature flags |
| `config/settings.py` | All model pricing + local model config |
| `router/backends/registry.py` | Backend registry (Ollama, ExLlamaV2, llama.cpp, MLX) |
| `router/cache.py` | ChromaDB ELO-cache implementation |
| `router/tiers.py` | Tier routing logic |
| `router/realtime.py` | WebSocket / SSE streaming |
| `router/module_catalog.py` | Module/page registration |
| `router/page_registry.py` | Navigation page registry |
| `router/gamesystems.html` | Game systems catalog UI |
| `router/games.html` | Games browser UI |

---

## Invariants That Must Not Break

1. Cloud API calls must NEVER happen by default in tests — gate them behind `--grep @spend`
2. Hard spend limits ($7/$10/$50) must always be enforced
3. Tier 0 patterns must be deterministic — no LLM calls for arithmetic, capitals, etc.
4. Cache cosine threshold must remain at 0.98 (lower = false hits)
5. The `/query` endpoint must respond in <30s under any load

---

## Tool Preferences

- **Containers:** `podman` (not docker)
- **File edits:** `sed -i 's/old/new/g' file` for string replacements
- **Package manager:** `uv` (preferred over pip for fresh installs)
- **Inference engine priority:** ExLlamaV3/TabbyAPI > vLLM > llama.cpp > Ollama (for tok/s)
- **Model target:** Qwen3.6-35B-A3B MoE variants finetunes and quants though smaller models are also possible for lower vRAM configs

---

## Game Systems

The `/gamesystems` page catalogs reusable game modules. The `/api/game-list` endpoint auto-discovers HTML games in `code/ready/`. Game categories are inferred from filename keywords (`sword`, `bow`, `siege`, `3d`, `iso`, etc.).

**Weapon categorization rules** (applied in `router/main.py:1463`):
- `sword`, `blade` → "Swords"
- `bow`, `archer` → "Archery"  
- `siege`, `ballista`, `catapult` → "Siege"
- Any weapon not matched by filename → falls through to generic "Game" category

Systems stored in `code/ready/` are auto-registered. Systems built as router HTML pages must be listed in `router/page_registry.py` and `router/module_catalog.py` to appear in the catalog.

---

## Privacy Guarantees

87.5% of queries never leave the machine. Users with strict data-locality requirements should set `DISABLE_CLOUD=1`. No PII detection/redaction is applied before cloud escalation — this is a known limitation that can be partly worked around by using LiteLLM, Venice AI, and other supported privacy-first providers.

---

## Paper Citation

```bibtex
@article{stolmar2026mullm,
  title={muLLM: Cost-Optimal LLM Routing via Lightweight Intent Classification},
  author={Stolmar, Peter},
  journal={arXiv preprint cs.CL},
  year={2026}
}
```
