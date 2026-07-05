# muLLM — Launch Readiness Checklist

## Status: PRE-LAUNCH (Session 4, 2026-03-29)

---

## MUST-HAVE Before Sharing (P0)

### Security
- [x] XSS protection — DOMPurify on all user-facing HTML
- [x] CORS lockdown — configurable origins, default localhost-only
- [x] Bearer token auth — MULLM_API_KEY middleware
- [x] Input validation — /query and /query/stream both validated
- [x] Budget enforcement — daily cap + per-request approval ceiling
- [x] Runaway detection — rapid-fire limit, complexity-based timeouts

### Data Integrity
- [x] Every dashboard number has a source (scoring_log.jsonl or real-time calc)
- [x] Fake metrics removed — LMA/RQS replaced with honest names
- [x] Enterprise projection has documented assumptions with sources
- [x] Efficiency score formula is documented and disclosed in tooltip
- [x] SIM mode clearly labeled with amber indicator
- [ ] Add data provenance tooltips to EVERY number on dashboard (hover = how this was calculated)
- [ ] Dev time saved (30s/15s assumptions) need user-configurable overrides

### UI Polish
- [x] Markdown rendering with syntax highlighting (marked.js + highlight.js)
- [x] Dark/light mode with system detect
- [x] PWA manifest + service worker for installable app
- [x] Mobile responsive (600px, 360px breakpoints)
- [x] Temperature presets (Precise/Balanced/Creative)
- [x] Token display with saved/avoided comparison
- [x] Escalate button persists 3 minutes
- [x] LIVE indicator shows latency on hover
- [x] All hover tooltips explain what each metric means
- [ ] Logo/favicon (current: inline SVG in manifest)
- [ ] Loading skeleton states for dashboard cards
- [ ] Empty state for first-time users (0 queries)
- [ ] Onboarding flow — "Send your first query" prompt

### Accessibility (WCAG 2.2 AA+)
- [x] Skip link to chat input
- [x] ARIA labels on main regions
- [x] Focus-visible outlines (2px teal)
- [x] prefers-reduced-motion support
- [x] Min 36px tap targets for buttons
- [x] user-scalable=yes, max-scale=5
- [x] 4:1+ contrast ratios on text (dark mode verified)
- [ ] 4:1+ contrast ratios on light mode (need visual verification)
- [ ] Screen reader testing with NVDA/VoiceOver
- [ ] Keyboard navigation testing (all features reachable via Tab)
- [ ] ARIA live regions for streaming responses (announce new content)

---

## SHOULD-HAVE Before Public Launch (P1)

### Features
- [ ] Cloud SSE streaming (Anthropic + OpenAI support it)
- [ ] Chat auto-title via local model (free, better UX)
- [ ] Chat export (.md / .json download)
- [ ] Fix split routing prompts (local model gives generic answers to sub-tasks)
- [ ] Multi-agent Level 1 — 9B classify, 27B execute with keep_alive:0

### Dashboard
- [ ] Implement Anomaly Detection card (real: flag cost spikes via stddev)
- [ ] Implement Time-of-Day Heatmap (real: aggregate scoring_log by hour)
- [ ] Implement Savings Velocity (real: $/hour rolling average from last 100 queries)
- [ ] Remove or implement Screenshot & GIF (canvas-to-image is fragile)
- [ ] Add Chart.js timeline chart for cost over time

### Enterprise
- [ ] OpenAI-compatible proxy support (OPENAI_BASE_URL env var)
- [ ] Azure OpenAI support
- [ ] OIDC/OAuth2 login (Google, GitHub, Microsoft)
- [ ] Per-user session tracking in scoring log

---

## NICE-TO-HAVE (P2-P3)

- [ ] Shareable summary export (PDF/HTML for board decks)
- [ ] SAML2 SSO
- [ ] Per-user quotas + RBAC
- [ ] AWS Bedrock provider
- [ ] mem0 shared memory across sessions
- [ ] ThreeJS/WebGL pipeline visualization
- [ ] Hosted demo at boilingfrog.dev/tools/mullm

---

## Quality Gates

### Before Showing to Anyone
1. All P0 checkboxes above are checked
2. Tests pass: `npx playwright test` (free tests only)
3. Server starts clean: `python -m router.main` with no errors
4. Dashboard loads with real data (not SIM)
5. Chat sends a query, gets a response, shows in tier bar
6. Mobile: open on phone, voice input works, chat is readable

### Before Public GitHub / HN Launch
1. All P1 checkboxes above are checked
2. README has 3-minute demo video
3. docker-compose.yml / podman-compose.yml for one-command setup
4. .env.example with clear instructions (no real keys!)
5. All "Coming Soon" cards either implemented or removed
6. Light mode tested on real devices
7. Lighthouse score > 90 (Performance, Accessibility, Best Practices)
