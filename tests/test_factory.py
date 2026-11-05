import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from router.factory import FactorySpec, Gate, apply_candidate, run_factory, run_gate


def spec(**overrides):
    return FactorySpec(name="game", goals=["Score increases"], tasks=["Implement scoring"],
                       writable_files=["game.py"], protected_files=["acceptance.py"],
                       artifacts=["game.py"], gates=[Gate(name="acceptance", command=[sys.executable, "acceptance.py"])],
                       **overrides)


def test_candidate_cannot_change_acceptance_or_escape(tmp_path):
    (tmp_path / "acceptance.py").write_text("assert True")
    for name in ("acceptance.py", "../escape", ".git/config"):
        with pytest.raises(ValueError):
            apply_candidate(tmp_path, spec(), json.dumps({"files": {"game.py": "ok", name: "bad"}}))
        assert not (tmp_path / "game.py").exists()


async def test_factory_end_to_end_creates_verified_worktree(tmp_path, monkeypatch):
    root = tmp_path / "game"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "acceptance.py").write_text("from game import score\nassert score(5, 2) == 7\n")
    (root / "factory.toml").write_text(f'''name = "game"
goals = ["score increases"]
tasks = ["implement scoring"]
writable_files = ["game.py"]
protected_files = ["acceptance.py"]
artifacts = ["game.py"]
[[gates]]
name = "score"
command = [{json.dumps(sys.executable)}, "acceptance.py"]
''')
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-m", "acceptance contract"], check=True, capture_output=True)

    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, json):
            assert json["force_tier"] == "local"
            assert json["allow_cloud_escalation"] is False
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "tier": "local", "cost": 0,
                "response": '{"files":{"game.py":"def score(a, b): return a + b\\n"}}'})
    monkeypatch.setattr("router.factory.httpx.AsyncClient", Client)
    result = await run_factory(root / "factory.toml", root, "http://127.0.0.1:6856")
    assert result["status"] == "accepted", result
    assert result["gates"][0]["returncode"] == 0
    assert result["artifacts"]["game.py"]["sha256"]
    assert not (root / "game.py").exists()
    assert Path(result["worktree"], "game.py").exists()


async def test_gate_failure_and_timeout(tmp_path):
    result = await run_gate(tmp_path, Gate(name="fail", command=[sys.executable, "-c", "raise SystemExit(2)"]), tmp_path / "fail.log")
    assert result["returncode"] == 2
    with pytest.raises(TimeoutError):
        await run_gate(tmp_path, Gate(name="hang", command=[sys.executable, "-c", "import time; time.sleep(30)"], timeout_seconds=1), tmp_path / "hang.log")
