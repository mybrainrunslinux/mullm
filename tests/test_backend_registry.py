from router.backends import registry
from router.backends.protocol import get_backend
from router.config import _flatten_toml


def test_cerebras_registers_as_openai_compatible_backend(monkeypatch):
    monkeypatch.setenv("CEREBRAS_API_KEY", "test-key")
    monkeypatch.setenv("CEREBRAS_MODEL", "gpt-oss-120b")

    registry.init_backends()

    backend = get_backend("cerebras")
    assert backend is not None
    assert backend.provider_name == "cerebras"


def test_cerebras_setup_key_env_mapping():
    from router.secrets import env_var_for_provider

    assert env_var_for_provider("cerebras") == "CEREBRAS_API_KEY"


def test_toml_maps_non_ollama_backend_settings():
    flat = _flatten_toml(
        {
            "inference": {
                "backends": {"priority": ["tabbyapi", "ollama"]},
                "tabbyapi": {"base_url": "http://127.0.0.1:5000/v1", "model": "local-exl3"},
                "vllm": {"base_url": "http://127.0.0.1:8000/v1", "model": "qwen"},
                "llamacpp": {"model_path": "/models/qwen.gguf", "n_ctx": 131072, "n_gpu_layers": 99},
                "exllamav2": {"model_path": "/models/exl2"},
                "mlx": {"model_path": "/models/mlx"},
            }
        }
    )

    assert flat["local_backend_priority"] == "tabbyapi,ollama"
    assert flat["tabbyapi_base_url"] == "http://127.0.0.1:5000/v1"
    assert flat["tabbyapi_model"] == "local-exl3"
    assert flat["vllm_base_url"] == "http://127.0.0.1:8000/v1"
    assert flat["vllm_model"] == "qwen"
    assert flat["llamacpp_model_path"] == "/models/qwen.gguf"
    assert flat["llamacpp_n_ctx"] == 131072
    assert flat["llamacpp_n_gpu_layers"] == 99
    assert flat["exllamav2_model_path"] == "/models/exl2"
    assert flat["mlx_model_path"] == "/models/mlx"
