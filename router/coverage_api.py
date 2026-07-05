"""Coverage, test-history, and visual QA inventory endpoints."""

from __future__ import annotations

import json
import mimetypes
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parents[1]
router = APIRouter()

MEDIA_DIRS = [
    ROOT / "test-results",
    ROOT / "playwright-report",
    ROOT / "cache" / "data" / "images",
    ROOT / "paper",
    ROOT / "benchmarks" / "archive" / "cache_data",
]
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4"}


def _rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _artifact_url(path: Path) -> str:
    return "/api/coverage/artifact/" + _rel(path)


def _safe_artifact_path(relpath: str) -> Path:
    candidate = (ROOT / relpath).resolve()
    if candidate.suffix.lower() not in MEDIA_SUFFIXES:
        raise HTTPException(status_code=404, detail="Unsupported artifact type")
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="Artifact not found")
    if not any(candidate.is_relative_to(base.resolve()) for base in MEDIA_DIRS if base.exists()):
        raise HTTPException(status_code=403, detail="Artifact path is outside allowed directories")
    return candidate


def _coverage_from_xml(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        root = ET.parse(path).getroot()  # nosec B314 -- internal coverage XML, not user input
        line_rate = float(root.attrib.get("line-rate", 0.0))
        modules = []
        for cls in root.findall(".//class"):
            filename = cls.attrib.get("filename", "")
            if not filename.startswith("router/"):
                continue
            modules.append(
                {
                    "name": filename,
                    "coverage": round(float(cls.attrib.get("line-rate", 0.0)) * 100, 1),
                    "statements": int(cls.attrib.get("complexity", 0) or 0),
                    "missing": 0,
                }
            )
        return {
            "source": _rel(path),
            "last_run_at": _mtime(path),
            "coverage_pct": round(line_rate * 100, 1),
            "modules": sorted(modules, key=lambda m: m["coverage"])[:16],
        }
    except Exception:
        return None


def _coverage_from_data(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        import coverage

        cov = coverage.Coverage(data_file=str(path))
        cov.load()
        modules = []
        total_statements = 0
        total_missing = 0
        for filename in sorted(cov.get_data().measured_files()):
            p = Path(filename)
            try:
                rel = _rel(p)
            except Exception:
                continue
            if not rel.startswith("router/") or "/static/" in rel:
                continue
            try:
                _, statements, _excluded, missing, _ = cov.analysis2(filename)
            except Exception:
                continue
            statements_count = len(statements)
            missing_count = len(missing)
            total_statements += statements_count
            total_missing += missing_count
            pct = 100.0 if statements_count == 0 else (statements_count - missing_count) / statements_count * 100
            modules.append(
                {
                    "name": rel,
                    "coverage": round(pct, 1),
                    "statements": statements_count,
                    "missing": missing_count,
                }
            )
        overall = 100.0 if total_statements == 0 else (total_statements - total_missing) / total_statements * 100
        return {
            "source": _rel(path),
            "last_run_at": _mtime(path),
            "coverage_pct": round(overall, 1),
            "modules": sorted(modules, key=lambda m: m["coverage"])[:16],
        }
    except Exception:
        return None


def _test_specs() -> list[dict[str, Any]]:
    specs = []
    for path in sorted((ROOT / "tests").glob("*")):
        if path.suffix not in {".py", ".js", ".ts"}:
            continue
        if path.name.startswith("_"):
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if path.suffix == ".py":
            count = text.count("def test_") + text.count("async def test_")
            kind = "pytest"
        else:
            count = text.count("test(") + text.count("test.describe(")
            kind = "playwright"
        if count:
            specs.append({"name": path.name, "kind": kind, "count": count, "path": _rel(path)})
    return specs


def _visual_artifacts() -> list[dict[str, Any]]:
    artifacts = []
    for base in MEDIA_DIRS:
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in MEDIA_SUFFIXES:
                continue
            try:
                rel = _rel(path)
            except Exception:
                continue
            typ = "video" if path.suffix.lower() in {".webm", ".mp4"} else "image"
            artifacts.append(
                {
                    "name": path.stem,
                    "type": typ,
                    "path": rel,
                    "url": _artifact_url(path),
                    "mtime": _mtime(path),
                    "size_bytes": path.stat().st_size,
                }
            )
    return sorted(artifacts, key=lambda a: a.get("mtime") or 0, reverse=True)[:80]


def _badge_payloads() -> list[dict[str, Any]]:
    out = []
    for base in (ROOT / "badges" / "preview", ROOT / "badges" / "benchmarks"):
        if not base.exists():
            continue
        for path in sorted(base.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            out.append({"id": path.stem, "path": _rel(path), **data})
    return out


def _benchmark_history() -> list[dict[str, Any]]:
    base = ROOT / "benchmarks" / "archive" / "cache_data"
    out = []
    if not base.exists():
        return out
    for path in sorted(base.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {"items": len(data) if isinstance(data, list) else None}
        score = data.get("score") or data.get("pass_rate") or data.get("total_score")
        solved = data.get("solved") or data.get("passed") or data.get("pass")
        total = data.get("total") or data.get("attempted") or data.get("max_score") or data.get("items")
        out.append(
            {
                "name": path.stem,
                "path": _rel(path),
                "mtime": _mtime(path),
                "score": score,
                "solved": solved,
                "total": total,
            }
        )
    return out[:32]


def coverage_payload() -> dict[str, Any]:
    specs = _test_specs()
    pytest_specs = [s for s in specs if s["kind"] == "pytest"]
    browser_specs = [s for s in specs if s["kind"] == "playwright"]
    coverage = _coverage_from_xml(ROOT / "coverage.xml") or _coverage_from_data(ROOT / ".coverage") or {
        "source": "",
        "last_run_at": None,
        "coverage_pct": None,
        "modules": [],
    }
    artifacts = _visual_artifacts()
    return {
        "generated_at": time.time(),
        "coverage": coverage,
        "total_specs": len(specs),
        "total_pytest_specs": len(pytest_specs),
        "total_playwright_specs": len(browser_specs),
        "pytest_tests": sum(int(s["count"]) for s in pytest_specs),
        "playwright_tests": sum(int(s["count"]) for s in browser_specs),
        "screenshots": artifacts,
        "visual_artifacts": artifacts,
        "specs": specs,
        "badges": _badge_payloads(),
        "history": _benchmark_history(),
        "project_dashboard": {
            "status": "workspace_required",
            "notes": "Per-project user code coverage is available when a workspace registry and sandboxed test runner are configured.",
        },
    }


@router.get("/api/coverage")
async def get_coverage() -> dict[str, Any]:
    return coverage_payload()


@router.get("/api/coverage/artifact/{relpath:path}")
async def get_coverage_artifact(relpath: str):
    path = _safe_artifact_path(relpath)
    media_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return FileResponse(path, media_type=media_type)
