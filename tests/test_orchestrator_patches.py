"""Unit tests for orchestrator patch application and retry logic."""
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch as mock_patch
import tempfile
import textwrap


@pytest.fixture
def orch(tmp_path):
    from router.orchestrator import Orchestrator
    o = Orchestrator(api_url="http://localhost:8100")
    o.repo_root = tmp_path
    return o


class TestApplyPatch:
    def test_new_file_ok(self, orch, tmp_path):
        p = {"file": "src/foo.py", "old": "", "new": "def foo():\n    return 1\n"}
        assert orch._apply_patch(p) == "ok"
        assert (tmp_path / "src/foo.py").read_text() == "def foo():\n    return 1\n"

    def test_new_file_truncated_refused(self, orch, tmp_path):
        # Python truncated mid-method (deep indent on last line)
        truncated = "def foo():\n    def inner():\n        x = (\n            1 +\n            "
        p = {"file": "src/bar.py", "old": "", "new": truncated}
        assert orch._apply_patch(p) == "truncated"
        assert not (tmp_path / "src/bar.py").exists()

    def test_truncated_sentinel_refused(self, orch, tmp_path):
        code = "def foo():\n    pass\n##TRUNCATED##"
        p = {"file": "src/baz.py", "old": "", "new": code}
        assert orch._apply_patch(p) == "truncated"

    def test_full_replace_existing_file(self, orch, tmp_path):
        f = tmp_path / "src/a.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("old content\n")
        p = {"file": "src/a.py", "old": "", "new": "new content\n"}
        assert orch._apply_patch(p) == "ok"
        assert f.read_text() == "new content\n"

    def test_old_not_found(self, orch, tmp_path):
        f = tmp_path / "src/b.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("actual content\n")
        p = {"file": "src/b.py", "old": "DOES NOT EXIST", "new": "replacement\n"}
        assert orch._apply_patch(p) == "old_not_found"
        assert f.read_text() == "actual content\n"  # unchanged

    def test_partial_replace_ok(self, orch, tmp_path):
        f = tmp_path / "src/c.py"
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text("line1\nline2\nline3\n")
        p = {"file": "src/c.py", "old": "line2", "new": "LINE2"}
        assert orch._apply_patch(p) == "ok"
        assert "LINE2" in f.read_text()


class TestTruncatedRetryListInit:
    """Regression: failed_truncated must be initialized BEFORE the TDD block uses it."""

    def test_failed_truncated_init_order(self):
        """Verify the list is initialized before TDD code runs."""
        import ast, inspect
        from router.orchestrator import Orchestrator
        source = inspect.getsource(Orchestrator.execute)
        # Find line numbers for both occurrences
        lines = source.split('\n')
        tdd_use_line = None
        init_line = None
        for i, line in enumerate(lines):
            if 'failed_truncated.append' in line and tdd_use_line is None:
                tdd_use_line = i
            if 'failed_truncated: list[dict] = []' in line and init_line is None:
                init_line = i
        assert init_line is not None, "failed_truncated init not found"
        assert tdd_use_line is not None, "failed_truncated.append not found"
        assert init_line < tdd_use_line, (
            f"failed_truncated initialized at line {init_line} but first used at {tdd_use_line} — "
            "TDD truncation will crash with NameError"
        )


class TestPatchedFileSetScope:
    """Regression: patched_file_set must exist even when no patches are applied."""

    def test_patched_file_set_always_initialized(self):
        """Verify patched_file_set is initialized before the apply block, not inside it."""
        import inspect
        from router.orchestrator import Orchestrator
        source = inspect.getsource(Orchestrator.execute)
        lines = source.split('\n')
        init_line = None
        apply_block_line = None
        for i, line in enumerate(lines):
            if 'patched_file_set: set[str] = set()' in line and init_line is None:
                init_line = i
            if 'if apply and patches:' in line and apply_block_line is None:
                apply_block_line = i
        assert init_line is not None, "patched_file_set init not found"
        assert apply_block_line is not None, "'if apply and patches:' not found"
        assert init_line < apply_block_line, (
            "patched_file_set initialized INSIDE 'if apply and patches:' block — "
            "tasks without patches will crash with NameError"
        )


class TestLooksComplete:
    def test_complete_python(self, orch):
        assert orch._looks_complete("def foo():\n    return 1\n", "foo.py") is True

    def test_truncated_sentinel(self, orch):
        assert orch._looks_complete("def foo():\n    pass\n##TRUNCATED##", "foo.py") is False

    def test_deep_indent_truncated(self, orch):
        # Last non-blank line has 12+ spaces of indent — mid-method truncation
        code = "class Foo:\n    def bar(self):\n        def inner():\n            x = 1 + \\"
        assert orch._looks_complete(code, "foo.py") is False

    def test_complete_js(self, orch):
        assert orch._looks_complete("function f() {\n  return 1;\n}\n", "f.js") is True

    def test_unbalanced_js_braces(self, orch):
        assert orch._looks_complete("function f() {\n  if (x) {\n    return 1;\n", "f.js") is False


class TestPostBuildHealthCheck:
    def test_warns_missing_index_html(self, orch, tmp_path, capsys):
        js = tmp_path / "src" / "game.js"
        js.parent.mkdir(parents=True, exist_ok=True)
        js.write_text("export const x = 1;\n")
        results = [{"patched_files": ["src/game.js"], "status": "done"}]
        orch._post_build_health_check(results)
        out = capsys.readouterr().out
        assert "no index.html" in out

    def test_no_warning_when_html_patched(self, orch, tmp_path, capsys):
        js = tmp_path / "src" / "game.js"
        js.parent.mkdir(parents=True, exist_ok=True)
        js.write_text("export const x = 1;\n")
        html = tmp_path / "index.html"
        html.write_text("<html></html>")
        results = [{"patched_files": ["src/game.js", "index.html"], "status": "done"}]
        orch._post_build_health_check(results)
        out = capsys.readouterr().out
        assert "no index.html" not in out

    def test_detects_broken_import(self, orch, tmp_path, capsys):
        js = tmp_path / "src" / "main.js"
        js.parent.mkdir(parents=True, exist_ok=True)
        js.write_text("import { Foo } from './missing-module.js';\n")
        results = [{"patched_files": ["src/main.js"], "status": "done"}]
        orch._post_build_health_check(results)
        out = capsys.readouterr().out
        assert "unresolved import" in out
        assert "missing-module.js" in out

    def test_no_broken_import_when_file_exists(self, orch, tmp_path, capsys):
        dep = tmp_path / "src" / "dep.js"
        dep.parent.mkdir(parents=True, exist_ok=True)
        dep.write_text("export const dep = 1;\n")
        js = tmp_path / "src" / "main.js"
        js.write_text("import { dep } from './dep.js';\n")
        results = [{"patched_files": ["src/main.js", "src/dep.js"], "status": "done"}]
        orch._post_build_health_check(results)
        out = capsys.readouterr().out
        assert "unresolved import" not in out
