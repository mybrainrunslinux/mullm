# Next Session — muLLM Launch Prep
_Saved: 2026-05-10. ARR paper deadline: May 25, 2026._

---

## Hard deadline first: Paper (May 25)

- [ ] Open Overleaf, check compiled PDF page count — must be ≤ 8 pages two-column (ACL format). Move overflow to appendix.
- [ ] Add limitations paragraph on agglutinative languages (Hungarian, Finnish, Turkish, Swahili — single words = multiple English tokens, classifier trained on English regex patterns misroutes unless multilingual DeBERTa active)
- [ ] Read every single word of the paper before submitting — this is a personal commitment, do not skip
- [ ] Anonymization pass: no author name, no "0101 Technology", no identifying URLs in main body
- [ ] Register at openreview.net (Gmail is fine now for ARR)
- [ ] Upload compiled anonymous PDF to OpenReview

---

## Email infrastructure (unblocks OpenReview registration and everything else)

- [ ] Google Workspace + forwarder for 0101technology.com (or Fastmail $36/yr)
- [ ] Decide on mullm.com contact email and wire it up
- [ ] Cookie/privacy banner on mullm.com (GDPR minimum for EU visitors — EMNLP audience is international)

---

## Platform installs — test all three OS

### Linux (main box, RTX 5090) — already working
- [ ] Confirm wheel installs clean in a fresh venv: `bash scripts/install-venv.sh`
- [ ] Confirm CVE scan passes: Grype on the venv

### Windows 10 / AMD 8GB ("Peti" box)
- [ ] Allowlist box on mullm.com OR scp wheel directly
- [ ] Install Ollama for Windows → pull `qwen2.5:7b` (fits 8GB; ROCm may not work on Win10, CPU fallback is fine at ~30-60s)
- [ ] `pip install -c constraints.txt mullm-1.0.0-py3-none-any.whl`
- [ ] First-run check: no mullm.toml + no API keys → browser opens to /setup
- [ ] Ship `scripts/training_data_sample.csv` to the box
- [ ] Run: `python3 scripts/retrain_classifier.py --data training_data_sample.csv --no-cuda`
  - Outputs to: `~/.mullm/models/routing-classifier-multilingual`
  - Takes 30–60 min on CPU — start it and walk away
- [ ] Send ~100 Hungarian queries as Peti, record misroutes
- [ ] Collect results: note which categories misroute most (deploy and conversation are thinnest in training data)

### Mac M4 Pro 24GB unified RAM
- [ ] Install Ollama for Mac (Metal acceleration is automatic, nothing special needed)
- [ ] Can run `qwen3-coder:30b` quantized — fits in 24GB unified
- [ ] `pip install -c constraints.txt mullm-1.0.0-py3-none-any.whl`
- [ ] Smoke test: send 10 queries, check routing logs
- [ ] MLX backend is future/optional — Ollama with Metal is sufficient for now

---

## Code review (personal commitment: read every line before publishing)

- [ ] Strategy: open PRs against main branch so review history is clean and public
- [ ] OR: use mullm + Claude Code to assist the review session by session
- [ ] Security scans already partially done (semgrep, Grype, badger) — user more confident here
- [ ] Key files to read carefully:
  - `router/main.py` — FastAPI entrypoint, all endpoints
  - `router/intent.py` — classifier pipeline
  - `router/config.py` — settings and secrets handling
  - `cache/vector.py` — ChromaDB interface
  - `config/settings.py` — all pricing, all model definitions
  - `scripts/install-venv.sh` — what actually runs on user machines

---

## Business setup (async, start applications now — they take time)

- [ ] DUNS application for **0101 Technology LLC** — free at dnb.com, ~30 business days
- [ ] DUNS application for **Boiling Frog** — clarify: is this a second LLC, DBA, or game studio? Apply same day as 0101.
- [ ] PyPI name reservation: `pip install mullm` should go to the right place — reserve even if not publishing yet

---

## Sites
- [ ] mullm.com: confirm accessible, limited allowlist initially
- [ ] breadboard game + caprese simulator live at mullm.com/breadboard
- [ ] tokenmeter.html live or linked
- [ ] slides live (for EMNLP demo link)

---

## Web measurements (do not update paper, but useful for blog/site)
- [ ] Run mullm on AMD 8GB box for a real session, record:
  - Local % (will be lower — slower model, more cloud escalation)
  - Latency median
  - Cost per session
- [ ] Compare to main box numbers for "minimum viable hardware" story

---

## Classifier follow-up (after Peti sessions)
- [ ] Add local/cloud label to training_data_sample.csv (second column: `tier`)
- [ ] Retrain combined 14-class model (7 intent × 2 tier) when data is sufficient
- [ ] Binary English model at `/home/peter/mullm/models/routing-classifier/` — do not touch until combined model is validated

---

## Pending caprese.html fixes (lower priority, before site launch)
- [ ] Non-Product lighting modes too dark — needs brightness boost
- [ ] Add 3+ plate options (at least one fancy round: gold rim, marble, terracotta)
- [ ] Olive/garlic position still slightly inside top bread
