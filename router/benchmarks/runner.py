"""
Benchmark runner for muLLM — HumanEval, MBPP, MultiPL-E, routing accuracy, latency, cache.

All network calls go to http://127.0.0.1:6856 (self-signed cert, verify=False).  # nosec B501 -- benchmark local server, SSL not applicable
All code execution happens in a subprocess sandbox with a 10-second timeout.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
import time
from typing import Any

import httpx

from router.config import settings

# ── Constants ─────────────────────────────────────────────────────────────────
MULLM_DEFAULT = "http://127.0.0.1:6856"
EXEC_TIMEOUT = 10  # seconds per problem


# ── Sandbox executor ──────────────────────────────────────────────────────────


def _extract_code(response: str) -> str:
    """Extract a Python code block from a model response.

    Priority:
    1. ```python ... ``` fenced block
    2. ``` ... ``` fenced block
    3. The full response (fallback — model may return raw code)

    Post-processing:
    - Strip unicode chars that cause SyntaxError (✓✗→²³ etc.)
    - Fix unterminated triple-quoted strings
    - Remove stray markdown artifacts
    """
    # Strip <think>...</think> reasoning blocks (Qwen3 / OmniCoder models output
    # chain-of-thought before the answer; the thinking often contains code
    # snippets that would be matched by the regex below instead of the real answer)
    response = re.sub(r"<think>.*?</think>", "", response, flags=re.DOTALL).strip()
    # Handle unclosed <think> tags (model truncated mid-thought — discard partial reasoning)
    if "<think>" in response:
        response = re.sub(r"<think>.*", "", response, flags=re.DOTALL).strip()
    # Strip orphaned </think> tags (no matching open tag)
    response = response.replace("</think>", "").strip()
    # Strip "Here's my reasoning:" / "Here's the solution:" preamble text
    response = re.sub(
        r"^(?:Here'?s?\s+(?:my\s+)?(?:reasoning|solution|implementation|approach|the\s+\w+)[:\s]*\n?)+",
        "",
        response,
        flags=re.IGNORECASE | re.MULTILINE,
    ).strip()

    # Try ```python block
    m = re.search(r"```python\s*\n(.*?)```", response, re.DOTALL)
    if m:
        code = m.group(1)
    else:
        # Try generic fenced block
        m = re.search(r"```\s*\n(.*?)```", response, re.DOTALL)
        if m:
            code = m.group(1)
        else:
            # Fallback: raw response
            code = response

    # ── Post-processing to fix common model output issues ──

    # Remove stray markdown fence lines that weren't caught
    code = re.sub(r"^```\w*\s*$", "", code, flags=re.MULTILINE)
    code = re.sub(r"^```\s*$", "", code, flags=re.MULTILINE)

    # Replace unicode characters that cause SyntaxError in comments/strings
    # These are safe to replace since they only appear in docstrings/comments
    _unicode_map = {
        "\u2713": "v",
        "\u2714": "v",
        "\u2715": "x",
        "\u2717": "x",  # ✓✔✕✗
        "\u2192": "->",
        "\u2190": "<-",
        "\u2194": "<->",  # →←↔
        "\u00b2": "^2",
        "\u00b3": "^3",
        "\u00b9": "^1",  # ²³¹
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',  # smart quotes
        "\u2026": "...",  # …
        "\u2014": "--",
        "\u2013": "-",  # em dash, en dash
        "\u2022": "*",  # bullet
        "\u00d7": "*",
        "\u00f7": "/",  # × ÷
        "\u2260": "!=",
        "\u2264": "<=",
        "\u2265": ">=",  # ≠ ≤ ≥
        "\u221e": "float('inf')",  # ∞
    }
    for uc, repl in _unicode_map.items():
        code = code.replace(uc, repl)

    # Fix unterminated triple-quoted strings: count triple-quote pairs
    for q in ['"""', "'''"]:
        count = code.count(q)
        if count % 2 != 0:
            # Odd number — close the last one
            code = code + "\n" + q

    # Strip remaining non-ASCII from comment lines (# ...) to prevent SyntaxError
    lines = code.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            # ASCII-only comments
            line = line.encode("ascii", "replace").decode("ascii")
        cleaned.append(line)
    code = "\n".join(cleaned)

    # Also sanitize non-ASCII in string literals that aren't part of the logic
    # Only do this if there are still non-ASCII chars that would cause SyntaxError
    try:
        compile(code, "<bench>", "exec")
    except SyntaxError:
        # Nuclear option: replace ALL non-ASCII with ASCII approximations
        code = code.encode("ascii", "replace").decode("ascii")

    return code.strip()


def _run_in_sandbox(code: str, test_code: str) -> tuple[bool, str]:
    """Execute code + test in a restricted subprocess.

    Returns (passed, error_message).
    Network is not explicitly blocked (no seccomp), but no env vars are
    inherited and the working directory is /tmp — good enough for a local bench.  # nosec B108 -- benchmark sandbox tmp path
    """
    full = code + "\n" + test_code
    try:
        result = subprocess.run(
            ["python3", "-c", full],
            timeout=EXEC_TIMEOUT,
            capture_output=True,
            text=True,
            env={"PATH": "/usr/bin:/bin"},  # minimal env, no network creds
            cwd="/tmp",  # nosec B108 -- benchmark sandbox tmp path
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout)[:500]
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as exc:
        return False, str(exc)[:300]


def _select_humaneval_problems(all_problems: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Select HumanEval problems reproducibly unless random sampling is explicit."""
    if limit < len(all_problems) and os.getenv("MULLM_BENCH_SAMPLE", "prefix").lower() == "random":
        import random as _random

        return _random.sample(all_problems, limit)
    return all_problems[:limit]


def _select_humaneval_task_ids(all_problems: list[dict[str, Any]], task_ids: list[str]) -> list[dict[str, Any]]:
    """Select explicit HumanEval task IDs, preserving requested order."""
    by_id = {str(problem.get("task_id")): problem for problem in all_problems}
    missing = [task_id for task_id in task_ids if task_id not in by_id]
    if missing:
        raise ValueError(f"Unknown HumanEval task_id(s): {', '.join(missing)}")
    return [by_id[task_id] for task_id in task_ids]


def _prepare_humaneval_test_code(test_code: str, entry_point: str) -> str:
    """Append the official HumanEval check call in strict mode."""
    if (
        os.getenv("MULLM_BENCH_LEGACY_NO_CHECK_CALL") != "1"
        and "def check(candidate)" in test_code
        and f"check({entry_point})" not in test_code
    ):
        return test_code.rstrip() + f"\n\ncheck({entry_point})\n"
    return test_code


# ── HTTP helpers ──────────────────────────────────────────────────────────────


def _make_client() -> httpx.AsyncClient:
    """Return an async httpx client that trusts the self-signed cert."""
    return httpx.AsyncClient(verify=False, timeout=300.0)  # nosec B501 -- benchmark local server, SSL not applicable


async def _query(client: httpx.AsyncClient, mullm_url: str, content: str, force_tier: str = "", target_model: str = "") -> dict[str, Any]:
    """POST /query and return the JSON response dict (or an error dict).

    For force_tier='local', the default path still goes through muLLM /query so
    audit/dashboard/cost/perf events stay visible. Set
    MULLM_BENCH_DIRECT_OLLAMA=1 for raw engine comparisons that intentionally
    bypass muLLM.
    """
    if force_tier == "local" and os.getenv("MULLM_BENCH_DIRECT_OLLAMA") == "1":
        return await _query_ollama_direct(client, content, target_model=target_model)
    payload: dict[str, Any] = {
        "content": content,
        "stream": False,
        "skip_cache": True,
        "source": "api",
        "temperature": 0.0,
        "context": {"num_predict": 8192, "bench_mode": True},
    }
    if force_tier:
        payload["force_tier"] = force_tier
    _warmup_sigs = ("warming up", "model is loading", "please wait", "ollama is starting")
    for attempt in range(4):
        try:
            r = await client.post(f"{mullm_url}/query", json=payload)
            r.raise_for_status()
            data = r.json()
            resp_text = data.get("response", "")
            if any(sig in resp_text.lower() for sig in _warmup_sigs):
                import asyncio as _aio
                await _aio.sleep(10 * (attempt + 1))
                continue
            return data
        except Exception as exc:
            return {"error": str(exc)[:300], "response": "", "tier_used": "error", "model_used": "error", "cost": 0}
    return {"error": "model warmup timeout after 4 retries", "response": "", "tier_used": "error", "model_used": "error", "cost": 0}


async def _query_ollama_direct(client: httpx.AsyncClient, content: str, target_model: str = "") -> dict[str, Any]:
    """Call Ollama directly for local bench — bypasses router token limits."""
    model = target_model or settings.ollama_model
    query_timeout = float(os.getenv("MULLM_BENCH_QUERY_TIMEOUT", "120"))
    num_predict = int(os.getenv("MULLM_BENCH_NUM_PREDICT", "4096"))

    try:
        r = await client.post(
            "http://localhost:11434/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": content}],
                "stream": False,
                "think": False,
                "options": {"temperature": 0.1, "num_predict": num_predict},
            },
            timeout=query_timeout,
        )
        r.raise_for_status()
        data = r.json()
        text = data.get("message", {}).get("content", "")
        # Strip special tokens that some models leak into response text
        text = re.sub(r"<\|[^|>]+\|>", "", text).strip()
        # Strip <think> blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        if "<think>" in text:
            text = re.sub(r"<think>.*", "", text, flags=re.DOTALL).strip()
        return {
            "response": text,
            "tier_used": "local",
            "model_used": model,
            "cost": 0,
        }
    except Exception as exc:
        return {"error": str(exc)[:300], "response": "", "tier_used": "error", "model_used": "error", "cost": 0}


# ── 1. HumanEval ─────────────────────────────────────────────────────────────


async def run_humaneval(
    mullm_url: str = MULLM_DEFAULT,
    force_tier: str = "",
    limit: int = 20,
    progress_cb=None,
    target_model: str = "",
    task_ids: list[str] | None = None,
) -> dict:
    """Run HumanEval problems through muLLM. Returns pass@1 and per-problem results.

    When limit > len(PROBLEMS) (20 inline), loads the full 164-problem set
    via load_problems(full=True), which downloads+caches from GitHub on first call.
    """
    from router.benchmarks.humaneval import PROBLEMS, load_problems

    if task_ids or limit > len(PROBLEMS):
        all_problems = load_problems(full=True)
    else:
        all_problems = PROBLEMS
    problems = _select_humaneval_task_ids(all_problems, task_ids) if task_ids else _select_humaneval_problems(all_problems, limit)
    results = []
    passed_count = 0

    async with _make_client() as client:
        for prob in problems:
            t0 = time.perf_counter()
            # Build a clear prompt asking for a complete Python implementation
            prompt = (
                f"Complete the following Python function. "
                f"Read the docstring carefully and implement ALL requirements it specifies. "
                f"Return the COMPLETE function including the def line and docstring. "
                f"No markdown, no explanation, no backticks. Just Python code. /no_think\n\n"
                f"{prob['prompt']}"
            )
            data = await _query(client, mullm_url, prompt, force_tier, target_model=target_model)
            latency_ms = (time.perf_counter() - t0) * 1000

            raw_response = data.get("response", "")

            code = _extract_code(raw_response)

            # If the model returned a complete function (starts with 'def <entry_point>'),
            # don't prepend the prompt — it would create a duplicate definition.
            # Otherwise prepend the prompt so imports + signature are present.
            ep = prob["entry_point"]
            if re.search(rf"^\s*def\s+{re.escape(ep)}\s*\(", code, re.MULTILINE):
                full_code = prob["prompt"].split(f"def {ep}")[0] + code
            else:
                # Model returned body-only code — indent it under the function def
                # Check if code needs indentation (first non-empty line at column 0)
                code_lines = code.split("\n")
                first_nonblank = next((ln for ln in code_lines if ln.strip()), "")
                if first_nonblank and not first_nonblank.startswith(("    ", "\t")):
                    code = "\n".join("    " + ln if ln.strip() else ln for ln in code_lines)
                full_code = prob["prompt"] + code
            test_code = _prepare_humaneval_test_code(prob["test"], ep)
            passed, error = await asyncio.to_thread(_run_in_sandbox, full_code, test_code)

            if passed:
                passed_count += 1

            n = len(results) + 1
            status = "✓" if passed else "✗"
            print(f"  HE [{n:3d}/{len(problems)}] {status} {latency_ms/1000:.1f}s  {prob['task_id']}{' err:'+error[:50] if error and not passed else ''}", flush=True)

            results.append(
                {
                    "task_id": prob["task_id"],
                    "passed": passed,
                    "error": error,
                    "tier": data.get("tier_used", "unknown"),
                    "model": data.get("model_used", "unknown"),
                    "query_error": data.get("error", ""),
                    "cost": data.get("cost", 0),
                    "latency_ms": round(latency_ms, 1),
                    "response_len": len(raw_response),
                    "response_text": code,
                }
            )

            if progress_cb:
                progress_cb(len(results), passed_count)

    pass_at_1 = passed_count / len(problems) if problems else 0.0
    return {
        "benchmark": "humaneval",
        "pass_at_1": round(pass_at_1, 4),
        "passed": passed_count,
        "total": len(problems),
        "results": results,
    }


# ── 2. MBPP ───────────────────────────────────────────────────────────────────


async def run_mbpp(mullm_url: str = MULLM_DEFAULT, force_tier: str = "", limit: int = 10, progress_cb=None, target_model: str = "") -> dict:
    """Run MBPP problems through muLLM. Returns pass@1 and per-problem results.

    When limit > len(PROBLEMS) (10 inline), loads the full sanitized set (427)
    via load_problems(full=True), which downloads+caches from HuggingFace on first call.
    """
    from router.benchmarks.mbpp import PROBLEMS, load_problems

    if limit > len(PROBLEMS):
        all_problems = load_problems(full=True)
    else:
        all_problems = PROBLEMS
    problems = all_problems[:limit]
    results = []
    passed_count = 0

    async with _make_client() as client:
        for prob in problems:
            t0 = time.perf_counter()
            prompt = (
                f"Write Python code to complete this function. "
                f"Output ONLY the Python function — no markdown fences, "
                f"no backticks, no explanation text, no unicode. ASCII only.\n\n"
                f"{prob['prompt']}"
            )
            data = await _query(client, mullm_url, prompt, force_tier, target_model=target_model)
            latency_ms = (time.perf_counter() - t0) * 1000

            raw_response = data.get("response", "")
            code = _extract_code(raw_response)

            # Prepend prompt context if model didn't include the function def
            ep = prob["entry_point"]
            if not re.search(rf"^\s*def\s+{re.escape(ep)}\s*\(", code, re.MULTILINE):
                code = f"def {ep}(*args, **kwargs):\n" + code

            passed, error = await asyncio.to_thread(_run_in_sandbox, code, prob["test"])
            if passed:
                passed_count += 1

            results.append(
                {
                    "task_id": prob["task_id"],
                    "passed": passed,
                    "error": error,
                    "tier": data.get("tier_used", "unknown"),
                    "model": data.get("model_used", "unknown"),
                    "cost": data.get("cost", 0),
                    "latency_ms": round(latency_ms, 1),
                    "response_len": len(raw_response),
                    "response_text": code,
                }
            )

            if progress_cb:
                progress_cb("local", len(results), passed_count)

    pass_at_1 = passed_count / len(problems) if problems else 0.0
    return {
        "benchmark": "mbpp",
        "pass_at_1": round(pass_at_1, 4),
        "passed": passed_count,
        "total": len(problems),
        "results": results,
    }


# ── 3. Routing accuracy ───────────────────────────────────────────────────────

_ROUTING_TEST_CASES: list[dict] = [
    # expected: "local" (simple, no cloud needed)
    {"content": "What is 2+2?", "expected_tier": "local"},
    {"content": "Say hello in French.", "expected_tier": "local"},
    {"content": "What color is the sky?", "expected_tier": "local"},
    {"content": "List 3 fruits.", "expected_tier": "local"},
    {"content": "What is the capital of France?", "expected_tier": "local"},
    {"content": "Translate 'good morning' to Spanish.", "expected_tier": "local"},
    {"content": "How many days in a week?", "expected_tier": "local"},
    {"content": "What is Python?", "expected_tier": "local"},
    # expected: "cloud" (complex / expensive tasks)
    {
        "content": (
            "Write a complete, production-ready REST API in Python using FastAPI with "
            "JWT authentication, rate limiting, PostgreSQL integration via SQLAlchemy, "
            "comprehensive error handling, OpenAPI docs, and Docker deployment config."
        ),
        "expected_tier": "cloud",
    },
    {
        "content": (
            "Analyze this 500-line Python codebase for security vulnerabilities, "
            "performance bottlenecks, and architectural anti-patterns. Provide a "
            "detailed report with line-by-line recommendations and refactoring plan."
        ),
        "expected_tier": "cloud",
    },
    {
        "content": (
            "Write a 2000-word technical essay comparing transformer architectures, "
            "attention mechanisms, and their implications for AGI development, citing "
            "specific papers and benchmarks."
        ),
        "expected_tier": "cloud",
    },
    {
        "content": (
            "Design a distributed microservices architecture for a real-time trading "
            "platform handling 1M transactions/second with sub-millisecond latency, "
            "fault tolerance, and compliance with SEC regulations."
        ),
        "expected_tier": "cloud",
    },
    # Borderline — we accept either tier
    {"content": "Explain recursion with a simple example.", "expected_tier": "any"},
    {"content": "Write a Python function to reverse a string.", "expected_tier": "any"},
    {"content": "What is machine learning?", "expected_tier": "any"},
    {"content": "Summarize the French Revolution in 3 sentences.", "expected_tier": "any"},
    {"content": "Write a haiku about coding.", "expected_tier": "any"},
    {"content": "Convert 100 Fahrenheit to Celsius.", "expected_tier": "any"},
    {"content": "What does CPU stand for?", "expected_tier": "any"},
    {"content": "Give an example of a sorting algorithm.", "expected_tier": "any"},
]


async def run_routing_accuracy(mullm_url: str = MULLM_DEFAULT) -> dict:
    """Test 20 pre-labeled queries against /classify to measure routing accuracy."""
    results = []
    correct = 0
    scored = 0  # only non-"any" cases count

    async with _make_client() as client:
        for case in _ROUTING_TEST_CASES:
            t0 = time.perf_counter()
            try:
                r = await client.post(
                    f"{mullm_url}/classify",
                    json={"content": case["content"]},
                )
                r.raise_for_status()
                data = r.json()
                latency_ms = (time.perf_counter() - t0) * 1000

                predicted = str(data.get("tier", data.get("recommended_tier", "unknown"))).lower()
                expected = case["expected_tier"]

                if expected == "any":
                    match = True  # always correct for borderline
                else:
                    scored += 1
                    # cache/free/local all satisfy "local" (cache is ≤ local cost)
                    local_equiv = {"local", "free", "cache"}
                    # cloud/cloud_full/cloud_cheap all satisfy "cloud"
                    cloud_equiv = {"cloud", "cloud_full", "cloud_cheap", "local_multi"}
                    match = (
                        predicted == expected
                        or (expected == "local" and predicted in local_equiv)
                        or (expected == "cloud" and predicted in cloud_equiv)
                    )
                    if match:
                        correct += 1

                results.append(
                    {
                        "content_preview": case["content"][:60],
                        "expected": expected,
                        "predicted": predicted,
                        "correct": match,
                        "latency_ms": round(latency_ms, 1),
                        "raw": data,
                    }
                )
            except Exception as exc:
                results.append(
                    {
                        "content_preview": case["content"][:60],
                        "expected": case["expected_tier"],
                        "predicted": "error",
                        "correct": False,
                        "latency_ms": 0,
                        "error": str(exc)[:200],
                    }
                )

    accuracy = correct / scored if scored else 0.0
    return {
        "benchmark": "routing",
        "accuracy": round(accuracy, 4),
        "correct": correct,
        "scored": scored,
        "total": len(_ROUTING_TEST_CASES),
        "results": results,
    }


# ── 4. Latency benchmark ──────────────────────────────────────────────────────

_LATENCY_QUERIES = [
    "What is 3 + 5?",
    "Name the planet closest to the sun.",
    "What is the boiling point of water in Celsius?",
    "Translate 'thank you' to Japanese.",
    "How many continents are there?",
    "What does HTML stand for?",
    "Who wrote Romeo and Juliet?",
    "What is the square root of 144?",
    "Name the primary colors.",
    "How many sides does a hexagon have?",
]


async def run_latency(mullm_url: str = MULLM_DEFAULT) -> dict:
    """Measure TTFT and total latency using the SSE streaming endpoint."""
    results = []

    async with _make_client() as client:
        for query in _LATENCY_QUERIES:
            t_start = time.perf_counter()
            ttft_ms: float | None = None
            total_chars = 0
            error: str | None = None

            try:
                params = {"content": query, "skip_cache": "true"}
                async with client.stream("GET", f"{mullm_url}/query/stream", params=params) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line:
                            continue
                        if line.startswith("data:"):
                            chunk = line[5:].strip()
                            if chunk and chunk != "[DONE]":
                                if ttft_ms is None:
                                    ttft_ms = (time.perf_counter() - t_start) * 1000
                                total_chars += len(chunk)
            except Exception as exc:
                error = str(exc)[:200]

            total_ms = (time.perf_counter() - t_start) * 1000
            results.append(
                {
                    "query": query,
                    "ttft_ms": round(ttft_ms, 1) if ttft_ms is not None else None,
                    "total_ms": round(total_ms, 1),
                    "chars": total_chars,
                    "error": error,
                }
            )

    valid = [r for r in results if r["ttft_ms"] is not None]
    ttft_vals = sorted(r["ttft_ms"] for r in valid)
    total_vals = sorted(r["total_ms"] for r in results)

    def _median(vals: list[float]) -> float:
        n = len(vals)
        if not n:
            return 0.0
        mid = n // 2
        return vals[mid] if n % 2 else (vals[mid - 1] + vals[mid]) / 2

    def _p95(vals: list[float]) -> float:
        if not vals:
            return 0.0
        idx = max(0, int(len(vals) * 0.95) - 1)
        return vals[idx]

    return {
        "benchmark": "latency",
        "ttft_median_ms": round(_median(ttft_vals), 1),
        "ttft_p95_ms": round(_p95(ttft_vals), 1),
        "total_median_ms": round(_median(total_vals), 1),
        "total_p95_ms": round(_p95(total_vals), 1),
        "queries_run": len(results),
        "results": results,
    }


# ── 5. Cache effectiveness ─────────────────────────────────────────────────────

_CACHE_QUERIES = [
    "What is the speed of light?",
    "Who invented the telephone?",
    "What is photosynthesis?",
    "Name the capital of Japan.",
    "What is Newton's first law of motion?",
    "Who painted the Mona Lisa?",
    "What is the Pythagorean theorem?",
    "What is DNA?",
    "Name the largest ocean.",
    "What year did World War II end?",
]


async def run_cache(mullm_url: str = MULLM_DEFAULT) -> dict:
    """Send the same 10 queries twice; measure cache hit rate and latency reduction."""

    async def _timed_query(client: httpx.AsyncClient, content: str, skip_cache: bool) -> tuple[dict, float]:
        t0 = time.perf_counter()
        payload: dict[str, Any] = {
            "content": content,
            "stream": False,
            "skip_cache": skip_cache,
        }
        try:
            r = await client.post(f"{mullm_url}/query", json=payload)
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            data = {"error": str(exc)[:200], "tier_used": "error", "source": "error"}
        return data, (time.perf_counter() - t0) * 1000

    async with _make_client() as client:
        # First pass: skip cache to populate it
        first_pass: list[tuple[dict, float]] = []
        for q in _CACHE_QUERIES:
            res, ms = await _timed_query(client, q, skip_cache=True)
            first_pass.append((res, ms))

        # Second pass: allow cache
        second_pass: list[tuple[dict, float]] = []
        for q in _CACHE_QUERIES:
            res, ms = await _timed_query(client, q, skip_cache=False)
            second_pass.append((res, ms))

    hits = sum(
        1
        for (res, _) in second_pass
        if str(res.get("tier_used", "") or res.get("source", "")).lower() in ("cache", "vector_cache", "cached")
    )
    hit_rate = hits / len(_CACHE_QUERIES) if _CACHE_QUERIES else 0.0

    first_lats = [ms for _, ms in first_pass]
    second_lats = [ms for _, ms in second_pass]
    avg_first = sum(first_lats) / len(first_lats) if first_lats else 0.0
    avg_second = sum(second_lats) / len(second_lats) if second_lats else 0.0
    speedup = avg_first / avg_second if avg_second > 0 else 1.0

    results = []
    for i, q in enumerate(_CACHE_QUERIES):
        r1, ms1 = first_pass[i]
        r2, ms2 = second_pass[i]
        tier2 = str(r2.get("tier_used", r2.get("source", "unknown"))).lower()
        results.append(
            {
                "query": q,
                "first_ms": round(ms1, 1),
                "second_ms": round(ms2, 1),
                "speedup": round(ms1 / ms2, 2) if ms2 > 0 else 1.0,
                "cache_hit": tier2 in ("cache", "vector_cache", "cached"),
                "second_tier": tier2,
            }
        )

    return {
        "benchmark": "cache",
        "hit_rate": round(hit_rate, 4),
        "hits": hits,
        "total": len(_CACHE_QUERIES),
        "avg_first_ms": round(avg_first, 1),
        "avg_second_ms": round(avg_second, 1),
        "speedup": round(speedup, 2),
        "results": results,
    }


# ── 6. MultiPL-E (re-exported from multipl_e module) ─────────────────────────
# Import here so callers can do `from router.benchmarks.runner import run_multipl_e`
from router.benchmarks.multipl_e import run_multipl_e as run_multipl_e  # noqa: E402, F401

# ── 7. MMLU (inline, self-contained) ─────────────────────────────────────────

_MMLU_QUESTIONS: list[dict] = [
    {
        "subject": "abstract_algebra",
        "question": "What is the order of the cyclic group Z_12?",
        "choices": ["4", "6", "12", "24"],
        "answer": "C",
    },
    {
        "subject": "abstract_algebra",
        "question": "Which of the following is NOT a field?",
        "choices": ["Q", "R", "Z", "C"],
        "answer": "C",
    },
    {
        "subject": "anatomy",
        "question": "Which organ produces insulin?",
        "choices": ["Liver", "Pancreas", "Kidney", "Stomach"],
        "answer": "B",
    },
    {
        "subject": "anatomy",
        "question": "The femur connects to which bone at the knee?",
        "choices": ["Fibula", "Tibia", "Patella", "Radius"],
        "answer": "B",
    },
    {
        "subject": "astronomy",
        "question": "What is the closest star to Earth?",
        "choices": ["Sirius", "Proxima Centauri", "Vega", "Betelgeuse"],
        "answer": "B",
    },
    {
        "subject": "astronomy",
        "question": "How many moons does Mars have?",
        "choices": ["0", "1", "2", "4"],
        "answer": "C",
    },
    {
        "subject": "clinical_knowledge",
        "question": "Normal adult resting heart rate range is:",
        "choices": ["40-60 bpm", "60-100 bpm", "100-140 bpm", "20-40 bpm"],
        "answer": "B",
    },
    {
        "subject": "college_chemistry",
        "question": "What is the pH of pure water at 25\u00b0C?",
        "choices": ["5", "6", "7", "8"],
        "answer": "C",
    },
    {
        "subject": "college_chemistry",
        "question": "Which element has atomic number 6?",
        "choices": ["Nitrogen", "Carbon", "Oxygen", "Boron"],
        "answer": "B",
    },
    {
        "subject": "college_computer_science",
        "question": "What is the time complexity of binary search?",
        "choices": ["O(n)", "O(n log n)", "O(log n)", "O(1)"],
        "answer": "C",
    },
    {
        "subject": "college_computer_science",
        "question": "Which data structure uses LIFO order?",
        "choices": ["Queue", "Stack", "Heap", "Tree"],
        "answer": "B",
    },
    {
        "subject": "college_mathematics",
        "question": "What is the derivative of sin(x)?",
        "choices": ["-cos(x)", "cos(x)", "-sin(x)", "tan(x)"],
        "answer": "B",
    },
    {
        "subject": "college_mathematics",
        "question": "What is the integral of 1/x dx?",
        "choices": ["x", "ln|x|", "1/x^2", "e^x"],
        "answer": "B",
    },
    {
        "subject": "college_physics",
        "question": "What is the speed of light in vacuum?",
        "choices": ["3x10^6 m/s", "3x10^8 m/s", "3x10^10 m/s", "3x10^4 m/s"],
        "answer": "B",
    },
    {
        "subject": "economics",
        "question": "GDP stands for:",
        "choices": [
            "Gross Domestic Product",
            "Global Development Plan",
            "General Domestic Price",
            "Gross Demand Percentage",
        ],
        "answer": "A",
    },
    {
        "subject": "electrical_engineering",
        "question": "Ohm's law states that V equals:",
        "choices": ["I/R", "IxR", "R/I", "I+R"],
        "answer": "B",
    },
    {
        "subject": "high_school_biology",
        "question": "DNA replication occurs during which phase?",
        "choices": ["G1", "S", "G2", "M"],
        "answer": "B",
    },
    {
        "subject": "high_school_chemistry",
        "question": "What is the chemical formula for water?",
        "choices": ["HO", "H2O", "H3O", "H2O2"],
        "answer": "B",
    },
    {
        "subject": "high_school_geography",
        "question": "What is the capital of Brazil?",
        "choices": ["Rio de Janeiro", "Sao Paulo", "Brasilia", "Salvador"],
        "answer": "C",
    },
    {
        "subject": "high_school_mathematics",
        "question": "What is 2^10?",
        "choices": ["512", "1024", "2048", "256"],
        "answer": "B",
    },
    {
        "subject": "high_school_physics",
        "question": "F=ma is Newton's:",
        "choices": ["First law", "Second law", "Third law", "Law of Gravity"],
        "answer": "B",
    },
    {
        "subject": "high_school_psychology",
        "question": "Classical conditioning was discovered by:",
        "choices": ["Freud", "Watson", "Pavlov", "Skinner"],
        "answer": "C",
    },
    {
        "subject": "high_school_statistics",
        "question": "The median of [1,2,3,4,5] is:",
        "choices": ["2", "3", "2.5", "4"],
        "answer": "B",
    },
    {
        "subject": "high_school_world_history",
        "question": "World War I began in:",
        "choices": ["1912", "1914", "1916", "1918"],
        "answer": "B",
    },
    {
        "subject": "human_aging",
        "question": "Normal life expectancy in developed countries is approximately:",
        "choices": ["60-65", "70-75", "78-85", "90-95"],
        "answer": "C",
    },
    {
        "subject": "machine_learning",
        "question": "What does CNN stand for in deep learning?",
        "choices": [
            "Central Neural Network",
            "Convolutional Neural Network",
            "Connected Neural Network",
            "Cyclic Neural Network",
        ],
        "answer": "B",
    },
    {
        "subject": "machine_learning",
        "question": "Which optimizer uses adaptive learning rates?",
        "choices": ["SGD", "Momentum", "Adam", "RMSProp"],
        "answer": "C",
        "alt_answer": "D",
    },
    {
        "subject": "moral_scenarios",
        "question": "Utilitarianism judges actions by:",
        "choices": ["Intent", "Duty", "Consequences", "Virtue"],
        "answer": "C",
    },
    {
        "subject": "nutrition",
        "question": "Which vitamin is produced by sunlight?",
        "choices": ["Vitamin A", "Vitamin B12", "Vitamin C", "Vitamin D"],
        "answer": "D",
    },
    {
        "subject": "world_religions",
        "question": "How many pillars of Islam are there?",
        "choices": ["3", "4", "5", "6"],
        "answer": "C",
    },
]

_MMLU_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_MMLU_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)


def _mmlu_extract_letter(response: str) -> str:
    """Extract first A/B/C/D letter from MMLU response (case-insensitive)."""
    text = _MMLU_THINK_RE.sub("", response).strip()
    if "<think>" in text:
        text = _MMLU_THINK_OPEN_RE.sub("", text).strip()

    # "the answer is X" pattern
    m = re.search(r"\bthe\s+(?:correct\s+)?answer\s+is\s+['\"]?([A-D])['\"]?", text, re.IGNORECASE)
    if m:
        return m.group(1).upper()

    # Bold: **B** or *B*
    m = re.search(r"\*{1,2}([A-D])\*{1,2}", text)
    if m:
        return m.group(1).upper()

    # Letter with punctuation: B) B. B: B,
    m = re.search(r"(?:^|\n)\s*\(?([A-D])\)?[).:\s]", text)
    if m:
        return m.group(1).upper()

    # First bare A-D word
    m = re.search(r"\b([A-D])\b", text)
    if m:
        return m.group(1).upper()

    return ""


async def run_mmlu(
    mullm_url: str = MULLM_DEFAULT,
    limit: int = 57,
    subject_filter: str = "",
    progress_cb=None,
    target_model: str = "",
) -> dict:
    """Run inline MMLU-style benchmark (30 questions) through muLLM.

    Self-contained — no external files needed.

    Args:
        mullm_url:      muLLM base URL
        limit:          Max questions to run (0 = all 30)
        subject_filter: Optional subject name substring filter
        progress_cb:    Optional callback(done: int, correct: int)

    Returns:
        dict with total, passed, accuracy, elapsed_ms, subjects_covered, results
    """
    questions = _MMLU_QUESTIONS
    if subject_filter:
        questions = [q for q in questions if subject_filter.lower() in q["subject"].lower()]
    if limit and limit < len(questions):
        questions = questions[:limit]

    results: list[dict] = []
    passed_count = 0
    subjects_seen: set[str] = set()
    t0_all = time.perf_counter()

    async with _make_client() as client:
        for i, q in enumerate(questions):
            subjects_seen.add(q["subject"])
            prompt = (
                f"{q['question']}\n\n"
                f"A. {q['choices'][0]}\n"
                f"B. {q['choices'][1]}\n"
                f"C. {q['choices'][2]}\n"
                f"D. {q['choices'][3]}\n\n"
                f"Answer with just the letter (A, B, C, or D). /no_think"
            )
            t0 = time.perf_counter()
            data = await _query(client, mullm_url, prompt, target_model=target_model)
            raw = data.get("response", "")
            model_answer = _mmlu_extract_letter(raw)

            # Auto-escalate shape check: if local gave no valid A/B/C/D letter,
            # the response is malformed — re-query via cloud immediately.
            # This catches empty outputs, repetition, "I don't know", etc.
            if not model_answer and data.get("tier_used", "").startswith("local"):
                data2 = await _query(client, mullm_url, prompt, force_tier="cloud")
                raw2 = data2.get("response", "")
                letter2 = _mmlu_extract_letter(raw2)
                if letter2:
                    data = data2
                    raw = raw2
                    model_answer = letter2

            latency_ms = (time.perf_counter() - t0) * 1000

            expected = q["answer"]
            alt = q.get("alt_answer", "")
            correct = (model_answer == expected) or (bool(alt) and model_answer == alt)

            if correct:
                passed_count += 1

            results.append(
                {
                    "subject": q["subject"],
                    "question_snippet": q["question"][:80],
                    "expected": expected,
                    "model_answer": model_answer,
                    "correct": correct,
                    "tier_used": data.get("tier_used", "unknown"),
                    "model_used": data.get("model_used", "unknown"),
                    "cost": data.get("cost", 0),
                    "latency_ms": round(latency_ms, 1),
                    "escalated": data.get("tier_used", "").startswith("cloud") and not data.get("tier_used", "").startswith("local"),
                }
            )

            if progress_cb:
                progress_cb(len(results), passed_count)

    elapsed_ms = (time.perf_counter() - t0_all) * 1000
    total = len(results)
    accuracy = passed_count / total if total else 0.0

    return {
        "benchmark": "mmlu_inline",
        "total": total,
        "passed": passed_count,
        "accuracy": round(accuracy, 4),
        "elapsed_ms": round(elapsed_ms, 1),
        "subjects_covered": sorted(subjects_seen),
        "results": results,
    }


# ── 8. GSM8K (inline, self-contained) ────────────────────────────────────────

_GSM8K_PROBLEMS: list[dict] = [
    {
        "id": "gsm_01",
        "problem": "Janet has 3 apples. She gives 2 to her friend and buys 5 more. How many apples does she have?",
        "answer": 6,
    },
    {"id": "gsm_02", "problem": "A train travels 60 mph for 3 hours. How many miles does it travel?", "answer": 180},
    {
        "id": "gsm_03",
        "problem": "If 5 workers can build a wall in 10 days, how many days would 10 workers take?",
        "answer": 5,
    },
    {"id": "gsm_04", "problem": "A store sells pencils for $0.25 each. How much do 12 pencils cost?", "answer": 3.0},
    {
        "id": "gsm_05",
        "problem": "Sarah is twice as old as her brother. Her brother is 8. How old is Sarah?",
        "answer": 16,
    },
    {"id": "gsm_06", "problem": "A rectangle has length 12 and width 5. What is its perimeter?", "answer": 34},
    {"id": "gsm_07", "problem": "If 30% of 200 students passed, how many passed?", "answer": 60},
    {"id": "gsm_08", "problem": "A car travels 240 miles on 8 gallons of gas. What is the MPG?", "answer": 30},
    {
        "id": "gsm_09",
        "problem": "A pizza is cut into 8 slices. If 3 people each eat 2 slices, how many slices remain?",
        "answer": 2,
    },
    {"id": "gsm_10", "problem": "Tom reads 25 pages per day. How many days to read a 300-page book?", "answer": 12},
    {"id": "gsm_11", "problem": "A shirt costs $40. It's on sale for 25% off. What's the sale price?", "answer": 30},
    {
        "id": "gsm_12",
        "problem": "A jar contains 15 red and 10 blue marbles. What fraction are red?",
        "answer": 0.6,
        "alt_answers": ["3/5", "0.6", "60%", "60"],
    },
    {"id": "gsm_13", "problem": "If a square has area 81, what is its side length?", "answer": 9},
    {
        "id": "gsm_14",
        "problem": "Mike earns $15/hour. He works 40 hours/week for 4 weeks. Total earnings?",
        "answer": 2400,
    },
    {
        "id": "gsm_15",
        "problem": "A recipe needs 2.5 cups of flour for 12 cookies. For 36 cookies, how many cups?",
        "answer": 7.5,
    },
    {
        "id": "gsm_16",
        "problem": "The sum of angles in a triangle is 180 degrees. Two angles are 60 degrees and 70 degrees. Third angle?",
        "answer": 50,
    },
    {"id": "gsm_17", "problem": "A population of 1000 grows by 10% per year. After 1 year?", "answer": 1100},
    {
        "id": "gsm_18",
        "problem": "A cylinder has radius 7 and height 10. What is the volume? (use pi=22/7)",
        "answer": 1540,
    },
    {"id": "gsm_19", "problem": "If 4x + 8 = 24, what is x?", "answer": 4},
    {"id": "gsm_20", "problem": "A store buys an item for $80 and sells it at 25% profit. Sale price?", "answer": 100},
]

_GSM_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)
_GSM_THINK_OPEN_RE = re.compile(r"<think>.*", re.DOTALL)


def _gsm_extract_number(response: str) -> str | None:
    """Extract final numeric answer from a GSM8K response."""
    text = _GSM_THINK_RE.sub("", response).strip()
    if "<think>" in text:
        text = _GSM_THINK_OPEN_RE.sub("", text).strip()

    # "Answer: 42" pattern
    m = re.search(r"Answer\s*:\s*\$?\s*(-?\d[\d,]*\.?\d*)", text, re.IGNORECASE)
    if m:
        return m.group(1).replace(",", "")

    # "#### 42" GSM8K format
    m = re.search(r"####\s*(-?\d[\d,]*\.?\d*)", text)
    if m:
        return m.group(1).replace(",", "")

    # "= 42" at end of line
    m = re.search(r"=\s*\$?\s*(-?\d[\d,]*\.?\d*)\s*$", text, re.MULTILINE)
    if m:
        return m.group(1).replace(",", "")

    # Last number in response
    numbers = re.findall(r"-?\d[\d,]*\.?\d*", text)
    if numbers:
        return numbers[-1].replace(",", "")

    return None


def _gsm_answers_match(predicted: str | None, prob: dict) -> bool:
    """Compare predicted answer to ground truth, with fraction support for gsm_12."""
    if predicted is None:
        return False

    expected = prob["answer"]
    alt_answers = prob.get("alt_answers", [])

    # Check alt string answers first (for fraction/percent problems)
    if alt_answers:
        pred_stripped = predicted.strip().rstrip("%")
        for alt in alt_answers:
            alt_stripped = str(alt).strip().rstrip("%")
            if pred_stripped == alt_stripped:
                return True
        # Also handle "3/5" → 0.6
        if "/" in predicted:
            try:
                num, den = predicted.split("/", 1)
                frac_val = float(num.strip()) / float(den.strip())
                if abs(frac_val - float(expected)) < 0.01:
                    return True
            except (ValueError, ZeroDivisionError):
                pass

    try:
        p = float(predicted.replace(",", ""))
        g = float(expected)
        return abs(p - g) < 0.01
    except (ValueError, AttributeError, TypeError):
        return str(predicted).strip() == str(expected).strip()


# ── ARC-Challenge (AI2 Reasoning Challenge) ────────────────────────────────
# 40 authentic ARC-Challenge questions — multi-choice science reasoning.
# Source: Clark et al. (2018), https://allenai.org/data/arc
_ARC_QUESTIONS: list[dict] = [
    {"id": "arc_01", "question": "Which property of a mineral can be determined just by looking at it?", "choices": ["luster", "hardness", "density", "solubility"], "answer": "A"},
    {"id": "arc_02", "question": "A student wants to observe a solar eclipse. What should the student use to safely observe the eclipse?", "choices": ["binoculars", "a telescope", "special eclipse glasses", "sunglasses"], "answer": "C"},
    {"id": "arc_03", "question": "Which of the following best explains why the moon appears to change shape over a month?", "choices": ["The moon rotates on its axis", "Different portions of the lit moon are visible from Earth", "The moon moves closer and farther from Earth", "Earth's shadow covers part of the moon"], "answer": "B"},
    {"id": "arc_04", "question": "A plant is placed in a dark room for one week. What would most likely happen to the plant?", "choices": ["The plant would grow faster", "The plant would make more food", "The plant's leaves would turn yellow", "The plant would absorb more water"], "answer": "C"},
    {"id": "arc_05", "question": "Which type of rock is formed from cooled magma?", "choices": ["sedimentary", "metamorphic", "igneous", "fossil"], "answer": "C"},
    {"id": "arc_06", "question": "What is the main source of energy for almost all living things on Earth?", "choices": ["the moon", "the sun", "wind", "water"], "answer": "B"},
    {"id": "arc_07", "question": "A student mixes baking soda and vinegar together in a cup. Bubbles form. This is an example of a:", "choices": ["physical change", "chemical change", "change in state", "magnetic change"], "answer": "B"},
    {"id": "arc_08", "question": "Which of Earth's layers is the thinnest?", "choices": ["inner core", "outer core", "mantle", "crust"], "answer": "D"},
    {"id": "arc_09", "question": "What causes seasons on Earth?", "choices": ["Earth's distance from the sun", "Earth's tilted axis", "The moon's gravity", "Sunspot activity"], "answer": "B"},
    {"id": "arc_10", "question": "A student cuts a piece of paper into smaller pieces. What kind of change is this?", "choices": ["chemical", "thermal", "physical", "nuclear"], "answer": "C"},
    {"id": "arc_11", "question": "Which gas do plants absorb during photosynthesis?", "choices": ["oxygen", "nitrogen", "carbon dioxide", "hydrogen"], "answer": "C"},
    {"id": "arc_12", "question": "Which of the following is a characteristic of all living things?", "choices": ["ability to move", "ability to reproduce", "ability to make food", "ability to see"], "answer": "B"},
    {"id": "arc_13", "question": "What layer of the atmosphere contains the ozone layer?", "choices": ["troposphere", "stratosphere", "mesosphere", "thermosphere"], "answer": "B"},
    {"id": "arc_14", "question": "A block of ice melts into water. Which best describes what happened to the water molecules?", "choices": ["They were destroyed", "They changed into a new substance", "They moved farther apart", "They decreased in number"], "answer": "C"},
    {"id": "arc_15", "question": "Which force keeps the moon in orbit around Earth?", "choices": ["magnetism", "gravity", "friction", "electricity"], "answer": "B"},
    {"id": "arc_16", "question": "What is the role of decomposers in an ecosystem?", "choices": ["Produce food from sunlight", "Break down dead organic matter", "Capture energy from the sun", "Hunt other organisms for food"], "answer": "B"},
    {"id": "arc_17", "question": "A ball rolling across the floor slows down and stops. What force caused it to stop?", "choices": ["gravity", "magnetism", "friction", "inertia"], "answer": "C"},
    {"id": "arc_18", "question": "Which of the following is an example of a renewable resource?", "choices": ["coal", "natural gas", "petroleum", "solar energy"], "answer": "D"},
    {"id": "arc_19", "question": "What is the basic unit of all living organisms?", "choices": ["atom", "molecule", "cell", "organ"], "answer": "C"},
    {"id": "arc_20", "question": "A student observes that a metal spoon left in hot soup becomes warm. How did the heat travel to the spoon?", "choices": ["radiation", "convection", "conduction", "evaporation"], "answer": "C"},
    {"id": "arc_21", "question": "Which planet in our solar system has the most moons?", "choices": ["Jupiter", "Saturn", "Uranus", "Neptune"], "answer": "B"},
    {"id": "arc_22", "question": "What process do plants use to convert sunlight into food?", "choices": ["respiration", "transpiration", "photosynthesis", "fermentation"], "answer": "C"},
    {"id": "arc_23", "question": "A student notices that a metal bridge expands slightly in summer and contracts in winter. What causes this?", "choices": ["Change in air pressure", "Change in temperature", "Change in humidity", "Change in wind speed"], "answer": "B"},
    {"id": "arc_24", "question": "Which of the following is NOT a type of wave that transfers energy?", "choices": ["sound wave", "light wave", "radio wave", "matter wave"], "answer": "D"},
    {"id": "arc_25", "question": "What type of symbiosis describes a relationship where one organism benefits and the other is neither helped nor harmed?", "choices": ["mutualism", "parasitism", "commensalism", "predation"], "answer": "C"},
    {"id": "arc_26", "question": "Which statement best describes the water cycle?", "choices": ["Water moves only from oceans to clouds", "Water is continuously recycled through evaporation, condensation, and precipitation", "Water is created by plants during photosynthesis", "Water flows only downhill and never returns"], "answer": "B"},
    {"id": "arc_27", "question": "A bird with a long, thin beak is most likely adapted for:", "choices": ["cracking seeds", "catching fish", "drinking nectar from flowers", "tearing meat"], "answer": "C"},
    {"id": "arc_28", "question": "Which of the following best describes a fossil fuel?", "choices": ["Energy from the sun", "Stored energy from ancient organisms", "Energy from moving water", "Energy from wind"], "answer": "B"},
    {"id": "arc_29", "question": "What happens to most of the sunlight that reaches Earth's surface?", "choices": ["It is reflected back into space", "It is absorbed and converted to heat", "It is used by all organisms for energy", "It is stored in rocks"], "answer": "B"},
    {"id": "arc_30", "question": "Which of the following would MOST increase the rate of a chemical reaction?", "choices": ["Decreasing temperature", "Decreasing the amount of reactants", "Increasing temperature", "Adding water"], "answer": "C"},
    {"id": "arc_31", "question": "A student observes that pond water contains many tiny organisms. Which tool would help the student see them best?", "choices": ["telescope", "microscope", "magnifying glass", "barometer"], "answer": "B"},
    {"id": "arc_32", "question": "Which best describes the difference between an atom and a molecule?", "choices": ["Atoms are larger than molecules", "A molecule is made of two or more atoms bonded together", "Atoms only exist in gases", "Molecules cannot be broken apart"], "answer": "B"},
    {"id": "arc_33", "question": "What is the main function of the roots of a plant?", "choices": ["To produce food through photosynthesis", "To absorb water and minerals from soil", "To release oxygen into the air", "To attract pollinators"], "answer": "B"},
    {"id": "arc_34", "question": "A student notices that a compass needle always points north. This is because Earth has a:", "choices": ["gravitational field", "magnetic field", "electric field", "pressure field"], "answer": "B"},
    {"id": "arc_35", "question": "Which of the following best explains why stars appear to twinkle at night?", "choices": ["Stars are burning and flickering", "Stars move rapidly back and forth", "Light from stars is bent by Earth's atmosphere", "Stars are very far away and small"], "answer": "C"},
    {"id": "arc_36", "question": "What is the correct order of the scientific method?", "choices": ["Question, Hypothesis, Experiment, Analysis, Conclusion", "Hypothesis, Question, Experiment, Conclusion, Analysis", "Experiment, Question, Hypothesis, Analysis, Conclusion", "Analysis, Hypothesis, Question, Experiment, Conclusion"], "answer": "A"},
    {"id": "arc_37", "question": "Which material is the best electrical conductor?", "choices": ["rubber", "wood", "plastic", "copper"], "answer": "D"},
    {"id": "arc_38", "question": "A student uses a lever to lift a heavy rock. The lever makes the task easier by:", "choices": ["Reducing the amount of work done", "Increasing the force applied over a shorter distance", "Reducing the force needed over a longer distance", "Eliminating friction"], "answer": "C"},
    {"id": "arc_39", "question": "Which of the following is an example of matter changing from liquid to gas?", "choices": ["Ice turning into water", "Water forming ice crystals", "Puddles disappearing after rain", "Steam condensing on a cold glass"], "answer": "C"},
    {"id": "arc_40", "question": "A student finds a rock with visible layers and tiny shell fragments inside. What type of rock is it most likely?", "choices": ["igneous", "metamorphic", "sedimentary", "granite"], "answer": "C"},
]


async def run_arc(
    mullm_url: str = MULLM_DEFAULT,
    limit: int = 40,
    progress_cb=None,
    force_tier: str = "",
    target_model: str = "",
) -> dict:
    """Run ARC-Challenge inline benchmark through muLLM.

    40 authentic AI2 Reasoning Challenge questions — multi-choice science reasoning.
    Source: Clark et al. (2018), allenai.org/data/arc

    Args:
        mullm_url:   muLLM base URL
        limit:       Number of questions to run (default 40 = all)
        progress_cb: Optional callback(done: int, correct: int)
        force_tier:  Optional tier override ("local", "cloud", etc.)

    Returns:
        dict with total, passed, accuracy, elapsed_ms, results
    """
    questions = _ARC_QUESTIONS[:limit] if limit else _ARC_QUESTIONS

    results: list[dict] = []
    passed_count = 0
    t0_all = time.perf_counter()

    async with _make_client() as client:
        for q in questions:
            prompt = (
                f"{q['question']}\n\n"
                f"A. {q['choices'][0]}\n"
                f"B. {q['choices'][1]}\n"
                f"C. {q['choices'][2]}\n"
                f"D. {q['choices'][3]}\n\n"
                f"Answer with just the letter (A, B, C, or D). /no_think"
            )
            t0 = time.perf_counter()
            data = await _query(client, mullm_url, prompt, force_tier, target_model=target_model)
            raw = data.get("response", "")
            model_answer = _mmlu_extract_letter(raw)  # reuse same A/B/C/D extractor

            # Auto-escalate shape check: if local gave no valid letter, escalate
            if not model_answer and not force_tier and data.get("tier_used", "").startswith("local"):
                data2 = await _query(client, mullm_url, prompt, force_tier="cloud")
                raw2 = data2.get("response", "")
                letter2 = _mmlu_extract_letter(raw2)
                if letter2:
                    data = data2
                    raw = raw2
                    model_answer = letter2

            latency_ms = (time.perf_counter() - t0) * 1000
            correct = model_answer == q["answer"]
            if correct:
                passed_count += 1

            results.append({
                "id": q["id"],
                "question_snippet": q["question"][:80],
                "expected": q["answer"],
                "model_answer": model_answer,
                "correct": correct,
                "tier_used": data.get("tier_used", "unknown"),
                "model_used": data.get("model_used", "unknown"),
                "cost": data.get("cost", 0),
                "latency_ms": round(latency_ms, 1),
            })

            if progress_cb:
                progress_cb(len(results), passed_count)

    elapsed_ms = (time.perf_counter() - t0_all) * 1000
    total = len(results)
    accuracy = passed_count / total if total else 0.0

    return {
        "benchmark": "arc_challenge",
        "total": total,
        "passed": passed_count,
        "accuracy": round(accuracy, 4),
        "elapsed_ms": round(elapsed_ms, 1),
        "results": results,
    }


async def run_gsm8k(
    mullm_url: str = MULLM_DEFAULT,
    limit: int = 20,
    progress_cb=None,
    force_tier: str = "",
    target_model: str = "",
) -> dict:
    """Run GSM8K math benchmark through muLLM.

    Loads full 1319-problem dataset from gsm8k_problems.jsonl when limit > 20.

    Args:
        mullm_url:   muLLM base URL
        limit:       Number of problems to run (0 = all, default 20)
        progress_cb: Optional callback(done: int, correct: int)

    Returns:
        dict with total, passed, accuracy, elapsed_ms, results
    """
    import json as _json
    from pathlib import Path as _Path
    _full_path = _Path(__file__).parent / "gsm8k_problems.jsonl"
    if limit > len(_GSM8K_PROBLEMS) and _full_path.exists():
        _raw = [_json.loads(l) for l in _full_path.read_text().splitlines() if l.strip()]
        # normalize schema: jsonl uses 'question'/'answer', inline uses 'problem'/'answer'
        all_problems = [{"id": r.get("id", f"gsm_{i}"), "problem": r.get("question", r.get("problem","")), "answer": r.get("answer", "")} for i, r in enumerate(_raw)]
    else:
        all_problems = _GSM8K_PROBLEMS
    problems = all_problems[:limit] if limit else all_problems
    results: list[dict] = []
    passed_count = 0
    t0_all = time.perf_counter()

    async with _make_client() as client:
        for prob in problems:
            prompt = f"Math problem: {prob['problem']}\n\nAnswer: <number> /no_think"
            t0 = time.perf_counter()
            data = await _query(client, mullm_url, prompt, force_tier, target_model=target_model)
            raw = data.get("response", "")
            model_answer = _gsm_extract_number(raw)

            # Auto-escalate shape check: if local returned no parseable number,
            # the response is malformed — re-query via cloud.
            if not model_answer and not force_tier and data.get("tier_used", "").startswith("local"):
                data2 = await _query(client, mullm_url, prompt, force_tier="cloud")
                raw2 = data2.get("response", "")
                num2 = _gsm_extract_number(raw2)
                if num2:
                    data = data2
                    raw = raw2
                    model_answer = num2

            latency_ms = (time.perf_counter() - t0) * 1000
            correct = _gsm_answers_match(model_answer, prob)

            if correct:
                passed_count += 1

            results.append(
                {
                    "problem_snippet": prob["problem"][:100],
                    "expected": prob["answer"],
                    "model_answer": model_answer,
                    "correct": correct,
                    "tier_used": data.get("tier_used", "unknown"),
                    "model_used": data.get("model_used", "unknown"),
                    "cost": data.get("cost", 0),
                    "latency_ms": round(latency_ms, 1),
                }
            )

            if progress_cb:
                progress_cb(len(results), passed_count)

    elapsed_ms = (time.perf_counter() - t0_all) * 1000
    total = len(results)
    accuracy = passed_count / total if total else 0.0

    return {
        "benchmark": "gsm8k_inline",
        "total": total,
        "passed": passed_count,
        "accuracy": round(accuracy, 4),
        "elapsed_ms": round(elapsed_ms, 1),
        "results": results,
    }
