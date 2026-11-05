"""Verified first-party model catalog, reviewed 2026-11-04.

Sources and rollout limitations: docs/MODELS.md. Prices are USD / million
standard tokens. Long-context rates are applied by standard_cost().
"""

FRONTIER_MODELS = {
    "gpt-6-luna": ("openai", 0.10, 0.50, 1_050_000),
    "gpt-6.1-terra": ("openai", 1.00, 5.00, 1_050_000),
    "gpt-6.1-sol": ("openai", 2.00, 10.00, 1_050_000),
    "gpt-6-astra": ("openai", 10.00, 50.00, 1_050_000),
    "claude-haiku-5-5": ("anthropic", 0.10, 0.50, 1_000_000),
    "claude-sonnet-5-5": ("anthropic", 2.00, 10.00, 1_000_000),
    "claude-opus-5-5": ("anthropic", 4.00, 20.00, 1_000_000),
    "claude-fable-5-1": ("anthropic", 10.00, 50.00, 1_000_000),
}


def catalog() -> dict[str, dict]:
    return {
        model: {"provider": provider, "cost_per_m_input": inp,
                "cost_per_m_output": out, "max_context": context}
        for model, (provider, inp, out, context) in FRONTIER_MODELS.items()
    }


def standard_cost(model: str, pricing: dict, input_tokens: int, output_tokens: int) -> float:
    """Standard uncached cost; never silently omit long-context surcharges."""
    inp, out = pricing["cost_per_m_input"], pricing["cost_per_m_output"]
    if model in FRONTIER_MODELS:
        if model.startswith("gpt-6") and input_tokens > 272_000:
            inp, out = inp * 2, out * 1.5
        elif model == "claude-haiku-5-5" and input_tokens > 100_000:
            inp, out = 0.50, 2.50
    return (input_tokens * inp + output_tokens * out) / 1_000_000
