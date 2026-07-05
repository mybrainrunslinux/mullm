# muLLM Privacy Statement

muLLM is a local-first LLM router. The majority of your data never leaves your machine.
This document explains exactly what is stored, where, and how to delete or export it.

---

## What Data Is Stored

### 1. Semantic Cache
- **Location:** `cache/data/semantic_cache.sqlite3` by default; `cache/data/chromadb/` only when `MULLM_SEMANTIC_CACHE_BACKEND=chroma` is explicitly enabled
- **Contains:** Query text, model response, routing metadata (model, tier, category, cost, latency, timestamp)
- **Purpose:** Semantic cache — avoids re-running the same queries
- **Scope:** Local disk only. Embeddings computed on-device via Ollama. Nothing sent to embedding APIs.

### 2. Scoring Log
- **Location:** `cache/data/scoring_log.jsonl`
- **Contains:** Routing metadata only — `intent_id`, `category`, `complexity`, `model_used`, `tier_used`, `tokens_used`, `cost`, `success`, `latency_ms`, `timestamp`
- **Does NOT contain:** Query text or response content (never has)
- **Purpose:** Operational metrics, cost tracking, routing quality analysis

### 3. Chat History
- **Location:** Browser IndexedDB (Dexie.js), client-side only
- **Contains:** Full conversation history
- **The server never persists conversation content to disk**
- **Deletable:** In-browser via the chat export/clear controls

### 4. Redis Cache
- **Ephemeral in-memory cache** — lost on Redis restart
- **Contains:** Recent query hashes and responses (exact-match layer)
- **No persistent storage**

---

## Cloud Escalation

When a query is routed to a cloud provider (typically <20% of queries), it is subject
to that provider's data handling policy:

| Provider | API Data Retention | Training Use |
|---|---|---|
| Anthropic (Claude) | 30 days | Not used via API |
| OpenAI (GPT-4o) | 30 days | Not used via API |
| Google (Gemini) | Varies | Check current policy |

You can disable cloud providers entirely in the muLLM settings.

---

## Your Rights

### Right to Access
All data lives on your machine. To inspect it:

```bash
# See data counts live
curl -sk https://127.0.0.1:8100/api/privacy/status | python3 -m json.tool
```

Or visit `/api/privacy/status` in your browser.

### Right to Deletion (GDPR Art. 17 / CCPA)
To purge all stored query data (semantic cache + scoring log):

```bash
curl -sk -X POST https://127.0.0.1:8100/api/privacy/purge-all \
  -H "Content-Type: application/json" \
  -d '{"confirm": "PURGE_ALL"}'
```

The confirmation token `"PURGE_ALL"` is required to prevent accidental deletion.
This clears the vector cache and truncates the scoring log. It does not delete
benchmark results, game votes, or other non-query data.

You can also use the **Purge All Data** button on the `/privacy` page.

### Right to Portability (GDPR Art. 20)
To export all stored data as a ZIP archive:

```bash
curl -sk https://127.0.0.1:8100/api/privacy/export -o mullm_export.zip
```

The ZIP contains:
- `scoring_log.jsonl` — routing metadata (no query content)
- `cache_export.jsonl` or `chroma_export.jsonl` — semantic cache entries including query text and responses when query-content logging is enabled
- `manifest.json` — export summary with entry counts and timestamp

---

## Retention Policy

By default, scoring log entries older than **90 days** are purged automatically on server startup.

To change the retention window, set the `DATA_RETENTION_DAYS` environment variable:

```bash
# Keep 30 days of logs
DATA_RETENTION_DAYS=30 python -m router.main --https

# Disable auto-purge entirely
DATA_RETENTION_DAYS=0 python -m router.main --https
```

The semantic cache is a performance cache, not a log. Use `/api/privacy/purge-all`
to clear it manually.

---

## Data Minimization

- **Local-first by design:** Simple queries never leave your machine
- **No telemetry:** muLLM sends no usage data to any external service
- **No accounts, no PII required:** The system has no user accounts and requires no personal information
- **Scoring log is metadata-only:** Query text has never been stored in the scoring log
- **Budget limits:** Cloud escalation is gated by per-day spend limits, preventing accidental data exposure

---

## API Summary

| Endpoint | Method | Description |
|---|---|---|
| `/api/privacy/status` | GET | Counts of stored data + date range |
| `/api/privacy/export` | GET | ZIP download of all stored data |
| `/api/privacy/purge-all` | POST | Delete all query data (requires `{"confirm":"PURGE_ALL"}`) |
| `/privacy` | GET | This information as an interactive HTML page |

---

*muLLM is open source. All routing logic is auditable in `router/intent.py` and `router/tiers.py`.
This document is informational. Consult legal counsel for formal compliance requirements.*
