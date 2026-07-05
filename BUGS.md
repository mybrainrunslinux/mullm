# muLLM -- Known Bugs

Updated: 2026-03-30 (Session 9)

---

## Active Bugs

### B1. Stop button doesn't reliably kill local model generation
The cancel endpoint fires and the request is marked cancelled, but Ollama may continue generating tokens server-side until the current inference completes. No feedback to the user about whether the stop actually worked.
- **Where:** `router/main.py` cancel logic, Ollama API limitations
- **Workaround:** The response is discarded even if generation continues

### B2. Split routing loses context between sub-tasks
When data from one sub-task is needed by the next, it doesn't carry over properly. Follow-up references within a split ("use the result from part 1") don't work.
- **Where:** `router/decomposer.py`, split execution in `router/main.py`
- **Fix:** Pass prior sub-task results as context to dependent sub-tasks

### B3. Session cost lost on server restart
`_session_costs` is in-memory dict -- gone on restart. No persistence.
- **Where:** `router/scorer.py`
- **Fix (quick):** Persist to JSONL alongside scoring log
- **Fix (proper):** Move to Redis when multi-user lands

### B4. Cloud SSE streaming not implemented
Only Ollama streams via `/query/stream`. Cloud API calls (Anthropic, OpenAI) return all-at-once. Huge UX gap -- cloud responses feel "stuck".
- **Where:** `router/cloud.py`, `router/main.py`
- **Fix:** Add `stream=True` to cloud httpx calls, yield SSE chunks

### B5. CLI orchestrate/code-apply targeting wrong files
`--orchestrate` and `--code --apply` fail when keyword auto-detection maps to the wrong file. The `_detect_files()` in orchestrator.py and `_file_hints` in mullm_cli.py have limited keyword-to-file mappings.
- **Where:** `mullm_cli.py` lines 467-486, `router/orchestrator.py` lines 280-308
- **Fix:** Expand keyword hints, allow explicit `--file` override, read file list from MULLM.md

### B6. CLI code generation needs explicit file context
When using `--code --apply` without `--file`, the local model gets no code context and can't generate patches. It correctly says "I need the file" but the UX is confusing.
- **Where:** `mullm_cli.py` cmd_code() file auto-detection
- **Fix:** Better error message, or auto-read mentioned filenames from the prompt

---

## Recently Fixed

- **Dashboard savings math** -- Fixed session 7c. Opus vs Opus Extended now uses correct token multipliers.
- **Cache false hits on math** -- Fixed. Short queries (<60 chars) require 0.96+ similarity.
- **Mobile ...more button visibility** -- Fixed. Responsive breakpoints adjusted.
- **False escalation on short math answers** -- Fixed. Short answers aren't degenerate for complexity 1-2.
- **Move chats between projects** -- Fixed. Event propagation, Dexie null handling resolved.
- **Send button cutoff** -- Fixed. Responsive fixes at all screen sizes.
- **File upload >10 files returns 422** -- Fixed. Chat file picker and drag/drop share client-side validation: max 10 files, 50MB per file, 500MB total.
- **Stale cache answers for temporal/realtime queries** -- Fixed. Normal `needs_web` or explicit web-enabled requests skip semantic cache lookup and storage; `force_tier=cache` remains an explicit manual cache probe.
