"""
MBPP (Mostly Basic Python Problems) benchmark — inline set + optional full download.

Inline: 10 handpicked problems (no network needed for quick bench).
Full: 427 sanitized problems from google-research/mbpp on HuggingFace.

Each dict: task_id, prompt, test, entry_point
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

_CACHE_PATH = Path(__file__).parent / "mbpp_sanitized.jsonl"
_HF_URL = "https://huggingface.co/datasets/google-research-datasets/mbpp/resolve/main/sanitized-mbpp.jsonl"

log = logging.getLogger(__name__)

PROBLEMS: list[dict] = [
    {
        "task_id": "MBPP/1",
        "prompt": (
            "Write a function find_max(numbers) that takes a list of numbers and "
            "returns the maximum value. Handle empty list by returning None."
        ),
        "test": (
            "assert find_max([1, 2, 3]) == 3\n"
            "assert find_max([-1, -5, -3]) == -1\n"
            "assert find_max([42]) == 42\n"
            "assert find_max([]) is None\n"
        ),
        "entry_point": "find_max",
    },
    {
        "task_id": "MBPP/2",
        "prompt": (
            "Write a function is_prime(n) that returns True if n is a prime number, "
            "False otherwise. Handle edge cases: n < 2 returns False."
        ),
        "test": (
            "assert is_prime(2) == True\n"
            "assert is_prime(3) == True\n"
            "assert is_prime(4) == False\n"
            "assert is_prime(17) == True\n"
            "assert is_prime(1) == False\n"
            "assert is_prime(0) == False\n"
            "assert is_prime(97) == True\n"
        ),
        "entry_point": "is_prime",
    },
    {
        "task_id": "MBPP/3",
        "prompt": (
            "Write a function count_vowels(s) that returns the count of vowels "
            "(a, e, i, o, u — case insensitive) in the string s."
        ),
        "test": (
            "assert count_vowels('hello') == 2\n"
            "assert count_vowels('AEIOU') == 5\n"
            "assert count_vowels('xyz') == 0\n"
            "assert count_vowels('') == 0\n"
            "assert count_vowels('Python Programming') == 4\n"
        ),
        "entry_point": "count_vowels",
    },
    {
        "task_id": "MBPP/4",
        "prompt": (
            "Write a function reverse_string(s) that returns the string reversed. "
            "Do not use slicing shortcut; use an explicit loop or reversed()."
        ),
        "test": (
            "assert reverse_string('hello') == 'olleh'\n"
            "assert reverse_string('') == ''\n"
            "assert reverse_string('a') == 'a'\n"
            "assert reverse_string('racecar') == 'racecar'\n"
        ),
        "entry_point": "reverse_string",
    },
    {
        "task_id": "MBPP/5",
        "prompt": (
            "Write a function sum_digits(n) that takes a non-negative integer n and "
            "returns the sum of its digits. E.g. sum_digits(123) == 6."
        ),
        "test": (
            "assert sum_digits(0) == 0\n"
            "assert sum_digits(9) == 9\n"
            "assert sum_digits(123) == 6\n"
            "assert sum_digits(9999) == 36\n"
            "assert sum_digits(100) == 1\n"
        ),
        "entry_point": "sum_digits",
    },
    {
        "task_id": "MBPP/6",
        "prompt": (
            "Write a function second_largest(lst) that returns the second largest "
            "distinct value in a list of numbers. Return None if there are fewer than "
            "two distinct values."
        ),
        "test": (
            "assert second_largest([1, 2, 3]) == 2\n"
            "assert second_largest([5, 5, 5]) is None\n"
            "assert second_largest([3, 1]) == 1\n"
            "assert second_largest([10, 20, 20, 30]) == 20\n"
            "assert second_largest([1]) is None\n"
        ),
        "entry_point": "second_largest",
    },
    {
        "task_id": "MBPP/7",
        "prompt": (
            "Write a function rotate_list(lst, k) that rotates list lst to the right "
            "by k positions. E.g. rotate_list([1,2,3,4,5], 2) == [4,5,1,2,3]."
        ),
        "test": (
            "assert rotate_list([1, 2, 3, 4, 5], 2) == [4, 5, 1, 2, 3]\n"
            "assert rotate_list([1, 2, 3], 0) == [1, 2, 3]\n"
            "assert rotate_list([1, 2, 3], 3) == [1, 2, 3]\n"
            "assert rotate_list([], 5) == []\n"
            "assert rotate_list([1], 100) == [1]\n"
        ),
        "entry_point": "rotate_list",
    },
    {
        "task_id": "MBPP/8",
        "prompt": (
            "Write a function group_by_first_letter(words) that takes a list of strings "
            "and returns a dict mapping each first letter (lowercase) to the list of words "
            "starting with that letter, preserving order. "
            "E.g. group_by_first_letter(['apple','ant','banana']) == {'a':['apple','ant'],'b':['banana']}."
        ),
        "test": (
            "assert group_by_first_letter(['apple', 'ant', 'banana']) == {'a': ['apple', 'ant'], 'b': ['banana']}\n"
            "assert group_by_first_letter([]) == {}\n"
            "assert group_by_first_letter(['Zoo', 'zebra']) == {'z': ['Zoo', 'zebra']}\n"
        ),
        "entry_point": "group_by_first_letter",
    },
    {
        "task_id": "MBPP/9",
        "prompt": (
            "Write a function matrix_transpose(matrix) that takes a 2D list (list of lists) "
            "and returns its transpose. E.g. [[1,2],[3,4]] -> [[1,3],[2,4]]."
        ),
        "test": (
            "assert matrix_transpose([[1, 2], [3, 4]]) == [[1, 3], [2, 4]]\n"
            "assert matrix_transpose([[1, 2, 3]]) == [[1], [2], [3]]\n"
            "assert matrix_transpose([[1], [2], [3]]) == [[1, 2, 3]]\n"
            "assert matrix_transpose([]) == []\n"
        ),
        "entry_point": "matrix_transpose",
    },
    {
        "task_id": "MBPP/10",
        "prompt": (
            "Write a function run_length_encode(s) that performs run-length encoding on "
            "string s: consecutive identical characters are replaced by (count, char) tuples. "
            "E.g. run_length_encode('aaabbc') == [(3,'a'),(2,'b'),(1,'c')]."
        ),
        "test": (
            "assert run_length_encode('aaabbc') == [(3, 'a'), (2, 'b'), (1, 'c')]\n"
            "assert run_length_encode('') == []\n"
            "assert run_length_encode('abcd') == [(1, 'a'), (1, 'b'), (1, 'c'), (1, 'd')]\n"
            "assert run_length_encode('aaaa') == [(4, 'a')]\n"
        ),
        "entry_point": "run_length_encode",
    },
]


def _fetch_sanitized() -> list[dict]:
    """Download sanitized MBPP from HuggingFace via datasets lib, cache to disk."""
    import re as _re

    log.info("Downloading sanitized MBPP from HuggingFace...")
    try:
        from datasets import load_dataset

        ds = load_dataset("google-research-datasets/mbpp", "sanitized", split="test")  # nosec B615 -- benchmark code, sandboxed
    except Exception as exc:
        log.error("MBPP download failed: %s", exc)
        return PROBLEMS

    problems = []
    for rec in ds:
        tid = rec.get("task_id", len(problems))
        prompt_text = rec.get("text", rec.get("prompt", ""))
        code = rec.get("code", rec.get("canonical_solution", ""))
        test_list = rec.get("test_list", [])
        test_setup = rec.get("test_setup_code", "")

        ep_match = _re.search(r"def\s+(\w+)\s*\(", code)
        entry_point = ep_match.group(1) if ep_match else f"solution_{tid}"

        test_str = ""
        if test_setup:
            test_str = test_setup + "\n"
        test_str += "\n".join(test_list) if isinstance(test_list, list) else str(test_list)

        problems.append(
            {
                "task_id": f"MBPP/{tid}",
                "prompt": f"Write a function {entry_point} that solves the following:\n{prompt_text}",
                "canonical_solution": code,
                "test": test_str,
                "entry_point": entry_point,
            }
        )

    if len(problems) < 100:
        log.warning("Only got %d MBPP problems, expected 400+", len(problems))
        return PROBLEMS

    with open(_CACHE_PATH, "w", encoding="utf-8") as f:
        for p in problems:
            f.write(json.dumps(p) + "\n")
    log.info("Cached %d sanitized MBPP problems to %s", len(problems), _CACHE_PATH)
    return problems


def load_problems(full: bool = False) -> list[dict]:
    """Return MBPP problem list.

    Args:
        full: If True, load all 427 sanitized problems (downloads on first call).
    """
    if not full:
        return PROBLEMS

    if _CACHE_PATH.exists() and _CACHE_PATH.stat().st_size > 1000:
        try:
            lines = [ln for ln in _CACHE_PATH.read_text(encoding="utf-8").splitlines() if ln.strip()]
            problems = [json.loads(ln) for ln in lines]
            if len(problems) >= 100:
                log.debug("Loaded %d MBPP problems from cache", len(problems))
                return problems
        except Exception as exc:
            log.warning("MBPP cache read failed: %s", exc)

    return _fetch_sanitized()
