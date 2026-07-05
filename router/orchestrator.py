"""
muLLM Orchestrator — repo-scale task planning and execution.

Indexes a repository, reads task lists (BUGS.md, REQUESTS.md, TODO.md),
decomposes them into routable subtasks, executes via muLLM pipeline,
and applies patches with rollback support.

Also loads project context (CLAUDE.md, MULLM.md) for code-gen tasks.

Usage:
    from router.orchestrator import Orchestrator
    orch = Orchestrator(api_url="https://127.0.0.1:6856")
    plan = await orch.plan_from_file("BUGS.md")
    results = await orch.execute(plan)
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import structlog

    log = structlog.get_logger()
except ImportError:
    import logging as _logging

    class _KwargLogger:
        """Stdlib logger wrapper that accepts structlog-style kwargs."""

        def __init__(self, name: str):
            self._log = _logging.getLogger(name)

        def _fmt(self, msg: str, kw: dict) -> str:
            if kw:
                pairs = " ".join(f"{k}={v}" for k, v in kw.items())
                return f"{msg} {pairs}"
            return msg

        def info(self, msg: str, **kw: Any):
            self._log.info(self._fmt(msg, kw))

        def warning(self, msg: str, **kw: Any):
            self._log.warning(self._fmt(msg, kw))

        def error(self, msg: str, **kw: Any):
            self._log.error(self._fmt(msg, kw))

        def debug(self, msg: str, **kw: Any):
            self._log.debug(self._fmt(msg, kw))

    log = _KwargLogger("orchestrator")


# ── Project Context ──────────────────────────────────────────

CONTEXT_FILES = [
    "CLAUDE.md",
    "MULLM.md",
    ".mullm.md",
    "ARCHITECTURE.md",
    "DESIGN.md",
]

TASK_FILES = [
    "BUGS.md",
    "REQUESTS.md",
    "TODO.md",
    "TODAY.md",
    "TOMORROW.md",
]

# File extensions to index
INDEX_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".html",
    ".css",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".cfg",
    ".ini",
    ".md",
    ".sh",
    ".bash",
    ".sql",
}

# Dirs to skip
SKIP_DIRS = {
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".git",
    "cache",
    "dist",
    "build",
    ".tox",
    ".mypy_cache",
    ".pytest_cache",
    "test-results",
}


@dataclass
class FileInfo:
    """Lightweight file metadata for the index."""

    path: str
    size: int
    lines: int
    ext: str
    summary: str = ""  # one-line description (filled by summarizer)


@dataclass
class Task:
    """A single actionable task from a task list."""

    id: int
    description: str
    source_file: str = ""
    source_line: int = 0
    priority: str = "medium"  # low, medium, high, critical
    target_files: list[str] = field(default_factory=list)
    suggested_tier: str = "local"
    depends_on: list[int] = field(default_factory=list)
    status: str = "pending"  # pending, running, done, failed, skipped
    result: dict = field(default_factory=dict)


@dataclass
class Plan:
    """Execution plan — ordered list of tasks with routing."""

    tasks: list[Task]
    context: str = ""  # project context from CLAUDE.md etc.
    repo_summary: str = ""
    total_estimated_cost: float = 0.0


class Orchestrator:
    """
    Repo-scale task orchestrator for muLLM.

    Workflow:
    1. index_repo() — scan files, build lightweight index
    2. load_context() — read CLAUDE.md, MULLM.md for system prompt
    3. plan_from_file() or plan_from_tasks() — parse task list, assign tiers
    4. execute() — run tasks through muLLM pipeline, apply patches
    """

    def __init__(
        self,
        api_url: str = "https://127.0.0.1:6856",
        repo_root: str | None = None,
        max_context_chars: int = 4000,
        verify_cmd: str = "",
        max_retries: int = 2,
        task_timeout: int = 600,
    ):
        self.api_url = api_url.rstrip("/")
        self.repo_root = Path(repo_root or os.getcwd())
        self.max_context_chars = max_context_chars
        self.verify_cmd = verify_cmd  # e.g. "npx playwright test tts.spec.js"
        self._retries_left = max_retries
        self.task_timeout = task_timeout
        self.file_index: list[FileInfo] = []
        self.project_context: str = ""
        self._session_id = f"orch-{int(time.time())}"

    # ── File Indexer ──────────────────────────────────────────

    def index_repo(self, root: Path | None = None) -> list[FileInfo]:
        """Scan repo, build file index with size/line counts."""
        root = root or self.repo_root
        self.file_index = []

        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            # Skip excluded dirs
            if any(skip in path.parts for skip in SKIP_DIRS):
                continue
            if path.suffix not in INDEX_EXTENSIONS:
                continue

            rel = str(path.relative_to(root))
            try:
                content = path.read_text(errors="replace")
                lines = content.count("\n") + 1
                size = path.stat().st_size
            except Exception:
                continue

            self.file_index.append(
                FileInfo(
                    path=rel,
                    size=size,
                    lines=lines,
                    ext=path.suffix,
                )
            )

        log.info(
            "repo_indexed", files=len(self.file_index), total_kb=round(sum(f.size for f in self.file_index) / 1024, 1)
        )
        return self.file_index

    def repo_summary(self) -> str:
        """One-paragraph repo summary from the index."""
        if not self.file_index:
            self.index_repo()

        by_ext: dict[str, int] = {}
        total_lines = 0
        total_kb = 0
        for f in self.file_index:
            by_ext[f.ext] = by_ext.get(f.ext, 0) + 1
            total_lines += f.lines
            total_kb += f.size

        ext_str = ", ".join(f"{cnt} {ext}" for ext, cnt in sorted(by_ext.items(), key=lambda x: -x[1])[:6])
        return (
            f"Repository: {len(self.file_index)} files, "
            f"{total_lines:,} lines, {total_kb // 1024}KB. "
            f"Breakdown: {ext_str}."
        )

    # ── Context Loader ────────────────────────────────────────

    def load_context(self) -> str:
        """Load project context from CLAUDE.md, MULLM.md, etc."""
        parts = []
        for name in CONTEXT_FILES:
            path = self.repo_root / name
            if path.exists():
                content = path.read_text(errors="replace")
                # Budget: cap each file to a portion of max context
                cap = self.max_context_chars // max(len(CONTEXT_FILES), 1)
                if len(content) > cap:
                    content = content[:cap] + "\n... [truncated]"
                parts.append(f"# {name}\n{content}")

        self.project_context = "\n\n".join(parts) if parts else ""
        log.info("context_loaded", files=len(parts), chars=len(self.project_context))
        return self.project_context

    def context_for_task(self, task: Task) -> str:
        """Return context appropriate for a task's tier.
        Local models get a short summary. Cloud gets full context."""
        if not self.project_context:
            self.load_context()

        if task.suggested_tier in ("cloud_cheap", "cloud_full"):
            return self.project_context
        # Local: short summary only
        return self.project_context[:1500] if self.project_context else ""

    # ── Task Parser ───────────────────────────────────────────

    def parse_task_file(self, filepath: str) -> list[Task]:
        """Parse a markdown task file into structured tasks."""
        path = self.repo_root / filepath
        if not path.exists():
            log.warning("task_file_not_found", path=filepath)
            return []

        content = path.read_text(errors="replace")
        tasks = []
        task_id = 0

        for i, line in enumerate(content.split("\n"), 1):
            # Track indent BEFORE stripping — sub-bullets are noise
            indent = len(line) - len(line.lstrip())
            line = line.strip()
            if not line:
                continue
            # Skip indented items (sub-bullets, notes, examples)
            if indent > 0:
                continue

            # Match: - [ ] task, - task, * task, numbered items, ### headers
            task_text = None
            priority = "medium"

            # Checkbox items
            m = re.match(r"^[-*]\s*\[[ x]\]\s+(.+)", line, re.I)
            if m:
                task_text = m.group(1).strip()
                # Skip checked items
                if re.match(r"^[-*]\s*\[x\]", line, re.I):
                    continue

            # Bullet items
            if not task_text:
                m = re.match(r"^[-*]\s+(.{15,})", line)
                if m:
                    task_text = m.group(1).strip()

            # Numbered items
            if not task_text:
                m = re.match(r"^\d+[.)]\s+(.{15,})", line)
                if m:
                    task_text = m.group(1).strip()

            # Headers as task groups (skip)
            if line.startswith("#"):
                # Detect priority from headers
                lower = line.lower()
                if any(w in lower for w in ("critical", "urgent", "must")):
                    priority = "critical"
                elif any(w in lower for w in ("high", "important")):
                    priority = "high"
                elif any(w in lower for w in ("low", "nice", "bonus")):
                    priority = "low"
                continue

            if task_text and len(task_text) > 10:
                # Detect target files from the task text
                target_files = self._detect_files(task_text)
                tier = self._estimate_tier(task_text)

                tasks.append(
                    Task(
                        id=task_id,
                        description=task_text,
                        source_file=filepath,
                        source_line=i,
                        priority=priority,
                        target_files=target_files,
                        suggested_tier=tier,
                    )
                )
                task_id += 1

        log.info("tasks_parsed", target=filepath, count=len(tasks))
        return tasks

    def _detect_files(self, text: str) -> list[str]:
        """Detect file references in task text."""
        found = []
        # Explicit file paths
        # Consume leading quote char separately so it never lands in group(1)
        for m in re.finditer(r"(?:^|[\s])[`'\"]{0,1}(\w\S+\.(?:py|html|js|ts|css|json))\b", text):
            candidate = m.group(1)
            # Only add if the file actually exists in this repo
            if (self.repo_root / candidate).exists():
                found.append(candidate)

        # Keyword hints only apply when running inside the mullm server repo itself
        if (self.repo_root / "router" / "main.py").exists():
            file_hints = {
                "dashboard": "router/dashboard.html",
                "chat": "router/chat.html",
                "setup": "router/setup.html",
                "classifier": "router/intent.py",
                "decomposer": "router/decomposer.py",
                "cloud": "router/cloud.py",
                "cache": "router/vector_cache.py",
                "scorer": "router/scorer.py",
                "settings": "config/settings.py",
                "cli": "mullm_cli.py",
                "main": "router/main.py",
                "router": "router/main.py",
                "tiers": "router/tiers.py",
            }
            lower = text.lower()
            for hint, path in file_hints.items():
                if re.search(rf"\b{re.escape(hint)}\b", lower) and path not in found:
                    found.append(path)

        return found

    # Task types that should NOT generate FILE/OLD/NEW patches
    _NON_CODE_PATTERNS = re.compile(
        r"\b(?:analyz|review|evaluat|assess|check|inspect|audit|score|rate|rank|"
        r"descri|list|explain|document|spec|design|architect|plan|consider|"
        r"does.*look|is there|should we|would|could|might|what if|discuss|"
        r"vision|strategy|roadmap|brainstorm|think about|decide)\b",
        re.IGNORECASE,
    )
    # Question-form tasks: "Does X?", "Is X?", "Are X?" — never generate code
    _QUESTION_RE = re.compile(r"^\s*(?:does|is|are|can|will|would|should|has|have|do)\b", re.IGNORECASE)

    def _is_code_task(self, text: str) -> bool:
        """Return True if task should produce FILE/OLD/NEW code patches."""
        lower = text.lower()
        # Question-form tasks are never code — they're analysis/review
        if self._QUESTION_RE.match(text):
            return False
        # Explicit code signals override non-code patterns
        if re.search(r"\b(?:write|implement|create|build|add|fix|patch|refactor|"
                     r"update|generate|render|compute|parse|handle|return|emit)\b", lower):
            return True
        # Non-code patterns: analysis, design, review, discussion
        if self._NON_CODE_PATTERNS.search(text):
            return False
        return True  # default: treat as code

    def _estimate_tier(self, text: str) -> str:
        """Estimate routing tier for a task."""
        lower = text.lower()
        base_tier = "local_multi"

        # Non-code tasks → local (cheap plain query)
        if not self._is_code_task(text):
            base_tier = "local"
        # Documentation / simple updates → local
        elif re.search(r"\b(?:doc|readme|comment|typo|rename|update.*text)\b", lower):
            base_tier = "local"
        # Bug fixes, small code changes → local_multi (30B)
        elif re.search(r"\b(?:fix|bug|patch|tweak|adjust|remove|add.*button)\b", lower):
            base_tier = "local_multi"
        # Medium complexity → local_multi (30B)
        elif re.search(r"\b(?:refactor|implement|feature|endpoint|component|test)\b", lower):
            base_tier = "local_multi"
        # Architecture / design / complex → cloud_cheap
        elif re.search(r"\b(?:architect|saml|oauth|oidc|scale|enterprise|security)\b", lower):
            base_tier = "cloud_cheap"

        # Bias based on historical actuals (auto-improve)
        history = self._load_tier_history()
        words = set(lower.split())
        matches = [h for h in history if len(words & set(h.get("desc", "").lower().split())) >= 3]
        if len(matches) >= 2:
            from collections import Counter
            vote = Counter(h["actual"] for h in matches).most_common(1)[0][0]
            if vote != base_tier:
                log.info("tier_estimate_biased", estimated=base_tier, historical=vote)
                return vote
        return base_tier

    def _log_tier_estimate(self, desc: str, estimated: str, actual: str) -> None:
        """Append estimated vs actual tier to ~/.mullm/tier_estimates.jsonl."""
        import datetime as _dt
        import json as _json
        log_path = Path.home() / ".mullm" / "tier_estimates.jsonl"
        log_path.parent.mkdir(exist_ok=True)
        entry = {"ts": _dt.datetime.utcnow().isoformat(), "desc": desc[:120],
                 "estimated": estimated, "actual": actual}
        with open(log_path, "a") as f:
            f.write(_json.dumps(entry) + "\n")

    def _load_tier_history(self) -> list[dict]:
        """Load last 200 tier estimate entries from disk."""
        import json as _json
        log_path = Path.home() / ".mullm" / "tier_estimates.jsonl"
        if not log_path.exists():
            return []
        try:
            lines = log_path.read_text().splitlines()[-200:]
            return [_json.loads(l) for l in lines if l.strip()]
        except Exception:
            return []

    # ── Plan Builder ──────────────────────────────────────────

    async def plan_from_file(self, task_file: str) -> Plan:
        """Parse a task file and build an execution plan."""
        if not self.file_index:
            self.index_repo()
        if not self.project_context:
            self.load_context()

        tasks = self.parse_task_file(task_file)

        # Estimate costs
        tier_costs = {
            "local": 0.0,
            "local_multi": 0.0,
            "cloud_cheap": 0.005,
            "cloud_full": 0.05,
        }
        total_est = sum(tier_costs.get(t.suggested_tier, 0.01) for t in tasks)

        return Plan(
            tasks=tasks,
            context=self.project_context,
            repo_summary=self.repo_summary(),
            total_estimated_cost=round(total_est, 4),
        )

    async def plan_from_tasks(self, task_descriptions: list[str]) -> Plan:
        """Build a plan from a list of task strings."""
        if not self.file_index:
            self.index_repo()
        if not self.project_context:
            self.load_context()

        tasks = []
        for i, desc in enumerate(task_descriptions):
            tasks.append(
                Task(
                    id=i,
                    description=desc,
                    target_files=self._detect_files(desc),
                    suggested_tier=self._estimate_tier(desc),
                )
            )

        return Plan(
            tasks=tasks,
            context=self.project_context,
            repo_summary=self.repo_summary(),
        )

    # ── Verify ───────────────────────────────────────────────

    async def _verify(self, task: Task) -> tuple[bool, str]:
        """Run verify_cmd and return (success, error_output)."""
        if not self.verify_cmd:
            return True, ""
        import subprocess

        try:
            env = {**os.environ, "NODE_TLS_REJECT_UNAUTHORIZED": "0", "MULLM_URL": self.api_url}
            result = await asyncio.to_thread(
                subprocess.run,
                self.verify_cmd,
                shell=True, # nosec B604 -- verify_cmd is operator-configured, not user HTTP input
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(self.repo_root),
                env=env,
            )
            if result.returncode == 0:
                log.info("verify_passed", task_id=task.id)
                return True, ""
            error = (result.stdout + result.stderr)[-500:]
            log.warning("verify_failed", task_id=task.id, error=error[:100])
            return False, error
        except subprocess.TimeoutExpired:
            return False, "Verify command timed out (60s)"
        except Exception as e:
            return False, str(e)[:200]

    async def _bugfix_tdd_prepass(
        self, task: Task, file_ctx: str, api_url: str, post_fn
    ) -> str:
        """Write a failing test for a bug-fix task, pre-verify it fails, return test code.

        Returns the test code string to inject into the fix prompt, or "" if skipped.
        The test proves the bug is real before the fix is attempted.
        """
        import re as _re

        test_prompt = (
            f"You are doing TDD to fix a bug. Write a failing test first.\n\n"
            f"## Task (bug to fix)\n{task.description}\n\n"
            f"## Source\n{file_ctx[:8000]}\n\n"
            f"## Instructions\n"
            f"Write a test that:\n"
            f"1. Will FAIL on the current (buggy) code\n"
            f"2. Will PASS after the bug is fixed\n"
            f"3. Tests the specific broken behavior, not a trivially true assertion\n"
            f"Return ONLY the test code block — no prose."
        )
        test_payload = {
            "content": test_prompt,
            "source": "api",
            "session_id": self._session_id,
            "skip_cache": True,
            "force_tier": "cloud_cheap",
            "context": {"num_predict": -1},
        }
        try:
            tr = await asyncio.to_thread(post_fn, f"{api_url}/query", test_payload, 120)
            if tr.status_code != 200:
                return ""
            test_text = tr.json().get("response", "")
            # Extract code block
            m = _re.search(r'```(?:\w+)?\s*\n(.*?)```', test_text, _re.DOTALL)
            test_code = m.group(1).strip() if m else test_text.strip()
            if not test_code or len(test_code) < 50:
                return ""

            # Write test file
            test_path = self._test_path_for(task.target_files[0] if task.target_files else "")
            if test_path:
                full_test_path = self.repo_root / test_path
                full_test_path.parent.mkdir(parents=True, exist_ok=True)
                full_test_path.write_text(test_code + "\n")

            # Pre-verify: test should FAIL on buggy code
            pre_ok, pre_err = await self._verify(task)
            if pre_ok:
                log.warning("bugfix_tdd_weak_test", task_id=task.id,
                            note="Test passes on buggy code — test may be too weak")
                print("     ⚠️  bugfix_tdd: test passes on bugged code (weak test)", flush=True)
            else:
                log.info("bugfix_tdd_test_confirmed", task_id=task.id,
                         note="Test correctly fails on buggy code")
                print("     ✓  bugfix_tdd: test fails on bugged code (real test)", flush=True)

            return test_code
        except Exception as e:
            log.warning("bugfix_tdd_prepass_error", task_id=task.id, error=str(e)[:100])
            return ""

    # ── Executor ──────────────────────────────────────────────

    @staticmethod
    def _test_path_for(filepath: str) -> str:
        """Return the test file path for a given source file, or '' if not applicable."""
        p = Path(filepath)
        ext = p.suffix
        stem = p.stem
        parent = str(p.parent)
        if ext == ".py":
            return str(Path(parent) / f"test_{stem}.py")
        if ext in (".js", ".ts"):
            return str(Path(parent) / f"{stem}.test{ext}")
        if ext in (".jsx", ".tsx"):
            return str(Path(parent) / f"{stem}.test{ext}")
        if ext == ".html":
            return ""  # no test file for HTML
        return ""

    def _parse_patches(self, response: str) -> list[dict]:
        """Parse FILE/OLD/NEW patch blocks from a code-gen response."""
        patches = []
        parts = re.split(r"(?:^|\n)FILE:\s*", response)
        for part in parts[1:]:
            lines = part.strip().split("\n")
            if not lines:
                continue
            filepath = lines[0].strip().strip("`").strip()
            # Security: block path traversal outside repo_root
            try:
                _abs = Path(filepath) if Path(filepath).is_absolute() else (self.repo_root / filepath)
                _resolved = _abs.resolve()
                _repo_resolved = self.repo_root.resolve()
                _within_repo = str(_resolved).startswith(str(_repo_resolved) + os.sep) or _resolved == _repo_resolved
            except Exception:
                continue
            if ".." in filepath and not _within_repo:
                log.warning("patch_path_unsafe", filepath=filepath)
                continue
            if Path(filepath).is_absolute():
                if not _within_repo:
                    log.warning("patch_path_unsafe", filepath=filepath)
                    continue
                filepath = str(_resolved.relative_to(_repo_resolved))
            rest = "\n".join(lines[1:])
            old_match = re.search(r"OLD:\s*\n(?:```[^\n]*\n)?(.*?)(?:```|\nNEW:)", rest, re.DOTALL)
            new_match = re.search(r"NEW:\s*\n(?:```[^\n]*\n)?(.*?)(?:```|\nFILE:|\Z)", rest, re.DOTALL)
            if old_match and new_match:
                patches.append(
                    {
                        "file": filepath,
                        "old": old_match.group(1).rstrip("\n"),
                        "new": new_match.group(1).rstrip("\n"),
                    }
                )
        return patches

    def _read_file_context(self, filepath: str) -> str:
        """Read a target file and return content for code-gen context."""
        path = self.repo_root / filepath
        if not path.exists():
            return ""
        try:
            return path.read_text(errors="replace")
        except Exception:
            return ""

    @staticmethod
    def _fuzzy_find_old(old_code: str, current: str, threshold: float = 0.82) -> tuple[str, float] | None:
        """Find the closest matching substring in current for old_code using difflib.

        Returns (matched_substring, ratio) if ratio >= threshold, else None.
        Compares line-by-line windows of the same length as old_code.
        """
        import difflib

        old_lines = old_code.splitlines()
        current_lines = current.splitlines()
        n = len(old_lines)
        if n == 0 or n > len(current_lines):
            return None

        best_ratio = 0.0
        best_start = -1
        # Slide a window of size n over the file
        for i in range(len(current_lines) - n + 1):
            window = current_lines[i : i + n]
            ratio = difflib.SequenceMatcher(None, old_lines, window, autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_start = i

        if best_ratio >= threshold and best_start >= 0:
            matched = "\n".join(current_lines[best_start : best_start + n])
            return matched, best_ratio
        return None

    def _apply_patch(self, patch: dict) -> str:
        """Apply a single FILE/OLD/NEW patch. Returns 'ok', 'truncated', 'old_not_found', or 'empty'."""
        import textwrap

        filepath = patch["file"]
        path = self.repo_root / filepath

        old_code = patch["old"]
        if not path.exists():
            # File doesn't exist — create it with NEW content regardless of OLD block
            new_code = self._strip_commentary_from_patch(patch["new"])
            if not new_code.strip():
                return "empty"
            if not self._looks_complete(new_code, filepath):
                log.warning("patch_truncated_refused", target=filepath,
                            last_line=new_code.strip().split("\n")[-1][:80])
                return "truncated"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_code)
            log.info("patch_new_file", target=filepath, size=len(new_code))
            return "ok"
        try:
            current = path.read_text(errors="replace")
        except Exception:
            return "empty"

        if not old_code.strip():
            # Empty OLD on existing file = full replace
            new_code = self._strip_commentary_from_patch(patch["new"])
            if not self._looks_complete(new_code, filepath):
                log.warning("patch_truncated_refused", target=filepath,
                            last_line=new_code.strip().split("\n")[-1][:80])
                return "truncated"
            path.write_text(new_code)
            log.info("patch_full_replace", target=filepath)
            return "ok"

        if old_code not in current:
            # Try normalized whitespace
            old_stripped = textwrap.dedent(old_code).strip()
            if old_stripped and old_stripped in current:
                old_code = old_stripped
            else:
                # Fuzzy match: find best-matching window in file using difflib
                fuzzy = self._fuzzy_find_old(old_code, current)
                if fuzzy is not None:
                    log.info("patch_fuzzy_match", target=filepath, ratio=f"{fuzzy[1]:.2f}")
                    old_code = fuzzy[0]
                else:
                    log.warning(
                        "patch_old_not_found", target=filepath, old_len=len(old_code), old_preview=old_code[:80]
                    )
                    return "old_not_found"

        new_code = self._strip_commentary_from_patch(patch["new"])
        patched = current.replace(old_code, new_code, 1)
        if patched == current:
            return "empty"

        try:
            path.write_text(patched)
            log.info("patch_applied", target=filepath, old_len=len(old_code), new_len=len(patch["new"]))
            return "ok"
        except Exception:
            return "empty"

    # Phrases that signal loose natural-language commentary, not code
    _COMMENTARY_PHRASES = re.compile(
        r"(?:has been updated|as requested|the above|this change[sd]?|"
        r"we(?:'ve| have) (?:updated|changed|modified|added|removed)|"
        r"the panel title|the following change|i(?:'ve| have) (?:updated|changed|modified)|"
        r"note that|please note|here is|this (?:updates?|modifies?|adds?|removes?))",
        re.IGNORECASE,
    )

    # Prefixes that mark a line as legitimate code (comments, indentation, etc.)
    _CODE_LINE_RE = re.compile(r"^(?:\s|//|/\*|\*|#[^!]?|<!|<[a-zA-Z/]|[{}()\[\];,=+\-*/%<>!&|^~?:@$\"'`0-9])")

    @staticmethod
    def _looks_complete(code: str, filepath: str) -> bool:
        """Heuristic: does this code look like a complete file rather than truncated output?"""
        if not code.strip():
            return False
        # Explicit truncation sentinel from Ollama done_reason=length detection
        if "##TRUNCATED##" in code:
            return False
        ext = Path(filepath).suffix
        stripped = code.strip()
        last = stripped.split("\n")[-1].strip()
        if last.endswith((",", "+", "-", "||", "&&", "?", ":")):
            return False
        if ext in (".js", ".ts", ".jsx", ".tsx"):
            opens = code.count("{")
            closes = code.count("}")
            if abs(opens - closes) > 1:  # stricter: allow only 1 imbalance
                return False
            # Detect merged-brace corruption: `}identifier(` or `}identifier.` on the same line
            # (e.g. `}AtTime(0, t0);` — a closing brace fused with a continuation statement).
            # Balanced braces won't catch this since it's syntactically balanced but semantically broken.
            _merged_brace_re = re.compile(r"^\s*\}[A-Za-z_$][A-Za-z0-9_$]*[\s(.\[]")
            for ln in code.split("\n"):
                if _merged_brace_re.match(ln):
                    log.warning("looks_complete_merged_brace", line=ln.strip()[:80])
                    return False
            # Detect import injected after non-import code (LLM sometimes inserts import blocks
            # mid-file after class/function definitions). Only flag if a bare `import` line follows
            # a non-blank, non-import, non-comment line.
            _import_re = re.compile(r"^\s*import\s")
            _comment_or_blank_re = re.compile(r"^\s*(?://|/\*|\*|$)")
            seen_non_import = False
            for ln in code.split("\n"):
                if _comment_or_blank_re.match(ln):
                    continue
                if _import_re.match(ln):
                    if seen_non_import:
                        log.warning("looks_complete_import_after_code", line=ln.strip()[:80])
                        return False
                else:
                    seen_non_import = True
        if ext == ".py":
            if last.endswith(":") or last.endswith("\\"):
                return False
            # Check if last non-blank line is deeply indented — indicates truncation
            # mid-function/method body (3+ levels of nesting = >= 12 spaces)
            non_blank = [l for l in code.split("\n") if l.strip() and not l.strip().startswith("#")]
            if non_blank:
                last_code_line = non_blank[-1]
                indent = len(last_code_line) - len(last_code_line.lstrip())
                if indent >= 12:
                    return False
        return True

    # LLM thinking tokens and patch-format markers that must never appear in output files.
    # /no_think and /think start with '/' which _CODE_LINE_RE treats as code — explicit blocklist needed.
    # OLD:/NEW: fall through conservative default — also blocklisted here.
    # Bare '---' separators start with '-' which _CODE_LINE_RE also keeps.
    # Conversation turn markers (Human:/User:/Assistant:) must match the full prefix — they may have
    # arbitrary content after the colon so we DON'T anchor to end-of-line for them.
    _ARTIFACT_LINE_RE = re.compile(
        r"^(?:"
        r"/no_think\s*$"
        r"|/think\s*$"
        r"|OLD:\s*$"
        r"|NEW:\s*$"
        r"|---\s*$"
        r"|Human:\s"
        r"|User:\s"
        r"|Assistant:\s"
        r")",
        re.IGNORECASE,
    )

    def _strip_commentary_from_patch(self, new_code: str) -> str:
        """Remove loose natural-language commentary that an LLM may have
        injected into a NEW code block.  Only strips lines that are clearly
        not code — errs on the side of keeping content."""
        lines = new_code.split("\n")
        cleaned: list[str] = []
        stripped_any = False
        for line in lines:
            # Blank lines are always kept
            if not line.strip():
                cleaned.append(line)
                continue
            # Strip known LLM artifacts that slip past the code-line heuristic:
            # /no_think, /think (thinking tokens), OLD:/NEW: (patch markers), --- (separators)
            if self._ARTIFACT_LINE_RE.match(line):
                log.warning("patch_artifact_stripped", line=line[:80])
                stripped_any = True
                continue
            # Lines that start with typical code characters are kept
            if self._CODE_LINE_RE.match(line):
                cleaned.append(line)
                continue
            # If the line looks like an English sentence with commentary phrases
            if self._COMMENTARY_PHRASES.search(line):
                log.warning("patch_commentary_stripped", line=line[:120])
                stripped_any = True
                continue
            # Default: keep the line (conservative)
            cleaned.append(line)
        if stripped_any:
            return "\n".join(cleaned)
        return new_code

    async def execute(
        self,
        plan: Plan,
        dry_run: bool = False,
        max_parallel: int = 3,
        code_mode: bool = False,
        apply: bool = False,
        target_file: str = "",
        fast: bool = False,
        cost_optimize: bool = False,
        tdd: bool = True,
        git_commit: bool = False,
        feature_branches: int = 0,
        resume: bool = False,
        task_file: str = "",
        onefile: bool = False,
        bugfix_tdd: bool = False,
        escalate_timeout: int = 0,
        verify_on_failure: bool = False,
    ) -> list[dict]:
        """Execute a plan — route each task through muLLM.

        Args:
            code_mode: Generate code with FILE/OLD/NEW patches
            apply: Apply patches to files after generation
            target_file: Default file to use as context (tasks may override)
            fast: Auto-escalate to cloud if local times out (15s)
            cost_optimize: Prefer cheapest routing
            tdd: Write tests before implementation (default True)
            bugfix_tdd: Write failing test first, pre-verify it fails, then fix (real TDD for bugs)
            git_commit: Auto-commit applied patches after execution
            feature_branches: Split tasks across N feature branches then merge (0=off)
        """
        import requests  # type: ignore[import-untyped]
        import urllib3

        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

        # ── Resume: load checkpoint and pre-mark done tasks ──
        checkpoint: dict = {}
        if resume and task_file:
            checkpoint = self._load_checkpoint(task_file)
            if checkpoint:
                done_count = sum(1 for v in checkpoint.values() if v.get("status") == "done")
                print(f"  ♻️  Resuming — {done_count}/{len(plan.tasks)} tasks already done, skipping them", flush=True)
            else:
                print("  ♻️  No checkpoint found — starting fresh", flush=True)
        for t in plan.tasks:
            cp_entry = checkpoint.get(str(t.id), {})
            if cp_entry.get("status") == "done" and cp_entry.get("verified") is not False:
                t.status = "done"
                t.result = {
                    "tier_used": cp_entry.get("tier_used", "resumed"),
                    "patches_applied": cp_entry.get("patches_applied", 0),
                    "patched_files": cp_entry.get("patched_files", []),
                    "cost": cp_entry.get("cost", 0),
                    "resumed": True,
                }

        results: list[dict[str, object]] = []
        sem = asyncio.Semaphore(max_parallel)
        # Lock for sequential file writes to avoid race conditions
        file_lock = asyncio.Lock()
        # Lock for git operations — serializes per-task commits and reverts
        git_lock = asyncio.Lock()

        # Auto-detect protocol: try HTTPS first, fall back to HTTP
        api_url = self.api_url
        # For the consolidation block below we need api_url resolved first — run detection inline
        try:
            import requests as _req_probe  # type: ignore[import-untyped]
            import urllib3 as _u3
            _u3.disable_warnings(_u3.exceptions.InsecureRequestWarning)
            _req_probe.get(f"{api_url}/health", timeout=3, verify=False)  # nosec B501
        except Exception:
            _flip = api_url.replace("https://", "http://", 1) if api_url.startswith("https://") else api_url.replace("http://", "https://", 1)
            try:
                _req_probe.get(f"{_flip}/health", timeout=3, verify=False)  # nosec B501
                api_url = _flip
            except Exception:
                pass

        # ── Mini-DAG game build: parallel component agents → merge ─────────────
        # When onefile + target doesn't exist: split tasks into component groups,
        # run each group as a parallel agent, then merge all components into one file.
        if onefile and target_file and not (self.repo_root / target_file).exists():
            import requests as _req  # type: ignore[import-untyped]
            _pending = [t for t in plan.tasks if t.status != "done"]
            if _pending:
                _ext = Path(target_file).suffix.lower()
                _is_html = _ext in (".html", ".htm", "")
                _single_hdr = (
                    "SINGLE-FILE BUILD: ALL code goes into one self-contained HTML file. "
                    "Use inline <script> and <style> tags only. "
                    "No ES6 import/export — use global variables and IIFE patterns. "
                    "No external CDN dependencies unless unavoidable (prefer inline Three.js via CDN <script src>)."
                    if _is_html else f"All code in one file: {target_file}."
                )

                # ── Phase 1: group tasks into themed components ──────────────
                _n = len(_pending)
                _group_size = max(3, (_n + 4) // 5)  # 5 groups, min 3 tasks each
                _groups: list[list] = []
                for _i in range(0, _n, _group_size):
                    _groups.append(_pending[_i:_i + _group_size])

                _component_labels = [
                    "Core physics engine, character model, and primary game mechanics",
                    "Rendering, visual effects, skybox, parallax, and environment",
                    "UI/HUD, controls, input methods, and responsive layout",
                    "Level system, terrain generation, and progression",
                    "Advanced features, upgrades, and polish",
                ]

                def _component_prompt(label: str, tasks_in_group: list, idx: int) -> str:
                    specs = "\n".join(f"  - {t.description}" for t in tasks_in_group)
                    return (
                        f"You are writing the '{label}' component of a browser game.\n\n"
                        f"{_single_hdr}\n\n"
                        f"Your component covers these features:\n{specs}\n\n"
                        f"Write ONLY self-contained JavaScript + HTML/CSS for this component.\n"
                        f"Use global variable namespace prefix `C{idx}_` for all your globals to avoid collisions.\n"
                        f"Output a clearly commented JS block (no FILE/OLD/NEW — just raw JS/CSS code).\n"
                        f"This will be merged with other components by a merge agent.\n"
                        f"/no_think"
                    )

                # ── Run component agents in parallel ─────────────────────────
                print(f"  🎮 Mini-DAG: {len(_groups)} parallel component agents → merge → {target_file}", flush=True)

                async def _run_component(label: str, group_tasks: list, idx: int) -> tuple[int, str, float]:
                    _prompt = _component_prompt(label, group_tasks, idx)
                    _pld = {
                        "content": _prompt,
                        "source": "api",
                        "session_id": f"{self._session_id}-c{idx}",
                        "skip_cache": True,
                        "context": {"num_predict": -1},
                    }
                    print(f"    ⏳ Component {idx+1}/{len(_groups)}: {label[:50]}…", flush=True)
                    try:
                        _r = await asyncio.to_thread(
                            lambda: _req.post(f"{api_url}/query", json=_pld, timeout=self.task_timeout, verify=False)  # nosec B501
                        )
                        if _r.status_code == 200:
                            _d = _r.json()
                            _code = _d.get("response", "")
                            _cost = _d.get("cost", 0)
                            print(f"    ✅ Component {idx+1} done  cost=${_cost:.4f}  model={_d.get('model_used','?')}", flush=True)
                            return idx, _code, _cost
                        else:
                            print(f"    ❌ Component {idx+1} server error {_r.status_code}", flush=True)
                            return idx, "", 0.0
                    except Exception as _e:
                        print(f"    ❌ Component {idx+1} failed: {_e}", flush=True)
                        return idx, "", 0.0

                _component_coros = [
                    _run_component(
                        _component_labels[min(_gi, len(_component_labels)-1)],
                        _grp,
                        _gi,
                    )
                    for _gi, _grp in enumerate(_groups)
                ]
                _component_results = await asyncio.gather(*_component_coros)
                _component_results = sorted(_component_results, key=lambda x: x[0])
                _total_cost = sum(c for _, _, c in _component_results)

                # ── Phase 2: merge agent ──────────────────────────────────────
                _components_block = "\n\n".join(
                    f"=== COMPONENT {i+1} ===\n{code}"
                    for i, (_, code, _) in enumerate(_component_results)
                    if code.strip()
                )
                _all_specs = "\n".join(f"- {t.description}" for t in _pending)
                _merge_prompt = (
                    f"You are the merge agent. Assemble a complete, production-quality browser game "
                    f"from the component code blocks below.\n\n"
                    f"{_single_hdr}\n\n"
                    f"Full game spec (for reference):\n{_all_specs}\n\n"
                    f"Component outputs to integrate:\n{_components_block[:40000]}\n\n"
                    f"Produce ONE complete self-contained HTML file.\n"
                    f"Resolve any namespace conflicts (remove C0_/C1_/etc prefixes, unify into clean names).\n"
                    f"IMPORTANT: Respond ONLY with FILE/OLD/NEW block:\n"
                    f"FILE: {target_file}\nOLD:\nNEW:\n<complete HTML>\n/no_think"
                )
                _merge_pld = {
                    "content": _merge_prompt,
                    "source": "api",
                    "session_id": f"{self._session_id}-merge",
                    "skip_cache": True,
                    "context": {"num_predict": -1},
                }
                print(f"  🔀 Merge agent assembling final {target_file}…", flush=True)
                try:
                    _mr = await asyncio.to_thread(
                        lambda: _req.post(f"{api_url}/query", json=_merge_pld, timeout=self.task_timeout, verify=False)  # nosec B501
                    )
                    if _mr.status_code == 200:
                        _md = _mr.json()
                        _mresp = _md.get("response", "")
                        _total_cost += _md.get("cost", 0)
                        _patches = self._parse_patches(_mresp)
                        # Fallback: merge agent returned raw HTML without FILE/OLD/NEW wrapper
                        if not _patches and "<!DOCTYPE" in _mresp or ("<html" in _mresp and not _patches):
                            import re as _re2
                            _html_match = _re2.search(r'(<!DOCTYPE.*?</html>)', _mresp, _re2.DOTALL | _re2.IGNORECASE)
                            if _html_match:
                                _patches = [{"file": target_file, "old": "", "new": _html_match.group(1)}]
                        if apply and _patches:
                            for _p in _patches:
                                _st = self._apply_patch(_p)
                                results.append({
                                    "dag_build": True,
                                    "components": len(_groups),
                                    "tasks": len(_pending),
                                    "file": _p["file"],
                                    "patch_status": _st,
                                    "total_cost": round(_total_cost, 4),
                                    "merge_model": _md.get("model_used", "?"),
                                })
                                if _st == "ok":
                                    print(f"  ✅ Game assembled → {_p['file']}  total_cost=${_total_cost:.4f}", flush=True)
                                else:
                                    print(f"  ❌ Merge patch failed ({_st}) → {_p['file']}", flush=True)
                        else:
                            results.append({
                                "dag_build": True, "components": len(_groups),
                                "tasks": len(_pending), "patches_found": len(_patches),
                                "total_cost": round(_total_cost, 4),
                            })
                        return results
                    else:
                        print(f"  ❌ Merge agent server error {_mr.status_code}", flush=True)
                except Exception as _me:
                    print(f"  ❌ Merge agent failed: {_me}", flush=True)
                # Fall through to per-task mode on failure

        api_url = self.api_url
        try:
            requests.get(f"{api_url}/health", timeout=3, verify=False) # nosec B501 -- local backend health probe, SSL not applicable
        except Exception:
            # Flip protocol
            if api_url.startswith("https://"):
                api_url = api_url.replace("https://", "http://", 1)
            else:
                api_url = api_url.replace("http://", "https://", 1)
            try:
                requests.get(f"{api_url}/health", timeout=3, verify=False) # nosec B501 -- local backend health probe, SSL not applicable
                log.info("protocol_fallback", url=api_url)
            except Exception:
                pass  # will fail per-task with a clear error

        # Pre-read file context for code-gen mode (shared across tasks)
        file_context_cache: dict[str, str] = {}
        if code_mode and target_file:
            content = self._read_file_context(target_file)
            if content:
                file_context_cache[target_file] = content

        total_tasks = len(plan.tasks)
        completed_tasks = 0
        active_tasks: dict[int, float] = {}  # task_id → start_time
        _progress_lock = asyncio.Lock()

        async def run_task(task: Task) -> dict:
            nonlocal completed_tasks
            async with sem:
                task.status = "running"
                start = time.time()
                short_desc = task.description[:55] + ("…" if len(task.description) > 55 else "")
                async with _progress_lock:
                    active_tasks[task.id] = start
                    running_count = len(active_tasks)
                print(f"  ⏳ [{completed_tasks}/{total_tasks}] +{running_count} running  {short_desc}", flush=True)

                # Build prompt with context
                context = self.context_for_task(task)
                file_hint = ""
                if task.target_files:
                    # Only hint the first (primary) target — extra files are verify commands, not edit targets
                    file_hint = f"\nTarget file: {task.target_files[0]}"

                # Determine if this task should produce code patches or a plain answer
                task_is_code = code_mode and self._is_code_task(task.description)

                if task_is_code:
                    task_target = task.target_files[0] if task.target_files else target_file
                    # onefile: force all patches to target_file (only override when no explicit target)
                    if onefile and target_file and not task.target_files:
                        task_target = target_file
                    # Read file context if not cached
                    file_ctx = ""
                    if task_target:
                        if task_target not in file_context_cache:
                            fc = self._read_file_context(task_target)
                            if fc:
                                file_context_cache[task_target] = fc
                        fc = file_context_cache.get(task_target, "")
                        if fc:
                            snippet = fc[:32000]
                            trunc_note = f" [TRUNCATED — showing {len(snippet):,}/{len(fc):,} chars]" if len(fc) > 32000 else ""
                            file_ctx = f"\n\nRelevant file {task_target} ({len(fc):,} chars{trunc_note}):\n{snippet}"

                    # Inject repo file list to prevent hallucinated imports
                    try:
                        import subprocess as _sp
                        _fl = _sp.run(
                            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                            capture_output=True, text=True, cwd=str(self.repo_root), timeout=5
                        ).stdout.strip()
                        if _fl:
                            file_ctx += f"\n\nExisting repo files (only import from these):\n{_fl[:3000]}"
                    except Exception:
                        pass

                    # Prefix ensures classifier routes as 'code' not 'lookup'
                    _onefile_html = (
                        (task_target or "").endswith(".html") or
                        (onefile and (target_file or "").endswith(".html")) or
                        onefile  # APK always targets a single HTML
                    )
                    if onefile and _onefile_html:
                        _single_target = task_target or target_file or "index.html"
                        _onefile_constraint = (
                            f"SINGLE-FILE BUILD: ALL code goes into {_single_target}. "
                            "Use inline <script> and <style> tags only. "
                            "Do NOT create separate .js/.ts/.css files. "
                            "Do NOT use ES6 import/export — use global variables and IIFE patterns.\n\n"
                        )
                    elif onefile and target_file and not _onefile_html:
                        _onefile_constraint = (
                            f"SINGLE-FILE BUILD: ALL code goes into {target_file}. "
                            "Do not create sibling files — everything in one file.\n\n"
                        )
                    else:
                        _onefile_constraint = ""
                    prompt = (
                        f"{_onefile_constraint}"
                        f"Write code to: {task.description}{file_hint}\n\n"
                        f"IMPORTANT: Respond ONLY with FILE/OLD/NEW blocks — no prose, no markdown headers.\n"
                        f"For EXISTING files: copy OLD code EXACTLY from the file, then put NEW code.\n"
                        f"For NEW files that do not exist yet: OLD block MUST be completely empty (just write 'OLD:' then immediately 'NEW:').\n"
                        f"CRITICAL: Never put placeholder or example code in OLD block for new files — leave it blank.\n"
                        f"CRITICAL: NEW block must contain ONLY valid code, never explanatory text.\n"
                        f"Format:\nFILE: <path>\nOLD:\n<exact old code or empty>\nNEW:\n<new code>"
                        f"{file_ctx}"
                        f"\n/no_think"
                    )
                elif code_mode:
                    # Non-code task in code run: plain query, save output as notes
                    prompt = f"{task.description}{file_hint}"
                else:
                    prompt = f"{task.description}{file_hint}\n\nRespond with FILE/OLD/NEW blocks. For new files leave OLD empty."

                if context:
                    prompt += f"\n\nProject context:\n{context[:2000]}"

                if dry_run:
                    task.status = "skipped"
                    return {
                        "task_id": task.id,
                        "description": task.description[:80],
                        "tier": task.suggested_tier,
                        "dry_run": True,
                        "target_files": task.target_files,
                    }

                try:
                    payload = {
                        "content": prompt,
                        "source": "api",
                        "session_id": self._session_id,
                        "skip_cache": True,
                    }
                    if task.suggested_tier:
                        payload["force_tier"] = task.suggested_tier
                    if cost_optimize:
                        payload["cost_strategy"] = "cost_optimize"
                    if task_is_code:
                        # Unlimited output — prevent mid-file truncation
                        payload["context"] = {"num_predict": -1}
                        # Only force local if the plan didn't assign a cloud tier
                        _planned_tier = task.suggested_tier or ""
                        if _planned_tier not in ("cloud_cheap", "cloud_full"):
                            payload["force_tier"] = "local_multi"
                    elif code_mode and not task_is_code:
                        # Non-code task: cheap local is fine
                        payload["force_tier"] = "local"

                    # --escalate-timeout: pre-escalate to cloud if local estimate is too slow
                    _TIER_EST_S = {"local": 120, "local_multi": 240, "cloud_cheap": 180, "cloud_full": 300}
                    if escalate_timeout > 0 and task_is_code:
                        current_tier = payload.get("force_tier", task.suggested_tier or "local_multi")
                        est_s = _TIER_EST_S.get(current_tier, 0)
                        if est_s > escalate_timeout and current_tier in ("local", "local_multi"):
                            new_tier = "cloud_cheap"
                            payload["force_tier"] = new_tier
                            print(f"     ⏫ pre-escalate {current_tier}→{new_tier} (est ~{est_s}s > {escalate_timeout}s threshold)", flush=True)

                    def _post(url, pld, timeout):
                        return requests.post(
                            url,
                            json=pld,
                            timeout=timeout,
                            verify=False, # nosec B501 -- internal local service call
                        )

                    # bugfix_tdd: write failing test first, pre-verify it fails, inject as context
                    if bugfix_tdd and task_is_code and apply:
                        _test_ctx = await self._bugfix_tdd_prepass(
                            task, file_ctx if "file_ctx" in dir() else "", api_url, _post
                        )
                        if _test_ctx:
                            payload["content"] += (
                                "\n\n## Failing Test (written to prove bug, must pass after fix)\n"
                                f"```typescript\n{_test_ctx}\n```\n"
                                "Fix the source code so this test passes."
                            )

                    if fast and task.suggested_tier in ("local", "local_multi"):
                        # Fast mode: try local with 15s timeout, escalate to cloud
                        try:
                            r = await asyncio.to_thread(
                                _post,
                                f"{api_url}/query",
                                payload,
                                15,
                            )
                        except requests.Timeout:
                            log.info("fast_escalate", task_id=task.id)
                            payload["force_tier"] = "cloud_cheap"
                            payload["skip_cache"] = True
                            r = await asyncio.to_thread(
                                _post,
                                f"{api_url}/query",
                                payload,
                                self.task_timeout,
                            )
                    else:
                        r = await asyncio.to_thread(
                            _post,
                            f"{api_url}/query",
                            payload,
                            self.task_timeout,
                        )

                    # Handle 429 rate limit: back off and retry up to 3 times
                    _backoff_attempts = 0
                    while r.status_code == 429 and _backoff_attempts < 3:
                        _backoff_attempts += 1
                        wait_s = 30 * _backoff_attempts
                        print(f"     ⏸  429 rate limited — backing off {wait_s}s (attempt {_backoff_attempts}/3)", flush=True)
                        await asyncio.sleep(wait_s)
                        r = await asyncio.to_thread(_post, f"{api_url}/query", payload, self.task_timeout)

                    patches_applied = 0
                    patched_file_set: set[str] = set()
                    if r.status_code == 200:
                        data = r.json()
                        task.status = "done"  # may be downgraded to pending below if no patches landed
                        response_text = data.get("response", "")
                        task.result = {
                            "response": response_text,
                            "tier_used": data.get("tier_used", "?"),
                            "model_used": data.get("model_used", "?"),
                            "cost": data.get("cost", 0),
                            "latency_ms": data.get("total_latency_ms", 0),
                        }

                        # Code-gen: parse and apply patches (only for actual code tasks)
                        if task_is_code and response_text:
                            patches = self._parse_patches(response_text)
                            task.result["patches_found"] = len(patches)
                            if apply and patches:
                                async with file_lock:
                                    failed_truncated: list[dict] = []
                                    failed_old_not_found: list[dict] = []
                                    # TDD: generate test file first if enabled
                                    if tdd and patches:
                                        primary = patches[0]["file"]
                                        test_path = self._test_path_for(primary)
                                        if test_path and not (self.repo_root / test_path).exists():
                                            test_prompt = (
                                                f"Write tests for: {task.description}\n\n"
                                                f"Test file: {test_path}\n"
                                                f"IMPORTANT: Respond ONLY with FILE/OLD/NEW blocks.\n"
                                                f"FILE: {test_path}\nOLD:\nNEW:\n<test code here>"
                                            )
                                            test_payload = {
                                                "content": test_prompt,
                                                "source": "api",
                                                "session_id": self._session_id,
                                                "skip_cache": True,
                                                "force_tier": "local_multi",
                                                "min_complexity": 3,
                                                "context": {"num_predict": -1},
                                            }
                                            try:
                                                tr = await asyncio.to_thread(
                                                    _post, f"{api_url}/query", test_payload, self.task_timeout
                                                )
                                                if tr.status_code == 200:
                                                    test_text = tr.json().get("response", "")
                                                    for tp in self._parse_patches(test_text):
                                                        st = self._apply_patch(tp)
                                                        if st == "ok":
                                                            log.info("tdd_test_written", file=tp["file"])
                                                        elif st == "truncated":
                                                            failed_truncated.append(tp)
                                            except Exception as te:
                                                log.warning("tdd_test_failed", error=str(te)[:100])

                                    for p in patches:
                                        status = self._apply_patch(p)
                                        if status == "ok":
                                            patches_applied += 1
                                            f = p["file"]
                                            patched_file_set.add(f)
                                            updated = self._read_file_context(f)
                                            if updated:
                                                file_context_cache[f] = updated
                                        elif status == "truncated":
                                            failed_truncated.append(p)
                                        elif status == "old_not_found":
                                            failed_old_not_found.append(p)

                                    # Auto-retry truncated patches: escalate tier, ask to complete
                                    for p in failed_truncated:
                                        fp = p["file"]
                                        partial = p["new"].replace("##TRUNCATED##", "").strip()
                                        retry_prompt = (
                                            f"The previous code generation was cut off mid-file. "
                                            f"Complete the file from where it stopped.\n\n"
                                            f"FILE: {fp}\nOLD:\nNEW:\n{partial}\n"
                                            f"[CONTINUE FROM HERE — output ONLY the complete file content in NEW block]"
                                        )
                                        escalated = "cloud_cheap" if task.suggested_tier in ("local", "local_multi") else "cloud_full"
                                        retry_payload = {
                                            "content": retry_prompt,
                                            "source": "api",
                                            "session_id": self._session_id,
                                            "skip_cache": True,
                                            "force_tier": escalated,
                                            "min_complexity": 3,
                                            "context": {"num_predict": -1},
                                        }
                                        try:
                                            rr = await asyncio.to_thread(_post, f"{api_url}/query", retry_payload, self.task_timeout)
                                            if rr.status_code == 200:
                                                rtext = rr.json().get("response", "")
                                                for rp in self._parse_patches(rtext):
                                                    if self._apply_patch(rp) == "ok":
                                                        patches_applied += 1
                                                        log.info("truncated_retry_ok", file=fp, tier=escalated)
                                                        print(f"     🔁 truncated retry → {escalated}: {fp}", flush=True)
                                                        fc = self._read_file_context(rp["file"])
                                                        if fc:
                                                            file_context_cache[rp["file"]] = fc
                                        except Exception as re_:
                                            log.warning("truncated_retry_failed", file=fp, error=str(re_)[:80])

                                    # Auto-retry old_not_found patches: send current file + ask to regen OLD block
                                    for p in failed_old_not_found:
                                        fp = p["file"]
                                        current_content = self._read_file_context(fp) or ""
                                        retry_prompt = (
                                            f"Update the file to: {task.description}\n\n"
                                            f"Current file content:\n{current_content[:8000]}\n\n"
                                            f"Respond ONLY with FILE/OLD/NEW. Copy exact lines from the file above for OLD block.\n"
                                            f"FILE: {fp}\nOLD:\n<exact lines from file>\nNEW:\n<updated code>"
                                        )
                                        retry_payload = {
                                            "content": retry_prompt,
                                            "source": "api",
                                            "session_id": self._session_id,
                                            "skip_cache": True,
                                            "force_tier": "cloud_cheap",
                                            "min_complexity": 3,
                                            "context": {"num_predict": -1},
                                        }
                                        try:
                                            rr = await asyncio.to_thread(_post, f"{api_url}/query", retry_payload, self.task_timeout)
                                            if rr.status_code == 200:
                                                rtext = rr.json().get("response", "")
                                                for rp in self._parse_patches(rtext):
                                                    if self._apply_patch(rp) == "ok":
                                                        patches_applied += 1
                                                        log.info("old_not_found_retry_ok", file=fp)
                                                        print(f"     🔁 old_not_found retry ok: {fp}", flush=True)
                                                        fc = self._read_file_context(rp["file"])
                                                        if fc:
                                                            file_context_cache[rp["file"]] = fc
                                        except Exception as re_:
                                            log.warning("old_not_found_retry_failed", file=fp, error=str(re_)[:80])

                                    # Verify: run tests after patching (or on any failure when verify_on_failure is set)
                                    _any_patch_failure = bool(failed_old_not_found) or bool(failed_truncated)
                                    if self.verify_cmd and (patches_applied > 0 or (verify_on_failure and task_is_code and _any_patch_failure)):
                                        verify_ok, verify_err = await self._verify(task)
                                        task.result["verified"] = verify_ok
                                        if not verify_ok and self._retries_left > 0:
                                            self._retries_left -= 1
                                            log.info("verify_failed_retrying", task_id=task.id, error=verify_err[:80])
                                            # Retry: send error back to model
                                            retry_prompt = (
                                                f"The previous patch caused a test failure:\n"
                                                f"{verify_err[:500]}\n\n"
                                                f"Fix the issue. Original task: {task.description}\n"
                                                f"Show the corrected change as FILE/OLD/NEW format."
                                            )
                                            payload["content"] = retry_prompt
                                            r2 = await asyncio.to_thread(
                                                _post,
                                                f"{api_url}/query",
                                                payload,
                                                120,
                                            )
                                            if r2.status_code == 200:
                                                retry_text = r2.json().get("response", "")
                                                retry_patches = self._parse_patches(retry_text)
                                                for rp in retry_patches:
                                                    if self._apply_patch(rp) == "ok":
                                                        patches_applied += 1
                                                        f = rp["file"]
                                                        updated = self._read_file_context(f)
                                                        if updated:
                                                            file_context_cache[f] = updated
                                                # Re-verify
                                                v2_ok, _ = await self._verify(task)
                                                task.result["verified"] = v2_ok
                                                task.result["retried"] = True

                            # ── Per-task git revert on verify failure ──────────────────
                            # If verify ran and ultimately failed (after all retries), revert
                            # just the files this task modified so subsequent tasks don't read
                            # corrupted source.  git checkout HEAD -- <files> is O(changed files)
                            # and ignores gitignored paths (node_modules, assets, etc.).
                            if (apply and git_commit and patched_file_set
                                    and task.result.get("verified") is False):
                                import subprocess as _sp
                                async with git_lock:
                                    files_to_revert = list(patched_file_set)
                                    rv = _sp.run(
                                        ["git", "checkout", "HEAD", "--"] + files_to_revert,
                                        cwd=self.repo_root,
                                        capture_output=True,
                                        text=True,
                                    )
                                    if rv.returncode == 0:
                                        log.warning(
                                            "task_files_reverted",
                                            task_id=task.id,
                                            n=len(files_to_revert),
                                        )
                                        print(
                                            f"     ↩️  verify failed — reverted {len(files_to_revert)} file(s)",
                                            flush=True,
                                        )
                                        patched_file_set.clear()
                                        patches_applied = 0
                                    else:
                                        log.warning(
                                            "task_files_revert_failed",
                                            task_id=task.id,
                                            err=rv.stderr[:120],
                                        )

                            task.result["patches_applied"] = patches_applied
                            task.result["patched_files"] = list(patched_file_set)
                            # If local produced 0 patches, escalate to cloud and retry once.
                            used_tier = payload.get("force_tier", task.suggested_tier or "local_multi")
                            if task_is_code and patches_applied == 0 and used_tier in ("local", "local_multi"):
                                log.warning("task_no_patches_escalating_cloud", task_id=task.id,
                                            desc=task.description[:60])
                                print("     ⏫ 0 patches from local — escalating to cloud_cheap for retry",
                                      flush=True)
                                payload["force_tier"] = "cloud_cheap"
                                r2 = await asyncio.to_thread(_post, f"{api_url}/query", payload, self.task_timeout)
                                if r2.status_code == 200:
                                    retry_text = r2.json().get("response", "")
                                    retry_patches = self._parse_patches(retry_text)
                                    task.result["patches_found_cloud"] = len(retry_patches)
                                    if apply and retry_patches:
                                        async with file_lock:
                                            for rp in retry_patches:
                                                if self._apply_patch(rp) == "ok":
                                                    patches_applied += 1
                                                    patched_file_set.add(rp["file"])
                                    task.result["patches_applied"] = patches_applied
                                    task.result["patched_files"] = list(patched_file_set)
                                    task.result["escalated_to_cloud"] = True
                            # If still 0 patches after escalation, reset to pending for next run
                            if task_is_code and patches_applied == 0:
                                task.status = "pending"
                                log.warning("task_no_patches_reset_pending", task_id=task.id,
                                            desc=task.description[:60])
                    else:
                        task.status = "failed"
                        task.result = {"error": f"HTTP {r.status_code}: {r.text[:200]}"}
                except Exception as e:
                    task.status = "failed"
                    task.result = {"error": str(e)[:200]}

                elapsed = time.time() - start
                async with _progress_lock:
                    active_tasks.pop(task.id, None)
                    completed_tasks += 1
                    done_pct = int(100 * completed_tasks / total_tasks)
                    remaining = len(active_tasks)

                status_icon = "✅" if task.status == "done" else "❌"
                patches_n = task.result.get("patches_applied", 0)
                patch_note = f"  {patches_n} patch(es)" if patches_n else ""
                tier_actual = task.result.get("tier_used", "?")
                tier_estimated = task.suggested_tier
                if tier_actual != tier_estimated and tier_actual not in ("?", ""):
                    tier_note = f"[{tier_estimated}→{tier_actual}]"
                    self._log_tier_estimate(task.description, tier_estimated, tier_actual)
                else:
                    tier_note = f"[{tier_actual}]"
                print(
                    f"  {status_icon} [{completed_tasks}/{total_tasks} {done_pct}%]"
                    f"  {elapsed:.1f}s  {tier_note}{patch_note}  {short_desc}",
                    flush=True,
                )
                if remaining:
                    print(f"     ↳ {remaining} still running…", flush=True)

                log.info(
                    "task_done",
                    task_id=task.id,
                    status=task.status,
                    elapsed_s=round(elapsed, 1),
                    tier_estimated=tier_estimated,
                    tier_actual=tier_actual,
                    cost=task.result.get("cost", 0),
                )

                # Persist checkpoint so --resume can skip this task next run
                if task_file:
                    self._save_checkpoint(task_file, plan.tasks, self.repo_root)

                return {
                    "task_id": task.id,
                    "description": task.description[:80],
                    "status": task.status,
                    "elapsed_s": round(elapsed, 1),
                    **task.result,
                }

        # ── DAG Execution ──────────────────────────────────────────
        # Infer implicit ordering edges: tasks sharing a target file must run
        # sequentially so each patch sees the previous task's writes.
        task_by_id: dict[int, Task] = {t.id: t for t in plan.tasks}
        if code_mode and apply:
            # Only chain tasks that share an EXPLICIT target_files entry.
            # Tasks with no target_files are independent and can run in parallel.
            file_task_order: dict[str, list[int]] = {}
            for t in plan.tasks:
                if t.target_files:  # only explicit targets create ordering constraints
                    key = t.target_files[0]
                    file_task_order.setdefault(key, []).append(t.id)
            for file_key, tid_list in file_task_order.items():
                for i in range(1, len(tid_list)):
                    pred, succ = tid_list[i - 1], tid_list[i]
                    if pred not in task_by_id[succ].depends_on:
                        task_by_id[succ].depends_on.append(pred)

        # Build done events for DAG gating
        done_events: dict[int, asyncio.Event] = {t.id: asyncio.Event() for t in plan.tasks}

        # Track which file-keys were touched (for synthesis pass)
        file_results: dict[str, list[dict]] = {}
        _file_result_lock = asyncio.Lock()

        async def run_with_deps(task: Task) -> dict:
            # Wait for all upstream tasks to complete
            for dep_id in task.depends_on:
                ev = done_events.get(dep_id)
                if ev:
                    await ev.wait()
            # Skip tasks pre-marked done by --resume
            if task.status == "done" and task.result.get("resumed"):
                done_events[task.id].set()
                return {
                    "task_id": task.id,
                    "description": task.description[:80],
                    "status": "done",
                    "elapsed_s": 0.0,
                    "resumed": True,
                    **task.result,
                }
            result = await run_task(task)
            done_events[task.id].set()
            # Track results per file for synthesis
            if code_mode and apply:
                fk = (task.target_files[0] if task.target_files else target_file) or "_none"
                async with _file_result_lock:
                    file_results.setdefault(fk, []).append(result)
            return result

        raw = await asyncio.gather(
            *(run_with_deps(t) for t in plan.tasks),
            return_exceptions=True,
        )
        for r in raw:
            if isinstance(r, Exception):
                results.append({"error": str(r)})
            else:
                results.append(r)  # type: ignore[arg-type]

        # Synthesis pass: reconcile files touched by multiple tasks
        if code_mode and apply:
            import requests as _req
            for file_key, fres in file_results.items():
                patched_count = sum(1 for r in fres if r.get("patches_applied", 0) > 0)
                if patched_count > 1 and file_key != "_none":
                    fpath = self.repo_root / file_key
                    if fpath.exists():
                        final_content = fpath.read_text(errors="replace")
                        synth_prompt = (
                            f"The following file was patched by {patched_count} separate tasks. "
                            f"Review it for conflicts, duplicate code, inconsistent style, or broken logic, "
                            f"and produce a clean reconciled version.\n\n"
                            f"FILE: {file_key}\nOLD:\n{final_content[:24000]}\nNEW:\n"
                        )
                        synth_payload = {
                            "content": synth_prompt,
                            "source": "api",
                            "session_id": self._session_id,
                            "skip_cache": True,
                            "force_tier": "local_multi",
                            "min_complexity": 3,
                        }
                        try:
                            sr = await asyncio.to_thread(
                                lambda sp=synth_payload: _req.post(
                                    f"{api_url}/query", json=sp,
                                    timeout=self.task_timeout, verify=False # nosec B501 -- internal local service call
                                )
                            )
                            if sr.status_code == 200:
                                synth_text = sr.json().get("response", "")
                                for sp in self._parse_patches(synth_text):
                                    if self._apply_patch(sp) == "ok":
                                        log.info("synthesis_applied", file=file_key)
                        except Exception as se:
                            log.warning("synthesis_failed", file=file_key, error=str(se)[:100])

        # Summary
        done = sum(1 for r in results if r.get("status") == "done")
        failed = sum(1 for r in results if r.get("status") == "failed")
        total_cost: float = sum(float(str(r.get("cost", 0) or 0)) for r in results)  # type: ignore[misc]
        total_patches: int = sum(int(r.get("patches_applied", 0) or 0) for r in results)

        log.info("plan_complete", done=done, failed=failed, total_cost=round(total_cost, 4))

        # ── onefile synthesis ────────────────────────────────────
        if onefile and code_mode and apply:
            out_path = target_file or "index.html"
            if not Path(out_path).is_absolute():
                out_path = str(self.repo_root / out_path)
            self._synthesize_to_single_file(results, out_path, api_url, title=getattr(plan, 'title', None) or "Game")

        # ── Git commit ──────────────────────────────────────────
        if apply and git_commit and total_patches > 0:
            self._git_commit_results(results, plan, feature_branches=feature_branches)

        # ── Post-build health check ──────────────────────────────
        if code_mode and apply:
            self._post_build_health_check(results)

        return results

    # ── Checkpoint ────────────────────────────────────────────

    @staticmethod
    def _checkpoint_path(task_file: str) -> Path:
        return Path(task_file).resolve().with_suffix(".checkpoint.json")

    @staticmethod
    def _save_checkpoint(task_file: str, tasks: list, repo_root: Path) -> None:
        import datetime as _dt
        import json as _json
        data = {
            "task_file": str(Path(task_file).resolve()),
            "repo_root": str(repo_root),
            "saved": _dt.datetime.utcnow().isoformat(),
            "tasks": {
                str(t.id): {
                    "status": t.status,
                    "description": t.description[:120],
                    "patches_applied": t.result.get("patches_applied", 0),
                    "patched_files": t.result.get("patched_files", []),
                    "tier_used": t.result.get("tier_used", ""),
                    "cost": t.result.get("cost", 0),
                    "verified": t.result.get("verified"),
                }
                for t in tasks
            },
        }
        cp = Orchestrator._checkpoint_path(task_file)
        cp.write_text(_json.dumps(data, indent=2))

    @staticmethod
    def _load_checkpoint(task_file: str) -> dict:
        import json as _json
        cp = Orchestrator._checkpoint_path(task_file)
        if not cp.exists():
            return {}
        try:
            return _json.loads(cp.read_text()).get("tasks", {})
        except Exception:
            return {}

    def _detect_html_output(self, results: list[dict]) -> str | None:
        """Find the primary HTML game file from patched results."""
        # Prefer index.html, then any .html among patched files
        candidates: list[str] = []
        for r in results:
            for f in r.get("patched_files", []):
                if f.endswith(".html"):
                    candidates.append(f)
        # index.html wins; else most-frequently patched html
        for c in candidates:
            if Path(c).name == "index.html":
                return str(self.repo_root / c)
        if candidates:
            from collections import Counter
            return str(self.repo_root / Counter(candidates).most_common(1)[0][0])
        # Fallback: look for any index.html in repo root
        idx = self.repo_root / "index.html"
        if idx.exists():
            return str(idx)
        return None

    def _post_build_health_check(self, results: list[dict]) -> None:
        """After code-gen, warn about missing entry points and broken JS imports."""
        import re

        all_patched: list[Path] = []
        for r in results:
            for f in r.get("patched_files", []):
                all_patched.append(self.repo_root / f)

        js_files = [p for p in all_patched if p.suffix in (".js", ".ts", ".jsx", ".tsx") and p.exists()]
        html_files = [p for p in all_patched if p.suffix == ".html" and p.exists()]

        # Check for missing index.html in web/game projects
        if js_files and not html_files:
            root_index = self.repo_root / "index.html"
            if not root_index.exists():
                print(
                    f"\n  ⚠️  {len(js_files)} JS/TS file(s) written but no index.html found.",
                    flush=True,
                )
                print(
                    "     Add a task: 'Create index.html entry point wiring all modules' to your task file.",
                    flush=True,
                )

        # Scan for broken imports in patched JS files
        import_re = re.compile(r"""from\s+['"]([^'"]+)['"]\s*;?""")
        broken: list[tuple[str, str]] = []
        for js_path in js_files:
            if not js_path.exists():
                continue
            try:
                text = js_path.read_text(errors="replace")
            except Exception:
                continue
            for m in import_re.finditer(text):
                specifier = m.group(1)
                if specifier.startswith("."):
                    # Relative import — resolve and check
                    target = (js_path.parent / specifier).resolve()
                    # Try with common extensions if no extension given
                    if not target.suffix:
                        candidates = [target.with_suffix(s) for s in (".js", ".ts", ".jsx", ".tsx")]
                    else:
                        candidates = [target]
                    if not any(c.exists() for c in candidates):
                        rel_js = js_path.relative_to(self.repo_root)
                        broken.append((str(rel_js), specifier))

        if broken:
            print(f"\n  ⚠️  {len(broken)} unresolved import(s) detected:", flush=True)
            for src, imp in broken[:8]:
                print(f"     {src} → '{imp}'", flush=True)
            if len(broken) > 8:
                print(f"     … and {len(broken) - 8} more", flush=True)
            print(
                "     Tip: ensure every imported module has a matching task in your task file.",
                flush=True,
            )

    def _synthesize_to_single_file(
        self, results: list[dict], output_path: str, api_url: str, title: str = "Game"
    ) -> bool:
        """Merge all generated files into one self-contained HTML file."""

        import requests

        output = Path(output_path)
        # Collect all patched + existing files from this run
        files_content: dict[str, str] = {}
        for r in results:
            for f in r.get("patched_files", []):
                p = self.repo_root / f
                if p.exists():
                    try:
                        files_content[f] = p.read_text(errors="replace")
                    except Exception:
                        pass

        # Also include the current output file if it exists
        if output.exists() and str(output.relative_to(self.repo_root)) not in files_content:
            try:
                files_content[str(output.relative_to(self.repo_root))] = output.read_text(errors="replace")
            except Exception:
                pass

        if not files_content:
            print("  ⚠️  --onefile: no generated files found to synthesize", flush=True)
            return False

        print(f"\n  🔧 --onefile: synthesizing {len(files_content)} file(s) → {output_path}", flush=True)

        parts = []
        for fname, content in files_content.items():
            ext = Path(fname).suffix
            lang = {"py": "python", "js": "javascript", "ts": "typescript", "css": "css",
                    "html": "html", "json": "json"}.get(ext.lstrip("."), "text")
            parts.append(f"--- FILE: {fname} ---\n```{lang}\n{content[:8000]}\n```")

        files_dump = "\n\n".join(parts)
        prompt = (
            f"You are given the components of a browser game called '{title}'. "
            f"Merge ALL of them into ONE completely self-contained index.html file. "
            f"Requirements:\n"
            f"- Single file, no external dependencies except CDN links that are already present\n"
            f"- All JS inline in <script> tags, all CSS inline in <style> tags\n"
            f"- No ES6 import/export — use global scope or IIFE\n"
            f"- Must be fully playable in a browser by opening the file\n"
            f"- Preserve ALL game logic, visuals, and interactions from the components\n"
            f"- Output ONLY the complete HTML file, nothing else\n\n"
            f"COMPONENTS:\n{files_dump}"
        )

        try:
            resp = requests.post(
                f"{api_url}/query",
                json={"content": prompt, "force_tier": "cloud_cheap", "source": "api", "skip_cache": True},
                timeout=300, verify=False, # nosec B501 -- internal local service call
            )
            if resp.status_code != 200:
                print(f"  ⚠️  synthesis request failed: HTTP {resp.status_code}", flush=True)
                return False
            text = resp.json().get("response", "") or resp.json().get("content", "")
            # Strip markdown fence if present
            import re as _re
            m = _re.search(r"```html\s*([\s\S]+?)```", text)
            if m:
                text = m.group(1).strip()
            if not text.strip().startswith("<"):
                print("  ⚠️  synthesis returned non-HTML response", flush=True)
                return False
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(text)
            size_kb = len(text) // 1024
            print(f"  ✅ --onefile: wrote {size_kb}KB to {output_path}", flush=True)
            return True
        except Exception as exc:
            print(f"  ⚠️  synthesis failed: {exc}", flush=True)
            return False

    @staticmethod
    def rehost_html(html_path: str, inline: bool = False) -> str:
        """Download CDN resources from an HTML file and rewrite links.

        inline=True: embed JS/CSS as inline <script>/<style> (for --onefile --rehost)
        inline=False: save to vendor/ dir beside the file and rewrite src/href
        Returns path of the rewritten file.
        """
        import base64
        import re as _re
        import urllib.request
        from pathlib import Path as _Path

        p = _Path(html_path)
        html = p.read_text(errors="replace")

        cdn_pattern = _re.compile(
            r'(src|href)=["\']('
            r'https?://(?:unpkg\.com|cdn\.jsdelivr\.net|cdnjs\.cloudflare\.com|'
            r'cdn\.skypack\.dev|esm\.sh|jspm\.dev|cdn\.tailwindcss\.com|'
            r'fonts\.googleapis\.com|fonts\.gstatic\.com)'
            r'[^"\']+)["\']',
            _re.IGNORECASE,
        )

        vendor_dir = p.parent / "vendor"
        if not inline:
            vendor_dir.mkdir(exist_ok=True)

        rewrites: dict[str, str] = {}

        for m in cdn_pattern.finditer(html):
            url = m.group(2)
            if url in rewrites:
                continue
            try:
                print(f"  ↓ {url[:70]}", flush=True)
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=15) as r: # nosec B310 -- controlled internal URL
                    content_bytes = r.read()
                    content_type = r.headers.get("Content-Type", "")
            except Exception as exc:
                print(f"  ⚠️  could not fetch {url}: {exc}", flush=True)
                continue

            is_js = "javascript" in content_type or url.endswith(".js") or url.endswith(".mjs")
            is_css = "css" in content_type or url.endswith(".css")
            is_font_binary = any(url.endswith(e) for e in (".woff", ".woff2", ".ttf", ".eot"))

            if inline:
                if is_font_binary:
                    b64 = base64.b64encode(content_bytes).decode()
                    mime = content_type.split(";")[0].strip() or "font/woff2"
                    rewrites[url] = f"data:{mime};base64,{b64}"
                elif is_js or is_css:
                    rewrites[url] = url  # handled below as tag swap
                    # Store decoded content for tag replacement
                    rewrites[url + "__content__"] = content_bytes.decode("utf-8", errors="replace")
            else:
                slug = _re.sub(r"[^a-zA-Z0-9._-]", "_", url.split("//", 1)[-1])[:80]
                dest = vendor_dir / slug
                dest.write_bytes(content_bytes)
                rewrites[url] = f"vendor/{slug}"

        # Apply rewrites
        def replace_src(m: _re.Match) -> str:
            attr, url = m.group(1), m.group(2)
            if url not in rewrites:
                return m.group(0)
            new_url = rewrites[url]
            if inline:
                # Replace <script src=...> with inline <script>
                content = rewrites.get(url + "__content__", "")
                is_script = attr.lower() == "src"
                is_link_css = attr.lower() == "href"
                if content and is_script:
                    return f"<script>{content}</script>"
                elif content and is_link_css:
                    return f"<style>{content}</style>"
                elif new_url.startswith("data:"):
                    return f'{attr}="{new_url}"'
            return f'{attr}="{new_url}"'

        # Replace <script src=...> and <link href=...> tags fully when inlining
        if inline:
            script_re = _re.compile(
                r'<script\s[^>]*src=["\'](' + '|'.join(_re.escape(u) for u in rewrites if not u.endswith("__content__")) + r')["\'][^>]*>\s*</script>',
                _re.IGNORECASE,
            )
            link_re = _re.compile(
                r'<link\s[^>]*href=["\'](' + '|'.join(_re.escape(u) for u in rewrites if not u.endswith("__content__")) + r')["\'][^>]*>',
                _re.IGNORECASE,
            )

            def replace_script(m: _re.Match) -> str:
                url = m.group(1)
                content = rewrites.get(url + "__content__", "")
                return f"<script>{content}</script>" if content else m.group(0)

            def replace_link(m: _re.Match) -> str:
                url = m.group(1)
                content = rewrites.get(url + "__content__", "")
                return f"<style>{content}</style>" if content else m.group(0)

            if rewrites:
                html = script_re.sub(replace_script, html)
                html = link_re.sub(replace_link, html)
        else:
            html = cdn_pattern.sub(replace_src, html)

        p.write_text(html)
        print(f"  ✅ --rehost: rewrote {len(rewrites)} CDN resource(s) in {html_path}", flush=True)
        return html_path

    def _git_commit_results(self, results: list[dict], plan: Plan, feature_branches: int = 0) -> None:
        """Commit applied patches. With feature_branches>1, split into N branches then merge."""
        import subprocess

        def _run(cmd: list[str], cwd: Path | None = None) -> tuple[int, str]:
            r = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd or self.repo_root)
            return r.returncode, (r.stdout + r.stderr).strip()

        # Collect all patched files from results
        patched_results = [r for r in results if r.get("patches_applied", 0) > 0]
        if not patched_results:
            return

        # Determine base branch
        rc, base_branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if rc != 0:
            base_branch = "main"
        base_branch = base_branch.strip()

        import datetime
        ts = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M")

        if feature_branches <= 1:
            # Single commit on current branch
            rc, _ = _run(["git", "add", "-A"])
            task_descs = [r.get("description", "")[:50] for r in patched_results[:5]]
            msg = f"feat(orchestrator): apply {len(patched_results)} task(s)\n\n"
            msg += "\n".join(f"- {d}" for d in task_descs)
            if len(patched_results) > 5:
                msg += f"\n- ...and {len(patched_results) - 5} more"
            rc, out = _run(["git", "commit", "-m", msg])
            if rc == 0:
                print(f"  📦 Committed {len(patched_results)} task(s) on {base_branch}", flush=True)
            else:
                print(f"  ⚠️  Git commit failed: {out[:200]}", flush=True)
        else:
            # Feature-branch mode: group tasks by their patched files to minimize merge conflicts
            # First commit ALL changes to base (they're already on disk), then reconstruct branches
            # by resetting files and re-applying per-group to separate branches.
            # Simpler approach: commit each group's files to its own branch from the same base.

            # Collect all changed files and map them to groups
            n = min(feature_branches, len(patched_results))
            groups = [patched_results[i::n] for i in range(n)]
            # Collect all files touched (for stashing)
            all_patched_files: list[str] = []
            for r in patched_results:
                all_patched_files.extend(r.get("patched_files", []))
            all_patched_files = list(dict.fromkeys(all_patched_files))  # dedupe, preserve order

            if not all_patched_files:
                # Fallback: single commit
                rc, _ = _run(["git", "add", "-A"])
                msg = f"feat(orchestrator): apply {len(patched_results)} task(s)\n\n" + "\n".join(f"- {r.get('description','')[:50]}" for r in patched_results[:5])
                rc, out = _run(["git", "commit", "-m", msg])
                if rc == 0:
                    print(f"  📦 Committed {len(patched_results)} task(s) on {base_branch}", flush=True)
                return

            merged_branches: list[str] = []

            for i, group in enumerate(groups):
                group_files: list[str] = []
                for r in group:
                    group_files.extend(r.get("patched_files", []))
                group_files = list(dict.fromkeys(group_files))
                if not group_files:
                    continue

                branch_name = f"orch/{ts}-f{i+1}"
                # Create branch from current base
                rc, _ = _run(["git", "checkout", "-b", branch_name])
                if rc != 0:
                    print(f"  ⚠️  Could not create branch {branch_name}", flush=True)
                    _run(["git", "checkout", base_branch])
                    continue

                # Stage only this group's files
                add_cmd = ["git", "add"] + group_files
                rc, _ = _run(add_cmd)
                task_descs = [r.get("description", "")[:50] for r in group[:3]]
                msg = f"feat: batch {i+1}/{n} — {len(group)} task(s)\n\n" + "\n".join(f"- {d}" for d in task_descs)
                rc, out = _run(["git", "commit", "-m", msg])
                if rc == 0:
                    merged_branches.append(branch_name)
                    print(f"  📦 Branch {branch_name}: {len(group_files)} file(s), {len(group)} task(s)", flush=True)
                else:
                    print(f"  ⚠️  Branch {branch_name} commit failed: {out[:100]}", flush=True)
                # Return to base
                _run(["git", "checkout", base_branch])

            # Merge all feature branches back
            for branch in merged_branches:
                rc, out = _run(["git", "merge", "--no-ff", branch, "-m", f"merge: {branch}"])
                if rc == 0:
                    print(f"  🔀 Merged {branch}", flush=True)
                    _run(["git", "branch", "-d", branch])
                else:
                    print(f"  ⚠️  Merge conflict on {branch}: {out[:100]}", flush=True)

    # ── Utility ───────────────────────────────────────────────

    def print_plan(self, plan: Plan) -> str:
        """Pretty-print a plan for human review."""
        lines = [
            "muLLM Orchestrator Plan",
            f"{'─' * 50}",
            f"Repo: {plan.repo_summary}",
            f"Tasks: {len(plan.tasks)}",
            f"Est. cost: ${plan.total_estimated_cost:.4f}",
            f"Context: {len(plan.context)} chars",
            "",
        ]
        for t in plan.tasks:
            tier_icon = {
                "local": "🟢",
                "local_multi": "🔵",
                "cloud_cheap": "🟡",
                "cloud_full": "🔴",
            }.get(t.suggested_tier, "⚪")
            files = f" → {', '.join(t.target_files)}" if t.target_files else ""
            display = t.description[:80] + ("…" if len(t.description) > 80 else "")
            lines.append(f"  {tier_icon} [{t.suggested_tier}] {display}{files}")

        return "\n".join(lines)
