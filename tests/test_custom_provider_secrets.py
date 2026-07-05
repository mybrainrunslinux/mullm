from router.secrets import env_var_for_provider


def test_custom_provider_env_names_are_scoped():
    assert env_var_for_provider("custom_acme_router") == "MULLM_CUSTOM_ACME_ROUTER_API_KEY"
    assert env_var_for_provider("custom_acme_router_url") == "MULLM_CUSTOM_ACME_ROUTER_BASE_URL"
    assert env_var_for_provider("custom_acme_router_model") == "MULLM_CUSTOM_ACME_ROUTER_MODEL"


def test_custom_provider_rejects_unsafe_ids():
    assert env_var_for_provider("custom_bad-name") is None
    assert env_var_for_provider("custom_") is None


def test_search_and_hybrid_provider_env_names():
    assert env_var_for_provider("brave_search") == "BRAVE_SEARCH_API_KEY"
    assert env_var_for_provider("google_cse_id") == "GOOGLE_CSE_ID"
    assert env_var_for_provider("private_gpu_url") == "PRIVATE_GPU_BASE_URL"
    assert env_var_for_provider("runpod_url") == "RUNPOD_BASE_URL"
