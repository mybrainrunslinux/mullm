"""Software Factory: isolated, local-inference builds with executable acceptance gates."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import tomllib
import uuid

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator


class Gate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    command: list[str] = Field(min_length=1)
    timeout_seconds: int = Field(default=120, ge=1, le=3600)


class FactorySpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    target: str = "game"
    goals: list[str] = Field(min_length=1)
    business_rules: list[str] = []
    preferences: list[str] = []
    tasks: list[str] = Field(min_length=1)
    writable_files: list[str] = Field(min_length=1)
    protected_files: list[str] = Field(min_length=1)
    artifacts: list[str] = Field(min_length=1)
    gates: list[Gate] = Field(min_length=1)

    @model_validator(mode="after")
    def safe_paths(self):
        for value in self.writable_files + self.protected_files + self.artifacts:
            path = Path(value)
            if path.is_absolute() or ".." in path.parts or ".git" in path.parts or not path.parts:
                raise ValueError(f"Expected relative project path: {value}")
        if set(self.writable_files) & set(self.protected_files):
            raise ValueError("Acceptance files must not be writable by the model")
        return self


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
        if not isinstance(content, str) or len(content.encode()) > 1_000_000:
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
              "manifest_sha256": _digest(spec_path), "gates": [], "artifacts": {}}
    try:
        protected = {name: _digest(_path(work, name)) for name in spec.protected_files}
        headers = {"Authorization": "Bearer " + os.environ["MULLM_API_KEY"]} if os.environ.get("MULLM_API_KEY") else {}
        async with httpx.AsyncClient(timeout=30, follow_redirects=False, headers=headers) as client:
            for task in spec.tasks:
                context = {name: _path(work, name).read_text()[:20_000]
                           for name in spec.writable_files if _path(work, name).is_file()}
                prompt = json.dumps({"task": task, "goals": spec.goals,
                                     "business_rules": spec.business_rules, "preferences": spec.preferences,
                                     "target": spec.target, "files": context,
                                     "writable_files": spec.writable_files,
                                     "output_contract": 'Return only JSON: {"files":{"relative/path":"complete file content"}}'})
                response = await client.post(api_url.rstrip("/") + "/query", json={
                    "content": prompt, "force_tier": "local", "allow_cloud_escalation": False,
                    "skip_cache": True, "session_id": "factory-" + run_id})
                response.raise_for_status()
                payload = response.json()
                if payload.get("cost", 0) != 0 or payload.get("tier") not in ("local", "local_multi"):
                    raise RuntimeError("Factory expected local inference; refusing unexpected provider result")
                apply_candidate(work, spec, payload["response"])
        for index, gate in enumerate(spec.gates):
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
        report["status"] = "failed"
        report["error"] = str(exc)
    finally:
        (evidence / "report.json").write_text(json.dumps(report, indent=2))
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--server-url", default="http://127.0.0.1:6856")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    report = asyncio.run(run_factory(args.spec, args.root.resolve(), args.server_url, dry_run=args.dry_run))
    print(json.dumps(report, indent=2))
    return 0 if report["status"] in ("accepted", "planned") else 1


if __name__ == "__main__":
    raise SystemExit(main())
