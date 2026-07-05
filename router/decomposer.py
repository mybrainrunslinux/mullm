"""
muLLM prompt decomposer — splits multi-part prompts into parallel sub-tasks.

Fast path: regex-based pattern detection (numbered lists, bullets, semicolons, "then").
Slow path: LLM-based decomposition via ollama_client (only when fast path returns None).
"""
from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger("mullm.decomposer")

try:
    import ollama as ollama_client  # type: ignore
except ImportError:
    ollama_client = None  # type: ignore

_CLOUD_CHEAP_SIGNALS = re.compile(
    r"\b(compare|contrast|analyze|design|architecture|diagram|mermaid|critique"
    r"|review|trade.?off|pros?.and.cons?|evaluate)\b",
    re.IGNORECASE,
)
_CLOUD_FULL_SIGNALS = re.compile(
    r"\b(production|implement.+complete|full.+implement|comprehensive|end.?to.?end"
    r"|deploy.+entire|build.+system)\b",
    re.IGNORECASE,
)

_NUMBERED_RE = re.compile(r"(?:^|\s)(\d+)\.\s+(.+?)(?=\s+\d+\.|$)", re.DOTALL)
_BULLET_RE = re.compile(r"^[-*•]\s+(.+)$", re.MULTILINE)
_SEMICOLON_RE = re.compile(r";\s*")
_THEN_RE = re.compile(r"\b(?:then|after\s+that|next,?|followed\s+by)\b", re.IGNORECASE)
_AND_ALSO_RE = re.compile(r"\band\s+also\b|\band\b", re.IGNORECASE)


def _quick_tier_estimate(text: str) -> str:
    """Estimate the routing tier for a single text query."""
    if _CLOUD_FULL_SIGNALS.search(text):
        return "cloud_full"
    if _CLOUD_CHEAP_SIGNALS.search(text):
        return "cloud_cheap"
    return "local"


def _fast_decompose(content: str) -> list[dict] | None:
    """
    Fast regex-based decomposition. Returns None for single tasks.
    Each returned item: {"task": str, "suggested_tier": str, "depends_on": list[int]}
    """
    content = content.strip()

    # Try numbered list (inline or multiline)
    numbered = _NUMBERED_RE.findall(content)
    if len(numbered) >= 2:
        tasks = [t.strip() for _, t in numbered if t.strip()]
        if len(tasks) >= 2:
            return [
                {"task": t, "suggested_tier": _quick_tier_estimate(t), "depends_on": []}
                for t in tasks
            ]

    # Try bullet list
    bullets = _BULLET_RE.findall(content)
    if len(bullets) >= 2:
        return [
            {"task": t.strip(), "suggested_tier": _quick_tier_estimate(t), "depends_on": []}
            for t in bullets if t.strip()
        ]

    # Try semicolons
    parts = [p.strip() for p in _SEMICOLON_RE.split(content) if p.strip()]
    if len(parts) >= 2:
        return [
            {"task": t, "suggested_tier": _quick_tier_estimate(t), "depends_on": []}
            for t in parts
        ]

    # Try "then" sequential pattern
    then_parts = [p.strip() for p in _THEN_RE.split(content) if p.strip()]
    if len(then_parts) >= 2:
        result = []
        for i, t in enumerate(then_parts):
            result.append({
                "task": t,
                "suggested_tier": _quick_tier_estimate(t),
                "depends_on": [i - 1] if i > 0 else [],
            })
        return result

    # Try "and also" / "and" pattern (last resort)
    and_parts = [p.strip() for p in _AND_ALSO_RE.split(content) if p.strip() and len(p.strip()) > 5]
    if len(and_parts) >= 2:
        return [
            {"task": t, "suggested_tier": _quick_tier_estimate(t), "depends_on": []}
            for t in and_parts
        ]

    return None


def _parse_decompose_output(raw: str | None) -> list[dict] | None:
    """Parse JSON output from LLM decomposition. Returns None on failure."""
    if not raw:
        return None
    raw = raw.strip()

    # Try direct JSON array
    try:
        data = json.loads(raw)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "tasks" in data:
            return data["tasks"]
        return None
    except json.JSONDecodeError:
        pass

    # Try to find embedded JSON
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return None


def _validate_subtasks(tasks: list) -> list[dict] | None:
    """Validate and normalize subtask list. Returns None if all tasks are invalid."""
    valid_tiers = {"local", "cloud_cheap", "cloud_full", "cache"}
    result = []
    for item in tasks:
        if not isinstance(item, dict):
            continue
        task = str(item.get("task", "")).strip()
        if not task:
            continue
        tier = item.get("suggested_tier", "local")
        if tier not in valid_tiers:
            tier = "local"
        # Filter out invalid depends_on entries
        raw_deps = item.get("depends_on", [])
        n = len(result)  # valid index so far
        deps = [d for d in raw_deps if isinstance(d, int) and 0 <= d < n]
        result.append({"task": task, "suggested_tier": tier, "depends_on": deps})
    return result if result else None


def _classify_subtasks(tasks: list[str], sequential: bool = False) -> list[dict]:
    """Classify a list of task strings into tier-annotated dicts."""
    result = []
    for i, t in enumerate(tasks):
        result.append({
            "task": t,
            "suggested_tier": _quick_tier_estimate(t),
            "depends_on": [i - 1] if sequential and i > 0 else [],
        })
    return result


def build_execution_order(tasks: list[dict]) -> list[list[int]]:
    """Topological sort of tasks into execution waves (parallel batches)."""
    if not tasks:
        return []
    n = len(tasks)
    placed = set()
    waves: list[list[int]] = []

    for _ in range(n):
        wave = []
        for i in range(n):
            if i in placed:
                continue
            deps = tasks[i].get("depends_on", [])
            valid_deps = [d for d in deps if isinstance(d, int) and 0 <= d < n]
            if all(d in placed for d in valid_deps):
                wave.append(i)
        if not wave:
            # Circular dependency — dump remaining
            remaining = [i for i in range(n) if i not in placed]
            waves.append(remaining)
            break
        waves.append(wave)
        placed.update(wave)
        if placed == set(range(n)):
            break

    return waves


async def decompose_prompt(content: str) -> list[dict]:
    """
    Decompose a prompt into sub-tasks.
    Fast path (regex) first; falls back to single-task list for simple queries.
    """
    fast = _fast_decompose(content)
    if fast:
        validated = _validate_subtasks(fast)
        if validated:
            return validated

    # Single task fallback
    return [{"task": content, "suggested_tier": _quick_tier_estimate(content), "depends_on": []}]
