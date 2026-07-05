# Theme 2 Framing — "From Models to Systems and Ecosystems"
# ~400 words to add to §5 (or as §5.0 "Ecosystem Implications")
# Raw bullets + candidate sentences. Mix, cut, and write in your own voice.

---

## The Research Question This Section Must Answer

EMNLP Theme 2 asks: "how do people, organizations, and communities **use and interact** with language technology?" — not just "does the system work?"

The section needs to shift from "here is a system that reduces costs" to "here is evidence about a new way individuals interact with LLMs, and what that changes."

---

## Angle 1 — The Individual Developer as a New Deployment Tier

Before affordable local inference (~2024), the deployment options were binary: pay cloud prices or don't deploy. muLLM represents a third path — a zero-marginal-cost local tier that makes individual-scale deployment economically viable for the first time.

**Candidate sentences:**
- "Prior to capable local inference, individual developers faced a binary choice: pay production cloud rates for every query, or self-censor LLM usage to stay within a budget. muLLM's local-first hierarchy changes this calculus: the free tier is now the *default*, not a fallback."
- "The 15,363-query production window represents a query volume that would have cost approximately $600 at Sonnet rates — a figure that would deter sustained personal deployment. At $27.87 actual cost, it becomes a rounding error in a developer's tooling budget."
- "We propose 'individual-scale deployment' as an underexplored research regime: single-user, sustained, domain-specific workloads where cache hit rates compound and classifier accuracy specializes over time — properties invisible to population-scale benchmark evaluation."

---

## Angle 2 — Cost Changes What People Ask

When queries are free, usage patterns change. Users iterate, ask "dumb" questions they'd suppress at $0.01/query, and use the system as a scratchpad rather than a deliberate tool.

**Candidate sentences:**
- "An anecdotal but observable effect of $0 routing: the query distribution shifts toward exploratory, low-stakes queries that users suppress when each interaction has a visible cost. The 15,363-query volume from a single developer over 22 days — roughly 700 queries/day — is itself evidence of this behavioral shift."
- "Cost-per-query creates a selection bias in how people interact with LLMs: users mentally filter queries through 'is this worth paying for?' Local-first routing removes that filter. The resulting query distribution is noisier, more repetitive, and more representative of genuine cognitive workload than the carefully crafted benchmark prompts that dominate evaluation datasets."
- "This has a direct implication for ecosystem design: systems evaluated on curated benchmark distributions may be optimized for queries users *would send if paying*, not queries users *actually want to send*."

---

## Angle 3 — Privacy as an Interaction-Shaping Force

87.5% of queries never leave the machine. This changes which queries people will actually ask.

**Candidate sentences:**
- "Privacy is not merely a compliance property — it is an interaction design property. Users suppress queries involving personal context, internal business logic, or sensitive data when those queries will be transmitted to third-party servers. A system that resolves 87.5% of queries locally changes *which questions get asked*, not just how cheaply they are answered."
- "The local-first architecture creates a privacy floor by default: the majority of queries are processed on-device without configuration, consent dialogs, or explicit user action. This shifts the burden of privacy from opt-in to opt-out."
- "We observe that query categories with the highest groundtruth hit rates — date/time, file operations, arithmetic — are also among the categories most frequently involving personal context (calendar events, local file paths, personal finances). The colocation of high-sensitivity categories with the zero-egress tier is not incidental."

---

## Angle 4 — Compounding as a New Ecosystem Property

LLM systems typically scale *cost* with usage. muLLM scales *efficiency* with usage. This inverts the standard cost curve.

**Candidate sentences:**
- "A distinctive property of the muLLM architecture is that it inverts the standard cost curve: usage increases efficiency rather than cost. Each resolved query contributes to cache density; each cache hit reduces future marginal cost. This compounding dynamic has no analogue in stateless inference systems."
- "At the ecosystem level, this suggests a new class of 'personal infrastructure' where an individual's deployed LLM system becomes progressively more efficient and domain-specialized over time — accumulating a semantic model of the user's recurring queries — without requiring retraining, fine-tuning, or centralized data collection."
- "The ELO-cache mechanism (§5.2) extends this compounding to answer quality: cached entries are displaced only by demonstrably better answers, causing the system to converge toward an individually-calibrated knowledge store across model generations."

---

## Suggested 400-Word Structure

**Para 1 (~80 words):** Individual-scale deployment as a new regime. The binary choice was cloud-or-nothing; the four-tier hierarchy creates a third path. Use the $600 vs $27.87 figure. Name it "individual-scale deployment."

**Para 2 (~80 words):** Cost changes behavior. At $0, usage patterns shift toward exploratory queries. The 700 queries/day volume is evidence. Benchmark distributions are biased toward "queries worth paying for."

**Para 3 (~80 words):** Privacy as interaction design. 87.5% local egress changes which questions get asked. Personal context gets unsuppressed. Shift from opt-in to opt-out privacy.

**Para 4 (~80 words):** Compounding as the distinguishing ecosystem property. Unlike stateless inference, this system gets cheaper and better with use. ELO-cache accumulates best-ever answers. Name "personal infrastructure" as a new category.

**Para 5 (~80 words):** What this means for ecosystem research. Individual-scale deployment is understudied. Almost all systems research assumes enterprise or population scale. The distinct properties here (domain specialization, compounding, privacy floor, cost inversion) suggest it deserves its own study. Point at future work.
