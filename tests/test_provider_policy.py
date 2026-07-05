from router import provider_policy
from router import provider_selector


def test_provider_policy_records_backoff(tmp_path, monkeypatch):
    policy_path = tmp_path / "provider_policy.json"
    monkeypatch.setattr(provider_policy, "POLICY_PATH", policy_path)

    assert provider_policy.provider_available("openai")
    provider_policy.record_failure("openai", status_code=429, backoff_seconds=60)

    state = provider_policy.status()
    assert state["providers"]["openai"]["available"] is False
    assert state["providers"]["openai"]["last_status_code"] == 429
    assert state["providers"]["openai"]["backoff_seconds_remaining"] > 0

    provider_policy.record_success("openai")
    assert provider_policy.provider_available("openai")


def test_provider_policy_update_persists_mode(tmp_path, monkeypatch):
    monkeypatch.setattr(provider_policy, "POLICY_PATH", tmp_path / "provider_policy.json")

    state = provider_policy.update_policy({"mode": "quality", "aggressiveness": "cheap_first"})

    assert state["mode"] == "quality"
    assert state["aggressiveness"] == "cheap_first"


def test_provider_selection_skips_configured_provider_when_client_missing(monkeypatch):
    monkeypatch.setattr(provider_selector.settings, "openai_api_key", "sk-openai-test")
    monkeypatch.setattr(provider_selector.settings, "anthropic_api_key", "")
    monkeypatch.setattr(provider_selector.settings, "google_api_key", "google-test")
    monkeypatch.setattr(provider_policy, "provider_available", lambda provider: True)
    monkeypatch.setattr(
        provider_selector,
        "provider_client_available",
        lambda provider: provider != "google",
    )

    selected = provider_selector.select_provider_model("cloud_cheap", mode="cost")

    assert selected.provider == "openai"
    assert selected.model == provider_selector.provider_model_map()["openai"][0]
    assert all(candidate.provider != "google" for candidate in selected.candidates)
