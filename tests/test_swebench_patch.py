"""Unit tests for SWE-bench patch extraction and sanitization."""
import pytest
from router.benchmarks.swebench import _extract_patch, _sanitize_patch


# ── _sanitize_patch ───────────────────────────────────────────────────────────

class TestSanitizePatch:
    def test_clean_patch_unchanged(self):
        patch = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def foo():\n"
            "-    return 1\n"
            "+    return 2\n"
        )
        assert _sanitize_patch(patch) == patch.rstrip()

    def test_strips_prose_before_diff(self):
        raw = (
            "Here is my patch to fix the issue:\n\n"
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def foo():\n"
            "-    return 1\n"
            "+    return 2\n"
        )
        result = _sanitize_patch(raw)
        assert result.startswith("diff --git")
        assert "Here is my patch" not in result

    def test_strips_prose_bleed_into_hunk(self):
        """Model injects explanation line inside the hunk body."""
        raw = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " def foo():\n"
            "This line was wrong because of off-by-one\n"  # <- injected prose
            "-    return 1\n"
            "+    return 2\n"
        )
        result = _sanitize_patch(raw)
        assert "This line was wrong" not in result
        assert "-    return 1" in result
        assert "+    return 2" in result

    def test_strips_think_block(self):
        raw = (
            "<think>Let me analyze the issue carefully...</think>\n"
            "diff --git a/bar.py b/bar.py\n"
            "--- a/bar.py\n"
            "+++ b/bar.py\n"
            "@@ -5,4 +5,4 @@\n"
            " x = 1\n"
            "-y = 2\n"
            "+y = 3\n"
        )
        result = _sanitize_patch(raw)
        assert "<think>" not in result
        assert "diff --git" in result

    def test_extracts_from_diff_fenced_block(self):
        raw = (
            "Here is the fix:\n"
            "```diff\n"
            "diff --git a/utils.py b/utils.py\n"
            "--- a/utils.py\n"
            "+++ b/utils.py\n"
            "@@ -10,3 +10,3 @@\n"
            " def helper():\n"
            "-    pass\n"
            "+    return True\n"
            "```\n"
        )
        result = _sanitize_patch(raw)
        assert result.startswith("diff --git")
        assert "Here is the fix" not in result

    def test_multi_file_patch_preserved(self):
        patch = (
            "diff --git a/a.py b/a.py\n"
            "--- a/a.py\n"
            "+++ b/a.py\n"
            "@@ -1,2 +1,2 @@\n"
            " x = 1\n"
            "-y = 2\n"
            "+y = 3\n"
            "diff --git a/b.py b/b.py\n"
            "--- a/b.py\n"
            "+++ b/b.py\n"
            "@@ -5,2 +5,2 @@\n"
            " a = 1\n"
            "-b = 2\n"
            "+b = 99\n"
        )
        result = _sanitize_patch(patch)
        assert result.count("diff --git") == 2
        assert "+y = 3" in result
        assert "+b = 99" in result

    def test_no_newline_marker_preserved(self):
        patch = (
            "diff --git a/f.py b/f.py\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old\n"
            "\\ No newline at end of file\n"
            "+new\n"
        )
        result = _sanitize_patch(patch)
        assert "\\ No newline at end of file" in result

    def test_index_line_preserved(self):
        patch = (
            "diff --git a/f.py b/f.py\n"
            "index abc123..def456 100644\n"
            "--- a/f.py\n"
            "+++ b/f.py\n"
            "@@ -1,2 +1,2 @@\n"
            " x = 1\n"
            "-y = 2\n"
            "+y = 3\n"
        )
        result = _sanitize_patch(patch)
        assert "index abc123" in result


# ── _extract_patch ────────────────────────────────────────────────────────────

class TestExtractPatch:
    def test_raw_diff_in_response(self):
        response = (
            "I'll fix this by changing the return value.\n\n"
            "diff --git a/mod.py b/mod.py\n"
            "--- a/mod.py\n"
            "+++ b/mod.py\n"
            "@@ -3,3 +3,3 @@\n"
            " def f():\n"
            "-    return 0\n"
            "+    return 1\n"
        )
        result = _extract_patch(response)
        assert result.startswith("diff --git")

    def test_patch_fenced_block(self):
        response = (
            "```patch\n"
            "diff --git a/x.py b/x.py\n"
            "--- a/x.py\n"
            "+++ b/x.py\n"
            "@@ -1 +1 @@\n"
            "-a\n"
            "+b\n"
            "```\n"
        )
        result = _extract_patch(response)
        assert "diff --git" in result

    def test_thinks_stripped_before_extraction(self):
        response = (
            "<think>analyzing...</think>\n"
            "diff --git a/q.py b/q.py\n"
            "--- a/q.py\n"
            "+++ b/q.py\n"
            "@@ -1 +1 @@\n"
            "-old\n"
            "+new\n"
        )
        result = _extract_patch(response)
        assert "diff --git" in result
        assert "<think>" not in result
