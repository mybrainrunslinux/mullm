"""First-party model catalog, documentation reviewed 2026-11-05.

Sources and rollout limitations: docs/MODELS.md. Prices are USD / million
standard tokens. Long-context rates are applied by standard_cost().
"""
from datetime import datetime, timezone

FRONTIER_MODELS = {
    "gpt-6-luna": ("openai", 0.10, 0.50, 1_050_000),
    "gpt-6.1-terra": ("openai", 1.00, 5.00, 1_050_000),
    "gpt-6.1-sol": ("openai", 2.00, 10.00, 1_050_000),
    "gpt-6-astra": ("openai", 10.00, 50.00, 1_050_000),
    "claude-haiku-5-5": ("anthropic", 0.10, 0.50, 1_000_000),
    "claude-sonnet-5-5": ("anthropic", 2.00, 10.00, 1_000_000),
    "claude-opus-5-5": ("anthropic", 4.00, 20.00, 1_000_000),
    "claude-fable-5-1": ("anthropic", 10.00, 50.00, 1_000_000),
    # Google list prices after introductory offers; standard_cost applies dated offers.
    "gemini-3.5-flash-lite": ("google", 0.30, 2.50, 1_048_576),
    "gemini-3.8-flash": ("google", 1.50, 7.50, 1_048_576),
    "gemini-4-argon": ("google", 4.00, 20.00, 1_048_576),
    # Peak, uncached rates are conservative across DeepSeek's time-of-day tariffs.
    "deepseek-flash": ("deepseek", 0.30, 1.20, 1_000_000),
    "deepseek-v4-flash": ("deepseek", 0.30, 1.20, 1_000_000),
    "deepseek-v4-pro": ("deepseek", 1.32, 3.96, 1_000_000),
    "glm-5.3": ("glm", 1.40, 4.40, 1_000_000),
    "glm-5.3-flash": ("glm", 0.15, 0.50, 1_000_000),
    "glm-5.3-flashx": ("glm", 0.37, 1.25, 1_000_000),
    "glm-5.1": ("glm", 1.40, 4.40, 200_000),
    "qwen-3.8-27b": ("cerebras", 0.99, 1.49, 131_072),
}


def catalog() -> dict[str, dict]:
    return {
        model: {"provider": provider, "cost_per_m_input": inp,
                "cost_per_m_output": out, "max_context": context}
        for model, (provider, inp, out, context) in FRONTIER_MODELS.items()
    }


def standard_cost(model: str, pricing: dict, input_tokens: int, output_tokens: int,
                  *, at: datetime | None = None) -> float:
    """Standard uncached cost; never silently omit long-context surcharges."""
    inp, out = pricing["cost_per_m_input"], pricing["cost_per_m_output"]
    today = (at or datetime.now(timezone.utc)).date().isoformat()
    if model == "gemini-4-argon" and today < "2026-12-01":
        inp, out = 2.0, 10.0
    elif model == "gemini-3.8-flash" and today < "2027-01-01":
        inp, out = 0.75, 3.75
    if model in FRONTIER_MODELS:
        if model.startswith("gpt-6") and input_tokens > 272_000:
            inp, out = inp * 2, out * 1.5
        elif model == "claude-haiku-5-5" and input_tokens > 100_000:
            inp, out = 0.50, 2.50
    return (input_tokens * inp + output_tokens * out) / 1_000_000
