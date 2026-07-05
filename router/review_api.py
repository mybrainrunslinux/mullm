"""Human review API for classifier/routing and close-call response labels."""

from __future__ import annotations

import csv
import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/review", tags=["review"])

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "cache" / "data"
ARCHIVE_DIR = ROOT / "benchmarks" / "archive" / "cache_data"

LABELS_PATH = DATA_DIR / "oracle_review_session_s36.jsonl"
ITEMS_PATH = DATA_DIR / "review_items.jsonl"
VOTES_PATH = DATA_DIR / "review_votes.jsonl"
DEFAULT_HOLDOUT_PATH = ROOT / "scripts" / "training_data_sample.csv"
HOLDOUT_LABELS_PATH = DATA_DIR / "holdout_review_labels.jsonl"

_write_lock = threading.Lock()
_problem_cache: list[dict[str, Any]] | None = None
_items_cache: list[dict[str, Any]] | None = None

DatasetParam = Annotated[str, Query(max_length=128)]


class ReviewLabelRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    human_local: bool


class CloseCallVoteRequest(BaseModel):
    prompt_hash: str = Field(..., min_length=16, max_length=128, pattern=r"^[a-fA-F0-9]+$")
    verdict: str = Field(..., pattern=r"^(local_ok|cloud_needed)$")


class HoldoutLabelRequest(BaseModel):
    id: str = Field(..., min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    human_category: str = Field(..., min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")
    accepted_prediction: bool | None = None
    notes: str = Field(default="", max_length=2000)


class HoldoutImportRequest(BaseModel):
    filename: str = Field(..., min_length=5, max_length=128, pattern=r"^[A-Za-z0-9_.-]+\.csv$")
    content: str = Field(..., min_length=1, max_length=2_000_000)


def _now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _read_jsonl(path: Path, max_rows: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if max_rows is not None and len(rows) >= max_rows:
                break
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                rows.append(value)
    return rows


def _safe_dataset_path(dataset: str) -> Path:
    """Return a whitelisted local review dataset path.

    User-replaceable review data belongs under cache/data/review_datasets or the
    built-in scripts/ sample. This avoids arbitrary file reads via query string.
    """
    if dataset in {"default", "classifier", "hungarian"}:
        return DEFAULT_HOLDOUT_PATH

    name = Path(dataset).name
    if not name.endswith(".csv"):
        raise HTTPException(status_code=400, detail="Review dataset must be a CSV file")
    path = DATA_DIR / "review_datasets" / name
    if not path.exists():
        raise HTTPException(status_code=404, detail="Review dataset not found")
    return path


def _available_holdout_datasets() -> list[dict[str, Any]]:
    datasets = [
        {
            "name": "default",
            "file": DEFAULT_HOLDOUT_PATH.name,
            "builtin": True,
            "available": DEFAULT_HOLDOUT_PATH.exists(),
        }
    ]
    user_dir = DATA_DIR / "review_datasets"
    if user_dir.exists():
        for path in sorted(user_dir.glob("*.csv")):
            datasets.append({"name": path.name, "file": path.name, "builtin": False})
    return datasets


def _validate_holdout_csv(path: Path) -> dict[str, Any]:
    rows = 0
    labels: set[str] = set()
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        if "query" not in fields:
            raise HTTPException(status_code=400, detail="CSV must include query column")
        if "category" not in fields and "expected_category" not in fields:
            raise HTTPException(status_code=400, detail="CSV must include category or expected_category column")
        for row in reader:
            query = str(row.get("query") or "").strip()
            label = str(row.get("expected_category") or row.get("category") or "").strip().lower()
            if query:
                rows += 1
            if label:
                labels.add(label)
    return {"rows": rows, "labels": sorted(labels)}


def _append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
    with _write_lock:
        with path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    try:
        from router.audit import audit_event
        audit_event(
            "review.write",
            path=str(path),
            record_id=record.get("id") or record.get("prompt_hash"),
            source=record.get("source", ""),
        )
    except Exception:
        pass


def _category_from_eval(eval_name: str) -> str:
    name = eval_name.lower()
    if "mbpp" in name or "humaneval" in name or "code" in name:
        return "code"
    if "gsm" in name or "math" in name:
        return "math"
    if "mmlu" in name:
        return "knowledge"
    if "hellaswag" in name or "truthfulqa" in name:
        return "reasoning"
    return "lookup"


def _problem_sources() -> tuple[list[dict[str, Any]], dict[str, dict[str, bool | None]]]:
    dataset = (
        _read_json(DATA_DIR / "routerbench_dataset_1k.json")
        or _read_json(ARCHIVE_DIR / "routerbench_dataset_1k.json")
        or []
    )
    router_results = _read_json(ARCHIVE_DIR / "routerbench_all.json") or _read_json(DATA_DIR / "routerbench_all.json") or {}

    votes_by_id: dict[str, dict[str, bool | None]] = {}
    if isinstance(router_results, dict):
        for router_name, payload in router_results.items():
            if not isinstance(payload, dict):
                continue
            for result in payload.get("results", []) or []:
                if not isinstance(result, dict) or "id" not in result:
                    continue
                routed_local = result.get("routed_local")
                votes_by_id.setdefault(str(result["id"]), {})[str(router_name)] = (
                    bool(routed_local) if routed_local is not None else None
                )
    return dataset if isinstance(dataset, list) else [], votes_by_id


def _load_problems() -> list[dict[str, Any]]:
    global _problem_cache
    if _problem_cache is not None:
        return _problem_cache

    dataset, votes_by_id = _problem_sources()
    problems: list[dict[str, Any]] = []
    max_count = max(len(votes_by_id), min(len(dataset), 700))
    for index in range(max_count):
        problem_id = f"tb_{index + 1:03d}"
        sample = dataset[index] if index < len(dataset) and isinstance(dataset[index], dict) else {}
        votes = votes_by_id.get(problem_id, {})
        prompt = str(sample.get("prompt") or sample.get("content_preview") or "").strip()
        if not prompt:
            continue
        category = str(sample.get("category") or _category_from_eval(str(sample.get("eval_name") or "")))
        tier = "local" if votes.get("hybrid_llm") or votes.get("mullm") else "cloud"
        problems.append(
            {
                "id": problem_id,
                "prompt": prompt[:4096],
                "category": category,
                "tier": tier,
                "router_votes": votes,
            }
        )

    _problem_cache = problems
    return problems


def _labels_by_id() -> dict[str, dict[str, Any]]:
    labels: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(LABELS_PATH):
        label_id = str(row.get("id") or "")
        if label_id:
            labels[label_id] = row
    return labels


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8"), usedforsecurity=False).hexdigest()


def _load_items() -> list[dict[str, Any]]:
    global _items_cache
    if _items_cache is not None:
        return _items_cache

    rows = _read_jsonl(ITEMS_PATH, max_rows=500)
    items: list[dict[str, Any]] = []
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        if not prompt:
            continue
        item = {
            "prompt_hash": str(row.get("prompt_hash") or _prompt_hash(prompt)),
            "prompt": prompt[:4096],
            "cloud_response": str(row.get("cloud_response") or "")[:12_000],
            "local_response": str(row.get("local_response") or "")[:12_000],
            "model": row.get("model"),
            "cost": row.get("cost"),
            "complexity": row.get("complexity"),
            "category": row.get("category"),
            "local_model": row.get("local_model"),
            "local_latency_ms": row.get("local_latency_ms"),
        }
        items.append(item)

    _items_cache = items
    return items


def _holdout_id(dataset_name: str, row_number: int, query: str) -> str:
    digest = hashlib.sha1(f"{dataset_name}:{row_number}:{query}".encode(), usedforsecurity=False).hexdigest()[:12]
    return f"ho_{row_number}_{digest}"


def _load_holdout(dataset: str = "default") -> list[dict[str, Any]]:
    from router.intent import classify
    from router.scorer import select_tier

    path = _safe_dataset_path(dataset)
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "query" not in (reader.fieldnames or []):
            raise HTTPException(status_code=400, detail="Holdout CSV must include query column")
        for row_number, row in enumerate(reader, start=2):
            query = str(row.get("query") or "").strip()
            if not query:
                continue
            expected = str(row.get("expected_category") or row.get("category") or "").strip().lower()
            intent = classify(query)
            tier = select_tier(intent)
            rows.append(
                {
                    "id": _holdout_id(path.name, row_number, query),
                    "dataset": path.name,
                    "row": row_number,
                    "query": query,
                    "expected_category": expected,
                    "predicted_category": getattr(intent.category, "value", str(intent.category)),
                    "predicted_complexity": intent.complexity,
                    "predicted_tier": getattr(tier, "value", str(tier)),
                    "confidence": round(float(intent.confidence), 4),
                }
            )
    return rows


def _holdout_labels(dataset: str = "default") -> dict[str, dict[str, Any]]:
    path = _safe_dataset_path(dataset)
    labels: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(HOLDOUT_LABELS_PATH):
        if row.get("dataset") == path.name and row.get("id"):
            labels[str(row["id"])] = row
    return labels


def _votes_by_hash() -> dict[str, dict[str, Any]]:
    votes: dict[str, dict[str, Any]] = {}
    for row in _read_jsonl(VOTES_PATH):
        prompt_hash = str(row.get("prompt_hash") or "")
        if prompt_hash:
            votes[prompt_hash] = row
    return votes


def _router_accuracy(labels: dict[str, dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    totals: dict[str, int] = {}
    correct: dict[str, int] = {}
    for problem in _load_problems():
        label = labels.get(problem["id"])
        if not label:
            continue
        human_local = bool(label.get("human_local"))
        for name, vote in (problem.get("router_votes") or {}).items():
            if vote is None:
                continue
            totals[name] = totals.get(name, 0) + 1
            correct[name] = correct.get(name, 0) + int(bool(vote) == human_local)
    return {
        name: {"total": total, "correct": correct.get(name, 0), "accuracy": correct.get(name, 0) / total}
        for name, total in sorted(totals.items())
        if total
    }


@router.get("/stats")
async def review_stats() -> dict[str, Any]:
    labels = _labels_by_id()
    problems = _load_problems()
    return {
        "total": len(problems),
        "labeled": sum(1 for problem in problems if problem["id"] in labels),
        "router_accuracy": _router_accuracy(labels),
    }


@router.get("/next")
async def next_review_item(
    skip_labeled: bool = Query(default=True),
    exclude_id: str = Query(default="", max_length=4096),
) -> dict[str, Any]:
    labels = _labels_by_id()
    excluded = {part.strip() for part in exclude_id.split(",") if part.strip()}
    problems = _load_problems()
    for problem in problems:
        if problem["id"] in excluded:
            continue
        if skip_labeled and problem["id"] in labels:
            continue
        return {
            **problem,
            "total": len(problems),
            "labeled_so_far": sum(1 for p in problems if p["id"] in labels),
        }
    return {"done": True, "total": len(problems), "labeled_so_far": sum(1 for p in problems if p["id"] in labels)}


@router.post("/label")
async def label_review_item(payload: ReviewLabelRequest) -> dict[str, Any]:
    known = {problem["id"] for problem in _load_problems()}
    if payload.id not in known:
        raise HTTPException(status_code=404, detail="Unknown review item")
    record = {
        "id": payload.id,
        "human_local": payload.human_local,
        "human_tier": "local" if payload.human_local else "cloud",
        "labeled_at": _now_iso(),
        "source": "mullm1_review_ui",
    }
    _append_jsonl(LABELS_PATH, record)
    return {"ok": True, "labeled": len(_labels_by_id()), "id": payload.id}


@router.get("/items")
async def close_call_items() -> dict[str, Any]:
    votes = _votes_by_hash()
    items = []
    for item in _load_items():
        vote = votes.get(item["prompt_hash"])
        items.append({**item, "voted": bool(vote), "verdict": vote.get("verdict") if vote else None})
    return {
        "items": items,
        "total": len(items),
        "voted": sum(1 for item in items if item["voted"]),
    }


@router.post("/vote")
async def vote_close_call(payload: CloseCallVoteRequest) -> dict[str, Any]:
    known = {item["prompt_hash"] for item in _load_items()}
    if payload.prompt_hash not in known:
        raise HTTPException(status_code=404, detail="Unknown review prompt")
    _append_jsonl(
        VOTES_PATH,
        {
            "prompt_hash": payload.prompt_hash,
            "verdict": payload.verdict,
            "timestamp": _now_iso(),
            "source": "mullm1_review_ui",
        },
    )
    votes = _votes_by_hash()
    return {"ok": True, "voted": len(votes), "total": len(known)}


@router.get("/holdout")
async def holdout_items(
    dataset: DatasetParam = "default",
    skip_reviewed: bool = Query(default=False),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    labels = _holdout_labels(dataset)
    rows = _load_holdout(dataset)
    items = []
    for row in rows:
        label = labels.get(row["id"])
        if skip_reviewed and label:
            continue
        items.append(
            {
                **row,
                "reviewed": bool(label),
                "human_category": label.get("human_category") if label else None,
                "accepted_prediction": label.get("accepted_prediction") if label else None,
                "notes": label.get("notes", "") if label else "",
            }
        )
        if len(items) >= limit:
            break
    return {
        "dataset": _safe_dataset_path(dataset).name,
        "datasets": _available_holdout_datasets(),
        "items": items,
        "total": len(rows),
        "reviewed": len(labels),
    }


@router.get("/holdout/datasets")
async def holdout_datasets() -> dict[str, Any]:
    return {"datasets": _available_holdout_datasets()}


@router.post("/holdout/import")
async def import_holdout_dataset(payload: HoldoutImportRequest) -> dict[str, Any]:
    raw_name = Path(payload.filename).name
    content = payload.content.encode("utf-8")
    user_dir = DATA_DIR / "review_datasets"
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / raw_name
    path.write_bytes(content)
    meta = _validate_holdout_csv(path)
    return {"ok": True, "dataset": raw_name, **meta}


@router.get("/holdout/stats")
async def holdout_stats(dataset: DatasetParam = "default") -> dict[str, Any]:
    rows = _load_holdout(dataset)
    labels = _holdout_labels(dataset)
    total = len(rows)
    category_correct = sum(1 for row in rows if row["expected_category"] and row["expected_category"] == row["predicted_category"])
    reviewed_correct = sum(
        1
        for row in rows
        if row["id"] in labels and labels[row["id"]].get("human_category") == row["predicted_category"]
    )
    return {
        "dataset": _safe_dataset_path(dataset).name,
        "total": total,
        "reviewed": len(labels),
        "category_accuracy": category_correct / total if total else 0.0,
        "reviewed_prediction_accuracy": reviewed_correct / len(labels) if labels else None,
    }


@router.post("/holdout/label")
async def label_holdout_item(payload: HoldoutLabelRequest, dataset: DatasetParam = "default") -> dict[str, Any]:
    path = _safe_dataset_path(dataset)
    known = {row["id"]: row for row in _load_holdout(dataset)}
    if payload.id not in known:
        raise HTTPException(status_code=404, detail="Unknown holdout item")
    row = known[payload.id]
    record = {
        "id": payload.id,
        "dataset": path.name,
        "row": row["row"],
        "query_hash": hashlib.sha256(row["query"].encode("utf-8")).hexdigest(),
        "expected_category": row["expected_category"],
        "predicted_category": row["predicted_category"],
        "human_category": payload.human_category.lower(),
        "accepted_prediction": payload.accepted_prediction,
        "notes": payload.notes,
        "reviewed_at": _now_iso(),
        "source": "mullm1_holdout_review",
    }
    _append_jsonl(HOLDOUT_LABELS_PATH, record)
    return {"ok": True, "reviewed": len(_holdout_labels(dataset)), "id": payload.id}


@router.get("/holdout/export-training", response_class=PlainTextResponse)
async def export_holdout_training(dataset: DatasetParam = "default") -> PlainTextResponse:
    rows = _load_holdout(dataset)
    labels = _holdout_labels(dataset)
    lines = ["query,category"]
    for row in rows:
        label = labels.get(row["id"])
        category = str(label.get("human_category") if label else row["expected_category"]).strip().lower()
        if not category:
            continue
        query = row["query"].replace("\r\n", "\n").replace("\r", "\n")
        escaped_query = '"' + query.replace('"', '""') + '"'
        escaped_category = '"' + category.replace('"', '""') + '"'
        lines.append(f"{escaped_query},{escaped_category}")
    filename = f"{_safe_dataset_path(dataset).stem}_reviewed_training.csv"
    return PlainTextResponse(
        "\n".join(lines) + "\n",
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
