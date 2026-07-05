"""Lightweight scheduled classifier retraining runner.

The scheduler is intentionally conservative: it validates the configured CSV
and runs `scripts/retrain_classifier.py --dry-run` unless the operator disables
`classifier_retrain_dry_run`.
"""

from __future__ import annotations

import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Any

from router.config import settings

STATE_PATH = settings.cache_dir / "classifier_retrain_state.json"
_task: asyncio.Task | None = None
_stop_event: asyncio.Event | None = None


def _read_state() -> dict[str, Any]:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_state(state: dict[str, Any]) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _interval_seconds(schedule: str) -> int | None:
    value = (schedule or "off").strip().lower()
    if value in {"", "off", "manual"}:
        return None
    if value == "hourly":
        return 3600
    if value == "daily":
        return 86400
    if value == "weekly":
        return 604800
    if value.startswith("every:"):
        raw = value.split(":", 1)[1].strip()
        unit = raw[-1:]
        try:
            amount = int(raw[:-1] if unit in "smhd" else raw)
        except ValueError:
            return None
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}.get(unit, 1)
        return max(60, amount * mult)
    return None


def _count_samples(path: Path) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "query" not in (reader.fieldnames or []) or "category" not in (reader.fieldnames or []):
            raise ValueError("CSV must have query and category columns")
        return sum(1 for row in reader if (row.get("query") or "").strip())


def status() -> dict[str, Any]:
    state = _read_state()
    interval = _interval_seconds(settings.classifier_retrain_schedule)
    data_path = Path(settings.classifier_retrain_data_path).expanduser() if settings.classifier_retrain_data_path else None
    sample_count = None
    error = ""
    if data_path:
        try:
            sample_count = _count_samples(data_path)
        except Exception as exc:
            error = str(exc)
    last_started = float(state.get("last_started_at") or 0)
    next_due = last_started + interval if interval and last_started else None
    return {
        "enabled": settings.classifier_retrain_enabled,
        "schedule": settings.classifier_retrain_schedule,
        "interval_seconds": interval,
        "dry_run": settings.classifier_retrain_dry_run,
        "mode": settings.classifier_retrain_mode,
        "data_path": str(data_path) if data_path else "",
        "data_exists": bool(data_path and data_path.exists()),
        "sample_count": sample_count,
        "min_samples": settings.classifier_retrain_min_samples,
        "output_path": settings.classifier_retrain_output_path,
        "last_started_at": state.get("last_started_at"),
        "last_finished_at": state.get("last_finished_at"),
        "last_returncode": state.get("last_returncode"),
        "last_output_tail": state.get("last_output_tail", ""),
        "next_due_at": next_due,
        "running": _task is not None and not _task.done(),
        "error": error or state.get("error", ""),
    }


async def run_once(force: bool = False) -> dict[str, Any]:
    data = Path(settings.classifier_retrain_data_path).expanduser() if settings.classifier_retrain_data_path else None
    if data is None or not data.exists():
        raise FileNotFoundError("classifier_retrain_data_path is not set or does not exist")
    samples = _count_samples(data)
    if samples < settings.classifier_retrain_min_samples and not force:
        raise ValueError(
            f"Need at least {settings.classifier_retrain_min_samples} samples, got {samples}"
        )

    output = settings.classifier_retrain_output_path or str(
        Path.home() / ".mullm" / "models" / "routing-classifier-scheduled"
    )
    cmd = [
        "python",
        "scripts/retrain_classifier.py",
        "--data",
        str(data),
        "--output",
        output,
        "--mode",
        settings.classifier_retrain_mode,
    ]
    if settings.classifier_retrain_dry_run:
        cmd.append("--dry-run")

    started = time.time()
    _write_state({"last_started_at": started, "error": ""})
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.STDOUT,
    )
    stdout, _ = await proc.communicate()
    text = stdout.decode(errors="replace")
    state = {
        "last_started_at": started,
        "last_finished_at": time.time(),
        "last_returncode": proc.returncode,
        "last_output_tail": text[-4000:],
        "error": "" if proc.returncode == 0 else "retrain command failed",
    }
    _write_state(state)
    return status()


async def _loop() -> None:
    global _stop_event
    _stop_event = asyncio.Event()
    while not _stop_event.is_set():
        try:
            current = status()
            interval = current["interval_seconds"]
            due = bool(
                settings.classifier_retrain_enabled
                and interval
                and current["data_exists"]
                and (not current["last_started_at"] or time.time() >= current["next_due_at"])
            )
            if due:
                await run_once()
        except Exception as exc:
            state = _read_state()
            state["error"] = str(exc)
            _write_state(state)
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=60)
        except TimeoutError:
            pass


def start() -> None:
    global _task
    if _task is None or _task.done():
        _task = asyncio.create_task(_loop())


async def stop() -> None:
    if _stop_event is not None:
        _stop_event.set()
    if _task is not None:
        try:
            await asyncio.wait_for(_task, timeout=2)
        except TimeoutError:
            _task.cancel()
