"""WITH RICE / powerup mode — parallel top-model fan-out with marshal synthesis.

Fires the strongest configured model from each major provider in parallel,
then has a marshal model (Claude Sonnet) synthesize the single best answer.
Cost-optimization is deliberately bypassed; callers must confirm the spend
first (see the /query handler's powerup_needs_confirmation flow).

The Anthropic slot follows ``settings.cloud_power_model_anthropic``, which the
/setup ``fable_top_tier`` toggle switches between Claude Fable 5 (default in
0.9) and Claude Opus (pre-0.9 behavior).
"""

from __future__ import annotations

import asyncio
import hashlib
import time

import structlog

from router.config import settings
from router.models import PipelineResult, QueryRequest, TierLabel

log = structlog.get_logger("mullm.powerup")

_MARSHAL = ("anthropic", "claude-sonnet")

_MARSHAL_CODE = (
    "You are a marshal synthesizing code solutions from several frontier models. "
    "Select the BEST solution by: (1) correctness — does it actually solve the task? "
    "(2) edge-case handling, (3) clean idiomatic code, (4) prefer defensive when they disagree. "
    "Output ONLY the final code/answer — no preamble, no 'Model X said' commentary."
)
_MARSHAL_REASONING = (
    "You are a marshal synthesizing analyses from several frontier models. "
    "Build the STRONGEST answer by: (1) identify what each model got right that others missed, "
    "(2) resolve contradictions by choosing the better-reasoned position, "
    "(3) combine complementary insights. "
    "Output a single coherent answer — integrate the best of all three, don't just pick one winner."
)

_CODE_MARKERS = ("def ", "function ", "class ", "```python", "```js", "implement ", "write a program")


def powerup_models() -> list[tuple[str, str]]:
    """The (provider, model) trio for the current configuration."""
    return [
        ("anthropic", settings.cloud_power_model_anthropic),
        ("openai", settings.cloud_power_model_openai),
        ("google", settings.cloud_power_model_google),
    ]


def estimated_cost() -> float:
    """Rough per-query estimate for the confirmation dialog (~1.5k in / 1k out per model)."""
    from router.config import CLOUD_MODEL_PRICING
    from router.cloud import MODEL_IDS

    total = 0.0
    for _provider, model in powerup_models() + [_MARSHAL]:
        p = CLOUD_MODEL_PRICING.get(MODEL_IDS.get(model, model), {})
        total += (1500 * p.get("cost_per_m_input", 3.0) + 1000 * p.get("cost_per_m_output", 15.0)) / 1_000_000
    return round(total, 4)


async def powerup_pipeline(req: QueryRequest, pipeline_start: float) -> PipelineResult:
    """Fire the top model of each provider in parallel, marshal-synthesize the best response."""
    from router.cloud import execute_cloud, is_configured
    from router.realtime import get_system_date_context, try_resolve_identity, try_resolve_locally

    models = powerup_models()
    log.info("powerup_start", models=[m for _, m in models])

    # Groundtruth bypass — no need to blast three cloud models for "what is 2+2".
    gt = try_resolve_identity(req.content) or try_resolve_locally(req.content)
    if gt:
        elapsed = (time.perf_counter() - pipeline_start) * 1000
        return PipelineResult(
            response=gt,
            tier=TierLabel.GROUNDTRUTH,
            model_used="realtime",
            latency_ms=round(elapsed, 1),
            cost=0.0,
            tokens_used=0,
            session_id=req.session_id,
        )

    system_prompt = f"You are a helpful assistant.\n{get_system_date_context()}"

    history_prefix = ""
    if req.history:
        parts = []
        for msg in req.history[-6:]:
            role, content = msg.get("role", "user"), msg.get("content", "")
            if role in ("user", "assistant") and content:
                parts.append(f"{'User' if role == 'user' else 'Assistant'}: {content[:2000]}")
        if parts:
            history_prefix = "Previous conversation:\n" + "\n".join(parts) + "\n\nCurrent question: "
    full_prompt = history_prefix + req.content

    async def _call_one(provider: str, model_name: str) -> dict:
        try:
            if not is_configured(provider):
                return {"ok": False, "model": model_name, "error": f"{provider} not configured"}
            result = await execute_cloud(
                prompt=full_prompt,
                system=system_prompt,
                model_name=model_name,
                provider=provider,
            )
            return {
                "ok": True,
                "model": model_name,
                "provider": provider,
                "text": result["text"],
                "cost": result["cost"],
                "tokens": result["tokens_in"] + result["tokens_out"],
            }
        except Exception as exc:
            log.warning("powerup_model_failed", model=model_name, error=str(exc)[:120])
            return {"ok": False, "model": model_name, "error": str(exc)[:120]}

    results = await asyncio.gather(*[_call_one(p, m) for p, m in models])
    ok_results = [r for r in results if r["ok"]]

    if not ok_results:
        failed = [r.get("error", "unknown") for r in results]
        raise RuntimeError(f"powerup_all_failed: {failed}")

    total_cost = sum(r["cost"] for r in ok_results)
    intent_id = f"pw-{hashlib.md5(req.content.encode()).hexdigest()[:8]}"  # noqa: S324

    if len(ok_results) == 1:
        r = ok_results[0]
        elapsed = (time.perf_counter() - pipeline_start) * 1000
        return PipelineResult(
            response=r["text"],
            tier=TierLabel.CLOUD_POWER,
            model_used=r["model"],
            latency_ms=round(elapsed, 1),
            cost=total_cost,
            tokens_used=r["tokens"],
            session_id=req.session_id,
        )

    marshal_input = f"Question: {req.content}\n\n"
    for i, r in enumerate(ok_results, 1):
        marshal_input += f"--- Answer {i} ({r['model']}) ---\n{r['text'][:3000]}\n\n"
    marshal_input += "Synthesize the single best answer from the above. Output ONLY the answer."

    tokens_used = sum(r["tokens"] for r in ok_results)
    try:
        mp, mm = _MARSHAL
        is_code = any(kw in req.content.lower() for kw in _CODE_MARKERS)
        marshal_sys = _MARSHAL_CODE if is_code else _MARSHAL_REASONING
        marshal_result = await execute_cloud(
            prompt=marshal_input, system=marshal_sys, model_name=mm, provider=mp,
        )
        raw = marshal_result["text"]
        final_text = raw
        if raw.strip().startswith("```"):
            # Marshal echoed a fenced block from its inputs — unwrap it.
            stripped = raw.strip()
            body = stripped.split("\n", 1)[1] if "\n" in stripped else stripped
            final_text = body.rsplit("```", 1)[0] if body.rstrip().endswith("```") or "```" in body else body
        total_cost += marshal_result["cost"]
        tokens_used += marshal_result["tokens_in"] + marshal_result["tokens_out"]
        model_label = f"powerup({'+'.join(r['model'] for r in ok_results)}→{mm})"
    except Exception as exc:
        log.warning("powerup_marshal_failed", error=str(exc)[:120])
        best = max(ok_results, key=lambda r: r["tokens"])
        final_text = best["text"]
        model_label = f"powerup-fallback({best['model']})"

    elapsed = (time.perf_counter() - pipeline_start) * 1000
    log.info("powerup_complete", cost=total_cost, latency_ms=round(elapsed, 1),
             models_ok=len(ok_results), intent_id=intent_id)

    return PipelineResult(
        response=final_text,
        tier=TierLabel.CLOUD_POWER,
        model_used=model_label,
        latency_ms=round(elapsed, 1),
        cost=total_cost,
        tokens_used=tokens_used,
        session_id=req.session_id,
    )
