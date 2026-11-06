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


def test_product_review_cannot_precede_executable_acceptance():
    data = spec(publish_events=True).model_dump()
    data['gates'].insert(0, Gate(name='review', kind='human').model_dump())
    with pytest.raises(ValidationError, match='Product review must follow'):
        FactorySpec.model_validate(data)


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


def test_factory_rejects_invalid_dependency_graph():
    from router.factory import FactoryTask
    base = spec().model_dump()
    for tasks in (
        [FactoryTask(id="a", instruction="x", writable_files=["game.py"], depends_on=["missing"])],
        [FactoryTask(id="a", instruction="x", writable_files=["game.py"], depends_on=["b"]),
         FactoryTask(id="b", instruction="x", writable_files=["game.py"], depends_on=["a"])],
        [FactoryTask(id="a", instruction="x", writable_files=["acceptance.py"])],
    ):
        with pytest.raises(ValidationError):
            FactorySpec.model_validate({**base, "tasks": tasks})


@pytest.mark.parametrize("repair_succeeds", [True, False])
async def test_dag_repairs_from_executable_feedback_before_running_dependents(tmp_path, monkeypatch, repair_succeeds):
    root = tmp_path / "repair"
    root.mkdir()
    subprocess.run(["git", "init", str(root)], check=True, capture_output=True)
    (root / "acceptance.py").write_text("from game import score\nassert score(5, 2) == 7, 'score must add both inputs'\n")
    (root / "contract.txt").write_text("score adds two numbers")
    (root / "factory.toml").write_text(f'''name = "repair"
goals = ["correct scoring"]
writable_files = ["game.py", "ui.txt"]
context_files = ["contract.txt"]
protected_files = ["acceptance.py", "contract.txt"]
artifacts = ["game.py", "ui.txt"]
[[tasks]]
id = "ui"
instruction = "build UI"
depends_on = ["rules"]
writable_files = ["ui.txt"]
[[tasks]]
id = "rules"
instruction = "implement score"
writable_files = ["game.py"]
gates = ["score"]
max_attempts = 2
[[gates]]
name = "score"
command = [{json.dumps(sys.executable)}, "acceptance.py"]
''')
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Test", "-c", "user.email=test@example.org",
                    "commit", "-m", "contract"], check=True, capture_output=True)
    prompts = []
    class Client:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, url, **kwargs):
            prompt = json.loads(kwargs["json"]["content"])
            prompts.append(prompt)
            assert prompt["files"]["contract.txt"] == "score adds two numbers"
            assert "acceptance.py" not in prompt["files"]
            if len(prompts) == 1 or not repair_succeeds:
                files = {"game.py": "def score(a,b): return 0\n"}
            elif len(prompts) == 2:
                assert "score must add both inputs" in prompt["test_feedback"]
                files = {"game.py": "def score(a,b): return a+b\n"}
            else:
                assert prompt["task"] == "build UI"
                files = {"ui.txt": "ready"}
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {
                "tier": "local", "cost": 0, "model_used": "test-local", "response": json.dumps({"files": files})})
    monkeypatch.setattr("router.factory.httpx.AsyncClient", Client)
    result = await run_factory(root / "factory.toml", root, "http://127.0.0.1:6856")
    assert result["status"] == ("accepted" if repair_succeeds else "failed"), result
    assert len(prompts) == (3 if repair_succeeds else 2)
    assert result["tasks"][0]["id"] == "rules"
    assert result["tasks"][0]["attempts"][0]["status"] == "failed"
    assert result["elapsed_seconds"] > 0
    assert not (root / "game.py").exists()
    if not repair_succeeds:
        assert not Path(result["worktree"], "ui.txt").exists()


def test_ollama_thinking_and_structured_output_are_top_level():
    from router.models import QueryRequest, IntentObject
    from router.tiers import _build_ollama_payload
    request = QueryRequest(content="Generate JSON", context={"think": False, "format": "json", "num_predict": 123})
    payload = _build_ollama_payload(request, IntentObject(), "local-model")
    assert payload["think"] is False
    assert payload["format"] == "json"
    assert "think" not in payload["options"]
    assert payload["options"]["num_predict"] == 123


async def test_real_handoff_waits_for_decision_then_retests_candidate(tmp_path, monkeypatch):
    root=tmp_path/'handoff'; root.mkdir()
    subprocess.run(['git','init',str(root)],check=True,capture_output=True)
    (root/'check.py').write_text("from game import value\nassert value == 7\n")
    (root/'factory.toml').write_text(f'''name = "handoff"
goals = ["value seven"]
publish_events = true
human_intervention = true
writable_files = ["game.py"]
protected_files = ["check.py"]
artifacts = ["game.py"]
[[tasks]]
id = "engine"
instruction = "write value seven"
writable_files = ["game.py"]
gates = ["check"]
max_attempts = 1
[[gates]]
name = "check"
command = [{json.dumps(sys.executable)}, "check.py"]
''')
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.org','commit','-m','contract'],check=True,capture_output=True)
    calls={'inference':0,'polls':0}; snapshots=[]
    def response(data): return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
    class Client:
        def __init__(self,**kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def delete(self,url): return response({'released':True})
        async def post(self,url,json):
            if url.endswith('/api/factory/inference-lease'): return response({'lease_id':'test-lease','acquired':True})
            if url.endswith('/api/factory/runs'):
                snapshots.append(json['snapshot']['status']); return response({})
            if url.endswith('/api/agents/blocked'):
                assert calls['inference']==1
                return response({'session_id':'agent-test'})
            calls['inference']+=1
            if calls['inference']==2: assert calls['polls']>=2
            return response({'tier':'local','cost':0,'response':__import__('json').dumps({'files':{'game.py':'value = '+('7' if calls['inference']==2 else '0')}})})
        async def get(self,url):
            if url.endswith('/api/sessions'): return response({'sessions':[]})
            calls['polls']+=1
            assert calls['inference']==1
            return response({'resolved':calls['polls']>=2,'choice':'Retry'})
    monkeypatch.setattr('router.factory.httpx.AsyncClient',Client)
    result=await run_factory(root/'factory.toml',root,'http://localhost:6856')
    assert result['status']=='accepted',result
    assert 'needs_human' in snapshots
    assert result['tasks'][0]['attempts'][0]['gates'][0]['returncode'] != 0
    assert result['tasks'][0]['attempts'][1]['gates'][0]['returncode'] == 0
    assert result['human_decisions']==[{'session_id':'agent-test','choice':'Retry','source':'human'}]


@pytest.mark.parametrize('decision,expected', [('Accept','accepted'),('Reject','rejected')])
async def test_product_review_is_required_after_executable_checks(tmp_path, monkeypatch, decision, expected):
    root=tmp_path/'review';root.mkdir()
    (root/'app.txt').write_text('candidate')
    (root/'check.py').write_text('from pathlib import Path\nassert Path("app.txt").read_text() == "candidate"\n')
    (root/'factory.toml').write_text(f'''name = "review"
goals = ["usable candidate"]
publish_events = true
writable_files = ["app.txt"]
protected_files = ["check.py"]
artifacts = ["app.txt"]
[[tasks]]
id = "verify"
instruction = "verify candidate"
writable_files = ["app.txt"]
verification_only = true
gates = ["check"]
[[gates]]
name = "check"
command = [{json.dumps(sys.executable)}, "check.py"]
[[gates]]
name = "usability"
kind = "human"
prompt = "Is it usable?"
''')
    subprocess.run(['git','init',str(root)],check=True,capture_output=True)
    subprocess.run(['git','-C',str(root),'add','.'],check=True)
    subprocess.run(['git','-C',str(root),'-c','user.name=Test','-c','user.email=test@example.org','commit','-m','candidate'],check=True,capture_output=True)
    snapshots=[]
    def reply(data):return SimpleNamespace(raise_for_status=lambda:None,json=lambda:data)
    class Client:
        def __init__(self,**kwargs):pass
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def post(self,url,json):
            if url.endswith('/api/factory/runs'):
                snapshots.append(json['snapshot']['status']);return reply({})
            assert url.endswith('/api/agents/blocked'), 'Verification-only runs must not invoke a model'
            assert json['block_reason']=='product_review'
            return reply({'session_id':'review-card'})
        async def get(self,url):
            if url.endswith('/api/sessions'):return reply({'sessions':[]})
            assert 'accepted' not in snapshots
            return reply({'resolved':True,'choice':decision})
    monkeypatch.setattr('router.factory.httpx.AsyncClient',Client)
    result=await run_factory(root/'factory.toml',root,'http://localhost:6856')
    assert result['status']==expected,result
    assert 'needs_human' in snapshots
    assert result['gates'][0]['returncode']==0
    if expected=='rejected':assert not result['artifacts']


async def test_batch_dry_run_never_creates_worktrees_or_inference(tmp_path):
    from router.factory import run_batch
    for name in ('one','two'):
        root=tmp_path/name;root.mkdir()
        (root/'factory.toml').write_text('''name="test"
goals=["dry run"]
publish_events=true
tasks=["implement"]
writable_files=["app.py"]
protected_files=["check.py"]
artifacts=["app.py"]
[[gates]]
name="check"
command=["python3","check.py"]
''')
    manifest=tmp_path/'workspace.toml';manifest.write_text('[[projects]]\nroot="one"\n[[projects]]\nroot="two"\n')
    result=await run_batch(manifest,'http://127.0.0.1:1',dry_run=True)
    assert result['status']=='planned'
    assert len(result['projects'])==2
    assert not list(tmp_path.glob('*-factory-*'))
