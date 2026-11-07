# Changelog — muLLM

## [1.0.1] — 2026-11-07

- Local startup uses loopback HTTP without automatically creating an untrusted
  certificate. Explicit HTTPS and authenticated network access remain supported.
- Running `mullm` starts the app; startup and install guidance explain how to launch it.
- CLI, Factory, notifications, and orchestrator defaults follow the configured
  protocol and port. Incomplete explicit TLS configuration fails clearly.
- Release Checks now runs on main so its badge reflects main-branch results.
- Installed-browser checks cover Firefox and Chromium without certificate bypasses.
- Coding harness uses the core HTTP client instead of missing optional Requests;
  failed or unverified tasks return a nonzero exit code. A dedicated
  [coding assistant guide](docs/CODING_ASSISTANT.md) documents the shipped commands.

## [1.0.0] — 2026-11-07

Published on [PyPI](https://pypi.org/project/mullm/1.0.0/) and
[GitHub Releases](https://github.com/mybrainrunslinux/mullm/releases/tag/v1.0.0).

- Core wheel installs without repository constraints; SQLite remains the default
  semantic cache while optional ChromaDB still has unresolved advisories.
- Current OpenAI/Claude, Gemini, DeepSeek, GLM and Cerebras model catalogs;
  corrected Google SDK dependency, thinking-token accounting and dated pricing.
- Local Kev/System One classifier, optional Kev.js browser preview, and packaged
  classifier training.
- Software Factory with isolated candidate worktrees, executable acceptance gates,
  project/task views, durable optional defaults and blocking Need Human decisions.
- Optional notification outbox with Apprise adapters and HTTPS webhooks for 0101
  and other receivers. No notification destinations are enabled by default.
- Release, security and installation docs now distinguish tested core behavior
  from optional integrations and remaining publication requirements.

See [the release record](docs/RELEASE_1_0.md) for verification and remaining scope.

## Historical 1.0 draft — 2026-05-10

The following describes the earlier release plan and historical measurements.
It is not evidence that a 1.0 package was published; current behavior and
installation requirements are documented above and in the README.

### First public release

muLLM began as a personal productivity tool in early 2026 to stop paying frontier
model prices for queries that don't need them. The core observation: in 40 days of
production agentic coding workflows, 82.2% of queries required no cloud call at all.
Actual cloud spend: $73.51. Estimated equivalent spend routing everything to a
frontier model: $7,000–$15,000.

---

### Routing pipeline

- **Groundtruth LUT** — deterministic keyword/pattern table, sub-millisecond, $0
- **Semantic cache** — nomic-embed-text + ChromaDB, per-category cosine thresholds,
  ~14ms median, $0; 7,392 cache hits in first 40 days
- **Local 30B** — Ollama backend (qwen3-coder:30b), RTX 5090, ~5s median, $0
- **Cloud fallback** — Anthropic / OpenAI / Google with auto provider selection;
  hard budget limits and per-minute rate limiting as first-class safety features
- **Split routing** — decompose multi-part prompts, parallel cloud execution, merge

### Intent classifier

- DeBERTa-v3-small (44 MB), fine-tuned on developer query logs
- 7 categories: `code`, `deploy`, `note`, `lookup`, `research`, `conversation`, `creative`
- Sub-10ms inference, confidence threshold 0.80 before LLM fallback
- Per-category temperature presets (precise → creative)
- Per-category cache similarity thresholds (0.90–0.97)

### Server

- FastAPI on port 8100 (configurable via env / TOML)
- SSE streaming (`GET /query/stream`) for local model responses
- Request deduplication (2s window) — prevents duplicate parallel calls
- First-run detection: no mullm.toml + no API keys → auto-opens browser to /setup
- `remote_access` toggle: binds 127.0.0.1 (default) or 0.0.0.0 (LAN/phone)
- Startup banner prints LAN IP when remote_access is enabled

### Configuration

Layered priority (highest → lowest):
1. Environment variables (`MULLM_*`, `ANTHROPIC_API_KEY`, etc.)
2. `mullm.toml` in current directory (project-local)
3. `~/.mullm/config.toml` (user global)
4. Built-in defaults

Schema: `[core]`, `[core.budget]`, `[inference.ollama]`, `[cloud]`, `[cache]`

### Storage backends

- **JSONL** (default) — append-only scoring log, zero dependencies
- **SQLite** — structured queries, cost rollups, free query counting
- MongoDB and Snowflake adapters (optional, behind import guards)

### Packaging

- Python wheel: `mullm-1.0.0-py3-none-any.whl` (88 KB)
- `constraints.txt` — CVE-pinned lower bounds for 6 packages; install via
  `pip install -c constraints.txt mullm-1.0.0-py3-none-any.whl`
- `scripts/install-venv.sh` — venv creation, wheel install, CVE verification
- Container: `compose.yml` + `compose.gpu.yml` (Podman-first; NVIDIA CDI passthrough)
- `mullm-server` entry point

### Frontend

- `router/chat.html` — single-file chat, Dexie.js IndexedDB (client-side, no server DB)
- `router/dashboard.html` — live CPU/GPU/VRAM stats, cost tracking, routing analytics
- `sites/breadboard/` — Three.js circuit puzzle game; 6 tiers, 85 deterministic
  levels, K-map napkin Easter egg at level ≥ 51; colorblind SVG filters; full a11y
- `sites/breadboard/caprese.html` — Three.js Caprese sandwich simulator (it made you one)

### Observed production metrics (40-day window, single developer)

| Metric | Value |
|--------|-------|
| Total queries (deduplicated) | 30,030 |
| Local / free queries | 24,691 (82.2%) |
| Semantic cache hits | 7,392 (24.6%) |
| Actual cloud spend | $73.51 |
| Tokens routed | 31.8M |
| Equivalent Opus 4 flat spend | ~$3,200 |
| Equivalent Opus 4 agentic spend | ~$7,000–$15,000 |

### License

Apache 2.0 — © 2026 0101 Technology LLC
