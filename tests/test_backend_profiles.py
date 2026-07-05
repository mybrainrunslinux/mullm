from router.backend_profiles import backend_profiles


def ids(profiles):
    return {profile["id"] for profile in profiles}


def test_backend_profiles_hide_experimental_by_default():
    profiles = backend_profiles()
    visible = ids(profiles)

    assert "beginner_cache_groundtruth" in visible
    assert "ollama_safe_8gb" in visible
    assert "llamacpp_qwen36_27b_q4km" not in visible
    assert "llamacpp_qwen36_27b_mtp_nightly" not in visible

    beginner = next(profile for profile in profiles if profile["id"] == "beginner_cache_groundtruth")
    assert any("semantic cache" in note for note in beginner["notes"])
    assert not any("ChromaDB cache" in note for note in beginner["notes"])


def test_backend_profiles_include_experimental_without_nightly():
    visible = ids(backend_profiles(include_experimental=True))

    assert "llamacpp_qwen36_27b_q4km" in visible
    assert "tabbyapi_exllamav3" in visible
    assert "llamacpp_qwen36_27b_mtp_nightly" not in visible


def test_backend_profiles_include_nightly_only_when_enabled():
    visible = ids(backend_profiles(include_experimental=True, include_nightly=True))

    assert "llamacpp_qwen36_27b_mtp_nightly" in visible
