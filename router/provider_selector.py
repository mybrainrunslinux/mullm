"""Provider/model selection with tier guards, preferences, and policy modes."""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass
from typing import Any

from router import provider_policy
from router.config import CLOUD_MODEL_PRICING, settings

TIER_INDEX = {"cloud_cheap": 0, "cloud_full": 1, "cloud_power": 2}
DEFAULT_PROVIDER_ORDER = ["openai", "anthropic", "google", "cerebras", "deepseek", "glm"]
DEFAULT_WEIGHTS = {provider: 1.0 for provider in DEFAULT_PROVIDER_ORDER}
PROVIDER_CLIENT_MODULES = {
    "anthropic": "anthropic",
    "openai": "openai",
    "google": "google.genai",
    "cerebras": "openai",
    "deepseek": "openai",
    "glm": "openai",
}


@dataclass(frozen=True)
class ProviderCandidate:
    provider: str
    model: str
    tier: str
    configured: bool
    cost_per_m: float
    speed_score: float
    quality_score: float
    user_weight: float
    score: float = 0.0


@dataclass(frozen=True)
class ProviderSelection:
    provider: str
    model: str
    tier: str
    mode: str
    reason: str
    candidates: list[ProviderCandidate]


def provider_model_map() -> dict[str, tuple[str, str, str]]:
    return {
        "anthropic": (
            settings.cloud_cheap_model_anthropic,
            settings.cloud_full_model_anthropic,
            settings.cloud_power_model_anthropic,
        ),
        "openai": (
            settings.cloud_cheap_model_openai,
            settings.cloud_full_model_openai,
            settings.cloud_power_model_openai,
        ),
        "google": (
            settings.cloud_cheap_model_google,
            settings.cloud_full_model_google,
            settings.cloud_power_model_google,
        ),
        "cerebras": (
            settings.cloud_cheap_model_cerebras,
            settings.cloud_full_model_cerebras,
            settings.cloud_power_model_cerebras,
        ),
        "deepseek": (
            settings.cloud_cheap_model_deepseek,
            settings.cloud_full_model_deepseek,
            settings.cloud_power_model_deepseek,
        ),
        "glm": (
            settings.cloud_cheap_model_glm,
            settings.cloud_full_model_glm,
            settings.cloud_power_model_glm,
        ),
    }


def provider_configured(provider: str) -> bool:
    keys = {
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
        "google": settings.google_api_key,
        "cerebras": settings.cerebras_api_key,
        "deepseek": settings.deepseek_api_key,
        "glm": settings.glm_api_key,
    }
    key = keys.get(provider)
    return bool(key and "CHANGEME" not in str(key))


def provider_client_available(provider: str) -> bool:
    """Return True when the optional client library for a provider is importable."""
    module_name = PROVIDER_CLIENT_MODULES.get(provider)
    if not module_name:
        return False
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def provider_ready(provider: str) -> bool:
    """Return True only when a provider is configured, importable, and not backed off."""
    return (
        provider_configured(provider)
        and provider_client_available(provider)
        and provider_policy.provider_available(provider)
    )


def _cost_per_m(model: str) -> float:
    pricing = CLOUD_MODEL_PRICING.get(model, {})
    return float(pricing.get("cost_per_m_input", float("inf"))) + float(
        pricing.get("cost_per_m_output", float("inf"))
    )


def _speed_score(provider: str) -> float:
    return {
        "cerebras": 1.35,
        "deepseek": 1.1,
        "google": 1.05,
        "openai": 1.0,
        "anthropic": 0.95,
        "glm": 0.9,
    }.get(provider, 1.0)


def _quality_score(provider: str, tier: str) -> float:
    base = {
        "openai": 1.10,
        "anthropic": 1.08,
        "google": 1.02,
        "cerebras": 0.96,
        "deepseek": 0.92,
        "glm": 0.88,
    }.get(provider, 1.0)
    if tier == "cloud_power" and provider in {"openai", "anthropic", "google"}:
        return base + 0.08
    return base


def _ordered_providers(policy: dict[str, Any]) -> list[str]:
    raw = policy.get("provider_order")
    if not isinstance(raw, list):
        return list(DEFAULT_PROVIDER_ORDER)
    clean = [str(item) for item in raw if str(item) in provider_model_map()]
    return clean + [provider for provider in DEFAULT_PROVIDER_ORDER if provider not in clean]


def _weights(policy: dict[str, Any]) -> dict[str, float]:
    raw = policy.get("weights")
    weights = dict(DEFAULT_WEIGHTS)
    if isinstance(raw, dict):
        for provider, value in raw.items():
            if provider in weights:
                # Keep manual bias useful but bounded. It cannot cross tier guards.
                weights[provider] = max(0.25, min(2.0, float(value)))
    return weights


def candidates_for_tier(tier: str, policy: dict[str, Any] | None = None) -> list[ProviderCandidate]:
    idx = TIER_INDEX.get(tier, 0)
    data = policy or provider_policy.status()
    weights = _weights(data)
    candidates: list[ProviderCandidate] = []
    for provider, models in provider_model_map().items():
        model = models[idx]
        configured = provider_ready(provider)
        candidates.append(
            ProviderCandidate(
                provider=provider,
                model=model,
                tier=tier,
                configured=configured,
                cost_per_m=_cost_per_m(model),
                speed_score=_speed_score(provider),
                quality_score=_quality_score(provider, tier),
                user_weight=weights.get(provider, 1.0),
            )
        )
    return candidates


def select_provider_model(tier: str, mode: str | None = None) -> ProviderSelection:
    policy = provider_policy.status()
    selected_mode = mode or str(policy.get("mode") or "balanced")
    candidates = [candidate for candidate in candidates_for_tier(tier, policy) if candidate.configured]
    if not candidates:
        fallback_provider = settings.preferred_cloud_provider
        fallback = provider_model_map().get(fallback_provider, provider_model_map()["anthropic"])
        idx = TIER_INDEX.get(tier, 0)
        return ProviderSelection(
            provider=fallback_provider,
            model=fallback[idx],
            tier=tier,
            mode=selected_mode,
            reason="No configured provider was available; returning preferred provider so normal missing-key handling can explain setup.",
            candidates=[],
        )

    if selected_mode in {"cost", "cost_optimize", "aggressive_cost"}:
        chosen = min(candidates, key=lambda item: item.cost_per_m)
        reason = f"Selected {chosen.provider} because cost mode picked the cheapest configured {tier} candidate."
    elif selected_mode == "speed":
        chosen = max(candidates, key=lambda item: item.speed_score * item.user_weight)
        reason = f"Selected {chosen.provider} because speed mode favored low-latency configured {tier} candidates."
    elif selected_mode == "manual":
        order = _ordered_providers(policy)
        by_provider = {candidate.provider: candidate for candidate in candidates}
        chosen = next((by_provider[p] for p in order if p in by_provider), candidates[0])
        reason = f"Selected {chosen.provider} from manual provider order within the guarded {tier} tier."
    elif selected_mode == "quality":
        by_provider = {candidate.provider: candidate for candidate in candidates}
        preferred = settings.preferred_cloud_provider
        if preferred in by_provider:
            chosen = by_provider[preferred]
            reason = f"Selected {chosen.provider} because quality mode honors the configured preferred provider for {tier}."
        else:
            chosen = max(candidates, key=lambda item: item.quality_score * item.user_weight)
            reason = f"Selected {chosen.provider} because quality mode fell back to the highest-quality configured {tier} candidate."
    else:
        scored: list[ProviderCandidate] = []
        for candidate in candidates:
            score = (
                candidate.quality_score * candidate.user_weight
                + candidate.speed_score * 0.12
                - min(candidate.cost_per_m, 20.0) * 0.015
            )
            scored.append(ProviderCandidate(**{**candidate.__dict__, "score": score}))
        chosen = max(scored, key=lambda item: item.score)
        candidates = scored
        reason = f"Selected {chosen.provider} because balanced/quality mode produced the highest guarded {tier} score."

    return ProviderSelection(
        provider=chosen.provider,
        model=chosen.model,
        tier=tier,
        mode=selected_mode,
        reason=reason,
        candidates=candidates,
    )
