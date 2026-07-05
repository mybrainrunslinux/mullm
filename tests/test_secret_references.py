import subprocess

from router.config import _resolve_secret_reference


def test_secret_reference_ignores_normal_values():
    assert _resolve_secret_reference("sk-live") == "sk-live"
    assert _resolve_secret_reference(None) is None


def test_secret_reference_resolves_pass_uri(monkeypatch):
    monkeypatch.setattr("router.config.shutil.which", lambda name: "/usr/bin/pass" if name == "pass" else None)

    def fake_run(args, text, capture_output, check):
        assert args == ["pass", "show", "0101technology/mullm/llms/openai-api-key-test"]
        return subprocess.CompletedProcess(args, 0, stdout="secret-value\nmetadata\n", stderr="")

    monkeypatch.setattr("router.config.subprocess.run", fake_run)

    assert _resolve_secret_reference("pass:0101technology/mullm/llms/openai-api-key-test") == "secret-value"


def test_secret_reference_returns_none_when_pass_missing(monkeypatch):
    monkeypatch.setattr("router.config.shutil.which", lambda name: None)

    assert _resolve_secret_reference("pass:any/key") is None

