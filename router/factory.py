"""Software Factory: isolated, local-inference builds with executable acceptance gates."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
from graphlib import TopologicalSorter, CycleError
import json
import os
from pathlib import Path
import signal
import ssl
from urllib.parse import urlsplit
import subprocess
import time
import tomllib
import uuid
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    kind: Literal["command", "human"] = "command"
    command: list[str] = []
    prompt: str = "Review the candidate against its product and usability requirements."
    review_url: str | None = None
    timeout_seconds: int = Field(default=120, ge=1, le=3600)

    @model_validator(mode="after")
    def gate_contract(self):
        if self.kind == 'command' and not self.command:
            raise ValueError('Command gates require an executable command')
        if self.kind == 'human' and self.command:
            raise ValueError('Human gates do not execute commands')
        if self.review_url and urlsplit(self.review_url).scheme not in ('http','https'):
            raise ValueError('Review links must use HTTP or HTTPS')
        return self


class FactoryTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    instruction: str = Field(min_length=1)
    depends_on: list[str] = []
    writable_files: list[str] = Field(min_length=1)
    gates: list[str] = []
    context_files: list[str] | None = None
    max_output_tokens: int = Field(default=2400, ge=128, le=8192)
    verification_only: bool = False
    max_attempts: int = Field(default=3, ge=1, le=5)


class FactoryQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-zA-Z0-9_-]+$")
    prompt: str = Field(min_length=1, max_length=8000)
    options: list[str] = Field(min_length=1, max_length=12)


class FactorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    target: str = "game"
    goals: list[str] = Field(min_length=1)
    business_rules: list[str] = []
    preferences: list[str] = []
    tasks: list[str | FactoryTask] = Field(min_length=1)
    context_files: list[str] = []
    questions: list[FactoryQuestion] = []
    publish_events: bool = False
    human_intervention: bool = False
    writable_files: list[str] = Field(min_length=1)
    protected_files: list[str] = Field(min_length=1)
    artifacts: list[str] = Field(min_length=1)
    gates: list[Gate] = Field(min_length=1)

    @model_validator(mode="after")
    def safe_paths(self):
        for value in self.writable_files + self.protected_files + self.context_files + self.artifacts:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts or not path.parts:
                raise ValueError(f"Expected relative project path: {value}")
        if set(self.writable_files) & set(self.protected_files):
            raise ValueError("Acceptance files must not be writable by the model")
        if self.questions and not self.publish_events:
            raise ValueError("Clarification questions require event publishing")
        if len({q.id for q in self.questions}) != len(self.questions):
            raise ValueError("Question IDs must be unique")
        if self.human_intervention and not self.publish_events:
            raise ValueError("Human intervention requires event publishing")
        if any(g.kind == "human" for g in self.gates) and not self.publish_events:
            raise ValueError("Human review gates require event publishing")
        human_gate_seen = False
        for gate in self.gates:
            if gate.kind == "human":
                human_gate_seen = True
            elif human_gate_seen:
                raise ValueError("Product review must follow all executable gates")
        tasks = self.ordered_tasks()
        gate_names = [gate.name for gate in self.gates]
        if len(set(gate_names)) != len(gate_names):
            raise ValueError("Gate names must be unique")
        for task in tasks:
            if not set(task.writable_files).issubset(self.writable_files):
                raise ValueError("Task writes must be within the manifest allowlist")
            if task.verification_only and not task.gates:
                raise ValueError("Verification tasks require at least one gate")
            if task.context_files is not None and not set(task.context_files).issubset(self.writable_files + self.context_files):
                raise ValueError("Task context must be declared in the manifest")
            if any(g.kind == "human" and g.name in task.gates for g in self.gates):
                raise ValueError("Human review gates run after implementation, not inside task repair loops")
            if not set(task.gates).issubset(gate_names):
                raise ValueError("Unknown task gate")
        return self

    def ordered_tasks(self) -> list[FactoryTask]:
        tasks = []
        for index, value in enumerate(self.tasks):
            tasks.append(value if isinstance(value, FactoryTask) else FactoryTask(
                id=f"task-{index + 1}", instruction=value,
                depends_on=[tasks[-1].id] if tasks else [],
                writable_files=self.writable_files, max_attempts=1))
        by_id = {task.id: task for task in tasks}
        if len(by_id) != len(tasks):
            raise ValueError("Task IDs must be unique")
        if any(dep not in by_id for task in tasks for dep in task.depends_on):
            raise ValueError("Unknown task dependency")
        try:
            order = TopologicalSorter({task.id: task.depends_on for task in tasks}).static_order()
            return [by_id[key] for key in order]
        except CycleError as exc:
            raise ValueError("Task dependencies contain a cycle") from exc


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


def _path(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError(f"Path escapes worktree: {relative}")
    return path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def apply_candidate(root: Path, spec: FactorySpec, response: str) -> None:
    """Validate the entire candidate before writing any files."""
    data = json.loads(response)
    files = data.get("files")
    if not isinstance(files, dict) or not files:
        raise ValueError("Model must return a nonempty files object")
    if not set(files).issubset(spec.writable_files):
        raise ValueError("Candidate modifies files outside the manifest allowlist")
    checked = []
    for name, content in files.items():
        if not isinstance(content, str) or not content.strip() or len(content.encode()) > 1_000_000:
            raise ValueError("Candidate file is invalid or too large")
        checked.append((_path(root, name), content))
    for path, content in checked:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")


async def run_gate(root: Path, gate: Gate, log_path: Path) -> dict:
    # Generated application code runs only commands explicitly supplied by the
    # operator. Strip provider credentials from child-process environments.
    env = {k: v for k, v in os.environ.items() if k in (
        "PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "LANG", "LC_ALL")}
    env["DISABLE_CLOUD"] = "1"
    with log_path.open("wb") as log:
        process = await asyncio.create_subprocess_exec(
            *gate.command, cwd=root, env=env, stdout=log, stderr=asyncio.subprocess.STDOUT,
            start_new_session=os.name != "nt")
        try:
            await asyncio.wait_for(process.wait(), timeout=gate.timeout_seconds)
        except (TimeoutError, asyncio.CancelledError):
            if os.name != "nt":
                os.killpg(process.pid, signal.SIGKILL)
            else:
                process.kill()
            await process.wait()
            raise
    return {"name": gate.name, "returncode": process.returncode, "log": str(log_path)}


async def run_factory(spec_path: Path, root: Path, api_url: str, *, dry_run=False) -> dict:
    started = time.monotonic()
    spec = FactorySpec.model_validate(tomllib.loads(spec_path.read_text()))
    if dry_run:
        return {"status": "planned", "spec": spec.model_dump(), "inference": "local", "publishes": False}
    if _git(root, "status", "--porcelain"):
        raise ValueError("Factory requires a clean committed project; commit the spec and acceptance gates first")
    run_id = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    work = root.parent / (root.name + "-factory-" + run_id)
    branch = "factory/" + run_id
    _git(root, "worktree", "add", "-b", branch, str(work), "HEAD")
    evidence = Path(_git(root, "rev-parse", "--absolute-git-dir")) / "factory" / run_id
    evidence.mkdir(parents=True)
    report = {"status": "running", "run_id": run_id, "branch": branch,
              "worktree": str(work), "source_commit": _git(root, "rev-parse", "HEAD"),
              "name": spec.name, "plan": [task.model_dump() for task in spec.ordered_tasks()],
              "manifest_sha256": _digest(spec_path), "tasks": [], "gates": [], "artifacts": {}}
    headers, verify = {}, True
    async def save_report():
        report["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (evidence / "report.json").write_text(json.dumps(report, indent=2))
        with (evidence / "events.jsonl").open("a") as journal:
            journal.write(json.dumps({"timestamp": time.time(), "snapshot": report}) + "\n")
        if spec.publish_events:
            async with httpx.AsyncClient(timeout=5, headers=headers, verify=verify) as observer:
                response = await observer.post(api_url.rstrip('/') + '/api/factory/runs',
                                               json={'run_id': run_id, 'snapshot': report})
                response.raise_for_status()

    try:
        protected = {name: _digest(_path(work, name)) for name in spec.protected_files}
        from router.config import settings
        key = os.environ.get("MULLM_API_KEY") or settings.api_key
        headers = {"Authorization": "Bearer " + key} if key else {}
        verify = True
        certificate = Path(settings.ssl_certfile) if settings.ssl_certfile else settings.cache_dir / "certs" / "mullm.crt"
        if urlsplit(api_url).hostname in {"127.0.0.1", "localhost", "::1"} and certificate.is_file():
            verify = ssl.create_default_context(cafile=str(certificate))
        async def await_human(client, card_id, allowed=("retry", "resume"), rejected_status="stopped"):
            report['status'] = 'needs_human'
            report['human_request_id'] = card_id
            await save_report()
            while True:
                response = await client.get(api_url.rstrip('/') + '/api/sessions/' + card_id)
                response.raise_for_status()
                card = response.json()
                if card.get('resolved'):
                    choice = card.get('choice', '')
                    report.setdefault('human_decisions', []).append({'session_id': card_id, 'choice': choice})
                    report.pop('human_request_id', None)
                    if (allowed is not None and choice.strip().lower().removeprefix('1. ').removeprefix('2. ') not in allowed) or (allowed is None and choice.strip().lower() in ('stop','cancel')):
                        report['status'] = rejected_status
                        await save_report()
                        raise RuntimeError('Stopped by human decision: ' + choice)
                    report['status'] = 'running'
                    await save_report()
                    return choice
                await asyncio.sleep(1)

        async def checkpoint(client):
            if spec.publish_events:
                response = await client.get(api_url.rstrip('/') + '/api/sessions')
                response.raise_for_status()
                for card in response.json().get('sessions', []):
                    if card.get('run_id') == run_id and not card.get('resolved'):
                        await await_human(client, card['session_id'])

        await save_report()
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers=headers, verify=verify) as client:
            for question in spec.questions:
                response = await client.post(api_url.rstrip('/') + '/api/agents/blocked', json={
                    'agent_id': 'factory-' + run_id, 'run_id': run_id, 'block_reason': 'clarification',
                    'summary': question.prompt, 'options': question.options, 'severity': 'medium'})
                response.raise_for_status()
                answer = await await_human(client, response.json()['session_id'], allowed=None)
                report.setdefault('answers', {})[question.id] = answer
                await save_report()
            for task in spec.ordered_tasks():
                await checkpoint(client)
                task_report = {"id": task.id, "depends_on": task.depends_on, "status": "running", "attempts": []}
                report["tasks"].append(task_report)
                if task.verification_only:
                    task_report['verification_only'] = True
                    task_report['gates'] = []
                    for name in task.gates:
                        await checkpoint(client)
                        gate = next(g for g in spec.gates if g.name == name)
                        result = await run_gate(work, gate, evidence / f'{task.id}-{name}.log')
                        task_report['gates'].append(result)
                        if result['returncode'] != 0:
                            raise RuntimeError('Verification failed: ' + name)
                        if any(_digest(_path(work, name)) != digest for name, digest in protected.items()):
                            raise RuntimeError('Acceptance files changed during execution')
                    task_report['status'] = 'passed'
                    await save_report()
                    continue
                feedback = ""
                attempt, remaining = 0, task.max_attempts
                while remaining:
                    await checkpoint(client)
                    attempt += 1
                    remaining -= 1
                    attempt_started = time.monotonic()
                    attempt_report = {"attempt": attempt, "gates": []}
                    task_report["attempts"].append(attempt_report)
                    await save_report()
                    context = {name: _path(work, name).read_text()[:20_000]
                               for name in dict.fromkeys(task.writable_files + task.context_files if task.context_files is not None else spec.writable_files + spec.context_files)
                               if _path(work, name).is_file()}
                    prompt = json.dumps({"task": task.instruction, "goals": spec.goals,
                                         "business_rules": spec.business_rules, "preferences": spec.preferences,
                                         "target": spec.target, "files": context, "test_feedback": feedback,
                                         "product_decisions": report.get("answers", {}),
                                         "writable_files": task.writable_files,
                                         "output_contract": {"files": {name: "COMPLETE FILE CONTENT" for name in task.writable_files}},
                                         "instructions": "Return the files object only, using the exact allowed filenames. Write concise code; omit docstrings and commentary."})
                    prefix = f"{task.id}-{attempt}"
                    (evidence / f"{prefix}-prompt.json").write_text(prompt)
                    try:
                        lease_id = None
                        if spec.publish_events:
                            task_report['status'] = 'queued'
                            attempt_report['phase'] = 'waiting_for_inference'
                            await save_report()
                            while lease_id is None:
                                await checkpoint(client)
                                leased = await client.post(api_url.rstrip('/') + '/api/factory/inference-lease', json={'run_id': run_id})
                                leased.raise_for_status()
                                lease_id = leased.json().get('lease_id')
                                if lease_id is None:
                                    await asyncio.sleep(1)
                            task_report['status'] = 'running'
                            attempt_report['phase'] = 'generating'
                            await save_report()
                        try:
                            response = await client.post(api_url.rstrip("/") + "/query", json={
                            "content": prompt, "force_tier": "local", "allow_cloud_escalation": False,
                            "skip_cache": True, "temperature": 0.2, "context": {"think": False, "num_predict": task.max_output_tokens, "format": {
                                "type": "object", "properties": {"files": {"type": "object",
                                    "properties": {name: {"type": "string"} for name in task.writable_files},
                                    "additionalProperties": False, "minProperties": 1}},
                                "required": ["files"], "additionalProperties": False}},
                                "session_id": "factory-" + run_id})
                        finally:
                            if lease_id:
                                released = await client.delete(api_url.rstrip('/') + '/api/factory/inference-lease/' + lease_id)
                                released.raise_for_status()
                        response.raise_for_status()
                        payload = response.json()
                        attempt_report.update({key: payload.get(key) for key in ("model_used", "tokens_used", "latency_ms", "cost", "tier")})
                        (evidence / f"{prefix}-response.json").write_text(json.dumps(payload, indent=2))
                        if payload.get("cost", 0) != 0 or payload.get("tier") not in ("local", "local_multi"):
                            raise RuntimeError("Factory expected local inference; refusing unexpected provider result")
                        await checkpoint(client)
                        apply_candidate(work, spec.model_copy(update={"writable_files": task.writable_files}), payload["response"])
                        attempt_report['phase'] = 'testing'
                        await save_report()
                        for name in task.gates:
                            gate = next(gate for gate in spec.gates if gate.name == name)
                            result = await run_gate(work, gate, evidence / f"{prefix}-{name}.log")
                            attempt_report["gates"].append(result)
                            if any(_digest(_path(work, name)) != digest for name, digest in protected.items()):
                                raise RuntimeError("Acceptance files changed during execution")
                            if result["returncode"] != 0:
                                raise ValueError(f"Gate {name} failed:\n" + Path(result["log"]).read_text(errors="replace")[-6000:])
                        attempt_report["status"] = "passed"
                        task_report["status"] = "passed"
                    except (ValueError, httpx.HTTPError, TimeoutError) as exc:
                        feedback = str(exc)
                        attempt_report.update(status="failed", error=feedback)
                    finally:
                        attempt_report["elapsed_seconds"] = round(time.monotonic() - attempt_started, 3)
                        await save_report()
                    if task_report["status"] == "passed":
                        break
                    if remaining == 0 and spec.human_intervention:
                        task_report['status'] = 'needs_human'
                        response = await client.post(api_url.rstrip('/') + '/api/agents/blocked', json={
                            'agent_id': 'factory-' + run_id, 'run_id': run_id, 'task_id': task.id,
                            'summary': f'{spec.name}: {task.id} needs help after {attempt} attempts. Check the failure details and candidate files, then retry or stop.',
                            'context': feedback[-6000:], 'options': ['Retry', 'Stop'], 'severity': 'high'})
                        response.raise_for_status()
                        await await_human(client, response.json()['session_id'])
                        task_report['status'] = 'running'
                        remaining = task.max_attempts
                if task_report['status'] != 'passed':
                    task_report["status"] = "failed"
                    raise RuntimeError(f"Task {task.id} exhausted {task.max_attempts} attempts: {feedback}")
        for index, gate in enumerate(spec.gates):
            if gate.kind == 'human':
                async with httpx.AsyncClient(timeout=5, headers=headers, verify=verify) as reviewer:
                    response = await reviewer.post(api_url.rstrip('/') + '/api/agents/blocked', json={
                        'agent_id': 'factory-' + run_id, 'run_id': run_id, 'block_reason': 'product_review',
                        'summary': gate.prompt, 'context': 'Candidate worktree: ' + str(work),
                        'options': ['Accept', 'Reject'], 'severity': 'high',
                        'links': [{'label': 'Open candidate preview', 'url': gate.review_url}] if gate.review_url else []})
                    response.raise_for_status()
                    card_id = response.json()['session_id']
                    await await_human(reviewer, card_id, allowed=('accept',), rejected_status='rejected')
                    report['gates'].append({'name': gate.name, 'kind': 'human', 'returncode': 0, 'decision_id': card_id})
                continue
            if spec.publish_events:
                async with httpx.AsyncClient(timeout=5, headers=headers, verify=verify) as control_client:
                    await checkpoint(control_client)
            result = await run_gate(work, gate, evidence / f"gate-{index}.log")
            report["gates"].append(result)
            if result["returncode"] != 0:
                raise RuntimeError(f"Acceptance gate failed: {gate.name}")
            if any(_digest(_path(work, name)) != digest for name, digest in protected.items()):
                raise RuntimeError("Acceptance files changed during execution")
        for name in spec.artifacts:
            path = _path(work, name)
            if not path.is_file() or not path.stat().st_size:
                raise RuntimeError(f"Missing or empty deliverable: {name}")
            report["artifacts"][name] = {"sha256": _digest(path), "bytes": path.stat().st_size}
        report["status"] = "accepted"
    except asyncio.CancelledError:
        report["status"] = "cancelled"
        raise
    except Exception as exc:
        if report["status"] not in ("stopped", "rejected"):
            report["status"] = "failed"
        report["error"] = str(exc)
    finally:
        if report["status"] in ("stopped", "failed", "cancelled", "rejected"):
            for task_report in report["tasks"]:
                if task_report["status"] != "passed":
                    task_report["status"] = report["status"]
        try:
            await save_report()
        except httpx.HTTPError as exc:
            report['observation_error'] = str(exc)
            (evidence / 'report.json').write_text(json.dumps(report, indent=2))
    return report


async def run_batch(manifest: Path, api_url: str, *, dry_run=False) -> dict:
    data = tomllib.loads(manifest.read_text())
    projects = data.get('projects', [])
    if not projects:
        raise ValueError('Batch manifest requires projects')
    jobs = []
    roots = set()
    for project in projects:
        root = _path(manifest.parent.resolve(), project['root']).resolve()
        if root in roots:
            raise ValueError('Batch projects must have different roots')
        roots.add(root)
        spec = _path(root, project.get('spec', 'factory.toml'))
        config = FactorySpec.model_validate(tomllib.loads(spec.read_text()))
        if not config.publish_events:
            raise ValueError('Parallel projects require event publishing and inference scheduling')
        if not dry_run and _git(root, 'status', '--porcelain'):
            raise ValueError('Batch project must be clean: ' + str(root))
        jobs.append((spec, root))
    results = await asyncio.gather(*(run_factory(spec, root, api_url, dry_run=dry_run) for spec, root in jobs), return_exceptions=True)
    reports = [result if isinstance(result, dict) else {'status': 'failed', 'error': str(result)} for result in results]
    return {'status': ('planned' if dry_run else 'accepted') if all(r['status'] == ('planned' if dry_run else 'accepted') for r in reports) else 'incomplete', 'projects': reports}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path, nargs="?")
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--server-url", default="https://127.0.0.1:6856")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    if args.batch:
        report = asyncio.run(run_batch(args.batch.resolve(), args.server_url, dry_run=args.dry_run))
    else:
        if args.spec is None:
            parser.error('spec or --batch is required')
        report = asyncio.run(run_factory(args.spec, args.root.resolve(), args.server_url, dry_run=args.dry_run))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in ("accepted", "planned") else 1


if __name__ == "__main__":
    raise SystemExit(main())
