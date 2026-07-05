from router import civitai_api
from router.secrets import env_var_for_provider


def test_civitai_provider_env_aliases_present():
    assert env_var_for_provider("civitai") == "CIVITAI_API_KEY"
    assert env_var_for_provider("civit_ai") == "CIVIT_AI_API_KEY"


def test_civitai_headers_use_supported_env_alias(monkeypatch):
    monkeypatch.setattr(civitai_api.settings, "civitai_api_key", None)
    monkeypatch.delenv("CIVITAI_API_KEY", raising=False)
    monkeypatch.setenv("CIVIT_AI_API_KEY", "test-secret")

    assert civitai_api.civitai_headers() == {"Authorization": "Bearer test-secret"}

