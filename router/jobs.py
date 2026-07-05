"""Small explicit job registry for long-running or costly operations."""

from __future__ import annotations

import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Literal

JobStatus = Literal["queued", "running", "done", "error", "cancelled"]


@dataclass
class JobRecord:
    id: str
    kind: str
    status: JobStatus = "queued"
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    cost_budget_usd: float = 0.0
    message: str = ""
    result: dict | None = None

    def to_dict(self) -> dict:
        return asdict(self)


_jobs: dict[str, JobRecord] = {}


def create_job(kind: str, cost_budget_usd: float = 0.0, message: str = "") -> JobRecord:
    job = JobRecord(id=str(uuid.uuid4()), kind=kind, cost_budget_usd=cost_budget_usd, message=message)
    _jobs[job.id] = job
    return job


def get_job(job_id: str) -> JobRecord | None:
    return _jobs.get(job_id)


def list_jobs() -> list[dict]:
    return [job.to_dict() for job in sorted(_jobs.values(), key=lambda item: item.created_at, reverse=True)]


def update_job(job_id: str, status: JobStatus, message: str = "", result: dict | None = None) -> JobRecord | None:
    job = _jobs.get(job_id)
    if job is None:
        return None
    job.status = status
    job.updated_at = time.time()
    if message:
        job.message = message
    if result is not None:
        job.result = result
    return job
