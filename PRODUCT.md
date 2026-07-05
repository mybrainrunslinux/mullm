# muLLM — Product Spec

## Value Proposition
Local-first AI router that saves 99%+ on LLM costs. Your queries stay private, your GPU stays busy, cloud only when genuinely needed.

## Pricing

### Free Tier (forever)
- Local model routing (Ollama)
- ChromaDB vector cache (zero-cost repeat queries)
- Ground truth resolver (200+ instant answers: dates, math, ports, mythology, etc.)
- Basic chat UI with voice I/O
- 5 games in /code/

### Pro — $19.99 one-time (or $14.99 in emerging markets)
- Multi-provider cloud routing (Anthropic, OpenAI, Google)
- Cost analytics dashboard with executive breakdown
- Split routing (parallel sub-task decomposition)
- Budget controls and cost alerts
- /goo and /oai provider-specific endpoints
- Suggestions engine (follow-up query chips)
- Performance monitor with trace
- MCP + A2A protocol support
- Orchestrator (plan + execute from markdown)
- Priority cache (cloud responses cached for free reuse)

### Optional: Cloud Credits Pass-through — $5/mo
- $5 of cloud API credits included (Anthropic/OpenAI/Google)
- Markup: 0% (pass-through at cost, value is in the routing)
- Overage: user's own API keys, no markup
- Auto-top-up option

## Packaging

### Desktop (primary)
- **Tauri** (Rust + WebView2) — ~5MB installer, native performance
- Auto-detect GPU (nvidia-smi), suggest optimal Ollama model
- Bundled Ollama or detect existing installation
- System tray icon with quick-query
- Auto-update via GitHub Releases

### Mobile (stretch)
- **CapacitorJS** wrapping the web UI
- Connect to desktop instance over LAN (no local inference on phone)
- Or connect to a cloud-hosted muLLM instance

### Docker/Podman (self-hosted)
- `podman run -p 8100:8100 --gpus all mullm/mullm:latest`
- Compose file with Ollama + muLLM + Redis
- Ideal for teams/companies

## Licensing
- **BSL 1.1** (Business Source License) — free for personal/small-team use
- Commercial use >5 seats requires Pro license
- Source available (not obfuscated) — the value is the integration, not the code
- After 3 years, converts to Apache 2.0

## Security
- API keys stored in OS keychain (not .env files in production)
- HTTPS by default (self-signed for local, Let's Encrypt for hosted)
- No telemetry unless opted in
- All chat data stays in IndexedDB (client-side)
- Scoring log stays on disk (never uploaded)

## Marketing Angles
1. **"99.8% savings"** — real number from the dashboard, provable
2. **"Your GPU, your data"** — privacy story for enterprises
3. **"sub-millisecond answers"** — ground truth resolver is genuinely faster than any cloud API
4. **Cost-per-correct-answer benchmark** — unique metric nobody else publishes
5. **"One interface, every model"** — Anthropic + OpenAI + Google + local in one UI

## What a Fresh Rewrite Would Change

### Architecture (new-mullm)
- **Monorepo with workspaces**: `new-mullm/core`, `new-mullm/web`, `new-mullm/cli`, `new-mullm/games`
- Each workspace is its own package with its own tests
- Core: FastAPI + routing logic + cache + classifier (no HTML)
- Web: Vite + Svelte (or Solid) SPA — replaces the single-file HTMLs
- CLI: standalone Python package
- Games: separate static files, not in the router

### What to Keep
- The routing intelligence (classifier, tier logic, cost optimization)
- ChromaDB vector cache
- Ground truth resolver (realtime.py — this is gold)
- Scoring log + analytics pipeline
- MCP/A2A protocol support
- The pricing database in settings.py

### What to Replace
- Single-file HTMLs → component-based SPA (better maintainability)
- Inline CSS/JS → proper build pipeline with tree-shaking
- JSONL scoring log → SQLite (structured queries, migrations)
- Manual model config → auto-discovery (Ollama API, check provider health)

### What to Add
- Proper error boundaries (React-style, not try/catch in handlers)
- OpenTelemetry tracing (replace ad-hoc structlog)
- Rate limiting middleware (not per-endpoint checks)
- WebSocket for real-time updates (replace SSE)
- Plugin system from day one (not bolted on)

### Git Structure
```
new-mullm/
  core/          # FastAPI, routing, cache, classifier — its own git history
  web/           # Vite SPA — its own git history
  cli/           # Python CLI package
  games/         # Static game files
  docs/          # User-facing docs
  .github/       # CI/CD
```
Could use git submodules or a monorepo tool (Turborepo, Nx, or just workspaces).
The key insight: mullm's repo-indexer should ONLY index `core/` for code context.
Everything else is static assets or UI components.

## Estimated Timeline
- Fresh rewrite to shippable v1.0: 3-4 focused sessions
- Tauri packaging: 1 session
- Marketing site + docs: 1 session
- Beta launch: 5-6 sessions total
