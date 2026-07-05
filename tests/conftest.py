"""
Pytest session plugin — records test results to cache/data/test_runs.jsonl.
Each run appends one JSON line with pass/fail/skip counts and per-test outcomes.
"""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

_results: list[dict] = []
_start_time: float | None = None
_LOG_PATH = Path(__file__).parent.parent / "cache" / "data" / "test_runs.jsonl"
_MAX_MSG_BYTES = 2048


def pytest_sessionstart(session):
    global _start_time, _results
    _start_time = time.time()
    _results = []


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.skipped):
        msg = None
        if report.failed and report.longrepr:
            raw = str(report.longrepr)
            msg = raw[:_MAX_MSG_BYTES] + ("…" if len(raw) > _MAX_MSG_BYTES else "")
        _results.append({
            "name": report.nodeid,
            "outcome": report.outcome,
            "duration_s": round(report.duration, 3),
            "message": msg,
        })


def pytest_sessionfinish(session, exitstatus):
    if not _results:
        return

    try:
        git_sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL, text=True
        ).strip()
    except Exception:
        git_sha = "unknown"

    passed = sum(1 for r in _results if r["outcome"] == "passed")
    failed = sum(1 for r in _results if r["outcome"] == "failed")
    skipped = sum(1 for r in _results if r["outcome"] == "skipped")

    record = {
        "run_id": time.strftime("%Y%m%d_%H%M%S", time.gmtime()),
        "ts": round(time.time(), 3),
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "total": len(_results),
        "duration_s": round(time.time() - (_start_time or time.time()), 2),
        "git_sha": git_sha,
        "tests": _results,
    }

    try:
        _LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_PATH, "a") as f:
            f.write(json.dumps(record) + "\n")
    except Exception as e:
        print(f"\n[conftest] Warning: could not write test_runs.jsonl: {e}")
