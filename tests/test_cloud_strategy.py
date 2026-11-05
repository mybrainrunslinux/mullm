from router import cloud


def test_cost_strategy_picks_cheapest_configured_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", "sk-ant-test")
    monkeypatch.setattr(cloud.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(cloud.settings, "google_api_key", "AIza-test")
    monkeypatch.setattr(cloud.settings, "cerebras_api_key", None)
    monkeypatch.setattr(cloud.settings, "deepseek_api_key", None)
    monkeypatch.setattr(cloud.settings, "glm_api_key", None)

    assert cloud.model_for_tier(tier="cloud_cheap", cost_strategy="cost_optimize") == "claude-haiku-5-5"


def test_quality_strategy_keeps_preferred_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", "sk-ant-test")

    assert cloud.model_for_tier(tier="cloud_full", cost_strategy="quality") == "claude-sonnet-5-5"


def test_quality_strategy_falls_back_to_configured_provider(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "anthropic")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", None)
    monkeypatch.setattr(cloud.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(cloud.settings, "google_api_key", None)
    monkeypatch.setattr(cloud.settings, "cerebras_api_key", None)
    monkeypatch.setattr(cloud.settings, "deepseek_api_key", None)
    monkeypatch.setattr(cloud.settings, "glm_api_key", None)

    assert cloud.model_for_tier(tier="cloud_full", cost_strategy="quality") == "gpt-6.1-sol"


def test_gpt56_frontier_tier_mapping(monkeypatch):
    monkeypatch.setattr(cloud.settings, "preferred_cloud_provider", "openai")
    monkeypatch.setattr(cloud.settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(cloud.settings, "anthropic_api_key", None)
    monkeypatch.setattr(cloud.settings, "google_api_key", None)
    monkeypatch.setattr(cloud.settings, "cerebras_api_key", None)
    monkeypatch.setattr(cloud.settings, "deepseek_api_key", None)
    monkeypatch.setattr(cloud.settings, "glm_api_key", None)
    assert cloud.model_for_tier(tier="cloud_cheap", cost_strategy="quality") == "gpt-6-luna"
    assert cloud.model_for_tier(tier="cloud_full", cost_strategy="quality") == "gpt-6.1-sol"
    assert cloud.model_for_tier(tier="cloud_power", cost_strategy="quality") == "gpt-6-astra"


def test_gpt56_uses_responses_transport():
    assert cloud._openai_uses_responses("gpt-5.6-sol")
    assert cloud._openai_uses_responses("gpt-5.6-terra")
    assert cloud._openai_uses_responses("gpt-5.6-luna")
    assert not cloud._openai_uses_responses("gpt-4o-mini")
