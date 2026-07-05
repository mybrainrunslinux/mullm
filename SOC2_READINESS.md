# SOC2 Type II Readiness Assessment

*As of 2026-04-19. Honest gap analysis — no marketing.*

---

## What SOC2 Type II Actually Requires

SOC2 Type II is evidence that your controls **worked consistently over a period of time** (typically 6–12 months). An auditor collects evidence samples from that window. The Trust Service Criteria relevant to a SaaS API product like muLLM:

| Criteria | Scope |
|---|---|
| **CC6** | Logical and physical access controls — who can access what, how authenticated |
| **CC7** | System operations — monitoring, anomaly detection, incident response |
| **CC8** | Change management — how code changes are reviewed and deployed |
| **A1** | Availability — uptime commitments, monitoring, capacity |

---

## What muLLM Already Has (Evidence-Eligible Today)

### Audit Trail — `cache/data/scoring_log.jsonl`

The scoring log captures every query routed through the pipeline. Fields logged per request:

| Field | SOC2 Relevance |
|---|---|
| `intent_id` | Unique request identifier (non-repudiation) |
| `timestamp` | Unix epoch — sufficient for timeline reconstruction |
| `category` | Intent classification (what the system decided) |
| `complexity` | Routing decision factor |
| `model_used` | Which model served the request |
| `tier_used` | `cache` / `local` / `cloud_cheap` / `cloud_full` |
| `tokens_used` | Resource consumption per request |
| `cost` | Spend accountability |
| `success` | Whether the request succeeded |
| `latency_ms` | Performance record |
| `content_preview` | Partial query content (first N chars) |

**Strength:** JSONL is append-only in practice — no row updates, no deletes. This supports an immutability argument for CC7 (log integrity). Auditors accept JSONL with file-level integrity checks (e.g. daily SHA256 recorded to a separate store).

**Weakness:** No IP address, no user agent, no authenticated user identity in the log. A cloud user querying `/query` is indistinguishable from a local process.

### Access Control — `AuthMiddleware` in `router/main.py`

- Bearer token auth on all non-public endpoints
- Public paths explicitly whitelisted (`_PUBLIC_PATHS`, `_PUBLIC_PREFIXES`)
- Returns 401 with no information leakage on failure
- Single API key (`MULLM_API_KEY` env var) — no per-user tokens yet

**Strength:** There is a documented, code-enforced access boundary. CC6 can cite this.

**Weakness:** Single shared key = no per-user audit trail, no revocation per identity.

### Change Management — Git History

- All code changes tracked in git
- Branch-based development (`dev3`, `main`)
- Commit messages document intent
- No force-pushes to main (policy should be documented, not just practiced)

**Strength:** Git log is admissible SOC2 evidence for CC8 with a written policy.

### Dependency Scanning — `.github/workflows/grype.yml`

Weekly automated scan added (2026-04-19). Fails builds on HIGH/CRITICAL CVEs.

**Strength:** Demonstrates proactive vulnerability management for CC7.

### Health Endpoint — `GET /health`

Exists and returns Ollama status, loaded models, version. Sufficient as a liveness target for uptime monitoring.

---

## Gaps to Fill Before Starting the 6-Month Clock

### 1. Access Log Middleware (CC6, CC7) — **HIGH PRIORITY**

No per-request access log exists with IP, endpoint, status code, and user agent. Without this, you cannot demonstrate "logical access monitoring" for CC6 or anomaly detection for CC7.

**What to add:** FastAPI middleware writing one line per request to `cache/data/access_log.jsonl`:

```json
{"ts": 1774768746.6, "ip": "10.0.0.12", "method": "POST", "path": "/query", "status": 200, "ua": "curl/8.1", "latency_ms": 312.4}
```

The `AuthMiddleware` in `router/main.py` already touches every request — add the log write there or in a new `AccessLogMiddleware`.

### 2. Branch Protection Policy (CC8)

Document in writing (even a 1-page internal doc) that:
- All changes to `main` go through a branch
- No force-push to `main`
- At minimum 1-person review before merge (even if you are a solo founder, note the policy)

GitHub branch protection rules serve as automated evidence for this.

### 3. Incident Response Procedure (CC7) — **1 page suffices**

Write a minimal incident response runbook:
- How you detect an incident (monitoring alert, user report)
- Who is notified (even if it's just you)
- How you assess severity
- How you communicate with affected users
- Post-incident review requirement

Auditors do not expect a 50-person IR team. They expect documented intent.

### 4. Uptime Monitoring / Availability (A1)

No external uptime monitoring is in place. Options:
- **Free:** UptimeRobot (free tier, 5-min checks) pointing at `GET /health`
- **Self-hosted:** Cron job writing uptime ping results to a log file
- **Integrated:** Add a `/healthz` alias (standard Kubernetes convention, distinct from `/health`) that returns `{"status":"ok"}` with no Ollama dependency, for lightweight probing

**Minimum viable:** A cron job that runs `curl -sk https://127.0.0.1:8100/health` every 5 minutes and appends result to `cache/data/uptime_log.jsonl`. Must run for 6 months to count as evidence.

### 5. Encryption at Rest (CC6)

**Current state: plaintext.**

- `cache/data/scoring_log.jsonl` — plaintext on disk
- `cache/data/chromadb/chroma.sqlite3` — plaintext SQLite
- Any cached responses in ChromaDB — plaintext

**Options (ascending cost/complexity):**
1. **Filesystem encryption (easiest):** LUKS on the partition where `cache/data/` lives. Transparent to the application, auditors accept it.
2. **Application-level:** Encrypt individual records before writing — significant code change.
3. **Accept the risk:** Document that the server runs in a physically secured environment with no multi-tenant data. Auditors may accept this for a single-tenant deployment with a compensating control narrative.

### 6. Per-User Identity (CC6)

The current single-API-key model cannot distinguish between users. For a personal/internal tool this is acceptable with a compensating narrative. For a SaaS with multiple customers it is a blocker.

If/when muLLM becomes multi-tenant: add per-user API keys stored hashed in a DB, and include `user_id` in the access log and scoring log.

### 7. Data Retention Policy (CC6, GDPR)

No documented retention policy exists. Decide and document:
- How long are scoring logs retained? (90 days recommended for GDPR Article 5)
- How long are access logs retained?
- Is `content_preview` in the scoring log considered personal data? (Probably yes for EU users)
- Deletion procedure on request

---

## Recommended Additions to Start the Clock

Do these to make the monitoring period auditable from day one:

1. **Add `AccessLogMiddleware`** to `router/main.py` — logs `{ts, ip, method, path, status, ua, latency_ms}` to `cache/data/access_log.jsonl` (1-2 hours of work)
2. **Add `/healthz`** endpoint returning `{"status":"ok"}` — no Ollama dependency (15 minutes)
3. **Set up uptime cron** — 5-minute ping to `/healthz`, results to `cache/data/uptime_log.jsonl`
4. **Enable LUKS** on `cache/data/` partition or document compensating control
5. **Add grype to CI** — done (2026-04-19)
6. **Write 1-page IR procedure** — even a dated Markdown file in the repo counts
7. **Enable GitHub branch protection** on `main`
8. **Document data retention policy** — even 3 sentences in a PRIVACY.md

---

## Estimated Timeline and Cost

| Phase | Duration | Cost Estimate |
|---|---|---|
| Gap remediation (items above) | 2–4 weeks | $0 (engineering time) |
| Monitoring period | 6–12 months | $0 (evidence accumulation) |
| Auditor selection + scoping | 1–2 months | $2–5K |
| Type II audit + report | 2–3 months | $15–40K (startup-focused auditors) |
| **Total to first report** | ~12–18 months | **$17–45K** |

Lower-cost path: SOC2 readiness platforms like Vanta (~$15K/yr) or Drata automate evidence collection and reduce auditor prep time. They instrument your cloud/git/CI directly and pre-populate evidence. Worth evaluating once the monitoring period begins.

---

## Bottom Line

muLLM has a solid foundation: append-only logs, bearer auth, git-based change history, and now automated dependency scanning. The two biggest concrete gaps are:

1. **No per-request access log** (IP, endpoint, status) — blocks CC6/CC7 evidence
2. **No uptime monitoring** — blocks A1 evidence

Fix those two things first, start the cron/monitoring, and the 6-month clock can begin.
