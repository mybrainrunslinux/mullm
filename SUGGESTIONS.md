# muLLM -- Feature Suggestions

User-originated ideas. Roughly priority-ordered.

Updated: 2026-03-30 (Session 9)

---

## High Impact

### 1. Voice Output (TTS)
New button for on-device voice synthesis. Handful of voices in Settings. Reasonable limits on what gets read aloud (code should be described not read). Zero cost -- browser-native Web Speech API.
**Status:** Spec in MULLM.md, not yet implemented.

### 2. File Upload + Transform Pipeline
Upload a file (HTML/Python/JS), say "make these changes", muLLM splits, routes each change to cheapest tier, applies diffs, returns updated file. Foundation for git integration.
**Status:** Not started. Needs diff application logic.

### 3. Per-Subtask Escalation in Split Results
Individual "Escalate" buttons per split output + "Escalate All" that bumps each part one tier up.
**Status:** DONE (Session 7b). Escalate per sub-task + Escalate All buttons implemented.

### 4. Color Themes
Beyond dark/light: Synthwave, Neon, Pastels, High Contrast, Soft Grey. CSS custom property sets, swap via settings drawer. NOT labeled "colorblind mode" -- just aesthetic names.
**Status:** Not started.

### 5. Local Thinking + Agentic Modes
`local_thinking`: reasoning model with visible `<think>` chain-of-thought.
`local_agentic`: multi-step autonomous with N-step cap and cost tracking.
**Status:** local_multi exists as 2-pass plan+execute. Needs UI toggles and proper tier labels.

### 6. Project Context Loader
Recursive file walker (respects .gitignore), smart chunking, file type handlers, dependency graph builder. Enables "understand this project" queries.
**Status:** Not started. High effort.

### 7. URL/Screenshot/Diagram Understanding
Accept URLs (fetch + summarize), screenshots (vision model), diagrams (OCR + interpret). Route to vision tier automatically.
**Status:** Image/vision upload DONE. URL fetch not started.

### 8. Live 2D Agent Dots View
Every running query as a colored dot: grey=pending, blue=running, green=done, red=error. Click to cancel, retry, escalate. Mobile-friendly.
**Status:** Not started.

### 9. Critical Path Test Suite
Tag ~15 tests as `@critical` (run in <2 min). Full suite stays at `@full`. CI runs critical on every push.
**Status:** Not started.

---

## Medium Impact

### 10. Playable Tour GIF
Playwright video -> ffmpeg -> <3MB animated GIF. Auto-generated per commit.
**Status:** Screenshots and video capture exist, need ffmpeg post-process step.

### 11. A/B Comparison Mode
Send same query to local + cloud, show both results side by side. Let user decide quality.
**Status:** Not started.

### 12. Chat-to-Project Organization Improvements
Better drag-drop for moving chats. Inline rename instead of modal.
**Status:** Move chats DONE. Rename is modal-based.

### 13. mem0-style Conversation Memory
Track user preferences across sessions. "Remember I prefer TypeScript" type interactions.
**Status:** Not started. Needs design.

### 14. OpenAI-Compatible Proxy Mode
`OPENAI_BASE_URL=http://localhost:8100/v1` drop-in replacement. Any tool that speaks OpenAI API gets muLLM routing for free.
**Status:** Not started. Could be the killer feature.

---

## Implemented (for reference)

- Split routing with parallel execution (Session 2)
- Multi-project chat system with Dexie.js (Session 2)
- First-run /setup page with API key entry (Session 7c)
- Fast Mode auto-escalation (Session 7b)
- 10 MCP tools (Session 7b)
- Cache quality improvement (Session 7b)
- Per-subtask escalation (Session 7b)
- Stop button / request cancellation (Session 7)
- Dashboard with real metrics (Sessions 1-8)
- Voice input via Web Speech API (Session 2)
- System date injection + realtime resolver (Session 9)
- Conversation context for follow-up references (Session 9)
- needs_web web search (Session 9)
