# muLLM — Performance Characteristics

Measured on RTX 5090 32GB, qwen3.5:9b, Fedora Linux, 2026-03-30.

---

## Current Performance (Session 8)

### Query Latency

| Scenario | P50 | P95 | P99 | Notes |
|----------|-----|-----|-----|-------|
| Cache hit | 20ms | 50ms | 100ms | Semantic similarity > 0.85, ChromaDB lookup |
| Rules classifier | 0-3ms | 5ms | 10ms | Keyword/pattern match, no LLM call |
| LLM classifier | 1.3s | 2.5s | 3.5s | Ollama qwen3.5:9b, ~200 output tokens |
| Local generation | 3-8s | 12s | 25s | Depends on output length, complexity 2-3 |
| Local multi-agent | 10-15s | 25s | 40s | Plan + execute, two sequential LLM calls |
| Cloud (Sonnet) | 2-5s | 8s | 15s | Anthropic API latency + network |
| Split routing | 8-15s | 25s | 45s | Decompose + parallel execution |

### Throughput

| Metric | Value |
|--------|-------|
| Cache QPS | ~50 (limited by ChromaDB) |
| Local QPS | ~0.1 (GPU-serialized via semaphore) |
| Cloud QPS | ~3-5 (parallel HTTP, provider-limited) |
| Dashboard API | <5ms (cached 5s TTL) |
| System stats API | <130ms (nvidia-smi subprocess, cached 3s) |
| Performance API | <5ms (parses scoring log, no cache) |

### Resource Usage

| Resource | Idle | Under load |
|----------|------|-----------|
| GPU VRAM | 18GB (qwen3.5:9b loaded) | 18-22GB |
| System RAM | ~4GB (Python + ChromaDB) | ~6GB |
| CPU | <5% | 15-30% (embedding, JSON parsing) |
| Disk I/O | Minimal | Scoring log append (~1KB/query) |

---

## Context Window Scaling

The `num_ctx` parameter dramatically affects latency:

| num_ctx | KV Cache | Classification time | Generation time |
|---------|----------|-------------------|-----------------|
| Default (~2K) | ~0.5GB | 1-2s | 3-8s |
| 4096 | ~1GB | 2-3s | 4-10s |
| 32768 | ~8GB | 5-10s | 8-25s |
| 131072 | ~32GB | 20-60s | 30-120s |

**Current strategy:**
- Classifier: no num_ctx (Ollama default, ~2K) — fast classification
- Decomposer: no num_ctx (Ollama default) — fast splitting
- Generation (complexity 1-3): no num_ctx — fast responses for normal queries
- Generation (complexity 4-5): num_ctx: 32768 — large context for complex tasks
- CLI --code: min_complexity=3, 120s timeout — code gen gets adequate time

---

## Known Bottlenecks

### 1. GPU Serialization
Single Ollama semaphore means one local model call at a time. Split routing parallelizes cloud calls but local tasks are sequential.

**Fix:** OLLAMA_NUM_PARALLEL=3 + multiple small models (see ARCHITECTURE-AGENTS.md)

### 2. Embedding Model Context (512 tokens)
mxbai-embed-large has a 512-token context window. Long queries get truncated to ~500 chars before cache lookup/store, reducing cache quality for code-gen prompts.

**Fix:** Upgrade to nomic-embed-text or snowflake-arctic-embed (8K context). Config change only: `EMBED_MODEL=nomic-embed-text` (Suggestion #54)

### 3. Cold Start
First query after server restart takes 15-30s (model loading into VRAM). Subsequent queries are fast.

**Fix:** Pre-warm models on startup (already implemented in `_prewarm_models()`). OLLAMA_KEEP_ALIVE=300 keeps models hot.

### 4. ChromaDB at Scale
ChromaDB is single-node, in-process. Beyond ~10K cached entries, lookup latency increases.

**Fix:** Periodic vacuum, TTL-based eviction, or migrate to pgvector for multi-user.

### 5. Dashboard Polling
Dashboard polls /api/dashboard every 5s. With multiple tabs/users, this multiplies.

**Fix:** Switch to Server-Sent Events for dashboard updates (Suggestion #58 path). SSE infrastructure already exists (`/events` endpoint).

---

## Performance Goals

### Short-term (next 2 sessions)
- [ ] Cache hit P50 < 15ms
- [ ] Rules classification < 1ms
- [ ] Local generation P50 < 5s for simple queries
- [ ] Dashboard: SSE push instead of polling
- [ ] Embed model upgrade (512 → 8K context)

### Medium-term
- [ ] Multi-model parallel execution (3 workers)
- [ ] Connection pooling for cloud providers
- [ ] Response streaming for all tiers
- [ ] Cache eviction policy (LRU + TTL)
- [ ] P99 local < 15s

### Enterprise
- [ ] Support 100 concurrent users (horizontal scaling)
- [ ] P99 < 5s across all tiers
- [ ] Zero-downtime model reloads
- [ ] Geographic routing (nearest cloud provider)

---

## Monitoring

- **Live:** http://localhost:8100/performance — P50/P95/P99, tier distribution, slowest queries
- **API:** GET /api/performance — JSON metrics
- **CLI:** `mullm --perf` — terminal performance summary
- **Dashboard:** Real-time savings, latency, cache rate at /dashboard

---

*Updated: 2026-03-30, Session 8*
