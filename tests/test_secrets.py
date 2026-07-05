from router.secrets import env_file_status


def test_env_file_status_respects_explicit_service_envfile(monkeypatch, tmp_path):
    env_file = tmp_path / "mullm.env"
    env_file.write_text("OPENAI_API_KEY=redacted\n", encoding="utf-8")
    env_file.chmod(0o600)
    monkeypatch.setenv("MULLM_ENV_FILE", str(env_file))

    status = env_file_status()

    assert status["exists"] is True
    assert status["path"] == str(env_file)
    assert status["mode"] == "0o600"
    assert status["owner_only"] is True
