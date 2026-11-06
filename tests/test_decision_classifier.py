from types import SimpleNamespace

import pytest

from router import decision_classifier as decision


def test_systemone_batches_questions_and_parses():
    payload = decision.request_payload("write a parser", "kev-latest")
    assert payload["state"] == "write a parser"
    assert set(payload["questions"]) == {"intent", "complexity"}
    result = decision.parse_response({"answers": {
        "intent": {"choice": "code", "confidence": 0.95},
        "complexity": {"choice": "4", "confidence": 0.85}}})
    assert result == {"category": "code", "complexity": 4, "confidence": 0.85}


@pytest.mark.parametrize("url", ["https://api.typesafe.ai/v1/systemone", "http://example.com", "http://localhost", "file:///tmp/x"])
def test_hosted_decisions_do_not_bypass_budget(url):
    assert decision.classify("private query", SimpleNamespace(classifier_http_url=url)) is None


def test_local_systemone_wire_contract(monkeypatch):
    from router import config, intent

    class Client:
        def __init__(self, **kwargs):
            assert kwargs["trust_env"] is False
            assert kwargs["follow_redirects"] is False
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def post(self, url, json, headers):
            assert json["model"] == "kev-latest"
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"answers": {
                "intent": {"choice": "code", "confidence": 0.95},
                "complexity": {"choice": "4", "confidence": 0.9}}})

    monkeypatch.setattr("httpx.Client", Client)
    monkeypatch.setattr(config.settings, "classifier_backend", "systemone")
    monkeypatch.setattr(config.settings, "classifier_http_url", "http://127.0.0.1:8009/v1/systemone")
    monkeypatch.setattr(config.settings, "classifier_http_model", "kev-latest")
    result = intent.classify("write a parser")
    assert result.category.value == "code"
    assert result.complexity == 4
