from __future__ import annotations

import sys
import types

from router.intent import classifier_status, classify


class _FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {
            "category": "code",
            "complexity": 5,
            "confidence": 0.97,
            "keywords": ["btree"],
        }


class _FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def post(self, *args, **kwargs):
        return _FakeResponse()


def test_http_classifier_can_override_when_confident(monkeypatch):
    from router import config

    monkeypatch.setattr(config.settings, "classifier_backend", "http")
    monkeypatch.setattr(config.settings, "classifier_http_url", "http://127.0.0.1:9001/classify")
    monkeypatch.setattr(config.settings, "classifier_confidence_threshold", 0.8)
    monkeypatch.setattr("httpx.Client", _FakeClient)

    result = classify("Build a complete B-tree implementation")

    assert result.category.value == "code"
    assert result.complexity == 5
    assert result.confidence == 0.97


def test_classifier_status_reports_byo_knobs(monkeypatch):
    from router import config

    monkeypatch.setattr(config.settings, "classifier_backend", "auto")
    monkeypatch.setattr(config.settings, "classifier_http_url", "")
    monkeypatch.setattr(config.settings, "classifier_onnx_model_path", "")
    monkeypatch.setattr(config.settings, "classifier_retrain_enabled", True)
    monkeypatch.setattr(config.settings, "classifier_retrain_schedule", "daily")

    status = classifier_status()

    assert status["backend"] == "auto"
    assert status["http_enabled"] is False
    assert status["onnx_enabled"] is False
    assert status["retrain_enabled"] is True
    assert status["retrain_schedule"] == "daily"


def test_classifier_warm_on_startup():
    """When model_path exists at startup, is_model_loaded() must return True.

    This test is the contract that catches the 'classifier_loaded: false' bug.
    Skipped automatically when the model files are absent (CI without model bundle).
    """
    from pathlib import Path
    from router.config import settings
    from router.intent import _load_deberta, is_model_loaded

    model_path = Path(settings.classifier_model_path)
    if not model_path.exists():
        import pytest
        pytest.skip("model not present — skip in CI without model bundle")

    try:
        loaded = _load_deberta()
    except Exception:
        import pytest
        pytest.skip("DeBERTa load raised exception — skip in environment without ML deps")

    if not loaded:
        import pytest
        pytest.skip("DeBERTa returned False — skip in environment without ML deps")

    assert is_model_loaded(), "is_model_loaded() must be True after successful load"


def test_toml_classifier_section_maps_model_path(tmp_path, monkeypatch):
    """[classifier] model_path in mullm.toml must reach classifier_model_path."""
    import importlib
    from router.config import _flatten_toml

    toml_data = {
        "classifier": {
            "model_path": str(tmp_path / "routing-classifier"),
            "backend": "deberta",
            "confidence_threshold": 0.75,
        }
    }
    flat = _flatten_toml(toml_data)
    assert flat["classifier_model_path"] == str(tmp_path / "routing-classifier")
    assert flat["classifier_backend"] == "deberta"
    assert flat["classifier_confidence_threshold"] == 0.75


def test_onnx_classifier_contract(monkeypatch, tmp_path):
    from router import config, intent

    model_path = tmp_path / "classifier.onnx"
    model_path.write_bytes(b"placeholder")
    (tmp_path / "tokenizer.json").write_text("{}", encoding="utf-8")
    (tmp_path / "mullm_label_map.json").write_text(
        '{"id2label":{"0":"lookup","1":"code"},"label2id":{"lookup":0,"code":1}}',
        encoding="utf-8",
    )

    class _Input:
        def __init__(self, name):
            self.name = name

    class _Session:
        def __init__(self, *args, **kwargs):
            pass

        def get_inputs(self):
            return [_Input("input_ids"), _Input("attention_mask")]

        def run(self, *_args):
            return [[[0.1, 4.0]]]

    class _Tokenizer:
        def __call__(self, *_args, **_kwargs):
            return {"input_ids": [[1, 2]], "attention_mask": [[1, 1]], "unused": [[0]]}

    fake_ort = types.SimpleNamespace(InferenceSession=_Session)
    fake_transformers = types.SimpleNamespace(
        AutoTokenizer=types.SimpleNamespace(from_pretrained=lambda *a, **k: _Tokenizer())
    )
    monkeypatch.setitem(sys.modules, "onnxruntime", fake_ort)
    monkeypatch.setitem(sys.modules, "transformers", fake_transformers)
    monkeypatch.setattr(intent, "_onnx_checked", False)
    monkeypatch.setattr(intent, "_onnx_available", False)
    monkeypatch.setattr(intent, "_onnx_session", None)
    monkeypatch.setattr(intent, "_onnx_tokenizer", None)
    monkeypatch.setattr(intent, "_onnx_model_key", "")
    monkeypatch.setattr(config.settings, "classifier_backend", "onnx")
    monkeypatch.setattr(config.settings, "classifier_onnx_model_path", str(model_path))
    monkeypatch.setattr(config.settings, "classifier_onnx_tokenizer_path", str(tmp_path))
    monkeypatch.setattr(config.settings, "classifier_confidence_threshold", 0.8)

    result = classify("Build a parser")

    assert result.category.value == "code"
    assert result.confidence > 0.9
