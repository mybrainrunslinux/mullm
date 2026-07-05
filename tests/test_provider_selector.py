from router import provider_policy, provider_selector


def configure(monkeypatch, **keys):
    configured = {p for p, k in keys.items() if k}
    # Patch provider_ready directly — avoids stale settings state across test files
    monkeypatch.setattr(provider_selector, "provider_ready", lambda p: p in configured)


def test_cost_mode_picks_cheapest_configured_same_tier(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_policy, "POLICY_PATH", tmp_path / "provider_policy.json")
    configure(monkeypatch, openai="sk-test", anthropic="sk-ant-test", google="AIza-test")

    selection = provider_selector.select_provider_model("cloud_cheap", mode="cost_optimize")

    assert selection.model == "gpt-4o-mini"
    assert selection.tier == "cloud_cheap"


def test_manual_order_cannot_cross_tier_guard(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_policy, "POLICY_PATH", tmp_path / "provider_policy.json")
    configure(monkeypatch, openai="sk-test", anthropic="sk-ant-test")
    provider_policy.update_policy(
        {
            "mode": "manual",
            "provider_order": ["anthropic", "openai"],
            "weights": {"anthropic": 2.0},
        }
    )

    selection = provider_selector.select_provider_model("cloud_power")

    assert selection.provider == "anthropic"
    assert selection.model == provider_selector.settings.cloud_power_model_anthropic
    assert selection.model != provider_selector.settings.cloud_cheap_model_anthropic


def test_speed_mode_favors_cerebras_when_configured(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_policy, "POLICY_PATH", tmp_path / "provider_policy.json")
    configure(monkeypatch, openai="sk-test", cerebras="csk-test")

    selection = provider_selector.select_provider_model("cloud_full", mode="speed")

    assert selection.provider == "cerebras"
    assert selection.model == provider_selector.settings.cloud_full_model_cerebras


def test_balanced_weights_are_bounded(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_policy, "POLICY_PATH", tmp_path / "provider_policy.json")
    configure(monkeypatch, openai="sk-test", anthropic="sk-ant-test")
    provider_policy.update_policy({"mode": "balanced", "weights": {"anthropic": 200.0}})

    candidates = provider_selector.candidates_for_tier("cloud_full")
    anthropic = next(candidate for candidate in candidates if candidate.provider == "anthropic")

    assert anthropic.user_weight == 2.0
