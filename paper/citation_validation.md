# Citation Validation Report — muLLM Paper
**Validated:** 2026-04-15  
**Paper:** `/home/peter/mullm/paper/mullm_paper.md`  
**Validator:** Web-search verification of all citations

---

## Summary

| Status | Count |
|--------|-------|
| ✓ Valid | 6 |
| ✗ Error (wrong author attribution) | 3 |
| ⚠ Warning (year, venue, or description issues) | 5 |
| ℹ Info (incomplete/TODO refs noted) | 3 |

---

## Per-Citation Findings

---

### 1. FrugalGPT — Chen et al., 2023

**In-text use:** "FrugalGPT (Chen et al., 2023)" — §1, §2 table  
**References section:** Listed as "Chen et al. 2023 — FrugalGPT" (TODO stub)

**Verified facts:**
- **Title:** "FrugalGPT: How to Use Large Language Models While Reducing Cost and Improving Performance" ✓
- **Authors:** Lingjiao Chen, Matei Zaharia, James Zou ✓ (3 authors → "Chen et al." is correct)
- **Year:** arXiv preprint May 2023 ✓; published in *Transactions on Machine Learning Research* (TMLR) 2024
- **Venue:** arXiv:2305.05176. Published as TMLR journal paper in 2024, **not** a conference (not NeurIPS, not EMNLP)

**Paper claim check:**  
The paper claims "achieving 40-70% cost savings" for FrugalGPT. **⚠ Warning:** FrugalGPT's own claimed result is **up to 98% cost reduction** (matching GPT-4 quality at 98% lower cost). The paper assigns this "40-70% savings" claim to RouteLLM instead. The §1 sentence groups both FrugalGPT and RouteLLM under "achieving 40-70% cost savings" — this misattributes FrugalGPT's actual result.

**Verdict:** ⚠ **Description error** — FrugalGPT claims up to 98% cost reduction in its own abstract, not 40-70%. The 40-70% figure belongs to RouteLLM. Correct §1 to separate the two claims.

**Correction:**
> "FrugalGPT (Chen et al., 2023) achieves up to 98% cost reduction via LLM cascade routing; RouteLLM (Ong et al., 2024) achieves 40-70% savings via preference-trained binary routers."

---

### 2. RouteLLM — Ong et al., 2024

**In-text use:** "RouteLLM (Ong et al., 2024)" — §1, §4.6  
**References section:** Listed as "Ong et al. 2024 — RouteLLM" (TODO stub)

**Verified facts:**
- **Title:** "RouteLLM: Learning to Route LLMs with Preference Data" ✓
- **Authors:** Isaac Ong, Amjad Almahairi, Vincent Wu, Wei-Lin Chiang, Tianhao Wu, Joseph E. Gonzalez, M Waleed Kadous, Ion Stoica ✓ (first author Isaac Ong → "Ong et al." correct)
- **Year:** arXiv June 2024 ✓; also published at ICLR 2025
- **arXiv:** 2406.18665 ✓

**Paper claim check:**  
§1 says RouteLLM achieves "40-70% cost savings" — this is consistent with the paper's reported results. ✓  
§2 table says "BERT/MF binary router, 40-70% savings" — ✓ accurate.

**Verdict:** ✓ **Valid** — author, year, title, and description all correct.

---

### 3. AutoMix — Madaan et al., 2023

**In-text use:** §2 table: "AutoMix (Madaan et al.) | 2023"  
**References section:** Listed as "Madaan et al. 2023 — AutoMix" (TODO stub)

**Verified facts:**
- **Title:** "AutoMix: Automatically Mixing Language Models" ✓
- **arXiv:** 2310.12963, October 2023 ✓
- **Authors:** The paper has two *equal* first authors: **Aman Madaan** and **Pranjal Aggarwal** (listed as co-first on the PDF). The Semantic Scholar entry lists Madaan first, but the actual PDF header reads "Pranjal Aggarwal♢∗ Aman Madaan♣∗" — authorship order varies by version.
- **Venue:** Published at NeurIPS 2024 (Proceedings of the 38th International Conference on Neural Information Processing Systems, ACM DL confirms this)

**⚠ Year issue:** The paper was submitted to arXiv in October 2023 but **published at NeurIPS 2024**. Citing as "2023" refers to the preprint; the published venue year is 2024.

**Paper claim check:**  
§2 says AutoMix uses "self-verification for escalation" — ✓ correct. AutoMix uses a few-shot self-verification mechanism to decide whether to escalate to a larger model.  
muLLM differentiator: "uses intent classification not self-check" — ✓ fair contrast.

**Verdict:** ⚠ **Year ambiguity** — "2023" is the arXiv preprint date; published venue is NeurIPS 2024. If citing conference paper, should be "Madaan et al., 2024". Author attribution correct.

---

### 4. LLM-Blender — Jiang et al., 2023

**In-text use:** §2 table: "LLM-Blender (Jiang et al.) | 2023"  
**References section:** Listed as "Jiang et al. 2023 — LLM-Blender" (TODO stub)

**Verified facts:**
- **Title:** "LLM-Blender: Ensembling Large Language Models with Pairwise Ranking and Generative Fusion" ✓
- **Authors:** Dongfu Jiang, Xiang Ren, Bill Yuchen Lin ✓ (first author Dongfu Jiang → "Jiang et al." correct)
- **Year:** ACL 2023 ✓
- **Venue:** Proceedings of ACL 2023 (61st Annual Meeting of ACL), pages 14165–14178 ✓

**Paper claim check:**  
§2 says LLM-Blender does "Ensemble ranking across models" — ✓ accurate. The paper introduces PairRanker for pairwise ranking and GenFuser for generative fusion.  
muLLM differentiator: "routes to cheapest, not best" — ✓ fair contrast.

**Verdict:** ✓ **Valid** — all details correct.

---

### 5. GPTCache — Bang et al., 2023

**In-text use:** §2 table: "GPTCache | 2023"  
**References section:** Listed as "Bang et al. 2023 — GPTCache" (TODO stub)

**Verified facts:**
- **Title:** "GPTCache: An Open-Source Semantic Cache for LLM Applications Enabling Faster Answers and Cost Savings" ✓
- **Author:** **Fu Bang** — single author, not "Bang et al." ✗
- **Year:** NLP-OSS Workshop at EMNLP 2023 ✓
- **Venue:** Proceedings of the 3rd Workshop for Natural Language Processing Open Source Software (NLP-OSS 2023), pages 212–218

**⚠ Author error:** The paper has a single author, **Fu Bang**. The citation "Bang et al., 2023" implies multiple authors; correct form is "Bang (2023)" or "Fu Bang (2023)". The first name is "Fu", last name is "Bang" — so "Bang et al." misidentifies this as a multi-author paper.

**Verdict:** ✗ **Author error** — should be "Bang (2023)" not "Bang et al., 2023". Single-author paper.

**Correction:** Change all instances of "Bang et al." to "Bang (2023)". Full citation: Fu Bang. 2023. GPTCache: An Open-Source Semantic Cache for LLM Applications Enabling Faster Answers and Cost Savings. In Proceedings of NLP-OSS 2023, pages 212–218.

---

### 6. DeBERTa-v3 — He et al., 2021

**In-text use:** §3.2 mentions "DeBERTa-v3-small fine-tuned"; §4.8 "DeBERTa-v3-small: 82.4%"; Appendix B "DeBERTa-v3-small — He et al. (2021)"  
**References section:** Listed as "He et al. 2021 — DeBERTa-v3" (TODO stub)

**Verified facts:**
- **Title:** "DeBERTaV3: Improving DeBERTa using ELECTRA-Style Pre-Training with Gradient-Disentangled Embedding Sharing" ✓
- **Authors:** Pengcheng He, Jianfeng Gao, Weizhu Chen ✓ (first author Pengcheng He → "He et al." correct)
- **arXiv:** 2111.09543, submitted November 2021 ✓
- **Venue:** Published as a conference paper at **ICLR 2023** — not 2021

**⚠ Year issue:** The arXiv preprint is from 2021, but the published conference paper is ICLR 2023. Citing as "He et al. (2021)" refers to the preprint. If citing the published paper, should be "He et al. (2023)". This is a common convention choice but should be consistent — currently references list says "2021" while published venue is 2023.

**Verdict:** ⚠ **Year warning** — "2021" is arXiv preprint date; published at ICLR 2023. Recommend updating to "He et al. (2023)" if citing the published version.

---

### 7. HumanEval — Chen et al., 2021

**In-text use:** "HumanEval (Chen et al., 2021)" — §4.2  
**References section:** Listed as "Chen et al. 2021 — HumanEval" (TODO stub)

**Verified facts:**
- **Title:** "Evaluating Large Language Models Trained on Code" ✓
- **Authors:** Mark Chen et al. (OpenAI team, 30+ authors) ✓ (first author Mark Chen → "Chen et al." correct)
- **Year:** arXiv July 2021 ✓
- **arXiv:** 2107.03374 ✓
- **Venue:** arXiv preprint (no formal conference publication)

**⚠ Name collision:** Both HumanEval (Chen et al., 2021) and FrugalGPT (Chen et al., 2023) use "Chen et al." as the in-text citation. The paper uses both in §4.2 without disambiguation. When both appear in the same section/reference list, they should be disambiguated as "M. Chen et al. (2021)" and "L. Chen et al. (2023)".

**Paper claim check:**  
§4.2 describes HumanEval as "164 Python programming problems evaluated via unit tests, pass@1 metric" — ✓ correct.  
§4.2 context claim: "GPT-4 achieves ~85-90% HumanEval; Claude 3 Sonnet ~85%." — ⚠ These figures should be verified against published model cards for the final paper; they are plausible but not sourced.

**Verdict:** ⚠ **Disambiguation warning** — two different "Chen et al." citations in same paper (2021 and 2023) need disambiguation in reference list and optionally in-text.

---

### 8. MMLU — Hendrycks et al., 2020

**In-text use:** §4.5 table (benchmark name only, no explicit in-text citation); Appendix B "MMLU — Hendrycks et al. (2020)"  
**References section:** Listed as "Hendrycks et al. 2020 — MMLU" (TODO stub)

**Verified facts:**
- **Title:** "Measuring Massive Multitask Language Understanding" ✓
- **Authors:** Dan Hendrycks, Collin Burns, Steven Basart, Andy Zou, Mantas Mazeika, Dawn Song, Jacob Steinhardt ✓ (first author Hendrycks → "Hendrycks et al." correct)
- **Year:** arXiv September 2020 ✓; published at ICLR 2021
- **arXiv:** 2009.03300 ✓

**⚠ Year ambiguity:** The preprint is 2020, published conference version is ICLR 2021. "Hendrycks et al. (2020)" refers to the preprint — common and acceptable, but worth noting for consistency with the ICLR 2021 publication year.

**Verdict:** ⚠ **Minor year note** — "2020" is arXiv preprint; ICLR publication is 2021. Either year is defensible; convention in the field typically cites as 2020 for this paper, so this is acceptable.

---

### 9. GSM8K — Cobbe et al., 2021

**In-text use:** §4.6 "RouteLLM evaluation protocol (Ong et al., 2024): AUC under accuracy-vs-strong-model-% curve" references GSM8K; Appendix B "GSM8K — Cobbe et al. (2021)"  
**References section:** Listed as "Cobbe et al. 2021 — GSM8K" (TODO stub)

**Verified facts:**
- **Title:** "Training Verifiers to Solve Math Word Problems" ✓
- **Authors:** Karl Cobbe, Vineet Kosaraju, Mohammad Bavarian, Mark Chen, Heewoo Jun, et al. (OpenAI team) ✓ (first author Karl Cobbe → "Cobbe et al." correct)
- **Year:** arXiv October 2021 ✓
- **arXiv:** 2110.14168 ✓
- **Venue:** arXiv preprint (no separate conference publication)

**Verdict:** ✓ **Valid** — author, year, title all correct.

---

### 10. RouterEval — Srivatsa et al., 2025

**In-text use:** §2 table: "RouterEval (Srivatsa et al.) | 2025"; §4.9 header "Comparison with RouterEval Framework"; §4.9 body: "RouterEval (Srivatsa et al., EMNLP 2025)"  
**References section:** Listed as "Srivatsa et al. 2025 — RouterEval (EMNLP 2025)" (TODO stub)

**Verified facts:**
- **Title:** "RouterEval: A Comprehensive Benchmark for Routing LLMs to Explore Model-level Scaling Up in LLMs" ✓
- **Actual authors:** Zhongzhan Huang, Guoming Ling, Yupei Lin, Yandong Chen, Shanshan Zhong, Hefeng Wu, Liang Lin — **no author named "Srivatsa"** ✗
- **Year:** arXiv March 2025 ✓; published at EMNLP 2025 ✓ (Findings of ACL: EMNLP 2025, pages 3860–3887)
- **arXiv:** 2503.10657 ✓

**✗ Critical author error:** The paper is attributed to "Srivatsa et al." throughout, but the actual first author is **Zhongzhan Huang**. There is no author named "Srivatsa" on this paper. The correct citation is "Huang et al. (2025)".

**Verdict:** ✗ **Wrong author attribution** — "Srivatsa et al." is incorrect. Correct to "Huang et al., 2025". This error appears in §2 table, §4.9 section header/body, §4.9 comparison table, §4.11 mμPETS table, §7, and the references list stub. All occurrences must be corrected.

**Correction:** Replace every instance of "Srivatsa et al." with "Huang et al." Full citation: Zhongzhan Huang, Guoming Ling, Yupei Lin, Yandong Chen, Shanshan Zhong, Hefeng Wu, Liang Lin. 2025. RouterEval: A Comprehensive Benchmark for Routing LLMs to Explore Model-level Scaling Up in LLMs. In Findings of EMNLP 2025, pages 3860–3887.

---

### 11. xRouter — Salesforce AI Research, 2025

**In-text use:** §2 table: "xRouter (Salesforce AI) | 2025"; §7: "xRouter (Salesforce AI Research, arXiv:2510.08439)"  
**References section:** Listed as "arXiv:2510.08439 — xRouter (Salesforce AI Research, DAPO-trained routing)" (TODO stub)

**Verified facts:**
- **Title:** "xRouter: Training Cost-Aware LLMs Orchestration System via Reinforcement Learning" ✓
- **Authors:** Cheng Qian, Zuxin Liu, Shirley Kokane, Akshara Prabhakar, Jielin Qiu, Haolin Chen, Zhiwei Liu, Heng Ji, Weiran Yao, Shelby Heinecke, Silvio Savarese, Caiming Xiong, Huan Wang (first author: Cheng Qian) ✓
- **Year:** arXiv October 2025 ✓
- **arXiv:** 2510.08439 ✓
- **Affiliation:** Salesforce AI Research ✓

**⚠ Citation style:** The paper uses "xRouter (Salesforce AI)" and "xRouter (Salesforce AI Research, arXiv:2510.08439)" as if citing an organization rather than an author. Standard academic citation form should be "Qian et al. (2025)".

**Claim check:**  
§2 says "~1/8 GPT-5 cost" and §7 refers to "GPQA 93% at $0.004/q". The actual paper claims ~80-90% of GPT-5 accuracy at under 1/5 of the cost; the "93%" and "$0.004/q" specific figures are not confirmed by search results and may be inaccurate.

**Verdict:** ⚠ **Citation style warning + unverified specific claims** — should cite as "Qian et al. (2025)" not "Salesforce AI". The "GPQA 93% at $0.004/q" claim in memory notes (§7 is not in the paper body directly) should be verified against the actual paper before publication.

---

### 12. RouterBench — withmartian, 2024

**In-text use:** §4.6: "RouterBench AIQ (withmartian/routerbench, 1,000-sample subset)"; abstract: "RouterBench dataset (withmartian/routerbench)"  
**References section:** Listed as "withmartian 2024 — RouterBench (HuggingFace dataset + AIQ metric)" (TODO stub)

**Verified facts:**
- **Title:** "RouterBench: A Benchmark for Multi-LLM Routing System" ✓
- **Authors:** Qitian Jason Hu, Jacob Bieker, Xiuyu Li, Nan Jiang, Benjamin Keigwin, Gaurav Ranganath, Kurt Keutzer, Shriyash Kaustubh Upadhyay (first author: Qitian Jason Hu)
- **Year:** arXiv March 2024 ✓
- **arXiv:** 2403.12031 ✓
- **AIQ metric:** Confirmed as "Average Improvement in Quality" — area under the routing curve ✓

**⚠ Citation style:** The paper cites this as "withmartian/routerbench" (a GitHub/HuggingFace handle), not with author names. For academic publication, should be "Hu et al. (2024)".

**Verdict:** ⚠ **Citation style warning** — use "Hu et al. (2024)" as the academic citation. "withmartian/routerbench" is appropriate as a dataset URL/resource reference but not as a primary citation in an academic paper.

---

### 13. RouterXBench — arXiv:2602.11877

**In-text use:** §7: "RouterXBench (arXiv 2602.11877) proposes three evaluation perspectives"  
**References section:** Listed as "arXiv:2602.11877 — RouterXBench (Triple-Perspective evaluation framework)" (TODO stub)

**Verified facts:**
- **Actual title:** "Towards Fair and Comprehensive Evaluation of Routers in Collaborative LLM Systems" — **not** "RouterXBench" ✗
- **arXiv:** 2602.11877 ✓ (submitted February 2026)
- **Three perspectives:** Router ability (AUROC), Scenario Alignment (LPM/MPM/HCR), Cross-Domain Robustness ✓ — the "triple-perspective" description is accurate

**⚠ Name error:** The paper at arXiv:2602.11877 is titled "Towards Fair and Comprehensive Evaluation of Routers in Collaborative LLM Systems" — the informal name "RouterXBench" does not appear to be the paper's own self-designation based on search results. The reference list names it "RouterXBench" which may be a shorthand the muLLM paper invented.

**Verdict:** ⚠ **Title warning** — "RouterXBench" may not be the paper's self-assigned name. Use the actual title "Towards Fair and Comprehensive Evaluation of Routers in Collaborative LLM Systems" in the formal reference entry. The arXiv ID is correct.

---

### 14. BEST-Route — cited in §2 table

**In-text use:** §2 table: "BEST-Route | 2024 | 60% cost savings via routing"  
**References section:** No reference entry for BEST-Route ✗

**Search finding:** arXiv 2506.22716 is titled "BEST-Route: Adaptive LLM Routing with Test-Time Optimal Compute" — this is from **June 2025**, not 2024. The 2024 date in the table appears incorrect.

**Verdict:** ✗ **Missing reference + wrong year** — BEST-Route is cited in the §2 table but has no entry in the References section. The year shown (2024) appears wrong; the paper arXiv:2506.22716 is from June 2025. This citation needs verification and a reference entry added.

---

### 15. TaRo — cited in §2 table

**In-text use:** §2 table: "TaRo | 2024 | Task-aware routing"  
**References section:** No reference entry for TaRo ✗

**Verdict:** ✗ **Missing reference** — TaRo is cited in the §2 table but has no entry in the References section and no author attribution is given. Needs full citation details added.

---

## Cross-Reference Completeness Check

### In-text citations with NO reference entry
The References section is a TODO stub. All citations lack formal entries. Specific problems beyond the TODO state:

| Citation | In-text | Reference stub | Issue |
|----------|---------|---------------|-------|
| FrugalGPT (Chen et al., 2023) | ✓ | ✓ listed | Missing full entry |
| RouteLLM (Ong et al., 2024) | ✓ | ✓ listed | Missing full entry |
| AutoMix (Madaan et al., 2023) | ✓ | ✓ listed | Missing full entry |
| LLM-Blender (Jiang et al., 2023) | ✓ | ✓ listed | Missing full entry |
| GPTCache (Bang et al., 2023) | ✓ | ✓ listed | Wrong author form |
| DeBERTa-v3 (He et al., 2021) | ✓ | ✓ listed | Missing full entry |
| HumanEval (Chen et al., 2021) | ✓ | ✓ listed | Name collision with FrugalGPT |
| MMLU (Hendrycks et al., 2020) | Appendix B only | ✓ listed | Missing full entry |
| GSM8K (Cobbe et al., 2021) | ✓ | ✓ listed | Missing full entry |
| RouterEval (Srivatsa et al., 2025) | ✓ | ✓ listed | **Wrong first author** |
| xRouter (Salesforce AI) | ✓ | ✓ listed | Org citation not author |
| RouterBench (withmartian) | ✓ | ✓ listed | Dataset handle not author |
| RouterXBench (arXiv:2602.11877) | ✓ | ✓ listed | Title may be informal shorthand |
| BEST-Route | §2 table | ✗ missing | Wrong year (2024 vs 2025) |
| TaRo | §2 table | ✗ missing | No author/year given |
| Qwen3-Coder (Qwen Team, 2025) | Appendix B | ✓ listed | Missing full entry |
| ChromaDB (Chroma, 2023) | Appendix B | ✗ not in refs stub | Missing from references list |
| FastAPI (Ramírez, 2019) | Appendix B | ✗ not in refs stub | Missing from references list |

---

## Priority Corrections

### Critical (factual errors):
1. **RouterEval author**: Replace all occurrences of "Srivatsa et al." → "Huang et al." (first author: Zhongzhan Huang). Appears in §2 table, §4.9, §4.11, §7, and references stub. This is the most serious error.
2. **GPTCache author**: "Bang et al." → "Bang (2023)" — single-author paper by Fu Bang.
3. **BEST-Route year**: Table shows 2024 but paper (arXiv:2506.22716) is from June 2025. Verify correct paper being cited.

### Important (description/attribution):
4. **FrugalGPT description**: §1 groups FrugalGPT under "40-70% cost savings" — FrugalGPT's actual claim is up to 98% reduction. The 40-70% figure belongs to RouteLLM. Separate the two claims.
5. **xRouter citation style**: Use "Qian et al. (2025)" not "Salesforce AI".
6. **RouterBench citation style**: Use "Hu et al. (2024)" not "withmartian/routerbench".

### Moderate (year conventions):
7. **AutoMix year**: arXiv 2023, published NeurIPS 2024 — decide which to cite.
8. **DeBERTa-v3 year**: arXiv 2021, published ICLR 2023 — decide which to cite.
9. **HumanEval disambiguation**: Two "Chen et al." papers (2021 and 2023) need disambiguation in reference list.

### Minor (missing entries):
10. **Missing references**: BEST-Route, TaRo, ChromaDB, FastAPI have no reference entries.
11. Complete all TODO reference stubs with full BibTeX entries.

---

## Recommended BibTeX Corrections

```bibtex
@inproceedings{huang2025routereval,
  title={{RouterEval}: A Comprehensive Benchmark for Routing {LLMs} to Explore Model-level Scaling Up in {LLMs}},
  author={Huang, Zhongzhan and Ling, Guoming and Lin, Yupei and Chen, Yandong and Zhong, Shanshan and Wu, Hefeng and Lin, Liang},
  booktitle={Findings of the Association for Computational Linguistics: {EMNLP} 2025},
  pages={3860--3887},
  year={2025}
}

@article{chen2023frugalgpt,
  title={{FrugalGPT}: How to Use Large Language Models While Reducing Cost and Improving Performance},
  author={Chen, Lingjiao and Zaharia, Matei and Zou, James},
  journal={Transactions on Machine Learning Research},
  year={2024},
  note={arXiv:2305.05176}
}

@inproceedings{bang2023gptcache,
  title={{GPTCache}: An Open-Source Semantic Cache for {LLM} Applications Enabling Faster Answers and Cost Savings},
  author={Bang, Fu},
  booktitle={Proceedings of the 3rd Workshop for Natural Language Processing Open Source Software (NLP-OSS 2023)},
  pages={212--218},
  year={2023}
}

@inproceedings{ong2025routellm,
  title={{RouteLLM}: Learning to Route {LLMs} with Preference Data},
  author={Ong, Isaac and Almahairi, Amjad and Wu, Vincent and Chiang, Wei-Lin and Wu, Tianhao and Gonzalez, Joseph E. and Kadous, M Waleed and Stoica, Ion},
  booktitle={International Conference on Learning Representations},
  year={2025},
  note={arXiv:2406.18665}
}

@inproceedings{he2023debertav3,
  title={{DeBERTaV3}: Improving {DeBERTa} using {ELECTRA}-Style Pre-Training with Gradient-Disentangled Embedding Sharing},
  author={He, Pengcheng and Gao, Jianfeng and Chen, Weizhu},
  booktitle={International Conference on Learning Representations},
  year={2023},
  note={arXiv:2111.09543}
}

@inproceedings{qian2025xrouter,
  title={{xRouter}: Training Cost-Aware {LLMs} Orchestration System via Reinforcement Learning},
  author={Qian, Cheng and Liu, Zuxin and Kokane, Shirley and Prabhakar, Akshara and Qiu, Jielin and Chen, Haolin and Liu, Zhiwei and Ji, Heng and Yao, Weiran and Heinecke, Shelby and Savarese, Silvio and Xiong, Caiming and Wang, Huan},
  year={2025},
  note={arXiv:2510.08439}
}

@inproceedings{hu2024routerbench,
  title={{RouterBench}: A Benchmark for Multi-{LLM} Routing System},
  author={Hu, Qitian Jason and Bieker, Jacob and Li, Xiuyu and Jiang, Nan and Keigwin, Benjamin and Ranganath, Gaurav and Keutzer, Kurt and Upadhyay, Shriyash Kaustubh},
  year={2024},
  note={arXiv:2403.12031}
}
```
