from router import cloud


def test_cost_strategy_picks_cheapest_configured_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(cloud.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(cloud.settings, "google_api_key", "AIza-test")
    monkeypatch.setattr(cloud.settings, "cerebras_api_key", None)
    monkeypatch.setattr(cloud.settings, "deepseek_api_key", None)
    monkeypatch.setattr(cloud.settings, "glm_api_key", None)

    assert cloud.model_for_tier(tier="cloud_cheap", cost_strategy="cost_optimize") == "gpt-4o-mini"


def test_quality_strategy_keeps_preferred_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", "sk-ant-test")

    assert cloud.model_for_tier(tier="cloud_full", cost_strategy="quality") == "claude-sonnet-5"


def test_quality_strategy_falls_back_to_configured_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", None)
    monkeypatch.setattr(cloud.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(cloud.settings, "google_api_key", None)
    monkeypatch.setattr(cloud.settings, "cerebras_api_key", None)
    monkeypatch.setattr(cloud.settings, "deepseek_api_key", None)
    monkeypatch.setattr(cloud.settings, "glm_api_key", None)

    assert cloud.model_for_tier(tier="cloud_full", cost_strategy="quality") == "gpt-5.4-pro"
