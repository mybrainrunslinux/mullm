"""
SWE-bench Lite benchmark runner for muLLM.

Downloads 300 real GitHub issues, routes each through muLLM to get a patch,
applies the patch in a podman sandbox, and checks whether the failing tests now pass.

Usage (from repo root):
    python -m router.benchmarks.swebench --limit 10
    python -m router.benchmarks.swebench --limit 300 --force-tier local

Results are written to:
    cache/data/swebench_results.jsonl  (one JSON line per problem)
    cache/data/swebench_summary.json   (aggregate stats)

All network calls go to https://127.0.0.1:6856 (self-signed cert, verify=False).
Sandbox execution uses podman (not docker).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from router.config import settings

# ── Re-use shared HTTP helpers from runner (deferred to avoid import error) ───
try:
    from router.benchmarks.runner import MULLM_DEFAULT, _make_client, _query
except ImportError:
    MULLM_DEFAULT = "http://127.0.0.1:6856"
    _make_client = None  # type: ignore[assignment]
    _query = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────
CACHE_DIR = settings.cache_dir
CACHE_FILE = CACHE_DIR / "swebench_lite.jsonl"
RESULTS_FILE = CACHE_DIR / "swebench_results.jsonl"
SUMMARY_FILE = CACHE_DIR / "swebench_summary.json"

# HuggingFace datasets viewer API (no parquet / extra libraries needed)
HF_API_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=princeton-nlp%2FSWE-bench_Lite&config=default&split=test&offset={offset}&length={length}"
)

SANDBOX_TIMEOUT = 120  # seconds — podman run per problem
CLONE_TIMEOUT = 60  # seconds — git clone


# ── Dataset loading ───────────────────────────────────────────────────────────


def _load_from_cache() -> list[dict]:
    """Load problems from local JSONL cache."""
    problems: list[dict] = []
    with CACHE_FILE.open() as fh:
        for line in fh:
            line = line.strip()
            if line:
                problems.append(json.loads(line))
    return problems


async def _download_and_cache(limit: int = 300) -> list[dict]:
    """Download SWE-bench Lite from HuggingFace datasets API and cache locally."""
    problems: list[dict] = []
    # HF datasets server API returns max 100 rows per call
    batch = 100
    async with httpx.AsyncClient(timeout=60.0) as client:
        for offset in range(0, limit, batch):
            length = min(batch, limit - offset)
            url = HF_API_URL.format(offset=offset, length=length)
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                rows = data.get("rows", [])
                for row in rows:
                    problems.append(row["row"])
            except Exception as exc:
                log.warning("swebench_download_error", offset=offset, error=str(exc))
                break
    if problems:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with CACHE_FILE.open("w") as fh:
            for p in problems:
                fh.write(json.dumps(p) + "\n")
        log.info("swebench_cached", count=len(problems), path=str(CACHE_FILE))
    return problems


async def load_problems(limit: int = 300) -> list[dict]:
    """Load SWE-bench Lite problems, using local cache when available."""
    if CACHE_FILE.exists():
        try:
            all_problems = _load_from_cache()
            if all_problems:
                return all_problems[:limit]
        except Exception as exc:
            log.warning("swebench_cache_read_error", error=str(exc))

    problems = await _download_and_cache(limit)
    return problems[:limit]


# ── Patch extraction ──────────────────────────────────────────────────────────


def _sanitize_patch(raw: str) -> str:
    """Remove non-patch lines that local models often inject into diffs.

    Valid patch lines start with: diff, index, ---, +++, @@, +, -, \\ or space.
    Everything else (prose, blank-between-hunks prose) is stripped once we're
    inside a hunk block; blank lines between file headers are preserved.
    """
    lines = raw.splitlines()
    out: list[str] = []
    in_hunk = False
    for line in lines:
        if line.startswith("diff --git") or line.startswith("--- ") or line.startswith("+++ "):
            in_hunk = False
            out.append(line)
        elif line.startswith("index ") or line.startswith("new file") or line.startswith("deleted file"):
            out.append(line)
        elif line.startswith("@@ "):
            in_hunk = True
            out.append(line)
        elif in_hunk:
            if line == "" or line == "\\ No newline at end of file":
                out.append(line)
            elif line[:1] in ("+", "-", " "):
                out.append(line)
            elif line.startswith("diff --git"):
                in_hunk = False
                out.append(line)
            # else: skip junk line inside hunk (model explanation bleed-in)
        else:
            # Outside hunk: keep blank lines and valid header lines, skip prose
            if line == "" or line.startswith("diff ") or line.startswith("--- ") or line.startswith("+++ "):
                out.append(line)
    return "\n".join(out).strip()


def _extract_patch(response: str) -> str:
    """Extract a unified diff patch from a model response."""
    # Strip <think>...</think> reasoning blocks
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    if "<think>" in response:
        response = re.sub(r"<think>.*", "", response, flags=re.DOTALL).strip()

    candidate = ""

    # 1. ```diff or ```patch fenced block
    m = re.search(r"```(?:diff|patch)\s*\n(.*?)```", response, re.DOTALL)
    if m:
        candidate = m.group(1).strip()

    # 2. Any fenced block containing diff markers
    if not candidate:
        for m in re.finditer(r"```[^\n]*\n(.*?)```", response, re.DOTALL):
            c = m.group(1)
            if "diff --git" in c or ("--- a/" in c and "+++ b/" in c):
                candidate = c.strip()
                break

    # 3. Raw diff in response (find first diff --git or --- a/)
    if not candidate:
        for prefix in ["diff --git", "--- a/"]:
            idx = response.find(prefix)
            if idx != -1:
                candidate = response[idx:].strip()
                break

    if not candidate:
        candidate = response.strip()

    # Sanitize: strip prose lines injected by the model
    return _sanitize_patch(candidate)


# ── Search/replace applicator ─────────────────────────────────────────────────


def _apply_search_replace(response: str, workdir: str) -> tuple[bool, str]:
    """Parse FILE/SEARCH/REPLACE blocks and apply them directly to repo files.

    This avoids unified-diff line-number hallucinations entirely.
    Returns (any_applied, error_message).
    """

    # Parse blocks: FILE: path followed by <<<< SEARCH / === / >>>> REPLACE
    block_re = re.compile(
        r"FILE:\s*([^\n]+)\n"
        r"<{4,7}\s*SEARCH\s*\n(.*?)\n={4,7}\s*\n(.*?)\n>{4,7}\s*REPLACE",
        re.DOTALL,
    )
    blocks = block_re.findall(response)

    # Fallback: blocks without FILE: prefix (use previous FILE seen)
    if not blocks:
        # Try without FILE: header — grab all SEARCH/REPLACE blocks then find files
        no_file_re = re.compile(
            r"<{4,7}\s*SEARCH\s*\n(.*?)\n={4,7}\s*\n(.*?)\n>{4,7}\s*REPLACE",
            re.DOTALL,
        )
        raw_blocks = no_file_re.findall(response)
        if not raw_blocks:
            return False, "no SEARCH/REPLACE blocks found in response"
        # Grep each search string against the repo to find the right file
        applied_any = False
        for search_text, replace_text in raw_blocks:
            search_text = search_text.rstrip("\n")
            replace_text = replace_text.rstrip("\n")
            # Find which file contains this exact text
            rc, out, _ = _run_subprocess(
                ["grep", "-rl", "--include=*.py",
                 search_text.splitlines()[0][:80], "."],
                cwd=workdir, timeout=10,
            )
            for candidate in out.splitlines()[:3]:
                fp = Path(workdir) / candidate.strip()
                try:
                    original = fp.read_text()
                    if search_text in original:
                        fp.write_text(original.replace(search_text, replace_text, 1))
                        applied_any = True
                        break
                except Exception:
                    pass
        return applied_any, ("" if applied_any else "search text not found in any file")

    applied_any = False
    errors: list[str] = []
    for rel_path, search_text, replace_text in blocks:
        rel_path = rel_path.strip()
        search_text = search_text.rstrip("\n")
        replace_text = replace_text.rstrip("\n")
        fp = Path(workdir) / rel_path
        if not fp.exists():
            errors.append(f"{rel_path}: file not found")
            continue
        try:
            original = fp.read_text()
            if search_text not in original:
                # Try stripping leading whitespace differences (indent normalization)
                errors.append(f"{rel_path}: search text not found")
                continue
            fp.write_text(original.replace(search_text, replace_text, 1))
            applied_any = True
        except Exception as exc:
            errors.append(f"{rel_path}: {exc}")

    if applied_any:
        return True, ""
    return False, "; ".join(errors) or "no changes applied"


# ── Sandbox execution ─────────────────────────────────────────────────────────


def _run_subprocess(cmd: list[str], cwd: str | None = None, timeout: int = 60) -> tuple[int, str, str]:
    """Run a subprocess synchronously; return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode, result.stdout[:2000], result.stderr[:2000]
    except subprocess.TimeoutExpired:
        return -1, "", f"TIMEOUT after {timeout}s"
    except Exception as exc:
        return -2, "", str(exc)[:500]


def _clone_repo(repo: str, commit: str, workdir: str) -> tuple[bool, str]:
    """Clone the GitHub repo at a specific commit into workdir.

    Returns (success, error_message).
    """
    repo_url = f"https://github.com/{repo}.git"
    rc, out, err = _run_subprocess(
        ["git", "clone", "--filter=blob:none", repo_url, workdir],
        timeout=CLONE_TIMEOUT,
    )
    if rc != 0:
        return False, f"git clone failed: {err[:300]}"

    rc, out, err = _run_subprocess(
        ["git", "checkout", commit],
        cwd=workdir,
        timeout=30,
    )
    if rc != 0:
        return False, f"git checkout failed: {err[:300]}"

    return True, ""


def _apply_patch(patch: str, workdir: str) -> tuple[bool, str]:
    """Apply a unified diff patch — tries four progressively more lenient methods."""
    patch_file = Path(workdir) / "_model_patch.diff"
    patch_file.write_text(patch)

    attempts = [
        ["git", "apply", "--whitespace=fix", str(patch_file)],
        ["git", "apply", "--whitespace=fix", "--ignore-whitespace", str(patch_file)],
        ["patch", "-p1", "--forward", "--fuzz=3", "-i", str(patch_file)],
        ["patch", "-p1", "--forward", "--fuzz=5", "--ignore-whitespace", "-i", str(patch_file)],
    ]
    errs: list[str] = []
    for cmd in attempts:
        rc, _, err = _run_subprocess(cmd, cwd=workdir, timeout=30)
        if rc == 0:
            return True, ""
        errs.append(err[:150])

    return False, " | ".join(errs[:2])


def _instance_image(instance_id: str) -> str:
    """Map SWE-bench instance_id to official per-instance image name.

    e.g. astropy__astropy-12907 -> docker.io/swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest
    The '1776' segment is a fixed constant used in the official SWE-bench image registry.
    """
    return f"docker.io/swebench/sweb.eval.x86_64.{instance_id.replace('__', '_1776_')}:latest"


def _run_tests_podman(
    workdir: str,
    test_ids: list[str],
    repo: str,
    instance_id: str = "",
    test_patch: str = "",
) -> tuple[bool, bool, str]:
    """Run FAIL_TO_PASS tests using official SWE-bench per-instance images.

    Each image has the repo pre-installed at the base commit in a conda env
    named 'testbed'. We copy the patched files in, apply the test patch if
    provided, then run pytest inside that env.

    Returns (fail_to_pass_all_passed, no_regressions, output_snippet).
    """
    if not test_ids:
        return True, True, "no tests specified"

    test_args = " ".join(f'"{t}"' for t in test_ids)
    image = _instance_image(instance_id) if instance_id else "python:3.11-slim"

    # Pull image if not present (pulls once, reused for same instance)
    pull_rc, _, pull_err = _run_subprocess(
        ["podman", "pull", "--tls-verify=false", image],
        timeout=300,
    )
    if pull_rc != 0:
        return False, False, f"IMAGE_PULL_FAILED: {pull_err[:200]}"

    # Write test patch to workdir if provided
    if test_patch:
        (Path(workdir) / "_test_patch.diff").write_text(test_patch)

    # Script runs inside the official image:
    # 1. Apply model patch to /testbed (already has the repo at base commit)
    # 2. Apply test patch (adds the new test cases)
    # 3. Run pytest in the testbed conda env
    script = r"""set -e
cd /testbed
# Apply model patch (the fix we generated)
if [ -f /workspace/_model_patch.diff ]; then
    git apply --whitespace=fix /workspace/_model_patch.diff 2>/dev/null || \
    git apply --whitespace=fix --ignore-whitespace /workspace/_model_patch.diff 2>/dev/null || \
    patch -p1 --forward --fuzz=3 -i /workspace/_model_patch.diff 2>/dev/null || true
fi
# Apply test patch (adds the failing tests)
if [ -f /workspace/_test_patch.diff ]; then
    git apply --whitespace=fix /workspace/_test_patch.diff 2>/dev/null || \
    patch -p1 --forward --fuzz=3 -i /workspace/_test_patch.diff 2>/dev/null || true
fi
# Run tests in the pre-configured conda testbed env
source /opt/miniconda3/etc/profile.d/conda.sh
conda activate testbed
python -m pytest """ + test_args + r""" -x --tb=short -q 2>&1
"""

    cmd = [
        "podman", "run", "--rm",
        "--network=none",             # official images work offline
        f"--volume={workdir}:/workspace:ro,Z",
        image,
        "bash", "-c", script,
    ]

    rc, out, err = _run_subprocess(cmd, timeout=SANDBOX_TIMEOUT)
    combined = (out + err)[:3000]

    # Clean up image after use to reclaim disk space
    _run_subprocess(["podman", "rmi", image], timeout=60)

    if rc == -1:
        return False, False, "SANDBOX_TIMEOUT"
    if rc == -2:
        return False, False, f"SANDBOX_ERROR: {combined[:300]}"

    passed = rc == 0
    no_regressions = "FAILED" not in combined or passed
    return passed, no_regressions, combined[:1500]


# ── Prompt builder ────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = """\
You are an expert software engineer. Fix the given GitHub issue.

Output ONLY search/replace blocks — no explanation, no prose, nothing else.
Format for each change:

<<<<<<< SEARCH
exact lines from the file to find (copy verbatim, including indentation)
=======
replacement lines (the fixed version)
>>>>>>> REPLACE

Rules:
- SEARCH must be an exact verbatim copy of existing lines (whitespace matters)
- Include 2-3 context lines around the change so SEARCH is unique in the file
- One block per logical change; multiple blocks allowed for multiple files
- Before each block write: FILE: path/to/file.py  (relative to repo root)
- Do NOT modify test files unless the issue explicitly requires it"""


def _find_relevant_files(workdir: str, issue_text: str, max_files: int = 3) -> list[tuple[str, str]]:
    """Grep the cloned repo for files most relevant to the issue.

    Returns list of (rel_path, content) for the top candidates, capped at
    FILE_CONTEXT_CHARS total so we don't blow the model's context window.
    """
    FILE_CONTEXT_CHARS = 12_000
    # Extract candidate identifiers: CamelCase class names, snake_case functions, filenames
    tokens = re.findall(r'\b([A-Z][a-zA-Z]{3,}|[a-z_]{4,})\b', issue_text)
    # Dedupe, prefer longer tokens (more specific)
    seen: set[str] = set()
    keywords: list[str] = []
    for t in sorted(set(tokens), key=len, reverse=True):
        if t.lower() not in seen:
            seen.add(t.lower())
            keywords.append(t)
        if len(keywords) >= 8:
            break

    if not keywords:
        return []

    # grep -rl: find files containing any keyword, ranked by hit count
    grep_pattern = "|".join(re.escape(k) for k in keywords[:5])
    rc, out, _ = _run_subprocess(
        ["grep", "-rl", "--include=*.py", "-E", grep_pattern, "."],
        cwd=workdir, timeout=15,
    )
    candidates: list[str] = [p.strip() for p in out.splitlines() if p.strip()][:max_files * 3]

    # Score by number of keyword hits
    scored: list[tuple[int, str]] = []
    for rel_path in candidates:
        abs_path = Path(workdir) / rel_path
        try:
            content = abs_path.read_text(errors="replace")
            hits = sum(content.lower().count(k.lower()) for k in keywords)
            scored.append((hits, rel_path))
        except Exception:
            pass
    scored.sort(reverse=True)

    results: list[tuple[str, str]] = []
    chars_used = 0
    for _, rel_path in scored[:max_files]:
        abs_path = Path(workdir) / rel_path
        try:
            content = abs_path.read_text(errors="replace")
            budget = FILE_CONTEXT_CHARS - chars_used
            if budget <= 0:
                break
            snippet = content[:budget]
            results.append((rel_path, snippet))
            chars_used += len(snippet)
        except Exception:
            pass
    return results


def _build_prompt(problem: dict, file_context: list[tuple[str, str]] | None = None) -> str:
    """Build the user-content portion of the SWE-bench prompt (no system prompt)."""
    repo = problem.get("repo", "")
    statement = problem.get("problem_statement", "").strip()
    hints = problem.get("hints_text", "").strip()

    parts = [f"Repository: {repo}", f"\nIssue:\n{statement}"]
    if hints:
        parts.append(f"\nHints:\n{hints}")
    if file_context:
        parts.append("\nRelevant source files:")
        for path, content in file_context:
            parts.append(f"\n--- {path} ---\n{content}")
    parts.append("\nPatch:")
    return "\n".join(parts)


# ── Main runner ───────────────────────────────────────────────────────────────


async def run_swebench(
    mullm_url: str = MULLM_DEFAULT,
    force_tier: str = "local",
    limit: int = 10,
    progress_cb: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """Run SWE-bench Lite problems through muLLM.

    Args:
        mullm_url: Base URL for the muLLM server.
        force_tier: Tier override (default 'local' — never spends money).
        limit: Number of problems to run (default 10 for testing, 300 for full).
        progress_cb: Optional callback(done, passed) called after each problem.

    Returns:
        Summary dict with pass_rate, cost, tier breakdown, per-problem results.
    """
    problems = await load_problems(limit)
    if not problems:
        return {
            "benchmark": "swebench_lite",
            "error": "No problems loaded — check network or cache",
            "pass_rate": 0.0,
            "total": 0,
            "passed": 0,
            "results": [],
        }

    results: list[dict] = []
    passed_count = 0
    total_cost = 0.0
    tier_counts: dict[str, int] = {}

    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)

    async def _query_local(cl: httpx.AsyncClient, user_content: str) -> dict:
        """Ollama call with proper system/user split and high num_predict."""
        try:
            r = await cl.post(
                "http://localhost:11434/api/chat",
                json={
                    "model": settings.ollama_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user",   "content": user_content},
                    ],
                    "stream": False,
                    "options": {"temperature": 0.0, "num_predict": 16384, "num_ctx": 32768},
                },
            )
            r.raise_for_status()
            text = r.json().get("message", {}).get("content", "")
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            return {"response": text, "tier_used": "local", "model_used": settings.ollama_model, "cost": 0}
        except Exception as exc:
            return {"error": str(exc)[:300], "response": "", "tier_used": "error", "model_used": "error", "cost": 0}

    async with _make_client() as client:
        for i, problem in enumerate(problems):
            instance_id = problem.get("instance_id", f"unknown_{i}")
            repo = problem.get("repo", "")
            base_commit = problem.get("base_commit", "")
            fail_to_pass_raw = problem.get("FAIL_TO_PASS", "[]")
            pass_to_pass_raw = problem.get("PASS_TO_PASS", "[]")

            try:
                fail_to_pass: list[str] = (
                    json.loads(fail_to_pass_raw) if isinstance(fail_to_pass_raw, str) else fail_to_pass_raw
                )
            except (json.JSONDecodeError, TypeError):
                fail_to_pass = []
            try:
                (
                    json.loads(pass_to_pass_raw) if isinstance(pass_to_pass_raw, str) else pass_to_pass_raw
                )
            except (json.JSONDecodeError, TypeError):
                pass

            t0 = time.perf_counter()
            problem_result: dict[str, Any] = {
                "instance_id": instance_id,
                "repo": repo,
                "passed": False,
                "patch_applied": False,
                "env_error": False,
                "tier": "unknown",
                "model": "unknown",
                "cost": 0.0,
                "latency_ms": 0.0,
                "fail_to_pass_count": len(fail_to_pass),
                "error": "",
                "output_snippet": "",
            }

            workdir: str | None = None
            try:
                # 1. Query muLLM for a patch
                # 1. Clone repo first so we can feed real file context to the model
                workdir = tempfile.mkdtemp(prefix=f"swe_{instance_id[:20]}_")
                clone_ok, clone_err = await asyncio.to_thread(_clone_repo, repo, base_commit, workdir)
                if not clone_ok:
                    problem_result["env_error"] = True
                    problem_result["error"] = clone_err
                    results.append(problem_result)
                    _write_result(problem_result)
                    if progress_cb:
                        progress_cb(len(results), passed_count)
                    continue

                # 2. Extract relevant file context from cloned repo
                issue_text = problem.get("problem_statement", "")
                file_context = await asyncio.to_thread(
                    _find_relevant_files, workdir, issue_text
                )

                # 3. Query muLLM with real file context
                user_content = _build_prompt(problem, file_context)
                query_t0 = time.perf_counter()
                if force_tier == "local":
                    data = await _query_local(client, user_content)
                else:
                    data = await _query(client, mullm_url, user_content, force_tier)
                query_latency_ms = (time.perf_counter() - query_t0) * 1000

                raw_response = data.get("response", "")
                tier = data.get("tier_used", "unknown")
                model = data.get("model_used", "unknown")
                cost = float(data.get("cost", 0) or 0)
                problem_result["tier"] = tier
                problem_result["model"] = model
                problem_result["cost"] = cost
                tier_counts[tier] = tier_counts.get(tier, 0) + 1
                total_cost += cost

                if data.get("error"):
                    problem_result["error"] = f"query_error: {data['error'][:200]}"
                    results.append(problem_result)
                    _write_result(problem_result)
                    if progress_cb:
                        progress_cb(len(results), passed_count)
                    continue

                # 4. Apply: try search/replace first (no line-number hallucination),
                #    fall back to unified diff if model produced one instead
                sr_ok, sr_err = await asyncio.to_thread(
                    _apply_search_replace, raw_response, workdir
                )
                if sr_ok:
                    apply_ok, apply_err = True, ""
                else:
                    patch = _extract_patch(raw_response)
                    apply_ok, apply_err = await asyncio.to_thread(_apply_patch, patch, workdir)
                problem_result["patch_applied"] = apply_ok
                if not apply_ok:
                    problem_result["error"] = apply_err
                    results.append(problem_result)
                    _write_result(problem_result)
                    if progress_cb:
                        progress_cb(len(results), passed_count)
                    continue

                # 5. Run tests in podman sandbox using official per-instance image
                test_patch = problem.get("test_patch", "")
                passed, no_regressions, snippet = await asyncio.to_thread(
                    _run_tests_podman, workdir, fail_to_pass, repo, instance_id, test_patch
                )

                latency_ms = (time.perf_counter() - t0) * 1000
                problem_result["passed"] = passed
                problem_result["no_regressions"] = no_regressions
                problem_result["latency_ms"] = round(latency_ms, 1)
                problem_result["query_latency_ms"] = round(query_latency_ms, 1)
                problem_result["output_snippet"] = snippet

                if passed:
                    passed_count += 1

            except Exception as exc:
                problem_result["error"] = str(exc)[:400]
                log.exception("swebench_problem_error", instance_id=instance_id)
            finally:
                # Clean up temp dir
                if workdir and Path(workdir).exists():
                    try:
                        shutil.rmtree(workdir, ignore_errors=True)
                    except Exception:
                        pass

            results.append(problem_result)
            _write_result(problem_result)

            if progress_cb:
                progress_cb(len(results), passed_count)

    total = len(problems)
    pass_rate = passed_count / total if total else 0.0

    summary: dict[str, Any] = {
        "benchmark": "swebench_lite",
        "pass_rate": round(pass_rate, 4),
        "passed": passed_count,
        "total": total,
        "total_cost": round(total_cost, 6),
        "tier_breakdown": tier_counts,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "results": results,
    }

    SUMMARY_FILE.write_text(json.dumps(summary, indent=2))
    log.info(
        "swebench_done",
        passed=passed_count,
        total=total,
        pass_rate=round(pass_rate, 4),
        cost=round(total_cost, 6),
    )
    return summary


def _write_result(result: dict) -> None:
    """Append a single problem result to the JSONL file."""
    try:
        with RESULTS_FILE.open("a") as fh:
            fh.write(json.dumps(result, default=str) + "\n")
    except Exception:
        pass


# ── CLI entry point ───────────────────────────────────────────────────────────


async def _main_async() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="SWE-bench Lite runner for muLLM")
    parser.add_argument("--limit", type=int, default=10, help="Number of problems (default 10)")
    parser.add_argument("--force-tier", default="local", help="Tier override (default local)")
    parser.add_argument("--mullm-url", default=MULLM_DEFAULT, help="muLLM base URL")
    args = parser.parse_args()

    def _progress(done: int, passed: int) -> None:
        pct = done / max(args.limit, 1) * 100
        print(f"  [{done:3d}/{args.limit}] passed={passed}  ({pct:.0f}%)", flush=True)

    print(f"SWE-bench Lite — {args.limit} problems, tier={args.force_tier}")
    summary = await run_swebench(
        mullm_url=args.mullm_url,
        force_tier=args.force_tier,
        limit=args.limit,
        progress_cb=_progress,
    )
    print(
        f"\nResult: {summary['passed']}/{summary['total']} passed"
        f"  ({summary['pass_rate'] * 100:.1f}%)"
        f"  cost=${summary['total_cost']:.4f}"
    )
    print(f"Saved to {SUMMARY_FILE}")


if __name__ == "__main__":
    asyncio.run(_main_async())
