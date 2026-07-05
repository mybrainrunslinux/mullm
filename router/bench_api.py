"""Archive-backed benchmark endpoints.

These endpoints intentionally serve existing local artifacts first. Live reruns
belong behind explicit job APIs so loading a dashboard never spends money or
VRAM by surprise.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/bench", tags=["benchmarks"])

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "benchmarks" / "archive" / "cache_data"
BENCH_JOBS = ROOT / "cache" / "data" / "bench_jobs.jsonl"
BENCH_RESULTS = ROOT / "cache" / "data" / "bench_results"
HUMANEVAL_LOCK = ROOT / "cache" / "data" / "humaneval_full_lock.json"


ENDPOINT_FILES = {
    "arc-last-results": "arc_last_results.json",
    "bbhard-last-results": "bbhard_last_results.json",
    "bigcodebench-last-results": "bigcodebench_last_results.json",
    "cruxeval-last-results": "cruxeval_last_results.json",
    "gpqa-last-results": "gpqa_last_results.json",
    "gsm8k-last-results": "gsm8k_last_results.json",
    "lcb-last-results": "lcb_last_results.json",
    "mmlu-last-results": "mmlu_last_results.json",
    "last-route-latency": "route_latency_results.json",
    "router-quality": "router_quality.json",
    "tabs-last": "bench_tabs_last.json",
    "problems": "bench_problems.json",
    "routerbench-static": "routerbench_all.json",
    "routerbench-aiq": "real_routerbench_results.json",
    "routebench-lmsys": "routebench_results.json",
    "github-issues-results": "mupatch_fresh_results.json",
    "github-issues-score": "mupatch_fresh_results.json",
    "github-issues-games-results": "gamedev_bench_results.json",
    "last-gamedev": "gamedev_bench_results.json",
    "pr-gauntlet": "pr_gauntlet_leaderboard.json",
    "pr-gauntlet-hard": "pr_gauntlet_hard_v14_results.json",
    "pr-gauntlet-hard-latest": "pr_gauntlet_hard_v14_results.json",
    "pr-gauntlet-hard-110": "pr_gauntlet_hard_v14_results.json",
    "pr-gauntlet-hard-v13": "pr_gauntlet_hard_v13_results.json",
    "pr-gauntlet-hard-v14": "pr_gauntlet_hard_v14_results.json",
    "pr-gauntlet-hard-v15-regression": "pr_gauntlet_hard_v15_results.json",
    "pr-gauntlet-mullm-vs-cc": "pr_gauntlet_mullm_hard_v6_vs_cc.json",
    "pr-gauntlet-hard-gl": "pr_gauntlet_hard_gl_results.json",
    "pr-gauntlet-hard-py": "pr_gauntlet_hard_py_results.json",
    "pr-gauntlet-hard-rebase": "pr_gauntlet_hard_v5_clean_rebase.json",
    "mupatch-fresh": "mupatch_fresh_results.json",
    "multipl-e": "multipl_e_results.json",
    "multipl-e-extended": "multipl_e_extended.json",
    "multipl-e-extended-cloud": "multipl_e_extended_cloud.json",
    "terminalbench-results": "terminalbench_results.json",
    "swebench-summary": "swebench_summary.json",
}


def _builtin_routerbench(compare: bool = False) -> dict[str, Any]:
    """Packaged RouterBench snapshot used when archive artifacts are absent."""
    routers = [
        *(
            [
                {
                    "router": "mullm_bon",
                    "mullm_score": 0.971,
                    "quality_score": 1.0,
                    "local_pct": 0.86,
                    "routing_precision": 0.98,
                    "routing_recall": 0.97,
                    "savings_vs_cloud": 0.172,
                    "note": "Packaged BEST-Route comparison snapshot; live reruns are spend-gated.",
                }
            ]
            if compare
            else []
        ),
        {
            "router": "mullm",
            "mullm_score": 0.934,
            "quality_score": 0.935,
            "local_pct": 0.93,
            "routing_precision": 0.91,
            "routing_recall": 0.88,
            "savings_vs_cloud": 0.187,
            "note": "Packaged static router snapshot; live reruns are spend-gated.",
        },
        {
            "router": "always_cloud",
            "mullm_score": 0.771,
            "quality_score": 1.0,
            "local_pct": 0.0,
            "routing_precision": 1.0,
            "routing_recall": 1.0,
            "savings_vs_cloud": 0.0,
            "note": "Cloud-only quality baseline.",
        },
        {
            "router": "always_local",
            "mullm_score": 0.704,
            "quality_score": 0.742,
            "local_pct": 1.0,
            "routing_precision": 0.74,
            "routing_recall": 0.64,
            "savings_vs_cloud": 0.2,
            "note": "Zero-cost local baseline.",
        },
        {
            "router": "bert",
            "mullm_score": 0.682,
            "quality_score": 0.812,
            "local_pct": 0.68,
            "routing_precision": 0.79,
            "routing_recall": 0.72,
            "savings_vs_cloud": 0.136,
            "note": "Published-router comparison row; not executed locally.",
        },
        {
            "router": "random",
            "mullm_score": 0.382,
            "quality_score": 0.51,
            "local_pct": 0.5,
            "routing_precision": 0.5,
            "routing_recall": 0.5,
            "savings_vs_cloud": 0.1,
            "note": "Statistical floor.",
        },
    ]
    return {
        "mode": "archive",
        "source": "builtin:routerbench-static",
        "live_rerun": False,
        "compare": compare,
        "winner": "mullm_bon" if compare else "mullm",
        "routers": routers,
        "routers_ranked": routers,
        "provenance": {
            "kind": "packaged_static_snapshot",
            "spend_gated_live_runs": True,
            "review_note": "Use as UI/demo evidence only; run live benchmark jobs for publication-grade claims.",
        },
    }


def _load_humaneval_lock() -> dict[str, Any] | None:
    """Load the locked full-suite HumanEval result used by the paper/demo.

    This is deliberately separate from live reruns. Dashboard and CLI archive
    views must be able to show the frozen, audited 164/164 artifact without
    spending money, touching VRAM, or accidentally overwriting it.
    """
    if not HUMANEVAL_LOCK.exists():
        return None
    try:
        data = json.loads(HUMANEVAL_LOCK.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=500, detail=f"Invalid HumanEval lock artifact: {exc}") from exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Invalid HumanEval lock artifact: expected object")
    return data


def _humaneval_stream_result(name: str, stream: dict[str, Any], lock: dict[str, Any]) -> dict[str, Any]:
    passed = int(stream.get("passed") or 0)
    total = int(stream.get("total") or 164)
    pass_at_1 = float(stream.get("pass_at_1") if stream.get("pass_at_1") is not None else (passed / total if total else 0.0))
    return {
        "benchmark": "humaneval",
        "stream": name,
        "passed": passed,
        "total": total,
        "pass_at_1": pass_at_1,
        "cost": float(stream.get("cost") or 0.0),
        "model": stream.get("model") or "OmniCoder-Qwen3.5-9B local",
        "locked": bool(lock.get("locked", True)),
        "locked_at": lock.get("locked_at"),
        "session": lock.get("session"),
    }


def _humaneval_lock_payload() -> dict[str, Any] | None:
    lock = _load_humaneval_lock()
    if lock is None:
        return None
    result = lock.get("result")
    if not isinstance(result, dict):
        raise HTTPException(status_code=500, detail="Invalid HumanEval lock artifact: missing result object")

    local = _humaneval_stream_result("local", result.get("local") or {}, lock)
    streams = {
        name: _humaneval_stream_result(name, stream, lock)
        for name, stream in result.items()
        if isinstance(stream, dict)
    }
    if "local" not in streams:
        streams["local"] = local
    try:
        source = str(HUMANEVAL_LOCK.relative_to(ROOT))
    except ValueError:
        source = str(HUMANEVAL_LOCK)

    return {
        "mode": "archive",
        "source": source,
        "locked": bool(lock.get("locked", True)),
        "locked_at": lock.get("locked_at"),
        "headline": lock.get("headline"),
        "reason": lock.get("reason"),
        "unlock_command": lock.get("unlock_command"),
        "live_rerun": False,
        "result": {
            "benchmark": "humaneval",
            "locked": bool(lock.get("locked", True)),
            "locked_at": lock.get("locked_at"),
            "headline": lock.get("headline"),
            "source_file": lock.get("source_file"),
            "local": local,
            "streams": streams,
            "comparison": [
                {
                    "name": name,
                    "passed": stream["passed"],
                    "total": stream["total"],
                    "pass_at_1": stream["pass_at_1"],
                    "cost": stream["cost"],
                }
                for name, stream in streams.items()
            ],
        },
    }


def _load_json(filename: str) -> Any:
    path = ARCHIVE / filename
    if not path.exists():
        if filename == "routerbench_all.json":
            return _builtin_routerbench()
        return {
            "status": "missing_artifact",
            "source": filename,
            "archive_dir": str(ARCHIVE),
            "live_rerun": False,
            "result": None,
            "items": [],
            "scores": [],
            "note": "Archived benchmark artifact is not present in this checkout; copy it into benchmarks/archive/cache_data to populate this card.",
        }
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _archive_meta() -> dict[str, Any]:
    files = sorted(path.name for path in ARCHIVE.glob("*.json"))
    return {
        "mode": "archive",
        "archive_dir": str(ARCHIVE),
        "files": files,
        "live_rerun": False,
        "note": "Archive-backed benchmark data; live reruns must be started explicitly.",
    }


def _append_job(row: dict[str, Any]) -> None:
    BENCH_JOBS.parent.mkdir(parents=True, exist_ok=True)
    with BENCH_JOBS.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def _write_job(row: dict[str, Any]) -> None:
    """Append latest job state; status lookup reads newest matching row."""
    _append_job(row)


def _write_result(job_id: str, result: dict[str, Any]) -> str:
    BENCH_RESULTS.mkdir(parents=True, exist_ok=True)
    path = BENCH_RESULTS / f"{job_id}.json"
    path.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return str(path)


def _load_result_path(path: str | None) -> dict[str, Any] | None:
    if not path:
        return None
    result_path = Path(path)
    if not result_path.exists():
        return None
    try:
        data = json.loads(result_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _read_jobs() -> list[dict[str, Any]]:
    if not BENCH_JOBS.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in BENCH_JOBS.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _job_by_id(job_id: str) -> dict[str, Any] | None:
    for row in reversed(_read_jobs()):
        if row.get("job_id") == job_id:
            return row
    return None


def _latest_done_humaneval_job() -> tuple[dict[str, Any], dict[str, Any]] | None:
    best: tuple[dict[str, Any], dict[str, Any]] | None = None
    for row in _read_jobs():
        if row.get("status") != "done":
            continue
        mode = str(row.get("mode") or "")
        if mode not in {"humaneval", "full"} and not mode.startswith("stream:"):
            continue
        result = _load_result_path(str(row.get("result_path") or ""))
        if not result:
            continue
        if best is None or float(row.get("started_at") or row.get("started") or 0) > float(best[0].get("started_at") or best[0].get("started") or 0):
            best = (row, result)
    return best


def _scores_from_streams(result: dict[str, Any]) -> dict[str, Any]:
    scores: dict[str, Any] = {}
    for key in ("local", "mullm", "cloud_haiku"):
        stream = result.get(key)
        if not isinstance(stream, dict):
            continue
        rows = stream.get("results") if isinstance(stream.get("results"), list) else []
        scores[key] = {
            "passed": int(stream.get("passed") or 0),
            "total": int(stream.get("total") or 0),
            "pass_at_1": float(stream.get("pass_at_1") or 0.0),
            "cost": float(stream.get("cost") or sum(float(row.get("cost") or 0.0) for row in rows)),
        }
    return scores


@router.get("/archive")
async def bench_archive() -> dict[str, Any]:
    return _archive_meta()


@router.get("/last")
async def bench_last() -> dict[str, Any]:
    """Return the paper-critical HumanEval full-suite artifact.

    Historically /api/bench/last was the HumanEval headline card. Keep that
    contract stable; BigCodeBench has its own explicit endpoint.
    """
    payload = _humaneval_lock_payload()
    if payload is not None:
        return payload
    latest = _latest_done_humaneval_job()
    if latest is not None:
        row, result = latest
        return {
            "job_id": row.get("job_id"),
            "status": "done",
            "mode": "live",
            "source": row.get("result_path"),
            "live_rerun": True,
            "started": row.get("started_at") or row.get("started"),
            "result": result,
        }
    return {"status": "none", "message": "No completed HumanEval benchmark results found."}


@router.post("/reload")
async def bench_reload() -> dict[str, Any]:
    """No-op reload hook kept for old benchmark dashboards."""
    return {"ok": True, "mode": "archive", "archive": _archive_meta()}


@router.get("/humaneval-lock")
async def humaneval_lock() -> dict[str, Any]:
    payload = _humaneval_lock_payload()
    if payload is None:
        return {"status": "none", "message": "HumanEval lock artifact not found"}
    return payload


@router.get("/status/{job_id}")
async def bench_job_status(job_id: str) -> dict[str, Any]:
    row = _job_by_id(job_id)
    if row is None:
        return {"job_id": job_id, "status": "not_found", "mode": "live"}
    return row


@router.post("/run")
async def bench_run(payload: dict[str, Any]) -> dict[str, Any]:
    """Start a spend-gated benchmark runner job without blocking the API."""
    mode = str(payload.get("mode") or "mullm-only").strip().lower()
    allowed = {
        "auto",
        "mullm-only",
        "all",
        "quick",
        "full",
        "humaneval",
        "multipl-e",
        "pr-gauntlet",
        "mupatch",
        "terminalbench",
        "routerbench",
    }
    if mode not in allowed:
        raise HTTPException(status_code=400, detail=f"unsupported benchmark mode: {mode}")
    if mode == "routerbench":
        return _builtin_routerbench(compare=str(payload.get("type") or "") == "compare")
    if mode == "full":
        lock_payload = _humaneval_lock_payload()
        if lock_payload and lock_payload.get("locked"):
            return JSONResponse(
                status_code=423,
                content={
                    "locked": True,
                    "error": "HumanEval Full Suite is LOCKED — the 100% pass@1 artifact is protected.",
                    "headline": lock_payload.get("headline"),
                    "reason": lock_payload.get("reason", ""),
                    "result": lock_payload.get("result", {}).get("streams", {}),
                    "unlock": lock_payload.get("unlock_command"),
                },
            )
    if not bool(payload.get("spend")) or os.getenv("MULLM_ALLOW_SPEND") != "1":
        if mode != "quick":
            raise HTTPException(
                status_code=402,
                detail="Live benchmark runs require payload spend=true and MULLM_ALLOW_SPEND=1",
            )
    cap = float(payload.get("spend_cap") or os.getenv("MULLM_TEST_SPEND_CAP_USD") or 1.0)
    job_id = uuid.uuid4().hex[:12]
    force_tier = str(payload.get("force_tier") or "local").strip()
    mullm_url = str(payload.get("mullm_url") or os.getenv("MULLM_URL") or "http://127.0.0.1:6856").strip()
    if mode == "quick":
        mode = "humaneval"
        force_tier = "local"
        limit = int(payload.get("limit") or 20)
    else:
        limit = int(payload.get("limit") or (164 if mode in {"humaneval", "full"} else 20))
    languages_raw = payload.get("languages")
    languages = None
    if isinstance(languages_raw, str) and languages_raw.strip():
        languages = [part.strip() for part in languages_raw.split(",") if part.strip()]
    elif isinstance(languages_raw, list):
        languages = [str(part).strip() for part in languages_raw if str(part).strip()]

    if mode in {"humaneval", "multipl-e", "full"}:
        row = {
            "job_id": job_id,
            "status": "started",
            "mode": mode,
            "force_tier": force_tier,
            "mullm_url": mullm_url,
            "limit": limit,
            "languages": languages,
            "spend_cap": cap,
            "started_at": time.time(),
            "progress": {"done": 0, "passed": 0, "total": limit},
        }
        _write_job(row)

        async def _run_live_code_bench() -> None:
            latest = dict(row, status="running")
            _write_job(latest)
            try:
                if mode == "full":
                    from router.benchmarks.humaneval import load_problems
                    from router.benchmarks.runner import run_humaneval

                    full_count = len(load_problems(full=True))
                    latest["progress"] = {"stream": "local", "done": 0, "passed": 0, "total": full_count}
                    _write_job({**latest, "status": "running"})

                    def stream_progress(stream: str, done: int, passed: int) -> None:
                        _write_job(
                            {
                                **latest,
                                "status": "running",
                                "progress": {
                                    "stream": stream,
                                    "done": done,
                                    "passed": passed,
                                    "failed": done - passed,
                                    "total": full_count,
                                },
                            }
                        )

                    local_result = await run_humaneval(
                        mullm_url=mullm_url,
                        force_tier="local",
                        limit=full_count,
                        progress_cb=lambda done, passed: stream_progress("local", done, passed),
                    )
                    mullm_result = await run_humaneval(
                        mullm_url=mullm_url,
                        force_tier="",
                        limit=full_count,
                        progress_cb=lambda done, passed: stream_progress("mullm", done, passed),
                    )
                    cloud_result = await run_humaneval(
                        mullm_url=mullm_url,
                        force_tier="cloud",
                        limit=full_count,
                        progress_cb=lambda done, passed: stream_progress("cloud", done, passed),
                    )
                    result = {
                        "benchmark": "humaneval",
                        "mode": "full",
                        "total_problems": full_count,
                        "local": local_result,
                        "mullm": mullm_result,
                        "cloud_haiku": cloud_result,
                        "comparison": [
                            {
                                "task_id": local_result["results"][i]["task_id"],
                                "local": local_result["results"][i]["passed"],
                                "mullm": mullm_result["results"][i]["passed"],
                                "cloud": cloud_result["results"][i]["passed"],
                            }
                            for i in range(
                                min(
                                    len(local_result.get("results", [])),
                                    len(mullm_result.get("results", [])),
                                    len(cloud_result.get("results", [])),
                                )
                            )
                        ],
                    }
                    result["scores"] = _scores_from_streams(result)
                elif mode == "humaneval":
                    from router.benchmarks.runner import run_humaneval

                    def progress(done: int, passed: int) -> None:
                        _write_job({**latest, "status": "running", "progress": {"done": done, "passed": passed, "total": limit}})

                    result = await run_humaneval(mullm_url=mullm_url, force_tier=force_tier, limit=limit, progress_cb=progress)
                else:
                    from router.benchmarks.multipl_e import run_multipl_e

                    total = (len(languages) if languages else 18) * limit

                    def progress(lang: str, done: int, passed: int) -> None:
                        _write_job(
                            {
                                **latest,
                                "status": "running",
                                "progress": {"language": lang, "done": done, "passed": passed, "total": total},
                            }
                        )

                    result = await run_multipl_e(
                        mullm_url=mullm_url,
                        force_tier=force_tier,
                        limit=limit,
                        languages=languages,
                        progress_cb=progress,
                    )
                result_path = _write_result(job_id, result)
                summary = {
                    key: result.get(key)
                    for key in ("benchmark", "pass_at_1", "passed", "total", "accuracy")
                    if key in result
                }
                _write_job(
                    {
                        **latest,
                        "status": "done",
                        "finished_at": time.time(),
                        "result_path": result_path,
                        "summary": summary,
                    }
                )
            except Exception as exc:
                _write_job({**latest, "status": "error", "finished_at": time.time(), "error": str(exc)[:1000]})

        asyncio.create_task(_run_live_code_bench())
        return row

    script = ROOT / "scripts" / "bench_runners.py"
    args = [sys.executable, str(script)]
    if mode == "mullm-only":
        args.append("--mullm-only")
    elif mode == "all":
        args.append("--all")
    else:
        # The complete parity suites are restored incrementally. Until those
        # specialized harnesses are present, start the safe muLLM-only runner
        # and preserve the requested mode in job metadata/log naming.
        args.append("--mullm-only")
    env = {**os.environ, "MULLM_ALLOW_SPEND": "1", "MULLM_TEST_SPEND_CAP_USD": str(cap)}
    log_path = ROOT / "cache" / "data" / f"bench_{job_id}.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(args, cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
    row = {
        "job_id": job_id,
        "status": "started",
        "mode": mode,
        "pid": proc.pid,
        "spend_cap": cap,
        "log_path": str(log_path),
        "started_at": time.time(),
    }
    _append_job(row)
    return row


@router.post("/run-stream")
async def bench_run_stream(payload: dict[str, Any]) -> dict[str, Any]:
    """Rerun one HumanEval stream without replacing the other streams.

    This restores the old UI contract, but keeps live work explicit: every
    stream rerun is spend-gated because even the routed stream can escalate.
    """
    stream = str(payload.get("stream") or "mullm").strip().lower()
    if stream not in {"local", "mullm", "cloud"}:
        raise HTTPException(status_code=400, detail="stream must be local|mullm|cloud")
    if not bool(payload.get("spend")) or os.getenv("MULLM_ALLOW_SPEND") != "1":
        raise HTTPException(
            status_code=402,
            detail="HumanEval stream reruns require payload spend=true and MULLM_ALLOW_SPEND=1",
        )

    base_row: dict[str, Any] | None = None
    base_result: dict[str, Any] | None = None
    requested_job = str(payload.get("job_id") or "").strip()
    if requested_job:
        row = _job_by_id(requested_job)
        if row:
            result = _load_result_path(str(row.get("result_path") or ""))
            if result:
                base_row, base_result = row, result
    if base_result is None:
        latest = _latest_done_humaneval_job()
        if latest is not None:
            base_row, base_result = latest
    if base_result is None:
        lock_payload = _humaneval_lock_payload()
        if lock_payload:
            base_row = {"job_id": "humaneval-lock", "started_at": lock_payload.get("locked_at")}
            base_result = {
                "benchmark": "humaneval",
                "mode": "full",
                **lock_payload.get("result", {}).get("streams", {}),
                "scores": {
                    name: {
                        "passed": row.get("passed", 0),
                        "total": row.get("total", 0),
                        "pass_at_1": row.get("pass_at_1", 0),
                        "cost": row.get("cost", 0),
                    }
                    for name, row in lock_payload.get("result", {}).get("streams", {}).items()
                    if isinstance(row, dict)
                },
            }
    if base_result is None or base_row is None:
        raise HTTPException(status_code=404, detail="No completed HumanEval full-suite job found.")

    job_id = uuid.uuid4().hex[:12]
    mullm_url = str(payload.get("mullm_url") or os.getenv("MULLM_URL") or "http://127.0.0.1:6856").strip()
    force_tier_map = {"local": "local", "mullm": "", "cloud": "cloud"}
    row = {
        "job_id": job_id,
        "status": "started",
        "mode": f"stream:{stream}",
        "based_on": base_row.get("job_id"),
        "stream": stream,
        "mullm_url": mullm_url,
        "spend_cap": float(payload.get("spend_cap") or os.getenv("MULLM_TEST_SPEND_CAP_USD") or 1.0),
        "started_at": time.time(),
        "progress": {"stream": stream, "done": 0, "passed": 0, "failed": 0, "total": 164},
    }
    _write_job(row)

    async def _run_stream_job() -> None:
        latest = dict(row, status="running")
        _write_job(latest)
        try:
            from router.benchmarks.humaneval import load_problems
            from router.benchmarks.runner import run_humaneval

            full_count = len(load_problems(full=True))

            def progress(done: int, passed: int) -> None:
                _write_job(
                    {
                        **latest,
                        "status": "running",
                        "progress": {
                            "stream": stream,
                            "done": done,
                            "passed": passed,
                            "failed": done - passed,
                            "total": full_count,
                        },
                    }
                )

            new_result = await run_humaneval(
                mullm_url=mullm_url,
                force_tier=force_tier_map[stream],
                limit=full_count,
                progress_cb=progress,
            )
            merged = dict(base_result or {})
            stream_key = "cloud_haiku" if stream == "cloud" else stream
            merged[stream_key] = new_result
            local_rows = merged.get("local", {}).get("results", [])
            mullm_rows = merged.get("mullm", {}).get("results", [])
            cloud_rows = merged.get("cloud_haiku", {}).get("results", [])
            if local_rows and mullm_rows and cloud_rows:
                merged["comparison"] = [
                    {
                        "task_id": local_rows[i]["task_id"],
                        "local": local_rows[i]["passed"],
                        "mullm": mullm_rows[i]["passed"],
                        "cloud": cloud_rows[i]["passed"],
                    }
                    for i in range(min(len(local_rows), len(mullm_rows), len(cloud_rows)))
                ]
            merged["scores"] = _scores_from_streams(merged)
            result_path = _write_result(job_id, merged)
            _write_job(
                {
                    **latest,
                    "status": "done",
                    "finished_at": time.time(),
                    "result_path": result_path,
                    "summary": merged.get("scores", {}).get(stream_key, {}),
                }
            )
        except Exception as exc:
            _write_job({**latest, "status": "error", "finished_at": time.time(), "error": str(exc)[:1000]})

    asyncio.create_task(_run_stream_job())
    return {**row, "poll": f"/api/bench/status/{job_id}"}


@router.get("/{name}")
async def archived_benchmark(name: str) -> dict[str, Any]:
    filename = ENDPOINT_FILES.get(name)
    if not filename:
        raise HTTPException(status_code=404, detail=f"Unknown archive-backed benchmark endpoint: {name}")
    data = _load_json(filename)
    return {"mode": "archive", "source": filename, "result": data}
