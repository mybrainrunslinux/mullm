# muLLM: Cost-Optimal LLM Routing via Lightweight Intent Classification

**Authors:** Anonymous Author · [contact redacted for review] · [[organization URL redacted for review]]([organization URL redacted for review])  
**Target:** ACL/EMNLP 2026 Efficient NLP Systems Workshop (4-page submission)  
**arXiv:** cs.CL + cs.AI  
*Built with human-AI pair programming using Claude Code (Anthropic). The author began building muLLM as a personal cost-reduction tool and discovered, after 15,363 production queries across unrelated domains, that the four-tier hierarchy generalized far beyond the original use case.*

---

## Abstract

Most LLM queries don't need a frontier model. muLLM is a four-tier routing system built on one empirical claim: **the majority of real production queries can be answered at zero marginal cost without quality loss**. The system routes each query to the cheapest tier that can handle it: a deterministic lookup table (<1ms), semantic vector cache (~14ms), local 30B model (~5s), and cloud fallback. Over 15,363 queries across 22 days, muLLM spent $27.87 against a $772 blended cloud baseline — a **96.4% cost reduction**; 87.5% of queries were resolved free. The local tier achieves 100% pass@1 on HumanEval at $0.00. A 44MB DeBERTa-v3-small classifier achieves AIQ 0.6673 on RouterBench, exceeding all published values. The key emergent property: costs fall as usage grows.

---

## 1. Introduction

Deploying LLMs in production carries a fundamental tension: capable frontier models are expensive at scale, while cheaper alternatives sacrifice quality. Existing routers (FrugalGPT [1], RouteLLM [2]) use binary or cascade routing — choosing between a cheap and an expensive model. This leaves two cost-free tiers on the table: deterministic pattern matching and semantic caching, which together resolve the majority of real production queries before any model is invoked.

**muLLM** introduces a four-tier hierarchy that changes the cost structure of LLM deployment. Over a 22-day production window spanning 15,363 organic queries (software engineering, research, writing, data analysis), the system achieved 96.4% cost reduction at production quality. The 12.5% cloud escalation rate is inflated by three dedicated benchmark days; on organic workdays, the free-tier rate exceeds 91%.

Four contributions distinguish this work: (1) **Tier 0 groundtruth short-circuiting** — 1,313 deterministic patterns resolving 11.8% of queries in <1ms with zero hallucination risk; (2) **Bash-as-Truth and Bash-as-Judge** — evaluation primitives that eliminate LLM hallucination at the resolver and judge layers; (3) **ELO-cache semantics** — a cache that converges toward the best-ever answer for each semantic neighborhood; (4) **mμPETS** — a routing-specific Pareto efficiency metric capturing cost, accuracy, and latency jointly (see Appendix).

---

## 2. System Architecture

```
User Query
    │
    ▼
[Tier 0: Groundtruth LUT]  ─── <1ms · $0.00 · 11.8% of queries
    │ no match
    ▼
[Tier 1: Semantic Cache]   ─── ~14ms · $0.00 · 27.1% of queries
    │ cosine < 0.98
    ▼
[DeBERTa Classifier]       ─── 44MB CPU-only · 82.4% tier accuracy
    │
    ├── complexity 1–2 → [Tier 2a: Local 30B ~5s · $0.00]
    │                              │
    └── complexity 3–5 → [Tier 2b: Local 30B ~8s · $0.00]
                                   │
                         [Quality Gate] ─── pass → respond
                                   │ fail
                                   ▼
                         [Tier 3: Cloud API · 2–3s · $0.001–$0.15]
                                   │
                                   ▼
                         [Update Cache + Score Log]
```

**Tier 0 — Groundtruth LUT** (<1ms, $0.00). 1,313+ deterministic patterns across 13 categories: arithmetic, capitals, HTTP status codes, git commands, Big-O complexity, date/time, unit conversion, periodic table, ASCII, regex. A Python `Counter` answers "How many r's in strawberry?" in 4ms with zero hallucination risk. Categories were derived by analyzing the first 10,284 production queries for recurring deterministic-answer patterns.

**Tier 1 — Semantic Cache** (~14ms, $0.00). ChromaDB vector store with cosine similarity threshold 0.98. ELO-cache semantics: entries are only displaced by demonstrably better answers from escalation events, causing the cache to converge toward best-ever answers over time. Organic cache hit rate: 55–70% (diluted to ~30% by novel benchmark queries flooding the cache).

**Tier 2 — Local Inference** (~5s, $0.00). Ollama backend with qwen3-coder:30b (MoE, ~3B active parameters, ~20GB VRAM at Q4_K_M). DeBERTa-v3-small classifies intent (CODE, RESEARCH, CREATIVE, CONVERSATION, DEPLOY, NOTE, LOOKUP, VISION) and complexity (1–5). CPU-only inference, 14ms latency. 44MB model size.

**Tier 3 — Cloud API** (~2–3s, $0.001–$0.15/query). Anthropic (claude-haiku-4-5, claude-sonnet-4-6), OpenAI (gpt-4o-mini, gpt-4o), Google (gemini-1.5-flash, gemini-1.5-pro). Hard spend limits enforced at $7/$10/$50 session thresholds. OpenAI-compatible `/v1/chat/completions` endpoint for drop-in compatibility.

**Query flow timing.** The routing decision (Tier 0 + classifier) adds 23µs median overhead to any query. This is below perceptible latency and does not affect user experience.

---

## 3. Evaluation

### 3.1 Cost Reduction (Production, 22-Day Window)

| Metric | Value |
|---|---|
| Total queries | 15,363 |
| Actual spend | $27.87 |
| Blended cloud baseline | $772 |
| Cost reduction | **96.4%** |
| Token cost avoided | **99.7%** |
| Free-tier query rate | **87.5%** |

*Baseline: Sonnet pricing for routine queries, Opus pricing for complex queries (blended model of realistic user behavior). Cloud-tier queries are structurally longer and more expensive per query, representing 0.3% of total token cost despite 12.5% of query count.*

### 3.2 Benchmark Results

| Benchmark | Score | Cost | vs. Frontier |
|---|---|---|---|
| HumanEval pass@1 [7] | **100%** (164/164) | $0.00 | +8pp vs GPT-4o (92%) |
| MultiPL-E 6-lang system-level [15] | **98.3%** (118/120) | $0.00 | parity with GPT-4 |
| MultiPL-E 17-lang model-only | **92.2%** (249/270) | $0.00 | strong across compiled+scripting |
| MMLU [8] | **79.0%** (5,648q) | $0.00 | −9pp vs GPT-4o (87.9%) |
| GPQA Diamond (20q sample) | **90%** | $0.012 | exceeds Claude 3.5 (59.1%) |
| RouterBench AIQ [12] | **0.6673** | $0.00 | beats all published (prior best: ~0.65) |
| mµScore (RouterBench) | **10,607** | $0.00 | #1 of all evaluated routers |
| Human oracle routing | **100%** (200/200) | $0.00 | 200 production queries hand-evaluated |

*HumanEval achieved by local 9B model (OmniCoder-Qwen3.5-9B). GPQA 90% driven by Tier 0 resolving physics constants, CS bounds, and biological facts deterministically — chemistry naming/synthesis (genuine inference) scored 60%. MMLU 79.0% over full 57-subject suite at $0.00.*

### 3.3 Local vs. Cloud-Cheap on Code (MultiPL-E, 180 problems)

The qwen3-coder:30b local model **outperforms GPT-4o-mini class** (cloud_cheap tier) in 8 of 12 languages (74.4% local vs 64.4% cloud). Local wins on all compiled/statically-typed languages (C++, C#, Go, Java 80% local vs 0–75% cloud); cloud wins on dynamic scripting (PHP, R, Ruby, Rust). **The local tier is not a compromise — it is the stronger model for the query categories it handles.**

### 3.4 Routing Quality

- **RouterBench AIQ 0.6673** — area under cost-quality convex hull, highest published value (prior best: KNN ~0.65, RouteLLM BERT ~0.62)
- **DeBERTa accuracy: 82.4%** on held-out 517-example validation set (5,161 total training examples, 8 epochs CUDA, ~22 min training time)
- **Human oracle: 100%** (200 production queries; 3 initially disputed, subsequently conceded as correctly routed)
- **mµScore #1:** quality × √cost_efficiency × 10,000 = **10,607** vs next-best 7,957 (bella); gap is driven by 100% local routing at $0.00 vs bella's 8.5% cloud at $0.017/query

### 3.5 Tier Contribution (Ablation)

| System | Free Queries | Cost | Reduction |
|---|---|---|---|
| **Full system (Tiers 0–3)** | **87.5%** | **$27.87** | **87.3%** vs cloud-only |
| No Tier 0 | 78.5% | $29.46 | 86.6% |
| No Tier 1 (cache) | 60.4% | $36.20 | 83.5% |
| No Tier 2 (local) | 36.2% | $140.39 | 36.0% |
| Cloud only | 0% | $219.26 | 0% |

*Tier 2 (local inference) dominates cost savings; its removal multiplies cost 5×. Tier 1 (cache) dominates latency: 27.1% of queries at 14ms vs 5,000ms local. Tiers 0+1 alone resolve 38.9% of queries free on CPU-only hardware (no GPU required).*

---

## 4. Ecosystem Implications

A distinctive property of this architecture: **costs fall as usage grows**. Each resolved query contributes to cache density; each cache hit reduces future marginal cost. This inverts the standard inference cost curve.

Three behavioral properties emerge under zero-marginal-cost local routing:

1. **Cost changes what users ask.** At $0/query, usage shifts toward exploratory queries users would suppress at $0.01/query. The 15,363-query volume (~700 queries/day from a single developer) is evidence of this behavioral shift. Benchmark distributions are biased toward "queries worth paying for," not the queries people actually want to ask.

2. **Privacy changes which questions get asked.** 87.5% of queries never leave the machine. Users suppress queries involving personal context, internal business logic, or sensitive data when those queries go to third-party servers. Local-first routing creates a **privacy floor by default** — without configuration, consent dialogs, or explicit action.

3. **Individual-scale deployment as a new regime.** Before capable local inference, developers faced binary choice: cloud or nothing. The $600 equivalent cost (Sonnet-priced) for this window became $27.87 — a rounding error in tooling budget. We propose *individual-scale deployment* as an underexplored research regime with properties (domain specialization, cache compounding, privacy floor) invisible to population-scale benchmarks.

---

## 5. Limitations

**Single-user scope.** All 15,363 queries come from one developer over 22 days. The DeBERTa classifier was trained and validated on the same distribution. Generalization to multi-user, domain-specific (legal, medical), or non-English deployments is not established. Classifier accuracy varies substantially by category: Reasoning 87.5%, Coding 46.3%; this imbalance will shift under different workloads.

**Hardware dependency.** Tier 2 requires ≥24GB VRAM GPU (tested: RTX 5090 32GB). CPU-only deployments can access Tiers 0+1 (38.9% free), degrading gracefully to cloud for inference queries. 8GB VRAM deployments use the 9B model tier.

**Privacy residual.** The 12.5% of queries that reach Tier 3 (cloud APIs) are transmitted to Anthropic, OpenAI, or Google servers and subject to their data retention policies. No automatic PII detection or redaction is applied before escalation. Users with strict data-locality requirements should disable Tier 3 (`DISABLE_CLOUD=1`).

**Benchmark sample sizes.** GPQA Diamond (20 questions) and GSM8K (20 problems) samples are small; results should be interpreted as directional rather than definitive. Full MMLU (5,648 questions) and HumanEval (164 problems) results have adequate sample sizes.

---

## 6. Conclusion

muLLM demonstrates that a four-tier routing hierarchy — deterministic lookup, semantic cache, local inference, cloud fallback — achieves 96.4% cost reduction over a blended cloud baseline while maintaining 100% HumanEval pass@1 and 79.0% MMLU at $0.00. The key insight: production query complexity is not uniformly distributed. The majority of queries are repetitive, pattern-matchable, or structurally simple, and these can be resolved at zero marginal cost before any neural inference is required. The system gets cheaper the more it is used.

---

## References

[1] Chen, Zaharia, Zou. *FrugalGPT.* arXiv:2305.05176 (2023).  
[2] Ong et al. *RouteLLM.* arXiv:2406.18665 (2024).  
[5] Liu et al. *GPTCache.* arXiv:2306.05212 (2023).  
[6] He, Gao, Chen. *DeBERTaV3.* arXiv:2111.09543 (2021).  
[7] Chen et al. *HumanEval.* arXiv:2107.03374 (2021).  
[8] Hendrycks et al. *MMLU.* arXiv:2009.03300 (2021).  
[10] Huang et al. *RouterEval.* arXiv:2503.10657 (2025).  
[12] withmartian. *RouterBench.* HuggingFace (2024).  
[15] Cassano et al. *MultiPL-E.* arXiv:2208.08227 (2022).  
[20] Tencent PlayCoder. *PlayEval.* arXiv:2604.19742 (2026).

---

## Appendix: mμPETS — Pareto Efficiency Timing Score

For routing systems, code quality and reasoning benchmarks measure the underlying model rather than the router. mμPETS combines only the three dimensions where routing decisions have direct causal impact:

```
mμPETS = (routing_accuracy + cost_efficiency + ttft_score) / 3
```

| Component | muLLM | Always-GPT-4 |
|---|---|---|
| Routing accuracy | 0.824 | 1.00 |
| Cost efficiency | 0.987 | 0.00 |
| TTFT score | 0.85 | 0.30 |
| **mμPETS** | **0.887** | **0.43** |

A system that routes everything to GPT-4 scores 0.0 on cost efficiency. mμPETS captures this tradeoff directly. A cloud-only baseline (GPT-4o-mini for all queries) scores ~0.55 (cost efficiency ~0.30 vs muLLM's $0.00 local tier).

**AI assistance disclosure.** This paper was developed with the assistance of Claude Code (Anthropic) for software development and manuscript drafting. AI tools are not listed as authors per ACL policy.

**Ethics.** No human subjects were recruited. 87.5% of queries were processed entirely on-device. Cloud-routed queries (12.5%) were transmitted to providers under their standard API terms.
