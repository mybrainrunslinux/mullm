# EMNLP 2026 Submission Checklist — muLLM

## Key Dates
- **ARR submission deadline: May 25, 2026** ← the one that matters
- Author response / discussion: July 7–13, 2026
- EMNLP commitment deadline: August 2, 2026
- Notification: August 20, 2026
- Conference: October 24–29, 2026 (Budapest, Hungary)

You must submit to ACL Rolling Review (ARR) by May 25. At submission time, declare EMNLP 2026 as your intended venue. If accepted, commit by August 2.

---

## Before You Submit: High-Leverage Fixes (do these first)

### Fix 1 — The single-user problem (biggest rejection risk)
Get 1-2 other people to use muLLM for even 5-7 days and log their queries. 3,000 queries across 3 users transforms "one developer's toy" into "deployable system validated across users." Even one colleague with different query patterns (non-game-dev, non-coding) changes the story materially. This is the single highest-leverage action available.

### Fix 2 — Demote mμPQS / mμPETS to Appendix
Move §4.13 and §4.14 out of the main body. Lead with externally verified numbers (RouterBench AIQ, HumanEval). Author-defined metrics in main sections will be dismissed by reviewers regardless of how well-reasoned they are. Keep them as "proposed metrics — see Appendix E" with a one-paragraph forward reference.

### Fix 3 — Add a Theme 2 framing section
Add ~400 words at the start of §5 (or as §5.0) explicitly engaging with the research question: "What does local-first routing change about how individual developers interact with LLMs?" Answer: changes query distribution (users ask more freely when cost is $0), changes latency expectations, creates a privacy floor, and creates an individual-scale deployment archetype that didn't exist before. This turns the paper from "here's a system" to "here's evidence about a new ecosystem pattern."

### Fix 4 — Expand thin benchmark samples
- GSM8K: run to 250 (not 20). Already in the repo: `--mode gsm8k --limit 250`.
- GPQA: run to 50 questions minimum. 20 is not credible.
- BBH: either expand to 100+ or remove the result from the main table.

### Fix 5 — Tighten scope
Remove or compress: game generation anecdote (§5.1 last 2 paragraphs), Kaggle competition result, MCP/A2A protocol specifics (§3.4 last 3 bullets), PR-Gauntlet from the main paper (keep in Future Work as a 3-sentence bullet). Target 9-10 pages for content. EMNLP main: 8 pages content + references. Workshop: 4-6 pages.

### Fix 6 — Baseline comparison
Add one row to Table 1 comparing against "Gemini Flash only" or "GPT-4o-mini only" — a realistic cheap-cloud baseline that a cost-conscious user would actually choose. The Sonnet-equivalent baseline is fair but a reviewer will ask "why not compare against the cheapest reasonable alternative?"

---

## Paper Submission Process (ARR)

### Step 1 — Create ACL Anthology account
Go to https://softconf.com/acl/system/ or the ARR portal (https://aclrollingreview.org/). Create an account with your email. This is the START/SoftConf system. Do this early — account creation can have delays.

### Step 2 — Format the paper
ARR uses ACL style files. Download from: https://github.com/acl-org/acl-style-files
- Anonymous review: remove your name and institution from the PDF. Replace with "Anonymous Authors."
- Page limit: 8 pages content + unlimited references for long papers; 4 pages for short papers.
- Required sections: Abstract, Introduction, Related Work, Method, Experiments, Conclusion, Limitations, Ethics Statement.
- Limitations section is mandatory at ARR. You already have §5.3 — make sure it's labeled "Limitations."
- Ethics statement is mandatory. Appendix B (Responsible NLP Checklist) covers this but needs a dedicated "Ethics" section header.

Convert the markdown paper to LaTeX using the ACL template. This is a few hours of formatting work.

### Step 3 — Prepare supplementary material
- Code: the GitHub repo (https://github.com/mybrainrunslinux/mullm). Make sure it's public before submission.
- Data: the DeBERTa training set (5,161 examples from `cache/groundtruth_base.jsonl`) should be included or linked.
- No supplementary PDF limit at ARR, but reviewers are not required to read it.

### Step 4 — Complete the ARR checklist
At submission you fill out:
- Responsible NLP Checklist (you already have Appendix B — just map it to the online form)
- Limitations: already in §5.3
- Ethics: add the ethics section header
- AI assistance disclosure: already in Appendix D

### Step 5 — Select submission track
At ARR submission, indicate intended venue: **EMNLP 2026 Theme Track — "From Models to Systems and Ecosystems"**. You can also indicate a secondary track preference.

### Step 6 — Submit
Upload the anonymized PDF and supplementary materials. You get a paper ID. Confirm submission confirmation email.

### Step 7 — Author response (July 7-13)
Reviewers post their reviews. You get a 1-week window to respond. Keep the response short (< 500 words), address only concrete factual errors or misunderstandings, don't relitigate the whole paper. If a reviewer raises W1 (single-user), acknowledge it and point to any additional user data collected by then.

### Step 8 — EMNLP commitment (August 2)
If ARR returns positive reviews, you commit to EMNLP 2026 specifically. If reviews are borderline, you can choose to not commit and revise for the next ARR cycle (targeting EMNLP findings or another venue).

---

## If Not Ready by May 25

Next ARR cycle with EMNLP Findings option: submit to the June/July ARR cycle for EMNLP Findings (lower bar, same conference, same trip to Budapest). Findings papers are presented as posters; main conference papers may also be poster-only. The experience of going is the same.

Backup venues if main EMNLP doesn't work:
- **Efficient NLP Systems Workshop** (co-located with ACL/EMNLP): 4-page limit, practitioner audience, much higher acceptance rate
- **COLM 2026** (Conference on Language Modeling): newer venue, open to systems papers
- **NAACL 2026 Industry Track**: accepts production deployment reports

---

## Current Paper Status vs Submission Requirements

| Requirement | Status | Action |
|---|---|---|
| 8-page LaTeX format | Not started | Convert markdown → LaTeX |
| Anonymous PDF | Not started | Remove author name |
| Limitations section | ✓ §5.3 | Add "Limitations" header |
| Ethics section | ✓ Appendix B | Add "Ethics" header |
| AI disclosure | ✓ Appendix D | Already done |
| Multi-user data | ✗ Missing | Get 1-2 other users |
| mμPQS demoted | ✗ Still in main | Move to appendix |
| Thin benchmarks expanded | ✗ GPQA=20, GSM8K=20 | Run more samples |
| Theme 2 framing section | ✗ Missing | Write ~400 words |
| GitHub repo public | ? Verify | Confirm before submission |
| DAG diagram | ✓ dag_diagram.svg | Include as Figure |
| All citations have URLs | ✓ | Done |
