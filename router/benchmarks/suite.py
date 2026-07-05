"""
Combined benchmark suite — runs all benchmarks and returns a unified report.

Includes 9 internal benchmarks + RouteBench (LMSYS/Berkeley) + MMLU + LiveCodeBench + IFEval.
"""

from __future__ import annotations

import time
from typing import Any

from router.benchmarks.bbhard import run_bbhard  # noqa: E402
from router.benchmarks.bigcodebench import run_bigcodebench  # noqa: E402
from router.benchmarks.cruxeval import run_cruxeval  # noqa: E402
from router.benchmarks.gamedevbench import run_gamedevbench  # noqa: E402
from router.benchmarks.gpqa import run_gpqa  # noqa: E402
from router.benchmarks.gsm8k import run_gsm8k  # noqa: E402
from router.benchmarks.ifeval import run_ifeval  # noqa: E402
from router.benchmarks.livecodebench import run_livecodebench  # noqa: E402
from router.benchmarks.multipl_e import run_multipl_e
from router.benchmarks.routebench import run_routebench  # noqa: E402
from router.benchmarks.runner import (
    MULLM_DEFAULT,
    run_cache,
    run_humaneval,
    run_latency,
    run_mbpp,
    run_routing_accuracy,
)


def _composite_score(
    he: dict,
    mbpp: dict,
    routing: dict,
    latency: dict,
    cache: dict,
    gamedev: dict,
    mpe: dict | None = None,
    rb: dict | None = None,
    gsm8k: dict | None = None,
    mmlu: dict | None = None,
    ifeval: dict | None = None,
) -> float:
    """
    Weighted composite 'muLLM score' in [0, 100]:
      - HumanEval pass@1                : 16%  (was 17%)
      - MBPP pass@1                     : 11%  (was 12%)
      - MultiPL-E pass@1                :  7%  (was 8%)
      - Routing accuracy (internal)     : 13%  (was 14%)
      - RouteBench (LMSYS) accuracy     :  4%
      - Latency score                   : 13%  (was 14%, inverted: lower is better, cap at 5s)
      - Cache hit rate                  :  9%
      - GameDevBench avg score          :  4%
      - GSM8K accuracy                  :  8%  (grade-school math chain-of-thought)
      - MMLU accuracy                   :  8%  (was 10%, knowledge breadth, 57 subjects)
      - IFEval instruction following    :  7%  (new — instruction constraint satisfaction)
      Total                             : 100%
    """
    he_score = he.get("pass_at_1", 0.0)
    mbpp_score = mbpp.get("pass_at_1", 0.0)
    routing_score = routing.get("accuracy", 0.0)
    mpe_score = (mpe or {}).get("pass_at_1", 0.0)
    rb_score = (rb or {}).get("accuracy", 0.0)
    gsm8k_score = (gsm8k or {}).get("accuracy", 0.0)
    mmlu_score = (mmlu or {}).get("accuracy", 0.0)
    # IFEval: use prompt_accuracy (all constraints satisfied for a prompt)
    ifeval_score = (ifeval or {}).get("prompt_accuracy", 0.0)

    # Latency: 0ms → 1.0, 5000ms → 0.0, linear
    med_ms = latency.get("total_median_ms", 5000.0)
    lat_score = max(0.0, 1.0 - med_ms / 5000.0)

    cache_score = cache.get("hit_rate", 0.0)
    gamedev_score = gamedev.get("avg_score", 0.0)

    composite = (
        he_score * 0.16
        + mbpp_score * 0.11
        + mpe_score * 0.07
        + routing_score * 0.13
        + rb_score * 0.04
        + lat_score * 0.13
        + cache_score * 0.09
        + gamedev_score * 0.04
        + gsm8k_score * 0.08
        + mmlu_score * 0.08
        + ifeval_score * 0.07
    )
    return round(composite * 100, 2)


async def run_all(
    mullm_url: str = MULLM_DEFAULT,
    force_tier: str = "",
    humaneval_limit: int = 20,
    mbpp_limit: int = 10,
    gamedev_limit: int = 20,
    multipl_e_limit: int = 20,
    routebench_limit: int = 200,
    gsm8k_limit: int = 100,
    mmlu_limit: int = 50,
    livecodebench_limit: int = 20,
    ifeval_limit: int = 20,
    bigcodebench_limit: int = 50,
    bbhard_limit: int = 20,
    gpqa_limit: int = 20,
    cruxeval_limit: int = 20,
) -> dict[str, Any]:
    """Run all 16 benchmarks sequentially to avoid overwhelming the local model."""
    started_at = time.time()

    he = await run_humaneval(mullm_url, force_tier, humaneval_limit)
    mbpp = await run_mbpp(mullm_url, force_tier, mbpp_limit)
    mpe = await run_multipl_e(mullm_url, force_tier, multipl_e_limit)
    routing = await run_routing_accuracy(mullm_url)
    lat = await run_latency(mullm_url)
    cache = await run_cache(mullm_url)
    gamedev = await run_gamedevbench(mullm_url, force_tier, gamedev_limit)

    # RouteBench (LMSYS/Berkeley) — external router quality benchmark ($0)
    try:
        rb_raw = await run_routebench(mullm_url, limit=routebench_limit, concurrency=10)
        # Strip per_prompt_results to keep suite result manageable
        rb = {k: v for k, v in rb_raw.items() if k != "per_prompt_results"}
    except FileNotFoundError:
        # Prompts file not yet fetched — skip gracefully
        rb = {"accuracy": 0.0, "total": 0, "error": "prompts not fetched"}
    except Exception as exc:
        rb = {"accuracy": 0.0, "total": 0, "error": str(exc)[:200]}

    # GSM8K — grade-school math with chain-of-thought reasoning
    try:
        gsm8k = await run_gsm8k(mullm_url, limit=gsm8k_limit)
    except FileNotFoundError:
        # Problems not yet fetched — skip gracefully
        gsm8k = {"accuracy": 0.0, "total": 0, "error": "problems not fetched — run s34-fetch-gsm8k.sh"}
    except Exception as exc:
        gsm8k = {"accuracy": 0.0, "total": 0, "error": str(exc)[:200]}

    # MMLU — knowledge breadth across 57 subjects
    try:
        from router.benchmarks.mmlu import run_mmlu

        mmlu_raw = await run_mmlu(mullm_url, limit=mmlu_limit)
        # Drop per-question results to keep suite payload manageable
        mmlu = {k: v for k, v in mmlu_raw.items() if k != "results"}
    except FileNotFoundError:
        # Problems not yet fetched — skip gracefully
        mmlu = {"accuracy": 0.0, "total": 0, "error": "problems not fetched — run s34-fetch-mmlu.sh"}
    except Exception as exc:
        mmlu = {"accuracy": 0.0, "total": 0, "error": str(exc)[:200]}

    # LiveCodeBench — contamination-free coding from recent contests
    try:
        lcb_raw = await run_livecodebench(mullm_url, limit=livecodebench_limit, force_tier=force_tier)
        # Drop per-problem results to keep suite payload manageable
        lcb = {k: v for k, v in lcb_raw.items() if k != "results"}
    except FileNotFoundError:
        lcb = {"pass_at_1": 0.0, "total": 0, "error": "problems not fetched — run s34-fetch-livecodebench.sh"}
    except Exception as exc:
        lcb = {"pass_at_1": 0.0, "total": 0, "error": str(exc)[:200]}

    # IFEval — instruction following evaluation (word counts, keywords, format, etc.)
    try:
        ife_raw = await run_ifeval(mullm_url, limit=ifeval_limit, concurrency=3)
        # Strip per_prompt_results to keep suite result manageable
        ife = {k: v for k, v in ife_raw.items() if k != "per_prompt_results"}
    except FileNotFoundError:
        # Problems not yet fetched — skip gracefully
        ife = {"prompt_accuracy": 0.0, "total_prompts": 0, "error": "problems not fetched — run s34-fetch-ifeval.sh"}
    except Exception as exc:
        ife = {"prompt_accuracy": 0.0, "total_prompts": 0, "error": str(exc)[:200]}

    # BigCodeBench — practical real-world Python coding (50 problems)
    try:
        bcb_raw = await run_bigcodebench(mullm_url, limit=bigcodebench_limit, force_tier=force_tier)
        bcb = {k: v for k, v in bcb_raw.items() if k != "results"}
    except Exception as exc:
        bcb = {"accuracy": 0.0, "correct": 0, "total": 0, "error": str(exc)[:200]}

    # BIG-Bench Hard — hard reasoning (causal, logical, arithmetic, date, shuffled objects)
    try:
        bbh_raw = await run_bbhard(mullm_url, limit=bbhard_limit, force_tier=force_tier)
        bbh = {k: v for k, v in bbh_raw.items() if k != "results"}
    except Exception as exc:
        bbh = {"accuracy": 0.0, "correct": 0, "total": 0, "error": str(exc)[:200]}

    # GPQA — graduate-level science questions (chemistry, biology, physics, CS theory)
    try:
        gpqa_raw = await run_gpqa(mullm_url, limit=gpqa_limit, force_tier=force_tier)
        gpqa = {k: v for k, v in gpqa_raw.items() if k != "results"}
    except Exception as exc:
        gpqa = {"accuracy": 0.0, "correct": 0, "total": 0, "error": str(exc)[:200]}

    # CRUXEval — code reasoning (input→output and output→input)
    try:
        crux_raw = await run_cruxeval(mullm_url, limit=cruxeval_limit, force_tier=force_tier)
        crux = {k: v for k, v in crux_raw.items() if k != "results"}
    except Exception as exc:
        crux = {"accuracy": 0.0, "correct": 0, "total": 0, "error": str(exc)[:200]}

    score = _composite_score(he, mbpp, routing, lat, cache, gamedev, mpe, rb, gsm8k, mmlu, ife)

    return {
        "mullm_score": score,
        "elapsed_s": round(time.time() - started_at, 1),
        "humaneval": he,
        "mbpp": mbpp,
        "multipl_e": mpe,
        "routing": routing,
        "latency": lat,
        "cache": cache,
        "gamedev": gamedev,
        "routebench_lmsys": rb,
        "gsm8k": gsm8k,
        "mmlu": mmlu,
        "livecodebench": lcb,
        "ifeval": ife,
        "bigcodebench": bcb,
        "bbhard": bbh,
        "gpqa": gpqa,
        "cruxeval": crux,
        "summary": {
            "humaneval_pass_at_1_pct": round(he.get("pass_at_1", 0) * 100, 1),
            "mbpp_pass_at_1_pct": round(mbpp.get("pass_at_1", 0) * 100, 1),
            "multipl_e_pass_at_1_pct": round(mpe.get("pass_at_1", 0) * 100, 1),
            "routing_accuracy_pct": round(routing.get("accuracy", 0) * 100, 1),
            "routebench_lmsys_accuracy_pct": round(rb.get("accuracy", 0) * 100, 1),
            "latency_median_ms": lat.get("total_median_ms", 0),
            "latency_p95_ms": lat.get("total_p95_ms", 0),
            "cache_hit_rate_pct": round(cache.get("hit_rate", 0) * 100, 1),
            "gamedev_pass_rate_pct": round(gamedev.get("pass_rate", 0) * 100, 1),
            "gamedev_avg_score": gamedev.get("avg_score", 0),
            "gsm8k_accuracy_pct": round(gsm8k.get("accuracy", 0) * 100, 1),
            "gsm8k_local_pct": gsm8k.get("local_pct", 0),
            "mmlu_accuracy_pct": round(mmlu.get("accuracy", 0) * 100, 1),
            "mmlu_cost_savings_pct": mmlu.get("cost_savings_pct", 0.0),
            "livecodebench_pass_at_1_pct": round(lcb.get("pass_at_1", 0) * 100, 1),
            "ifeval_prompt_accuracy_pct": round(ife.get("prompt_accuracy", 0) * 100, 1),
            "ifeval_instruction_accuracy_pct": round(ife.get("instruction_accuracy", 0) * 100, 1),
            "bigcodebench_accuracy_pct": round(bcb.get("accuracy", 0) * 100, 1),
            "bbhard_accuracy_pct": round(bbh.get("accuracy", 0) * 100, 1),
            "gpqa_accuracy_pct": round(gpqa.get("accuracy", 0) * 100, 1),
            "cruxeval_accuracy_pct": round(crux.get("accuracy", 0) * 100, 1),
            "cruxeval_i2o_accuracy_pct": round(crux.get("i2o_accuracy", 0) * 100, 1),
            "cruxeval_o2i_accuracy_pct": round(crux.get("o2i_accuracy", 0) * 100, 1),
            "mullm_score": score,
        },
    }
