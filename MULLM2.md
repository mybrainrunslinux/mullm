# muLLM 2 — Architecture & Product Design

**Status:** Design document, pre-implementation  
**Author:** Peter Stolmar  
**Date:** 2026-04-19  
**Supercedes:** v1 monolith at router/main.py (~7000 lines)

---

## Background and Motivation

muLLM v1 proved the core thesis: a 23µs DeBERTa routing classifier + local Ollama tier makes
LLM-backed workflows 85% cheaper with no perceptible quality loss on routine tasks. The
architecture, however, was built to prove the thesis, not to live with it. A 7000-line monolith,
six scattered env vars, JSONL as a database, and RTX 5090 hard-wired into several code paths
make v1 impossible to ship outside the dev machine and difficult to extend without regressions.

v2 has three goals:
1. Make muLLM embeddable — a library teams import, not just a server they run.
2. Add the multimodal + agent features the v1 design left unimplemented.
3. Define a viable SaaS path (boilingfrog.dev) without compromising the free local-first core.

---

## 1. Core Architecture Redesign

### 1.1 Package structure

v1 is a single FastAPI app. v2 splits into a pip-installable core plus optional backend plugins:

```
mullm-core/            # pure Python, no GPU deps
  mullm/
    router/            # classify, tier selection, cost model
    cache/             # semantic cache (ChromaDB) + LUT
    agents/            # agent graph, task DAG, orchestrator
    validate/          # visual and semantic validation
    multimodal/        # intake normalization (text/image/pdf/joplin)
    server/            # FastAPI thin wrapper around the library
    cli/               # Click entrypoint

mullm-backend-ollama/  # pip install mullm-backend-ollama
mullm-backend-vllm/
mullm-backend-llamacpp/
mullm-backend-anthropic/
mullm-backend-openai/
mullm-backend-gemini/
```

The core has zero hard dependencies on any specific backend. Each backend implements a
`BackendProtocol` (typing.Protocol, not ABC) with three methods: `generate()`, `stream()`,
`health()`. This means muLLM can be imported in a notebook, a Lambda, or a CLI without pulling
in torch or httpx unless a backend actually needs it.

Rationale for Protocol over ABC: ABC inheritance couples the hierarchy; Protocol allows existing
third-party wrappers (litellm, openai SDK) to satisfy the interface without modification.

### 1.2 Layered execution pipeline

```
Intake → Classify → Route → Execute → Validate → Cache → Return
```

Each stage is a standalone callable with a typed signature. The server wires them into the HTTP
handler; the CLI wires them into a Rich console; a notebook can call them individually. v1
conflated all six stages inside endpoint functions, which is why adding visual validation to
v1 would require forking three handlers.

Stage contracts (Pydantic v2 models throughout, not dataclasses):
- `IntakeResult`: normalized text, media attachments, metadata
- `ClassifyResult`: tier recommendation, confidence, latency_ms
- `RouteResult`: chosen backend, chosen model, estimated cost_usd
- `ExecuteResult`: text, token counts, actual cost_usd, ttft_ms
- `ValidateResult`: passed: bool, diff_pct: float, ai_review: str | None
- `CacheResult`: hit: bool, similarity: float, cached_at: datetime

### 1.3 Config — TOML, not env vars

`~/.mullm/config.toml` (global) and `mullm.toml` (project-local, takes precedence):

```toml
[core]
local_first = true
max_cost_per_query_usd = 0.05
cache_similarity_threshold = 0.97

[backends.ollama]
base_url = "http://localhost:11434"
default_model = "qwen2.5:9b"
keepalive = "30m"

[backends.anthropic]
# api_key read from ANTHROPIC_API_KEY, never stored in config
default_model = "claude-haiku-4-5"

[classify]
deberta_model_path = "~/.mullm/models/routing-classifier/"
lut_path = "~/.mullm/lut.json"

[cache]
chromadb_path = "~/.mullm/chroma"
lut_max_entries = 50000
```

pydantic-settings v2 reads the TOML; environment variables override at the field level. Rejected
Dynaconf: too much magic, poor Pydantic interop. Rejected Hydra: overkill for a router config.

### 1.4 Structured storage

Replace JSONL scoring log with SQLite via aiosqlite + raw SQL (no ORM). Schema:

```sql
CREATE TABLE routing_events (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,            -- Unix timestamp
    query_hash TEXT NOT NULL,    -- sha256 of normalized prompt
    tier TEXT NOT NULL,          -- lut|cache|local|cloud
    backend TEXT,
    model TEXT,
    tokens_in INTEGER,
    tokens_out INTEGER,
    cost_usd REAL,
    latency_ms REAL,
    validated INTEGER DEFAULT 0
);

CREATE TABLE human_oracle (
    id INTEGER PRIMARY KEY,
    query_hash TEXT NOT NULL,
    correct_tier TEXT NOT NULL,
    annotated_by TEXT,           -- 'human'|'deberta'|'auto'
    ts REAL NOT NULL
);
```

Rejected SQLAlchemy: no async ORM that's both lightweight and stable on Python 3.12+. Raw
aiosqlite gives full control at 50 lines of boilerplate. ChromaDB stays for vector embeddings
— it is not being replaced, just kept out of the structured event path.

---

## 2. Multimodal Intake Pipeline

### 2.1 Intake normalization

All query types converge to `IntakeResult` before classification. The classifier sees text
regardless of input modality. This means the 23µs DeBERTa path is preserved for every query
type — vision understanding runs in parallel on media attachments, then its description is
appended to the text context before routing.

Supported input types at v2 launch:
- Plain text (existing)
- Image: PNG/JPG/WebP up to 20MB — passed to vision model (Gemini Flash Vision or local LLaVA)
- PDF: PyMuPDF extracts text + page images; text injected directly, images to vision path
- Screenshots: identical to image path, but metadata includes "screenshot" tag which biases
  routing toward "describe UI / explain error" intent
- Napkin sketches: image path + explicit `sketch=true` metadata, triggers "Design from sketch"
  flow (see §2.3)
- Joplin note URL: parsed via Joplin REST API (localhost:41184), note body + tags injected

### 2.2 Joplin integration

v1 had ad-hoc Joplin usage via shell scripts. v2 formalizes it:

```python
# mullm/multimodal/joplin.py
class JoplinIntake:
    async def by_title(self, title: str) -> IntakeResult: ...
    async def by_tag(self, tag: str) -> list[IntakeResult]: ...
    async def by_id(self, note_id: str) -> IntakeResult: ...
```

Token from `~/.config/joplin-desktop/settings.json`, never from env or config.toml (matches
existing Joplin token policy). The CLI `mullm ask --joplin "Note Title"` fetches the note and
uses its body as the prompt context.

### 2.3 Design-from-sketch flow

Upload napkin sketch → LLaVA describes layout intent in structured JSON → orchestrator spawns
Coder + Designer agents → live preview rendered. This makes "I drew it, build it" a first-class
workflow, not a one-off hack.

Sketch description schema:
```json
{
  "layout": "two-column with sidebar",
  "components": ["nav", "card grid", "modal"],
  "color_hints": ["dark", "blue accents"],
  "intent": "dashboard showing metrics"
}
```

The orchestrator treats this as a task spec, not a free-form prompt. Agents receive the schema,
not the raw vision output, so downstream routing stays deterministic.

### 2.4 UI drag-drop on every page

Single reusable Web Component `<mullm-drop-zone>` (vanilla JS, no framework, ~150 lines).
Embedded in chat.html, studio.html, and any future page via `<script src="/static/drop-zone.js">`.
Paste-from-clipboard supported via ClipboardEvent. Files sent as multipart/form-data to
`POST /intake` before the query is dispatched, so the server normalizes before the WebSocket
session starts.

---

## 3. Visual Validation System

### 3.1 Problem statement

v1's orchestrator applies code changes but has no way to know if a UI task produced the right
result. A Playwright test suite exists (59 tests) but tests are written by humans, not auto-
generated per-task. Visual validation closes this loop automatically.

### 3.2 Pipeline

```
Task completes → apply changes → Playwright screenshot (before + after)
→ pixelmatch diff (threshold: 5%) → if diff > threshold OR task was UI:
    → send before+after to vision model: "Does the after screenshot show [task description]?"
    → vision returns {passed: bool, issues: list[str]}
→ ValidateResult emitted → stored in routing_events.validated
```

Library choices:
- Playwright Python (already installed) for screenshots — consistent with existing test infra
- pixelmatch-py for pixel diff — pure Python port, no Node dependency in the hot path
- Vision model: Gemini Flash Vision (cheapest multimodal with good layout understanding);
  falls back to local LLaVA if offline

### 3.3 CLI integration

```bash
mullm run TASKS.md --visual-validate
```

Each task node in the DAG gets a `validate: bool` field. The orchestrator runs validation
after each apply step, embeds the screenshot diff in the task output, and blocks downstream
dependent tasks if validation fails. Human-in-the-loop pause (§5.5) is automatically triggered
on validation failure above a configurable diff threshold.

### 3.4 Regression detection

A screenshot baseline library stored at `~/.mullm/baselines/{project_id}/`. On every `mullm run`,
before applying changes, current state is snapshotted. After apply, diff is computed against the
task-specific expectation and also against the pre-task baseline to catch collateral damage.
This is the feature v1 is completely missing: accidental regressions in adjacent UI elements.

---

## 4. Better CLI (Click + Rich)

### 4.1 Command structure

Replace argparse in mullm_cli.py with Click groups. Rationale over Typer: Click has stable
semantics for command groups, Typer's magic annotation approach causes subtle issues with
complex option combinations (e.g., --orchestrate + --code + --apply as three separate flags
that only make sense together). Click forces explicit grouping.

```
mullm
├── ask "question"           # single query, prints answer
├── run TASKS.md             # orchestrate task file (replaces --orchestrate --code --apply)
├── watch [path]             # file watcher, re-runs on save
├── model
│   ├── list                 # show available models + VRAM usage
│   ├── pull <name>          # download via Ollama
│   └── bench [--router]     # run RouterBench or full benchmark suite
├── bench                    # alias: mullm model bench
├── config
│   ├── show                 # dump merged config (global + project)
│   └── set key value        # write to project mullm.toml
└── server
    ├── start                # start FastAPI server
    └── stop
```

### 4.2 Rich output

Every output goes through Rich. Not optional, not behind a flag. Rationale: the terminal is the
primary debugging surface; color and structure make routing decisions legible at a glance.

Output conventions:
- Routing decision: `[dim]LUT[/dim]` / `[green]local[/green]` / `[yellow]cloud haiku[/yellow]`
- Cost: always shown, even when $0.000000
- Task DAG: Rich `Tree` showing node status (pending / running / done / failed / blocked)
- Progress bars: `rich.progress.Progress` with TTFT column for streaming tasks

Shell completions generated via `click-completion` at install time for bash/zsh/fish.

### 4.3 Config file at ~/.mullm/config.toml

`mullm config show` merges global + project configs and displays as a Rich table. `mullm config set`
writes to the project-local `mullm.toml`. No GUI config needed — the CLI is the setup UX.

---

## 5. Agent Graph (DAG, not flat orchestrate)

### 5.1 v1 limitations

v1's orchestrator is a flat list of tasks executed sequentially. It works for 3-task scripts.
At 10+ tasks, it fails: no parallelism, no retry policy per node, no way to express "run B and C
in parallel, then D when both complete." Users worked around this by splitting TASKS.md files
manually.

### 5.2 DAG model

Tasks are nodes in a directed acyclic graph. Edges are typed:

```python
class EdgeType(str, Enum):
    DEPENDS_ON = "depends_on"   # blocking: target cannot start until source completes
    INFORMS = "informs"         # non-blocking: target receives source output as context
    BLOCKS = "blocks"           # explicit failure propagation: if source fails, target is skipped
```

Task spec in TOML or Markdown front-matter:

```toml
[[task]]
id = "write_tests"
type = "Tester"
prompt = "Write Playwright tests for the login flow"
depends_on = []

[[task]]
id = "implement_login"
type = "Coder"
prompt = "Implement login endpoint"
depends_on = ["write_tests"]    # TDD: tests first

[[task]]
id = "validate_login"
type = "Validator"
prompt = "Run tests and visual validation"
depends_on = ["implement_login"]
validate = true
```

### 5.3 Agent types

Six built-in agent types, each with a system prompt template and a default backend preference:

| Type       | Default backend | Primary capability                          |
|------------|-----------------|---------------------------------------------|
| Coder      | local           | Write/edit code files                       |
| Reviewer   | local           | Code review, suggest improvements           |
| Tester     | local           | Generate Playwright/pytest test cases       |
| Designer   | cloud (haiku)   | UI/UX decisions, layout, color              |
| Researcher | cloud (sonnet)  | Web search synthesis, paper reading         |
| Validator  | cloud (vision)  | Visual validation, screenshot review        |

Each agent type can be overridden per-task in the task spec. Cloud agents require explicit
`allow_cloud = true` in the task or in config.toml (default: false, local only).

### 5.4 Sub-agent depth

Agents can spawn sub-agents up to `max_agent_depth` (default: 2, configurable). A Coder agent
handling a complex file can spawn a Reviewer sub-agent inline. Sub-agents inherit parent context
window budget (parent's remaining tokens / 2 for child). This prevents the S26 catastrophe of
30 unconstrained Claude agents consuming quota.

### 5.5 Human-in-the-loop

Any node can declare `human_review = true`. The orchestrator pauses the DAG at that node, posts
a blocking notification to `/api/agents/blocked` (the unblock channel), and waits up to
`human_review_timeout_s` (default: 300) for a response. The response is injected as a "human
feedback" node that `informs` the paused node, then execution resumes. This replaces the current
ad-hoc pattern of posting to /unblock at arbitrary times.

---

## 6. Hardware Portability

### 6.1 CPU-first principle

v1 assumed RTX 5090. v2 makes CPU the baseline. Every feature must degrade gracefully:
- DeBERTa classifier: runs on CPU at ~2ms (vs 23µs on GPU). Acceptable for routing.
- Ollama local models: CPU inference enabled by default; CUDA/Metal auto-detected and used.
- ChromaDB: CPU cosine similarity. No FAISS GPU required.
- Playwright validation: runs on CPU headless, no GPU required.

### 6.2 Hardware detection at startup

```python
# mullm/hardware.py
class HardwareProfile:
    cuda_available: bool
    cuda_device_count: int
    vram_gb: float
    metal_available: bool    # Apple Silicon
    ram_gb: float
    cpu_cores: int
    recommended_quantization: Literal["Q4_K_M", "Q8_0", "F16"]
```

`recommended_quantization` selects the Ollama model variant to pull. 8GB VRAM → Q4_K_M of a
9B model. 32GB VRAM (RTX 5090) → F16 of a 32B model. 16GB unified RAM (M4 MacBook) → Q8_0
of a 14B model. This mapping is configurable in `mullm.toml` but the defaults are correct for
90% of hardware.

### 6.3 Platform paths

- **RTX 5090 (current)**: CUDA 13, F16 models, 23µs DeBERTa GPU, vLLM for high throughput
- **Mac M4**: Metal via Ollama, DeBERTa CPU (~2ms), full feature parity except CUDA kernels
- **CPU-only server**: Q4 models, 2ms DeBERTa, suitable for dev/CI where no GPU is attached
- **DGX/cloud**: muLLM becomes routing + cache layer in front of a vLLM endpoint; local tier
  routes to the on-prem vLLM rather than a laptop Ollama

### 6.4 Docker/podman setup

```bash
# One-command setup, no CUDA required on the host for basic functionality
podman run -p 8100:8100 ghcr.io/mullm/mullm:latest

# GPU passthrough
podman run --device nvidia.com/gpu=all -p 8100:8100 ghcr.io/mullm/mullm:cuda
```

Image layers: base (Python + FastAPI + DeBERTa), ollama-sidecar, backends. Total compressed
size target: <2GB for base, <4GB for cuda variant. Podman preferred over Docker per project
policy; docker-compose.yml provided as a compatibility alias.

---

## 7. Hosted SaaS Tier (boilingfrog.dev)

### 7.1 Tiers

| Tier       | Price      | Local models | Cloud routing | Notes                        |
|------------|------------|--------------|---------------|------------------------------|
| Free       | $0         | No           | 100 q/day     | Browser-only, no install     |
| Pro        | $49/mo     | BYOK only    | Unlimited     | Bring-your-own API keys      |
| Team       | $29/seat   | No           | Shared cache  | Usage dashboard, policies    |
| Enterprise | Custom     | On-prem      | Optional      | SSO, audit log, SLA          |

"Local models" on SaaS means the user installs muLLM locally and the SaaS orchestrates against
their machine. muLLM local = free forever is a hard commitment; SaaS is hosted convenience only.

### 7.2 BYOK model

Pro users supply their own Anthropic/OpenAI/Gemini keys. muLLM never proxies those keys through
the SaaS backend — the user's muLLM instance calls the cloud APIs directly. The SaaS layer
handles auth, usage tracking, and the shared cache only. This eliminates the security liability
of holding customer API keys and keeps costs predictable (muLLM SaaS pays zero LLM costs for
Pro users).

### 7.3 Shared semantic cache

Team tier shares a ChromaDB instance across seats. When one team member's query hits the cache,
all subsequent similar queries get the cached response. This is the primary Team-tier value
proposition: a team doing similar coding tasks rapidly warms a shared cache, driving marginal
cost toward zero.

Cache namespace isolation: per-project (not per-user) to maximize hit rate while preventing
cross-project data leakage.

### 7.4 Auth

Free: no auth, rate-limited by IP.  
Pro/Team: JWT issued at login, stored in HttpOnly cookie. No OAuth for v2 launch — custom auth
is simpler to audit and ship. OAuth added in v2.1 if demand justifies it.  
Enterprise: SAML 2.0 SSO, mTLS between client and server, immutable audit log to S3/GCS.

---

## 8. Developer & Vibecoder UX

### 8.1 Natural language build

```bash
mullm build "a cornhole game with Three.js physics and mobile touch controls"
```

Expands to a task DAG internally:
1. Researcher: "look up Three.js Rapier physics integration patterns" (local)
2. Designer: "design cornhole board layout, scoring UI, mobile controls" (cloud haiku)
3. Coder: "implement game from design spec" (cloud, large context)
4. Tester: "write Playwright tests for scoring, game-over state" (local)
5. Validator: "run tests, visual validation" (cloud vision)

The user sees a Rich DAG tree updating live. `--dry-run` shows the planned DAG and estimated
cost before any LLM calls are made. Estimated cost is shown before execution, actual cost shown
after, delta highlighted if over 20%.

### 8.2 Live preview server

```bash
mullm watch src/
```

File watcher (watchfiles, not watchdog — watchfiles is faster and Python-native) detects changes,
re-runs relevant tasks from the DAG (only tasks whose inputs changed), and hot-reloads the
preview server. Preview is a simple `http.server` on a random port with a browser-sync-style
WebSocket for reload signaling. No Node.js required.

### 8.3 Template library

Templates stored at `~/.mullm/templates/` (cloned from github.com/mullm/templates on first run).
```bash
mullm build --template threejs-game "my game description"
mullm build --template fastapi-crud "user management API"
mullm build --template react-dashboard "metrics dashboard"
```

Templates define the initial DAG structure and inject domain-specific context into agent prompts.
A game template tells the Designer agent to think in terms of game loops, not web pages.

### 8.4 VS Code extension

Extension ID: `mullm.mullm-vscode`. Capabilities at v2 launch:
- Hover over any LLM API call → estimated cost per 1000 calls
- Right-click selection → "Ask muLLM" → opens side panel with response
- Inline routing indicator: shows which tier would handle the current file's language/complexity
- Cost counter in status bar: session spend, updated per query

Extension communicates with the local muLLM server (localhost:8100). If server is not running,
extension shows "muLLM offline" and offers "Start server" button.

---

## 9. Benchmarking & Evaluation

### 9.1 RouterBench as first-class command

```bash
mullm bench router              # RouterBench: accuracy + cost + latency
mullm bench router --dataset gsm8k
mullm bench router --dataset humaneval
mullm bench router --dataset multipl-e
mullm bench full                # all benchmarks (expensive, prompts for confirmation)
```

RouterBench is the primary way to measure whether a muLLM configuration change improved or
degraded routing quality. It is not a one-off script; it is a persistent first-class command
with its own SQLite table (`bench_runs`) for historical comparison.

"Never rerun benchmarks without checking existing results first" is enforced in the CLI: before
any bench run, `mullm bench` checks `bench_runs` for results less than 24h old and prompts
"Results from 3h ago exist. Rerun? [y/N]".

### 9.2 Continuous eval

Every production routing decision is logged to `routing_events`. A background cron task
(via APScheduler, not a separate process) computes weekly metrics:
- Routing accuracy vs human oracle (where oracle data exists)
- Cost per correct routing decision
- Tier distribution drift (if % cloud queries rises, flag it)
- Cache hit rate trend

Results are posted to `GET /api/eval/weekly` and displayed on the dashboard. No external
service required — all computed from local SQLite.

### 9.3 Model ELO

ELO updated after every human-rated response (star ratings in the UI, thumbs on CLI output).
ELO stored per (model, task_category) pair so a model can rank high for code and low for
creative writing. Initial ELO = 1200 for all models. K-factor = 32 (aggressive for early data).

ELO is advisory only — it informs cost/quality tradeoff in routing but does not override the
cost model. A model with ELO 1400 that costs 10x more than ELO 1350 is not automatically
preferred; the user sets a `quality_weight` in config (0.0–1.0) to control the tradeoff.

### 9.4 A/B testing framework

```toml
[ab_test]
enabled = true
variant_a = {backend = "anthropic", model = "claude-haiku-4-5", pct = 50}
variant_b = {backend = "openai", model = "gpt-4o-mini", pct = 50}
task_filter = "code"   # only code-classified tasks participate
```

Results logged to `ab_test_events` table. `mullm bench ab-results` shows cost, latency,
and user rating distributions for each variant with statistical significance estimate (Fisher's
exact for pass/fail, Mann-Whitney for continuous metrics). No Bayesian machinery at v2 launch —
frequentist tests are sufficient and easier to explain.

---

## 10. v1 Backlog — v2 Inclusion Plan

### 10.1 Wake word detection

Library: openWakeWord (MIT, CPU-capable, ~50MB model). Runs as a subprocess, not in the FastAPI
event loop. Detected wake word sends a UDP datagram to localhost:8101; the mullm server picks
it up and opens the intake pipeline in mic mode (whisper.cpp for transcription). Activation
sound plays via `pydub`. Disabled by default; `mullm server start --wake-word "hey mullm"`.

### 10.2 INTAKE agent

Monitors Joplin tag `mullm/intake`, email via IMAP IDLE (standard library imaplib), and a
configurable Slack webhook. New items become tasks in the agent DAG with `human_review = true`
by default — INTAKE never executes autonomously without a human approval step. This prevents
the scenario where an email triggers a cloud spend the user didn't authorize.

### 10.3 Wan2.2 video generation

Backend plugin: `mullm-backend-wan22`. Exposes `generate_video(prompt, duration_s, fps)` via
the same BackendProtocol extension interface. Video tasks are classified separately from text
tasks (the DeBERTa classifier has a "media_generation" tier). Wan2.2 outputs go to
`~/.mullm/media/` with SHA256-named files; the server serves them from `/media/{hash}`.

### 10.4 /studio Three.js scene editor

Single-page app at `/studio`. Phase 1 (v2.0): place GLB files by drag-drop, orbit camera, basic
lighting controls, export scene as JSON. Phase 2 (v2.1): chat-to-scene (natural language → scene
mutations via agent), voice commands. Phase 3 (v2.2): game system shelf, test-drive mode.

The scene JSON format is a subset of Three.js Object3D serialization — no custom format that
requires a custom importer.

### 10.5 Speculative decoding (EAGLE-3)

Not implemented in v2.0; targeted for v2.1. EAGLE-3 requires the draft model to be loaded
alongside the target model, which doubles VRAM requirements. On RTX 5090 (32GB) this is
feasible for 9B + 1B draft pairs. DynaKV (dynamic KV cache compression) can be applied
independently of EAGLE-3 and is planned for v2.0 as it requires no model changes.

### 10.6 Session persistence

v1 stores chat history in Dexie.js (IndexedDB, browser-local). v2 adds optional server-side
session persistence in SQLite (`sessions` table, encrypted at rest with SQLCipher for Pro/Team).
Browser-local storage remains the default for free/local users — no server dependency for basic
use. Server-side sessions enable cross-device history sync for SaaS users.

### 10.7 Security: mTLS + air-gap mode

mTLS for Enterprise: client certs issued per-device, revocable via CRL. Air-gap mode: the server
starts with `--air-gap` flag which disables all outbound connections (no cloud backends, no
template sync, no telemetry). Immutable audit log: all `routing_events` rows write to an
append-only SQLite WAL; a scheduled job signs the WAL segment with a local private key and
archives it to a configurable path (S3-compatible or local NFS).

### 10.8 RigNet auto-rigging endpoint

`POST /api/rig` accepts a GLB, runs RigNet (ComfyUI venv, PyTorch 2.11+CUDA), returns a rigged
GLB. Already installed (v1 session), not yet exposed as an HTTP endpoint. v2 wires it in as a
task type: `type = "Rigger"` in the agent DAG. Rigging tasks route exclusively to local GPU;
no cloud fallback (model weights are local, not available via API).

### 10.9 Royal Ravine backend

Redis-backed card game state (Lua eval, ~200µs per state transition). Already designed; v2
exposes it at `/games/royal-ravine` as a WebSocket endpoint. UInt8 wire protocol for card
state, JSON for chat/human-readable events. Planned as a showcase for the muLLM-as-platform
story: an AI-augmented card game where the AI opponent runs on the local Ollama tier.

### 10.10 boilingfrog.dev deploy

Deployment target: single VPS (Hetzner CX52, 16 core / 32GB, ~$50/mo) behind Caddy (automatic
HTTPS). muLLM server + Caddy + podman. No Kubernetes for v2 launch — operational complexity is
not justified until Team tier has >10 active tenants. Migration to k8s planned for v2.1 when
horizontal scaling becomes necessary. Database: SQLite for metadata (adequate to ~100k queries/
day on a single node), ChromaDB for vectors. Backups: daily sqlite3 `.dump` to Hetzner Object
Storage.

---

## Migration from v1

The v1 FastAPI server remains functional throughout v2 development. Migration path:

1. `pip install mullm-core mullm-backend-ollama` alongside existing v1 install
2. muLLM core reads existing ChromaDB data — no migration needed (schema-compatible)
3. `mullm config migrate` reads scattered env vars and writes `~/.mullm/config.toml`
4. JSONL scoring log migrated to SQLite by `mullm db migrate` (one-time, idempotent)
5. v1 server and v2 server can run on different ports during transition (v1: 8100, v2: 8200)
6. v2 promoted to 8100 once all Playwright tests pass against v2 backend

No v1 feature is removed in v2.0. Deprecation (with warning) in v2.1, removal in v3.0.

---

## Open Questions (to resolve before implementation)

1. **DeBERTa retraining**: current 82.4% accuracy trained on 5,161 examples. v2 multimodal intake
   adds new intent categories (sketch, joplin, video). Need to decide whether to retrain the
   full classifier or add a lightweight intent-detection pre-pass for media types.

2. **ChromaDB vs Qdrant**: ChromaDB is sufficient for current scale (~50K vectors). Qdrant offers
   better filtered search and a production server mode. Decision deferred until cache size exceeds
   500K entries or filtered search becomes necessary for multi-tenant SaaS.

3. **A/B test infrastructure**: current plan uses SQLite + manual analysis. If the SaaS tier grows,
   a proper experimentation service (Statsig, GrowthBook) may be warranted. Defer until there are
   >1000 daily active users.

4. **Wake word model choice**: openWakeWord ships several models (hey_jarvis, alexa, etc.). A
   custom "hey mullm" model requires ~5 minutes of voice data and a simple CNN fine-tune on
   the openWakeWord base. This is worth doing — a generic wake word creates false positive risk
   in dev environments where those words appear in other contexts.
