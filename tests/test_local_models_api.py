from pathlib import Path

from router.local_models_api import _profile_by_id, _write_profile_env


def test_local_model_profiles_include_fast_and_exllamav3_targets():
    fast = _profile_by_id("ollama_omnicoder_9b_fast")
    exllama = _profile_by_id("tabbyapi_moe_30b_exllamav3")

    assert fast is not None
    assert fast["backend"] == "ollama"
    assert "MULLM_OLLAMA_MODEL" in fast["env"]
    assert exllama is not None
    assert exllama["backend"] == "tabbyapi"
    assert exllama["env"]["TABBYAPI_BASE_URL"].endswith("/v1")


def test_write_profile_env_is_restartable_fragment(tmp_path: Path):
    profile = _profile_by_id("tabbyapi_moe_30b_exllamav3")
    assert profile is not None
    target = tmp_path / "local-model.env"

    _write_profile_env(profile, target)

    text = target.read_text(encoding="utf-8")
    assert "MULLM_LOCAL_MODEL_PROFILE=tabbyapi_moe_30b_exllamav3" in text
    assert "TABBYAPI_BASE_URL=http://127.0.0.1:5000/v1" in text
    assert oct(target.stat().st_mode & 0o777) == "0o600"

